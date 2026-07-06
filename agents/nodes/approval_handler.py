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
"""Human approval workflow handler node."""
import logging
from datetime import datetime
from agents.state import AgentState
from agents.nodes.node_utils import mark_step_complete
from storage.database import get_session
from storage.incident_repository import IncidentRepository

logger = logging.getLogger(__name__)


def await_approval_node(state: AgentState) -> AgentState:
    """
    Handle human approval workflow.
    
    This node:
    1. Sets incident status to "pending_approval" in database
    2. For POC: Returns immediately (approval handled via API)
    3. In production: Would poll database or wait for webhook
    
    The actual approval/rejection is handled via:
    - Dashboard UI "Approve/Reject" buttons
    - API endpoint POST /incidents/{id}/approve
    
    Args:
        state: Current agent state
        
    Returns:
        Updated state with approval status
    """
    logger.info(f"[Approval Handler] Awaiting approval for incident {state['incident_id']}")
    
    try:
        # Update database status to pending_approval
        with get_session() as session:
            repo = IncidentRepository(session)
            update_data = {
                'status': 'PENDING_APPROVAL',
                'rca_text': state.get('rca_text'),
                'proposed_fix': state.get('proposed_fix'),
                'fix_explanation': state.get('fix_explanation')
            }
            
            # Ensure PDF path is persisted if it was generated
            if state.get('pdf_path'):
                update_data['pdf_path'] = state.get('pdf_path')
                logger.info(f"[Approval Handler] Saving PDF path to database: {state.get('pdf_path')}")
            
            # Ensure patch path is persisted if it was generated
            if state.get('patch_path'):
                update_data['patch_path'] = state.get('patch_path')
            
            repo.update(incident_id=state['incident_id'], **update_data)
        
        # For POC: Mark as needing approval and pause workflow
        # In production with LangGraph checkpointing, this would create a breakpoint
        state['approval_status'] = 'pending'
        state['current_node'] = 'await_approval'
        state['updated_at'] = datetime.utcnow().isoformat()
        
        # Update workflow tracking + persist to DB in a single call
        mark_step_complete(state, 'await_approval')
        
        quality_score = (state.get('overall_quality_score') or 0.0)
        state['messages'] = state.get('messages', []) + [
            f"⏸️ Awaiting human approval (quality score: {quality_score:.2f})",
            f"Requires approval: {state['requires_approval']}"
        ]
        
        logger.info(f"[Approval Handler] Incident {state['incident_id']} awaiting approval")

        # Send a "Pending Approval" notification with a deep-link to the incident UI
        try:
            from agents.workflow import _send_event_notification
            from config.settings import get_settings as _get_settings

            _settings = _get_settings()
            ui_base_url = getattr(_settings, "ui_base_url", "http://localhost:8080").rstrip("/")
            incident_url = f"{ui_base_url}/incidents/{state['incident_id']}"

            rca_preview = (state.get('rca_text') or '')[:300]
            quality_score = state.get('overall_quality_score', 0) or 0
            recommendation = state.get('quality_recommendation', 'MANUAL_REVIEW') or 'MANUAL_REVIEW'

            _send_event_notification(
                event="⏸️ Pending Approval — Review Required",
                incident_id=state['incident_id'],
                severity=state.get('severity', 'HIGH'),
                app_name=state.get('app_name', ''),
                environment=state.get('environment', ''),
                details=(
                    f"Incident **{state['incident_id']}** is awaiting human approval.\n"
                    f"Quality score: {quality_score:.2f}  |  Recommendation: {recommendation}\n\n"
                    f"**Review & Approve:** {incident_url}\n\n"
                    f"Root Cause Preview:\n{rca_preview}{'...' if len(rca_preview) >= 300 else ''}"
                ),
                project_id=state.get('project_id'),
            )
        except Exception as _notify_err:
            logger.warning("[Approval Handler] Could not send pending-approval notification: %s", _notify_err)
        
    except Exception as e:
        logger.error(f"[Approval Handler] Failed for {state['incident_id']}: {str(e)}")
        state['error_message'] = f"Approval handler failed: {str(e)}"
        state['messages'] = state.get('messages', []) + [
            f"Approval handler failed: {str(e)}"
        ]
    
    return state
