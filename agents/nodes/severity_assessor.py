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
"""Severity assessment node - determines if auto-fix should be triggered."""
import logging
from agents.state import AgentState
from agents.nodes.node_utils import mark_step_complete
from utils.severity_analyzer import SeverityAnalyzer
from storage.models import Severity

logger = logging.getLogger(__name__)


def assess_severity_node(state: AgentState) -> AgentState:
    """
    Assess error severity and determine if auto-fix workflow should proceed.
    
    This node:
    1. Uses OTLP severity if available, otherwise keyword-based classification
    2. Determines if auto-fix should be triggered
    3. Sets requires_approval flag based on severity
    
    Args:
        state: Current agent state
        
    Returns:
        Updated state with severity assessment results
    """
    logger.info(f"[Severity Assessment] Processing incident {state['incident_id']}")
    
    # Extract technology from metadata (set by OTLP parser)
    metadata = state.get('metadata') or {}
    source_technology = metadata.get('source_technology')

    # Pass project_id so the analyzer can use LLM classification
    analyzer = SeverityAnalyzer(project_id=state.get('project_id'))

    # Check if severity was already provided from OTLP
    existing_severity = state.get('severity')

    if existing_severity and existing_severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        # Use OTLP severity - DO NOT override with LLM (OTLP signal is ground truth)
        try:
            severity = Severity[existing_severity]
            confidence = 1.0
            logger.info(f"[Severity Assessment] Using OTLP severity: {severity.value}")
        except (KeyError, ValueError):
            logger.warning(f"[Severity Assessment] Invalid OTLP severity '{existing_severity}', re-analyzing")
            severity, confidence = analyzer.analyze_severity(
                error_title=state['error_title'],
                error_description=state['error_description'],
                stack_trace=state['stack_trace'],
                app_name=state.get('app_name'),
                environment=state.get('environment'),
                source_technology=source_technology,
            )
    else:
        # No OTLP severity — use LLM-first analyzer
        logger.info("[Severity Assessment] No OTLP severity found, running LLM+heuristic analysis...")
        severity, confidence = analyzer.analyze_severity(
            error_title=state['error_title'],
            error_description=state['error_description'],
            stack_trace=state['stack_trace'],
            app_name=state.get('app_name'),
            environment=state.get('environment'),
            source_technology=source_technology,
        )
    
    # Check if auto-fix should be triggered
    should_fix, reason = analyzer.should_auto_fix(
        severity=severity,
        recent_error_count=0,  # TODO: Query from database
        is_duplicate=state['is_duplicate']
    )
    
    # Update state
    state['severity'] = severity.value
    state['requires_approval'] = severity in [Severity.HIGH, Severity.CRITICAL]

    # Update workflow tracking + persist to DB in a single call
    mark_step_complete(state, 'assess_severity', extra_db_updates={'severity': severity.value})
    
    if should_fix:
        state['messages'] = [
            f"✓ Severity assessed as {severity.value} (confidence: {confidence:.2f})",
            f"Auto-fix triggered: {reason}"
        ]
        logger.info(f"[Severity Assessment] Auto-fix triggered for {state['incident_id']}: {reason}")
    else:
        state['messages'] = [
            f"✓ Severity assessed as {severity.value} (confidence: {confidence:.2f})",
            f"Auto-fix NOT triggered: {reason}"
        ]
        logger.info(f"[Severity Assessment] Auto-fix skipped for {state['incident_id']}: {reason}")

    # Send "Incident Created" notification so the team is alerted immediately
    try:
        from agents.workflow import _send_event_notification
        _send_event_notification(
            event="Incident Created",
            incident_id=state['incident_id'],
            severity=severity.value,
            app_name=state.get('app_name', ''),
            environment=state.get('environment', ''),
            details=(
                f"New incident detected: {state.get('error_title', 'Unknown')}\n"
                f"Severity: {severity.value}\n"
                f"Auto-fix: {'triggered' if should_fix else 'not triggered'} — {reason}"
            ),
            project_id=state.get('project_id'),
        )
    except Exception as _notify_err:
        logger.warning("[Severity Assessment] Could not send incident-created notification: %s", _notify_err)

    return state
