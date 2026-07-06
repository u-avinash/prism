"""
╔══════════════════════════════════════════════════════════════════════╗
║                          P  R  I  S  M                               ║
║       Autonomous AI Incident Management System                       ║
╚══════════════════════════════════════════════════════════════════════╝

  Building an Autonomous AI Incident Management System
  with LangGraph and OpenTelemetry

  Author   : Upadhyayula Avinash
  GitHub   : https://github.com/u-avinash
  LinkedIn : https://www.linkedin.com/in/avinash-upadhyayula/
  Email    : uavinash.csit@gmail.com

  Copyright (c) 2026-2035 Upadhyayula Avinash. All rights reserved.
"""
"""
Escalation handler node — evaluates escalation rules and SLA timers.

This node runs at two points in the workflow:
  1. After assess_severity  — set SLA due timestamp, check for immediate escalation
  2. After await_approval   — check if approval is overdue and escalate

It is intentionally non-blocking: any failure here is logged and the workflow
continues normally.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from agents.state import AgentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default SLA config (minutes).  Override via project runtime config.
# ---------------------------------------------------------------------------
_DEFAULT_SLA = {
    "CRITICAL": {"acknowledgement_minutes": 5,  "resolution_minutes": 30},
    "HIGH":     {"acknowledgement_minutes": 30, "resolution_minutes": 240},
    "MEDIUM":   {"acknowledgement_minutes": 120, "resolution_minutes": 1440},
    "LOW":      {"acknowledgement_minutes": 480, "resolution_minutes": 4320},
}

# Rejection reason codes exposed to the UI
REJECTION_REASON_CODES = [
    "wrong_root_cause",       # Fix targets wrong component
    "wrong_approach",         # Root cause correct, fix strategy wrong
    "breaks_functionality",   # Fix would introduce a regression
    "incomplete_fix",         # Fix is partial / misses edge cases
    "expected_behaviour",     # Not a bug — working as intended
    "needs_architecture",     # Requires architectural change, not a hotfix
    "other",                  # Free-form (captured in approval_notes)
]


def compute_sla_node(state: AgentState) -> AgentState:
    """
    Compute SLA due timestamp and initial SLA status for a new incident.

    Called immediately after assess_severity.
    Persists sla_resolution_due_at and sla_status to the DB.
    """
    incident_id = state.get('incident_id', '')
    severity = state.get('severity', 'HIGH').upper()
    project_id = state.get('project_id')

    try:
        sla_cfg = _load_sla_config(project_id, severity)
        resolution_minutes = sla_cfg.get('resolution_minutes', 240)

        now = datetime.utcnow()
        due_at = now + timedelta(minutes=resolution_minutes)

        state['sla_resolution_due_at'] = due_at.isoformat()
        state['sla_status'] = 'ON_TRACK'

        # Persist to DB
        _persist_sla(
            incident_id=incident_id,
            sla_resolution_due_at=due_at,
            sla_status='ON_TRACK',
        )

        logger.info(
            "[SLA] Incident %s: resolution due at %s (%d min, severity=%s)",
            incident_id, due_at.strftime('%Y-%m-%d %H:%M UTC'), resolution_minutes, severity
        )

    except Exception as exc:
        logger.warning("[SLA] Could not compute SLA for %s: %s", incident_id, exc)

    return state


def check_escalation_node(state: AgentState) -> AgentState:
    """
    Check escalation conditions at the await_approval gate.

    Evaluates:
      - Is the SLA at risk or breached?
      - Has the same error been seen more than N times recently?
      - Was the fix rejected twice with the same reason?

    Sends escalation notifications and updates sla_status.
    """
    incident_id = state.get('incident_id', '')
    severity = state.get('severity', 'HIGH').upper()
    project_id = state.get('project_id')

    try:
        now = datetime.utcnow()

        # --- SLA check ---
        due_str = state.get('sla_resolution_due_at')
        sla_status = 'ON_TRACK'

        if due_str:
            try:
                due_at = datetime.fromisoformat(due_str)
                remaining = (due_at - now).total_seconds() / 60  # minutes

                if remaining < 0:
                    sla_status = 'BREACHED'
                elif remaining < 30:
                    sla_status = 'AT_RISK'
                else:
                    sla_status = 'ON_TRACK'

                logger.info(
                    "[Escalation] Incident %s SLA: %s (%.0f min remaining)",
                    incident_id, sla_status, remaining
                )

                if sla_status in ('AT_RISK', 'BREACHED'):
                    _send_escalation_alert(
                        state=state,
                        reason=f"SLA {sla_status}: {abs(remaining):.0f} min "
                               f"{'overdue' if sla_status == 'BREACHED' else 'remaining'}",
                    )

            except (ValueError, TypeError) as ts_err:
                logger.debug("[Escalation] Could not parse SLA timestamp: %s", ts_err)

        # --- Recurring error check ---
        fix_attempt_count = state.get('fix_attempt_count', 0) or 0
        if fix_attempt_count >= 2:
            _send_escalation_alert(
                state=state,
                reason=f"Fix rejected {fix_attempt_count} times — may need architecture review",
            )
            logger.warning(
                "[Escalation] Incident %s fix rejected %d times",
                incident_id, fix_attempt_count
            )

        # Persist updated SLA status
        state['sla_status'] = sla_status
        _persist_sla(incident_id=incident_id, sla_status=sla_status)

    except Exception as exc:
        logger.warning("[Escalation] Escalation check failed for %s (non-critical): %s", incident_id, exc)

    return state


def record_rejection_feedback_node(state: AgentState) -> AgentState:
    """
    Record structured rejection feedback when a reviewer rejects a fix.

    Expects state to contain:
      - rejection_reason_code: one of REJECTION_REASON_CODES
      - approval_notes:        free-text reviewer notes (optional)

    Increments fix_attempt_count so the escalation node can detect repeat rejections.
    """
    incident_id = state.get('incident_id', '')
    reason_code = state.get('rejection_reason_code', 'other')
    notes = state.get('approval_notes', '')

    if reason_code not in REJECTION_REASON_CODES:
        logger.warning(
            "[Rejection] Unknown rejection_reason_code '%s' for %s — defaulting to 'other'",
            reason_code, incident_id
        )
        reason_code = 'other'

    # Increment attempt counter
    current_count = state.get('fix_attempt_count') or 0
    state['fix_attempt_count'] = current_count + 1

    try:
        from storage.database import get_session
        from storage.incident_repository import IncidentRepository

        with get_session() as session:
            repo = IncidentRepository(session)
            repo.update(
                incident_id=incident_id,
                rejection_reason_code=reason_code,
                fix_attempt_count=state['fix_attempt_count'],
                approval_notes=notes,
            )
    except Exception as exc:
        logger.warning("[Rejection] Could not persist rejection feedback for %s: %s", incident_id, exc)

    logger.info(
        "[Rejection] Incident %s rejected (attempt %d): code=%s notes=%s",
        incident_id, state['fix_attempt_count'], reason_code, notes[:100] if notes else ''
    )

    return state


# ---------------------------------------------------------------------------
# Post-Incident Review (PIR) node
# ---------------------------------------------------------------------------

def generate_pir_node(state: AgentState) -> AgentState:
    """
    Generate a Post-Incident Review (PIR) document after an incident is finalized.

    The PIR is stored as a comment on the incident and optionally sent as a
    Slack/Teams notification.  This node is best-effort — failures are logged
    but never block workflow completion.
    """
    incident_id = state.get('incident_id', '')

    try:
        from integrations.llm_provider import LLMProvider
        from storage.database import get_session
        from storage.incident_repository import IncidentRepository

        llm = LLMProvider(project_id=state.get('project_id'))

        created_at = state.get('created_at', '')
        completed_at = state.get('completed_at') or datetime.utcnow().isoformat()
        pr_url = state.get('pr_url', 'N/A')
        jira_url = state.get('jira_ticket_url', 'N/A')
        rca_text = state.get('rca_text', '')
        fix_explanation = state.get('fix_explanation', '')
        severity = state.get('severity', 'HIGH')
        app_name = state.get('app_name', '')
        error_title = state.get('error_title', '')
        source_technology = (state.get('metadata') or {}).get('source_technology', 'unknown')

        # Compute MTTR
        try:
            t_start = datetime.fromisoformat(created_at)
            t_end = datetime.fromisoformat(completed_at)
            mttr_minutes = round((t_end - t_start).total_seconds() / 60, 1)
            mttr_str = f"{mttr_minutes} minutes"
        except Exception:
            mttr_str = "N/A"

        pir_prompt = f"""You are generating a concise Post-Incident Review (PIR) document.

INCIDENT: {error_title}
APPLICATION: {app_name}
TECHNOLOGY: {source_technology}
SEVERITY: {severity}
MTTR: {mttr_str}
PR: {pr_url}
JIRA: {jira_url}

ROOT CAUSE ANALYSIS SUMMARY:
{rca_text[:600] if rca_text else 'N/A'}

FIX APPLIED:
{fix_explanation[:400] if fix_explanation else 'N/A'}

Generate a Post-Incident Review with these sections (keep each section to 2-3 sentences):
1. **What happened** — brief description of the incident
2. **Root cause** — the technical root cause in plain language
3. **Impact** — who/what was affected and for how long
4. **Resolution** — what was done to fix it
5. **Prevention** — 2-3 concrete action items to prevent recurrence
6. **Lessons learned** — one key takeaway for the team

Keep the total length under 300 words. Use Markdown formatting."""

        pir_text = llm.invoke(prompt=pir_prompt)

        # Store PIR as a system comment on the incident
        with get_session() as session:
            repo = IncidentRepository(session)
            pir_header = f"## 📋 Post-Incident Review\n_Auto-generated | MTTR: {mttr_str}_\n\n"
            repo.add_comment(
                incident_id=incident_id,
                content=pir_header + pir_text,
                author="prism-ai",
                comment_type="system",
            )

        logger.info("[PIR] Post-Incident Review generated for %s (MTTR: %s)", incident_id, mttr_str)

        state['messages'] = state.get('messages', []) + [
            f"✓ Post-Incident Review generated (MTTR: {mttr_str})"
        ]

    except Exception as exc:
        logger.warning("[PIR] PIR generation failed for %s (non-critical): %s", incident_id, exc)

    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def compute_final_sla_status(
    current_sla_status: Optional[str],
    sla_resolution_due_at: Optional[str],
) -> str:
    """
    Compute the definitive SLA outcome when an incident reaches a terminal state.

    Rules:
      - If already BREACHED before resolution → BREACHED (missed the deadline)
      - If resolved before the due timestamp → MET
      - If resolved after the due timestamp → BREACHED
      - If no SLA was configured → MET (no deadline to miss)

    This is called by the finalizer when an incident is COMPLETED, PR_CREATED,
    REJECTED, or FAILED so that the SLA pill in the UI shows the outcome instead
    of continuing to count down.
    """
    # Already confirmed breached before resolution — keep it
    if current_sla_status == 'BREACHED':
        return 'BREACHED'

    if not sla_resolution_due_at:
        return 'MET'  # No SLA configured — no deadline to miss

    try:
        due_at = datetime.fromisoformat(sla_resolution_due_at)
        if datetime.utcnow() <= due_at:
            return 'MET'       # Resolved within the SLA window
        else:
            return 'BREACHED'  # SLA window elapsed before resolution
    except (ValueError, TypeError):
        return 'MET'


def _load_sla_config(project_id: Optional[str], severity: str) -> Dict[str, Any]:
    """Load SLA config from project runtime config, falling back to defaults."""
    defaults = _DEFAULT_SLA.get(severity, _DEFAULT_SLA['HIGH'])

    if not project_id:
        return defaults

    try:
        from storage.auth_store import get_project_config
        config = get_project_config(project_id) or {}
        runtime = config.get('runtime') or {}
        sla_config = runtime.get('sla_config') or {}
        sev_config = sla_config.get(severity) or {}

        return {
            'acknowledgement_minutes': int(
                sev_config.get('acknowledgement_minutes', defaults['acknowledgement_minutes'])
            ),
            'resolution_minutes': int(
                sev_config.get('resolution_minutes', defaults['resolution_minutes'])
            ),
        }
    except Exception as exc:
        logger.debug("[SLA] Could not load project SLA config (%s), using defaults", exc)
        return defaults


def _persist_sla(
    incident_id: str,
    sla_resolution_due_at: Optional[datetime] = None,
    sla_status: Optional[str] = None,
) -> None:
    """Persist SLA fields to the incidents table."""
    try:
        from storage.database import get_session
        from storage.incident_repository import IncidentRepository

        updates: Dict[str, Any] = {}
        if sla_resolution_due_at is not None:
            updates['sla_resolution_due_at'] = sla_resolution_due_at
        if sla_status is not None:
            updates['sla_status'] = sla_status

        if updates:
            with get_session() as session:
                repo = IncidentRepository(session)
                repo.update(incident_id=incident_id, **updates)
    except Exception as exc:
        logger.debug("[SLA] Could not persist SLA fields for %s: %s", incident_id, exc)


def _send_escalation_alert(state: AgentState, reason: str) -> None:
    """Send an escalation notification via Slack/Teams."""
    try:
        from agents.workflow import _send_event_notification
        _send_event_notification(
            event="Escalation Alert",
            incident_id=state.get('incident_id', ''),
            severity=state.get('severity', 'HIGH'),
            app_name=state.get('app_name', ''),
            environment=state.get('environment', ''),
            details=(
                f"⚠️ ESCALATION: {reason}\n"
                f"Incident: {state.get('error_title', 'Unknown')}\n"
                f"Application: {state.get('app_name', '')}\n"
                f"Severity: {state.get('severity', 'HIGH')}"
            ),
            project_id=state.get('project_id'),
        )
    except Exception as exc:
        logger.debug("[Escalation] Could not send escalation notification: %s", exc)
