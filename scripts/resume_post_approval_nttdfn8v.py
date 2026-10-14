"""
Resume post-approval workflow for stuck incident NTTDFN8V.

This incident was approved at 2026-10-13 10:11 but the post-approval workflow
(Jira creation, PR creation, finalize) was never triggered because api_approve
did not call run_post_approval_workflow — a bug now fixed in ui/server.py.

Run this script once to manually trigger the post-approval steps:
    python scripts/resume_post_approval_nttdfn8v.py
"""
import sys
import logging

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

INCIDENT_ID = "NTTDFN8V"


def main() -> None:
    from storage.database import get_session
    from storage.incident_repository import IncidentRepository

    # Verify the incident exists and is approved
    with get_session() as session:
        repo = IncidentRepository(session)
        inc = repo.get_by_id(INCIDENT_ID)
        if not inc:
            logger.error("Incident %s not found in database.", INCIDENT_ID)
            sys.exit(1)

        approval_status = getattr(inc, "approval_status", None)
        status = getattr(inc, "status", None)
        pr_url = getattr(inc, "pr_url", None)
        jira_url = getattr(inc, "jira_ticket_url", None)

        logger.info("Incident %s — status=%s approval_status=%s", INCIDENT_ID, status, approval_status)

        if approval_status != "approved":
            logger.error(
                "Incident %s is not in approved state (approval_status=%s). "
                "Approve it via the UI first.",
                INCIDENT_ID, approval_status,
            )
            sys.exit(1)

        if pr_url:
            logger.info("Incident %s already has a PR: %s — nothing to do.", INCIDENT_ID, pr_url)
            sys.exit(0)

        if jira_url:
            logger.info("Jira ticket already created: %s", jira_url)

        project_id = getattr(inc, "project_id", None)

    logger.info("Triggering post-approval workflow for %s (project_id=%s) ...", INCIDENT_ID, project_id)

    try:
        from agents.workflow import run_post_approval_workflow

        final_state = run_post_approval_workflow(
            incident_id=INCIDENT_ID,
            project_id=project_id,
            trigger_source="operator_recovery",
            triggered_by="script:resume_post_approval_nttdfn8v",
            recovery_reason="Manual resume — post-approval workflow was not triggered after initial approval due to missing workflow trigger in api_approve.",
        )

        error = final_state.get("error_message")
        if error:
            logger.error("Post-approval workflow completed with error: %s", error)
            sys.exit(1)

        jira_key  = final_state.get("jira_ticket_key")
        jira_url  = final_state.get("jira_ticket_url")
        pr_url    = final_state.get("pr_url")
        pr_number = final_state.get("pr_number")
        branch    = final_state.get("fix_branch") or final_state.get("branch_name")

        print("\n" + "=" * 60)
        print("POST-APPROVAL WORKFLOW RESULTS")
        print("=" * 60)
        print(f"Incident   : {INCIDENT_ID}")
        print(f"Jira ticket: {jira_key} — {jira_url or 'N/A'}")
        print(f"PR         : #{pr_number} — {pr_url or 'N/A'}")
        print(f"Branch     : {branch or 'N/A'}")
        print("=" * 60)

        if jira_url or pr_url:
            logger.info("✓ Post-approval workflow completed successfully for %s", INCIDENT_ID)
        else:
            logger.warning(
                "Workflow completed but no Jira/PR was created for %s. "
                "Check that Jira and GitHub integrations are configured for the project.",
                INCIDENT_ID,
            )

    except Exception as exc:
        logger.error("Post-approval workflow failed for %s: %s", INCIDENT_ID, exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
