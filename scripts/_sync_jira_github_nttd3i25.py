"""
Repair script for incident NTTD3I25 (Jira: SCRUM-7):
  - Pushes existing GitHub branch / commit / PR details into the Jira
    Development panel via the DevInfo API and web-links fallback.
  - Appends a "GitHub Links" section to the Jira ticket description.

Run once to restore the missing Development panel entries on SCRUM-7.
"""
import sys
import logging

sys.path.insert(0, ".")

from storage.database import get_session
from storage.incident_repository import IncidentRepository
from integrations.jira_client import JiraClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

INCIDENT_ID = "NTTD3I25"


def sync():
    logger.info("── JIRA↔GitHub sync repair for incident %s ──", INCIDENT_ID)

    # ── 1. Load incident record ────────────────────────────────────────────────
    with get_session() as session:
        repo = IncidentRepository(session)
        inc = repo.get_by_id(INCIDENT_ID)
        if not inc:
            logger.error("Incident %s not found in database", INCIDENT_ID)
            sys.exit(1)

        ticket_key      = getattr(inc, "jira_ticket_key",  None)
        ticket_url      = getattr(inc, "jira_ticket_url",  None)
        repo_full_name  = getattr(inc, "repo_full_name",   None)
        fix_branch      = getattr(inc, "fix_branch",       None)
        commit_sha      = getattr(inc, "commit_sha",       None)
        commit_url      = getattr(inc, "commit_url",       None)
        pr_url          = getattr(inc, "pr_url",           None)
        pr_number       = getattr(inc, "pr_number",        None)
        error_file_path = getattr(inc, "error_file_path",  None)
        error_title     = getattr(inc, "error_title",      None)
        project_id      = getattr(inc, "project_id",       None)

    # ── 2. Validate we have enough data to sync ────────────────────────────────
    logger.info("Jira ticket : %s  (%s)", ticket_key, ticket_url)
    logger.info("Repo        : %s", repo_full_name)
    logger.info("Branch      : %s", fix_branch)
    logger.info("Commit SHA  : %s", commit_sha)
    logger.info("Commit URL  : %s", commit_url)
    logger.info("PR URL      : %s  (PR #%s)", pr_url, pr_number)

    if not ticket_key:
        logger.error("No Jira ticket key stored for incident %s — cannot sync", INCIDENT_ID)
        sys.exit(1)

    if not repo_full_name:
        logger.error("No repo_full_name stored for incident %s — cannot sync", INCIDENT_ID)
        sys.exit(1)

    if not any([fix_branch, commit_sha, pr_url]):
        logger.error(
            "No GitHub artefacts (branch / commit / PR) found for incident %s",
            INCIDENT_ID,
        )
        sys.exit(1)

    # ── 3. Initialise Jira client ──────────────────────────────────────────────
    try:
        jira_client = JiraClient(project_id=project_id)
    except ValueError as exc:
        logger.error("Jira not configured for project '%s': %s", project_id, exc)
        sys.exit(1)

    # ── 4. Push GitHub links to Jira Development panel + web links ────────────
    pr_title = f"[Auto-Fix] Incident #{INCIDENT_ID}: {error_title or 'Fix'}" if pr_number else None
    commit_message = (
        f"{ticket_key}: Fix: {error_title}" if error_title else f"{ticket_key}: auto-generated fix"
    )

    logger.info("Calling sync_all_dev_links for %s …", ticket_key)
    results = jira_client.sync_all_dev_links(
        ticket_key=ticket_key,
        repo_full_name=repo_full_name,
        branch_name=fix_branch,
        commit_sha=commit_sha,
        commit_url=commit_url,
        commit_message=commit_message,
        pr_url=pr_url,
        pr_number=pr_number,
        pr_title=pr_title,
        file_path=error_file_path,
    )

    logger.info("sync_all_dev_links results:")
    logger.info("  dev_info    : %s", results.get("dev_info"))
    logger.info("  branch_link : %s", results.get("branch_link"))
    logger.info("  commit_link : %s", results.get("commit_link"))
    logger.info("  pr_link     : %s", results.get("pr_link"))

    # ── 5. Update Jira ticket description with clickable GitHub links ──────────
    logger.info("Calling update_description_with_github_links for %s …", ticket_key)
    desc_ok = jira_client.update_description_with_github_links(
        ticket_key=ticket_key,
        repo_full_name=repo_full_name,
        branch_name=fix_branch,
        commit_sha=commit_sha,
        commit_url=commit_url,
        pr_url=pr_url,
        pr_number=pr_number,
    )
    logger.info("  description updated : %s", desc_ok)

    # ── 6. Summary ─────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("SYNC SUMMARY")
    print("=" * 60)
    print(f"Incident  : {INCIDENT_ID}")
    print(f"Jira      : {ticket_key}  {ticket_url or ''}")
    print(f"Branch    : {fix_branch or '—'}")
    print(f"Commit    : {(commit_sha or '')[:7] or '—'}")
    print(f"PR        : #{pr_number or '—'}  {pr_url or ''}")
    print()
    print("Results:")
    print(f"  DevInfo API synced : {results.get('dev_info')}")
    print(f"  Branch web-link    : {results.get('branch_link')}")
    print(f"  Commit web-link    : {results.get('commit_link')}")
    print(f"  PR web-link        : {results.get('pr_link')}")
    print(f"  Description update : {desc_ok}")
    print()

    any_success = desc_ok or any(results.values())
    if any_success:
        print("[OK] At least one sync method succeeded.")
        print(f"     Open the ticket to verify: {ticket_url or f'<jira_url>/browse/{ticket_key}'}")
    else:
        print("[FAIL] All sync methods failed -- check Jira credentials and API permissions.")
        sys.exit(1)


if __name__ == "__main__":
    sync()
