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
from __future__ import annotations

"""
Shared utilities for workflow node implementations.

Provides reusable helpers that eliminate boilerplate repeated across every
workflow node:

  1. ``mark_step_complete(state, step_name, extra_db_updates)``
     — Updates workflow tracking fields in state AND persists them to the DB
       in a single call.  Replaces the ~8-line pattern that appears in every
       workflow node.

  2. ``safe_int(value)`` / ``safe_float(value)``
     — Null-safe numeric coercions used in quality score handling.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from agents.state import AgentState, WORKFLOW_TOTAL_STEPS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Workflow step tracking helper
# ---------------------------------------------------------------------------

def mark_step_complete(
    state: AgentState,
    step_name: str,
    extra_db_updates: Optional[Dict[str, Any]] = None,
) -> AgentState:
    """
    Mark a workflow step as complete and persist tracking data to the DB.

    This helper replaces the following ~15-line boilerplate that previously
    appeared verbatim in every workflow node:

        completed_steps = list(state.get('workflow_completed_steps') or [])
        if step_name not in completed_steps:
            completed_steps.append(step_name)
        state['workflow_completed_steps'] = completed_steps
        state['workflow_progress_pct'] = len(completed_steps) / WORKFLOW_TOTAL_STEPS
        state['current_node'] = step_name
        state['updated_at'] = datetime.utcnow().isoformat()
        try:
            from storage.database import get_session
            from storage.incident_repository import IncidentRepository
            with get_session() as session:
                repo = IncidentRepository(session)
                repo.update(
                    incident_id=state['incident_id'],
                    current_workflow_node=step_name,
                    workflow_completed_steps=completed_steps,
                    workflow_progress_pct=state['workflow_progress_pct'],
                )
        except Exception as db_error:
            logger.warning("Failed to update workflow progress in DB: %s", db_error)

    Args:
        state:             Current AgentState dict (mutated in place and returned).
        step_name:         The canonical step ID (e.g. 'generate_rca').
        extra_db_updates:  Optional extra fields to persist in the same DB call
                           (e.g. ``{'rca_text': ..., 'rca_confidence': ...}``).

    Returns:
        The mutated state dict (same object, also modified in place).
    """
    # ── 1. Update in-memory state ────────────────────────────────────────────
    completed_steps: list = list(state.get("workflow_completed_steps") or [])
    if step_name not in completed_steps:
        completed_steps.append(step_name)

    state["workflow_completed_steps"] = completed_steps
    state["workflow_progress_pct"] = len(completed_steps) / WORKFLOW_TOTAL_STEPS
    state["current_node"] = step_name
    state["updated_at"] = datetime.utcnow().isoformat()

    # ── 2. Persist to DB (best-effort — never blocks the workflow) ────────────
    try:
        from storage.database import get_session
        from storage.incident_repository import IncidentRepository

        db_updates: Dict[str, Any] = {
            "current_workflow_node": step_name,
            "workflow_completed_steps": completed_steps,
            "workflow_progress_pct": state["workflow_progress_pct"],
        }
        if extra_db_updates:
            db_updates.update(extra_db_updates)

        with get_session() as session:
            repo = IncidentRepository(session)
            repo.update(incident_id=state["incident_id"], **db_updates)

    except Exception as db_error:
        logger.warning(
            "Failed to persist workflow step '%s' for incident %s: %s",
            step_name,
            state.get("incident_id"),
            db_error,
        )

    return state


# ---------------------------------------------------------------------------
# Null-safe numeric coercions
# ---------------------------------------------------------------------------

def safe_float(value: Any, default: float = 0.0) -> float:
    """Return ``float(value)`` or ``default`` if value is None / unconvertible."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Return ``int(value)`` or ``default`` if value is None / unconvertible."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# DB update helper (fire-and-forget)
# ---------------------------------------------------------------------------

def update_incident_db(incident_id: str, **kwargs: Any) -> None:
    """
    Persist arbitrary fields to the incidents table (best-effort).

    Use this instead of the verbose try/except pattern when you need to save
    data that is NOT part of standard workflow progress tracking:

        # Before:
        try:
            from storage.database import get_session
            from storage.incident_repository import IncidentRepository
            with get_session() as session:
                repo = IncidentRepository(session)
                repo.update(incident_id=incident_id, rca_text=rca_text, ...)
        except Exception as db_error:
            logger.warning(...)

        # After:
        update_incident_db(incident_id, rca_text=rca_text, rca_confidence=confidence)
    """
    if not kwargs:
        return
    try:
        from storage.database import get_session
        from storage.incident_repository import IncidentRepository

        with get_session() as session:
            repo = IncidentRepository(session)
            repo.update(incident_id=incident_id, **kwargs)
    except Exception as exc:
        logger.warning(
            "Failed to persist DB update for incident %s (%s): %s",
            incident_id,
            list(kwargs.keys()),
            exc,
        )
