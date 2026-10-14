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
"""Jira integration client — credentials loaded exclusively from project DB config."""
import base64
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from atlassian import Jira

from integrations.errors import (
    IntegrationAuthError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationTransientError,
    classify_integration_error,
    is_retryable_integration_error,
)
from integrations.verification import request as integration_request, tls_verify_value
from utils.retry_handler import retry_with_backoff

logger = logging.getLogger(__name__)

_RETRYABLE_JIRA_ERRORS = (
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationTransientError,
)


def _handle_jira_error(operation: str, exc: Exception, fallback: Any) -> Any:
    """Classify a Jira failure; re-raise authentication and retryable errors."""
    classified = classify_integration_error(
        "Jira",
        exc,
        status_code=getattr(exc, "status_code", None),
    )
    logger.error("Jira %s failed (%s): %s", operation, type(classified).__name__, classified)
    if is_retryable_integration_error(classified) or isinstance(classified, IntegrationAuthError):
        raise classified from exc
    return fallback


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with timezone offset."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


class JiraClient:
    """
    Jira client for incident ticket management.

    All credentials are loaded from the per-project DB config (stored encrypted).
    No fallback to environment variables or settings.py.
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        url: Optional[str] = None,
        username: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        self.project_id = project_id
        project_cfg = self._load_project_jira_config(project_id)

        self.url = (url or project_cfg.get("base_url") or "").strip().rstrip("/")
        self.username = (username or project_cfg.get("username") or "").strip()
        self.api_token = (api_token or project_cfg.get("api_token") or "").strip()
        self.jira_project_key = (project_cfg.get("project_key") or "").strip()
        # Configurable issue type with a sensible default of "Bug".
        # Override via Team Admin → Project Configuration → Jira → issue_type.
        self.jira_issue_type = (project_cfg.get("issue_type") or "Bug").strip()

        if not self.url or not self.username or not self.api_token or not self.jira_project_key:
            missing = [
                field for field, val in (
                    ("Jira URL", self.url),
                    ("username", self.username),
                    ("API token", self.api_token),
                    ("project key", self.jira_project_key),
                ) if not val
            ]
            raise ValueError(
                "Jira credentials not configured"
                + (f" for project '{project_id}'" if project_id else "")
                + f" — missing: {', '.join(missing)}. "
                "Configure via Team Admin → Project Configuration → Jira."
            )

        try:
            _verify_ssl = tls_verify_value()
            if _verify_ssl is False:
                # Suppress urllib3 InsecureRequestWarning when the administrator
                # has explicitly opted into unverified TLS (e.g. Zscaler proxy).
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.client = Jira(
                url=self.url,
                username=self.username,
                password=self.api_token,
                cloud=True,
                verify_ssl=_verify_ssl,
            )
            logger.info("Jira client initialised for %s", self.url)
        except Exception as exc:
            logger.error("Failed to initialise Jira client: %s", exc)
            raise

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_project_jira_config(self, project_id: Optional[str]) -> dict:
        if not project_id:
            return {}
        try:
            from storage.auth_store import get_project_config
            config = get_project_config(project_id) or {}
            return config.get("jira") or {}
        except Exception as exc:
            logger.warning("Failed to load project Jira config for %s: %s", project_id, exc)
            return {}

    def _basic_auth_headers(self) -> Dict[str, str]:
        """HTTP headers carrying Basic auth credentials for direct REST calls."""
        token = base64.b64encode(f"{self.username}:{self.api_token}".encode()).decode()
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── Ticket operations ─────────────────────────────────────────────────────

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        exceptions=_RETRYABLE_JIRA_ERRORS,
    )
    def create_incident_ticket(
        self,
        incident_id: str,
        app_name: str,
        environment: str,
        error_title: str,
        error_description: str,
        severity: str,
        stack_trace: Optional[str] = None,
        rca_text: Optional[str] = None,
        proposed_fix: Optional[str] = None,
        pr_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a Jira ticket for an incident."""
        priority_map = {
            "CRITICAL": "Highest",
            "HIGH": "High",
            "MEDIUM": "Medium",
            "LOW": "Low",
        }
        priority = priority_map.get(severity, "Medium")

        description = self._build_ticket_description(
            incident_id=incident_id,
            app_name=app_name,
            environment=environment,
            error_description=error_description,
            stack_trace=stack_trace,
            rca_text=rca_text,
            proposed_fix=proposed_fix,
            pr_url=pr_url,
        )

        def _sanitize(value: str) -> str:
            return " ".join(value.replace("\r", "").replace("\n", " ").split())

        issue_dict: dict = {
            "project": {"key": self.jira_project_key},
            "summary": (
                f"[{_sanitize(app_name)}] {_sanitize(error_title)}"
                f" (Incident #{incident_id})"
            ),
            "description": description,
            "issuetype": {"name": self.jira_issue_type},
            "priority": {"name": priority},
            "labels": [
                "auto-generated",
                "prism",
                f"incident-{incident_id}",
                f"app-{_sanitize(app_name).lower().replace(' ', '-')}",
                f"env-{_sanitize(environment).lower()}",
                f"severity-{_sanitize(severity).lower()}",
            ],
        }

        try:
            issue = self.client.issue_create(fields=issue_dict)
            ticket_key = issue["key"]
            ticket_url = f"{self.url}/browse/{ticket_key}"
            logger.info("Created Jira ticket %s for incident %s", ticket_key, incident_id)
            return {
                "ticket_key": ticket_key,
                "ticket_id": issue["id"],
                "ticket_url": ticket_url,
            }
        except Exception as exc:
            return _handle_jira_error("ticket creation", exc, None)

    def _build_ticket_description(
        self,
        incident_id: str,
        app_name: str,
        environment: str,
        error_description: str,
        stack_trace: Optional[str] = None,
        rca_text: Optional[str] = None,
        proposed_fix: Optional[str] = None,
        pr_url: Optional[str] = None,
    ) -> str:
        parts = [
            "h2. Incident Summary",
            f"*Incident ID:* {incident_id}",
            f"*Application:* {app_name}",
            f"*Environment:* {environment}",
            "*Auto-detected by:* Prism AI",
            "",
            "h2. Error Description",
            error_description,
            "",
        ]
        if stack_trace:
            parts += ["h2. Stack Trace", "{code:java}", stack_trace[:2000], "{code}", ""]
        if rca_text:
            parts += ["h2. Root Cause Analysis", rca_text, ""]
        if proposed_fix:
            parts += ["h2. Proposed Fix", proposed_fix[:1000], ""]
        if pr_url:
            parts += [
                "h2. Pull Request",
                "A fix has been automatically generated and submitted:",
                f"[View Pull Request|{pr_url}]",
                "",
            ]
        parts += [
            "----",
            "_This ticket was automatically created by Prism AI."
            " Please review and verify the analysis._",
        ]
        return "\n".join(parts)

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        exceptions=_RETRYABLE_JIRA_ERRORS,
    )
    def add_comment(self, ticket_key: str, comment: str) -> bool:
        try:
            self.client.issue_add_comment(ticket_key, comment)
            logger.info("Added comment to %s", ticket_key)
            return True
        except Exception as exc:
            return _handle_jira_error(f"add comment to {ticket_key}", exc, False)

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        exceptions=_RETRYABLE_JIRA_ERRORS,
    )
    def update_status(self, ticket_key: str, status: str) -> bool:
        try:
            transitions = self.client.get_issue_transitions(ticket_key)
            transition_id = next(
                (t["id"] for t in transitions if t["name"].lower() == status.lower()),
                None,
            )
            if not transition_id:
                logger.warning("Status '%s' not found for %s", status, ticket_key)
                return False
            self.client.issue_transition(ticket_key, transition_id)
            logger.info("Updated %s status to %s", ticket_key, status)
            return True
        except Exception as exc:
            return _handle_jira_error(f"update status for {ticket_key}", exc, False)

    def link_to_pr(self, ticket_key: str, pr_url: str) -> bool:
        comment = (
            "h3. Pull Request Created\n\n"
            "A fix has been automatically generated:\n"
            f"[View Pull Request|{pr_url}]\n\n"
            "_Please review the changes before merging._"
        )
        return self.add_comment(ticket_key, comment)

    def add_rca_update(
        self,
        ticket_key: str,
        rca_text: str,
        confidence: Optional[float] = None,
    ) -> bool:
        confidence_str = f" (Confidence: {confidence:.1%})" if confidence else ""
        comment = f"h3. Root Cause Analysis{confidence_str}\n\n{rca_text}"
        return self.add_comment(ticket_key, comment)

    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        exceptions=_RETRYABLE_JIRA_ERRORS,
    )
    def get_ticket(self, ticket_key: str) -> Optional[Dict[str, Any]]:
        try:
            issue = self.client.issue(ticket_key)
            return {
                "key": issue["key"],
                "id": issue["id"],
                "summary": issue["fields"]["summary"],
                "status": issue["fields"]["status"]["name"],
                "priority": issue["fields"]["priority"]["name"],
                "assignee": (issue["fields"].get("assignee") or {}).get("displayName"),
                "created": issue["fields"]["created"],
                "updated": issue["fields"]["updated"],
                "url": f"{self.url}/browse/{issue['key']}",
            }
        except Exception as exc:
            return _handle_jira_error(f"get ticket {ticket_key}", exc, None)

    def search_incidents(
        self,
        app_name: Optional[str] = None,
        environment: Optional[str] = None,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        try:
            jql_parts = [f"project = {self.jira_project_key}", 'labels = "prism"']
            if app_name:
                jql_parts.append(
                    f'labels = "app-{app_name.lower().replace(" ", "-")}"'
                )
            if environment:
                jql_parts.append(f'labels = "env-{environment.lower()}"')
            jql = " AND ".join(jql_parts) + " ORDER BY created DESC"

            issues = self.client.jql(jql, limit=max_results)
            results = [
                {
                    "key": issue["key"],
                    "summary": issue["fields"]["summary"],
                    "status": issue["fields"]["status"]["name"],
                    "created": issue["fields"]["created"],
                    "url": f"{self.url}/browse/{issue['key']}",
                }
                for issue in issues.get("issues", [])
            ]
            logger.info("Found %d tickets matching criteria", len(results))
            return results
        except Exception as exc:
            logger.error("Failed to search tickets: %s", exc)
            return []

    # ── Jira ticket description update with GitHub links ─────────────────────

    def update_description_with_github_links(
        self,
        ticket_key: str,
        repo_full_name: Optional[str] = None,
        branch_name: Optional[str] = None,
        commit_sha: Optional[str] = None,
        commit_url: Optional[str] = None,
        pr_url: Optional[str] = None,
        pr_number: Optional[int] = None,
    ) -> bool:
        """
        Append a *GitHub Links* section to the existing Jira ticket description.

        Called after PR/branch/commit creation so the ticket body contains
        direct clickable hyperlinks to every GitHub artefact.  Uses the Jira
        REST API v2 PUT endpoint so it works on both Jira Cloud and Server.

        Returns True when the description was successfully updated.
        """
        if not any([branch_name, commit_sha, pr_url]):
            logger.debug(
                "update_description_with_github_links: no GitHub artefacts for %s — skipping",
                ticket_key,
            )
            return False

        try:
            repo_url = f"https://github.com/{repo_full_name}" if repo_full_name else ""
            _gh_marker = "h2. GitHub Links"

            # Build the GitHub links section using Jira Wiki Markup
            github_parts: list = ["", "----", _gh_marker]
            if branch_name and repo_url:
                github_parts.append(
                    f"*Fix Branch:* [{branch_name}|{repo_url}/tree/{branch_name}]"
                )
            if commit_sha:
                short_sha = str(commit_sha)[:7]
                if commit_url:
                    github_parts.append(f"*Commit:* [{short_sha}|{commit_url}]")
                else:
                    github_parts.append(f"*Commit:* {short_sha}")
            if pr_url and pr_number:
                github_parts.append(f"*Pull Request:* [PR #{pr_number}|{pr_url}]")
            elif pr_url:
                github_parts.append(f"*Pull Request:* [View PR|{pr_url}]")
            if repo_url and repo_full_name:
                github_parts.append(f"*Repository:* [{repo_full_name}|{repo_url}]")

            github_section = "\n".join(github_parts)

            # Fetch the current description so we can append (or replace the section)
            try:
                issue = self.client.issue(ticket_key)
                current_desc: str = (
                    (issue.get("fields") or {}).get("description") or ""
                )
            except Exception as _fetch_exc:
                logger.warning(
                    "update_description_with_github_links: could not fetch description "
                    "for %s: %s — will append fresh section",
                    ticket_key, _fetch_exc,
                )
                current_desc = ""

            # If a previous GitHub Links section exists, replace it; otherwise append.
            if _gh_marker in current_desc:
                new_desc = current_desc[: current_desc.index(_gh_marker)].rstrip()
                new_desc = new_desc + github_section
            else:
                new_desc = current_desc.rstrip() + github_section

            resp = integration_request(
                "PUT",
                f"{self.url}/rest/api/2/issue/{ticket_key}",
                json={"fields": {"description": new_desc}},
                headers=self._basic_auth_headers(),
                timeout=15,
            )

            if resp.status_code in (200, 204):
                logger.info(
                    "GitHub links added to Jira ticket %s description "
                    "(branch=%s commit=%s pr=%s)",
                    ticket_key, branch_name, commit_sha, pr_number,
                )
                return True

            logger.warning(
                "update_description_with_github_links: Jira API returned %s for %s: %s",
                resp.status_code, ticket_key, resp.text[:200],
            )
            return False

        except Exception as exc:
            logger.error(
                "Failed to update description with GitHub links for %s: %s",
                ticket_key, exc,
            )
            return False

    # ── Jira Development Information API ─────────────────────────────────────

    def sync_development_info(
        self,
        ticket_key: str,
        repo_full_name: str,
        branch_name: Optional[str] = None,
        commit_sha: Optional[str] = None,
        commit_url: Optional[str] = None,
        commit_message: Optional[str] = None,
        pr_url: Optional[str] = None,
        pr_number: Optional[int] = None,
        pr_title: Optional[str] = None,
        file_path: Optional[str] = None,
        base_branch: str = "main",
    ) -> bool:
        """
        Push branch/commit/PR details into the Jira Development panel via
        the Jira Software Development Information API (devinfo/0.10).

        NOTE: On Jira Cloud, the devinfo/0.10/bulk endpoint requires an
        Atlassian Connect app OAuth token — Basic Auth is NOT accepted and
        will return 400/401/403.  When that happens this method returns False
        and sync_all_dev_links() falls back to create_remote_link() which
        creates clickable "Web Links" on the ticket using the standard REST
        API (which DOES accept Basic Auth).

        The Development panel in Jira Cloud can only be populated through the
        GitHub for Jira marketplace app or an equivalent OAuth Connect app.
        """
        try:
            repo_parts = repo_full_name.split("/", 1)
            repo_owner = repo_parts[0] if len(repo_parts) == 2 else ""
            repo_name = repo_parts[1] if len(repo_parts) == 2 else repo_full_name
            repo_url = f"https://github.com/{repo_full_name}"
            update_seq = int(time.time() * 1000)
            now_iso = _utc_now_iso()

            # ── Commit object ──────────────────────────────────────────────
            commit_objects: list = []
            if commit_sha:
                commit_obj: dict = {
                    "id": commit_sha,
                    "issueKeys": [ticket_key],
                    "message": commit_message or f"{ticket_key}: auto-generated fix",
                    "timestamp": now_iso,
                    "url": commit_url or f"{repo_url}/commit/{commit_sha}",
                    "author": {
                        "name": "Prism AI",
                        "email": "prism-ai@prism.local",
                    },
                    "fileCount": 1 if file_path else 0,
                    "updateSequenceId": update_seq,
                }
                if file_path:
                    blob_base = commit_sha if commit_sha else base_branch
                    commit_obj["files"] = [
                        {
                            "path": file_path,
                            "url": f"{repo_url}/blob/{blob_base}/{file_path}",
                            "changeType": "MODIFIED",
                        }
                    ]
                commit_objects.append(commit_obj)

            # ── Branch object ──────────────────────────────────────────────
            branch_objects: list = []
            if branch_name:
                branch_obj: dict = {
                    "id": branch_name,
                    "issueKeys": [ticket_key],
                    "name": branch_name,
                    "url": f"{repo_url}/tree/{branch_name}",
                    "createPullRequestUrl": (
                        f"{repo_url}/compare/{branch_name}?expand=1"
                    ),
                    "updateSequenceId": update_seq,
                }
                if commit_objects:
                    branch_obj["lastCommit"] = commit_objects[0]
                branch_objects.append(branch_obj)

            # ── Pull-request object ────────────────────────────────────────
            pr_objects: list = []
            if pr_url and pr_number:
                pr_obj: dict = {
                    "id": str(pr_number),
                    # displayId is the human-readable label shown in the panel
                    # (e.g. "#42").  Without it some Jira instances fall back to
                    # the raw `id` value which can look confusing.
                    "displayId": f"#{pr_number}",
                    "issueKeys": [ticket_key],
                    "title": pr_title or f"{ticket_key}: auto-generated fix",
                    "status": "OPEN",
                    "sourceBranch": branch_name or "",
                    "sourceBranchUrl": (
                        f"{repo_url}/tree/{branch_name}" if branch_name else ""
                    ),
                    "destinationBranch": base_branch,
                    "url": pr_url,
                    "reviewers": [],
                    "author": {
                        "name": "Prism AI",
                        "url": repo_url,
                        "avatar": "",
                    },
                    # lastUpdate is required by the Jira Software DevInfo API
                    # for pull-request objects.  Without it Jira silently drops
                    # the PR entry from the Development panel even though branch
                    # and commit objects in the same request are accepted.
                    "lastUpdate": now_iso,
                    "updateSequenceId": update_seq,
                }
                pr_objects.append(pr_obj)

            if not commit_objects and not branch_objects and not pr_objects:
                logger.debug(
                    "sync_development_info: nothing to push for ticket %s", ticket_key
                )
                return False

            payload = {
                "preventTransitions": False,
                "operationType": "NORMAL",
                "repositories": [
                    {
                        "id": f"github-{repo_owner}-{repo_name}",
                        "name": repo_name,
                        "description": "Managed by Prism AI",
                        "url": repo_url,
                        "commits": commit_objects,
                        "branches": branch_objects,
                        "pullRequests": pr_objects,
                        "updateSequenceId": update_seq,
                    }
                ],
            }

            resp = integration_request(
                "POST",
                f"{self.url}/rest/devinfo/0.10/bulk",
                json=payload,
                headers=self._basic_auth_headers(),
                timeout=15,
            )

            if resp.status_code in (200, 202):
                logger.info(
                    "Development info synced to Jira ticket %s "
                    "(branch=%s commit=%s pr=%s)",
                    ticket_key, branch_name, commit_sha, pr_number,
                )
                return True

            # 400/401/403 on Jira Cloud = devinfo API requires OAuth Connect app,
            # not Basic Auth.  Log at INFO (not WARNING) so the operator knows
            # this is expected without the GitHub for Jira marketplace app.
            if resp.status_code in (400, 401, 403):
                logger.info(
                    "Jira Dev Info API returned %s for ticket %s — "
                    "devinfo/0.10/bulk requires an Atlassian Connect OAuth app "
                    "(not Basic Auth). The Development panel can only be populated "
                    "via the GitHub for Jira marketplace app. "
                    "Falling back to remote web links.",
                    resp.status_code, ticket_key,
                )
            else:
                logger.warning(
                    "Jira Dev Info API returned %s for ticket %s: %s",
                    resp.status_code, ticket_key, resp.text[:300],
                )
            return False

        except Exception as exc:
            logger.error(
                "Failed to sync development info for ticket %s: %s", ticket_key, exc
            )
            return False

    def create_remote_link(
        self,
        ticket_key: str,
        url: str,
        title: str,
        tooltip: Optional[str] = None,
        icon_url: str = "https://github.com/favicon.ico",
        relationship: str = "mentioned in",
    ) -> bool:
        """
        Create a remote web link on a Jira issue.

        Remote links appear under the *Web links* section of the ticket and
        provide clickable navigation to branches, commits, and PRs even when
        the Jira↔GitHub marketplace app is not installed.

        Uses integration_request directly (with Basic Auth) instead of the
        Atlassian library's .post() method to avoid silent failures and ensure
        proper Content-Type / Accept headers are sent.
        """
        try:
            link_payload: dict = {
                "relationship": relationship,
                "object": {
                    "url": url,
                    "title": title,
                    "icon": {
                        "url16x16": icon_url,
                        "title": "GitHub",
                    },
                },
            }
            if tooltip:
                link_payload["object"]["summary"] = tooltip

            # Use integration_request (not self.client.post) so we get
            # consistent TLS handling, proper JSON headers, and a real
            # HTTP response object to inspect for success/failure.
            resp = integration_request(
                "POST",
                f"{self.url}/rest/api/3/issue/{ticket_key}/remotelink",
                json=link_payload,
                headers=self._basic_auth_headers(),
                timeout=15,
            )
            if resp.status_code in (200, 201):
                logger.info("Remote link added to %s: %s", ticket_key, title)
                return True
            logger.warning(
                "Remote link POST returned %s for %s (%s): %s",
                resp.status_code, ticket_key, title, resp.text[:200],
            )
            return False
        except Exception as exc:
            logger.warning(
                "Failed to add remote link to %s (%s): %s", ticket_key, title, exc
            )
            return False

    def sync_all_dev_links(
        self,
        ticket_key: str,
        repo_full_name: str,
        branch_name: Optional[str] = None,
        commit_sha: Optional[str] = None,
        commit_url: Optional[str] = None,
        commit_message: Optional[str] = None,
        pr_url: Optional[str] = None,
        pr_number: Optional[int] = None,
        pr_title: Optional[str] = None,
        file_path: Optional[str] = None,
        base_branch: str = "main",
    ) -> Dict[str, bool]:
        """
        Convenience wrapper that attempts the Jira Software DevInfo API first
        (populates the Development panel — requires GitHub for Jira marketplace
        app / OAuth Connect app), then ALWAYS creates remote web links via the
        standard REST API (Basic Auth accepted) so that branch, commit, and PR
        URLs are always visible as clickable links on the ticket regardless of
        whether the marketplace app is installed.

        Returns a dict with keys "dev_info", "branch_link", "commit_link",
        "pr_link" mapped to True/False depending on success.
        """
        results: Dict[str, bool] = {
            "dev_info": False,
            "branch_link": False,
            "commit_link": False,
            "pr_link": False,
        }

        # Attempt 1: push to Development panel via DevInfo API.
        # Will succeed only when the GitHub for Jira marketplace app (or an
        # equivalent Atlassian Connect OAuth app) is installed and authorised.
        # On Jira Cloud with Basic Auth this returns 400/401/403 — that is
        # expected and logged at INFO level; we always proceed to the fallback.
        results["dev_info"] = self.sync_development_info(
            ticket_key=ticket_key,
            repo_full_name=repo_full_name,
            branch_name=branch_name,
            commit_sha=commit_sha,
            commit_url=commit_url,
            commit_message=commit_message,
            pr_url=pr_url,
            pr_number=pr_number,
            pr_title=pr_title,
            file_path=file_path,
            base_branch=base_branch,
        )

        # Attempt 2: ALWAYS create remote web links via /rest/api/3/issue/remotelink
        # (standard Jira REST API, Basic Auth accepted on both Jira Cloud and Server).
        # These appear under "Web Links" on the ticket and are fully clickable even
        # without the GitHub marketplace app.
        repo_url = f"https://github.com/{repo_full_name}"

        if branch_name:
            results["branch_link"] = self.create_remote_link(
                ticket_key=ticket_key,
                url=f"{repo_url}/tree/{branch_name}",
                title=f"Branch: {branch_name}",
                tooltip=f"GitHub fix branch for {ticket_key}",
                relationship="implemented in",
            )

        if commit_sha and commit_url:
            results["commit_link"] = self.create_remote_link(
                ticket_key=ticket_key,
                url=commit_url,
                title=f"Commit: {commit_sha[:7]}",
                tooltip=commit_message or f"Fix commit for {ticket_key}",
                relationship="implemented in",
            )

        if pr_url and pr_number:
            results["pr_link"] = self.create_remote_link(
                ticket_key=ticket_key,
                url=pr_url,
                title=f"PR #{pr_number}: {pr_title or 'Auto-Fix'}",
                tooltip=f"Pull request fixing {ticket_key}",
                relationship="implemented in",
            )
        elif pr_url:
            # pr_number may be absent in some edge cases — still create the link
            results["pr_link"] = self.create_remote_link(
                ticket_key=ticket_key,
                url=pr_url,
                title="Pull Request: Auto-Fix",
                tooltip=f"Pull request fixing {ticket_key}",
                relationship="implemented in",
            )

        logger.info(
            "sync_all_dev_links for %s: dev_info=%s branch=%s commit=%s pr=%s",
            ticket_key,
            results["dev_info"],
            results["branch_link"],
            results["commit_link"],
            results["pr_link"],
        )
        return results
