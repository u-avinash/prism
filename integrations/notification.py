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
"""Notification client — credentials loaded exclusively from project DB config."""
import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Union

from integrations.verification import request as integration_request
from utils.retry_handler import retry_with_backoff

logger = logging.getLogger(__name__)


class NotificationClient:
    """
    Multi-channel notification client supporting Slack, Microsoft Teams, Email,
    and outbound generic webhooks (Zapier / Make / n8n compatible).

    All credentials / webhook URLs are loaded from the per-project DB config.
    No fallback to environment variables or settings.py.
    """

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id
        project_cfg = self._load_project_notification_config(project_id)

        self.slack_webhook = (project_cfg.get("slack_webhook_url") or "").strip()
        self.slack_channel = (project_cfg.get("slack_channel") or "").strip()
        self.teams_webhook = (project_cfg.get("teams_webhook_url") or "").strip()
        self.outbound_webhooks: list = project_cfg.get("outbound_webhooks") or []

        email_cfg = project_cfg.get("email") or {}
        self.email_enabled = bool(email_cfg.get("enabled", False))
        self.email_config = {
            "smtp_host": email_cfg.get("smtp_host", ""),
            "smtp_port": int(email_cfg.get("smtp_port", 587)),
            "from_email": email_cfg.get("from_email", ""),
            "to_email": email_cfg.get("to_email", ""),
            "password": email_cfg.get("password", ""),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_project_notification_config(self, project_id: Optional[str]) -> dict:
        if not project_id:
            return {}
        try:
            from storage.auth_store import get_project_config
            config = get_project_config(project_id) or {}
            slack_cfg = config.get("slack") or {}
            teams_cfg = config.get("teams") or {}
            return {
                "slack_webhook_url": slack_cfg.get("webhook_url", ""),
                "slack_channel": slack_cfg.get("channel", ""),
                "teams_webhook_url": teams_cfg.get("webhook_url", ""),
                "email": config.get("email") or {},
                # Outbound generic webhooks: list of {url, label, events: [...]}
                # events filter (optional): e.g. ["fix_approved", "incident_created"]
                "outbound_webhooks": config.get("outbound_webhooks") or [],
            }
        except Exception as exc:
            logger.warning("Failed to load notification config for project %s: %s", project_id, exc)
            return {}

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _build_deep_link(incident_id: Optional[Union[int, str]]) -> Optional[str]:
        if not incident_id:
            return None
        try:
            from config.settings import get_settings as _gs
            base = (_gs().ui_base_url or "http://localhost:8080").rstrip("/")
            return f"{base}/incidents/{incident_id}"
        except Exception:
            return f"http://localhost:8080/incidents/{incident_id}"

    @staticmethod
    def _extract_diff_snippet(proposed_fix: Optional[str], max_lines: int = 15) -> Optional[str]:
        if not proposed_fix:
            return None
        import re as _re
        import difflib
        blocks = _re.findall(r"```(?:\w+)?\n(.*?)\n```", proposed_fix, _re.DOTALL)
        if len(blocks) < 2:
            return None
        diff = list(difflib.unified_diff(
            blocks[0].splitlines(), blocks[1].splitlines(),
            fromfile="original", tofile="fixed", lineterm="",
        ))
        if not diff:
            return None
        return "\n".join(diff[:max_lines]) + ("\n…" if len(diff) > max_lines else "")

    # ── Public send interface ─────────────────────────────────────────────────

    def send_alert(
        self,
        title: str,
        message: str,
        channels: Optional[List[str]] = None,
        severity: str = "HIGH",
        incident_id: Optional[Union[int, str]] = None,
        jira_url: Optional[str] = None,
        proposed_fix: Optional[str] = None,
        event: Optional[str] = None,
    ) -> List[str]:
        """
        Send an alert to the specified channels (or all configured channels).

        Returns a list of channel names where the alert was successfully sent.
        Channels that are not configured for the project are silently skipped.

        `event` is used to filter outbound webhooks by their `events` allowlist.
        """
        if channels is None:
            channels = []
            if self.slack_webhook:
                channels.append("slack")
            if self.teams_webhook:
                channels.append("teams")
            if self.email_enabled:
                channels.append("email")
            if self.outbound_webhooks:
                channels.append("outbound")

        successful: list[str] = []
        for channel in channels:
            try:
                if channel == "slack" and self.slack_webhook:
                    self._send_slack(title, message, severity, incident_id, jira_url, proposed_fix)
                    successful.append("slack")
                    logger.info("Alert sent to Slack (project=%s)", self.project_id)

                elif channel == "teams" and self.teams_webhook:
                    self._send_teams(title, message, severity, incident_id, jira_url, proposed_fix)
                    successful.append("teams")
                    logger.info("Alert sent to Teams (project=%s)", self.project_id)

                elif channel == "email" and self.email_enabled:
                    self._send_email(title, message, severity, incident_id, jira_url)
                    successful.append("email")
                    logger.info("Alert sent via Email (project=%s)", self.project_id)

                elif channel == "outbound" and self.outbound_webhooks:
                    sent_count = self._send_outbound_webhooks(
                        title, message, severity, incident_id, jira_url, event
                    )
                    if sent_count > 0:
                        successful.append("outbound")

            except Exception as exc:
                logger.error("Failed to send alert to %s: %s", channel, exc)

        return successful

    # ── Slack ─────────────────────────────────────────────────────────────────

    @retry_with_backoff(max_retries=2, base_delay=1.0)
    def _send_slack(
        self,
        title: str,
        message: str,
        severity: str,
        incident_id: Optional[Union[int, str]],
        jira_url: Optional[str],
        proposed_fix: Optional[str] = None,
    ) -> None:
        color_map = {"CRITICAL": "#FF0000", "HIGH": "#FF6600", "MEDIUM": "#FFCC00", "LOW": "#36A64F"}
        color = color_map.get(severity, "#808080")
        deep_link = self._build_deep_link(incident_id)

        if deep_link and incident_id not in (None, ""):
            incident_text = f"*Incident:*\n<{deep_link}|{str(incident_id).strip()} → View →>"
        elif incident_id not in (None, ""):
            incident_text = f"*Incident ID:*\n{str(incident_id).strip()}"
        else:
            incident_text = "*Incident ID:*\nN/A"

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"🚨 {title}", "emoji": True}},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity}"},
                {"type": "mrkdwn", "text": incident_text},
            ]},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Details:*\n{message[:400]}"}},
        ]

        diff_snippet = self._extract_diff_snippet(proposed_fix)
        if diff_snippet:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Code Change:*\n```{diff_snippet[:700]}```"},
            })

        actions: list[dict] = []
        if deep_link:
            actions.append({"type": "button", "text": {"type": "plain_text", "text": "View Incident →"},
                            "url": deep_link, "style": "primary"})
        if jira_url:
            actions.append({"type": "button", "text": {"type": "plain_text", "text": "Open Jira ↗"},
                            "url": jira_url})
        if actions:
            blocks.append({"type": "actions", "elements": actions})

        payload: dict = {"attachments": [{"color": color, "blocks": blocks}]}
        response = integration_request("POST", self.slack_webhook, json=payload, timeout=10)
        response.raise_for_status()

    # ── Teams ─────────────────────────────────────────────────────────────────

    @retry_with_backoff(max_retries=2, base_delay=1.0)
    def _send_teams(
        self,
        title: str,
        message: str,
        severity: str,
        incident_id: Optional[Union[int, str]],
        jira_url: Optional[str],
        proposed_fix: Optional[str] = None,
    ) -> None:
        color_map = {"CRITICAL": "FF0000", "HIGH": "FF6600", "MEDIUM": "FFCC00", "LOW": "36A64F"}
        theme_color = color_map.get(severity, "808080")
        deep_link = self._build_deep_link(incident_id)
        id_value = str(incident_id).strip() if incident_id not in (None, "") else "N/A"

        sections: list[dict] = [{
            "activityTitle": "🚨 Error Alert",
            "facts": [
                {"name": "Severity", "value": severity},
                {"name": "Incident ID", "value": id_value},
            ],
            "text": message[:500],
        }]

        diff_snippet = self._extract_diff_snippet(proposed_fix)
        if diff_snippet:
            sections.append({
                "activityTitle": "Proposed Code Change",
                "text": f"<pre>{diff_snippet[:700]}</pre>",
            })

        actions: list[dict] = []
        if deep_link:
            actions.append({"@type": "OpenUri", "name": "View Incident →",
                            "targets": [{"os": "default", "uri": deep_link}]})
        if jira_url:
            actions.append({"@type": "OpenUri", "name": "Open Jira ↗",
                            "targets": [{"os": "default", "uri": jira_url}]})

        card: dict = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": title,
            "themeColor": theme_color,
            "title": f"🚨 {title}",
            "sections": sections,
        }
        if actions:
            card["potentialAction"] = actions

        response = integration_request("POST", self.teams_webhook, json=card, timeout=10)
        response.raise_for_status()

    # ── Outbound generic webhooks (Zapier / Make / n8n) ──────────────────────

    def _send_outbound_webhooks(
        self,
        title: str,
        message: str,
        severity: str,
        incident_id: Optional[Union[int, str]],
        jira_url: Optional[str],
        event: Optional[str] = None,
    ) -> int:
        """
        Deliver a standardised JSON event to all configured outbound webhook URLs.

        Each entry in `outbound_webhooks` may be:
          - A plain URL string, OR
          - A dict: {"url": "...", "label": "...", "events": ["fix_approved", ...]}

        When `events` is specified, only matching event types are delivered.
        Returns the number of webhooks that succeeded.

        Payload shape (Zapier / Make / n8n compatible):
        {
          "event":        "fix_approved",
          "incident_id":  "A7CB",
          "title":        "...",
          "severity":     "HIGH",
          "message":      "...",
          "jira_url":     "...",
          "incident_url": "http://localhost:8080/incidents/A7CB",
          "timestamp":    "2026-06-18T12:00:00Z"
        }
        """
        if not self.outbound_webhooks:
            return 0

        deep_link = self._build_deep_link(incident_id)
        payload = {
            "event": event or "incident_alert",
            "incident_id": str(incident_id) if incident_id not in (None, "") else None,
            "title": title,
            "severity": severity,
            "message": message[:800],
            "jira_url": jira_url,
            "incident_url": deep_link,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "project_id": self.project_id,
        }

        sent_count = 0
        for entry in self.outbound_webhooks:
            try:
                if isinstance(entry, str):
                    url = entry
                    allowed_events = None
                elif isinstance(entry, dict):
                    url = (entry.get("url") or "").strip()
                    allowed_events = entry.get("events")
                else:
                    continue

                if not url:
                    continue

                # Event filter check
                if allowed_events and event and event not in allowed_events:
                    logger.debug("[Outbound] Skipping webhook %s — event '%s' not in allowed %s",
                                 url[:40], event, allowed_events)
                    continue

                resp = integration_request("POST", url, json=payload, timeout=10)
                resp.raise_for_status()
                sent_count += 1
                logger.info("[Outbound] Webhook delivered to %s (event=%s)", url[:60], event)

            except Exception as exc:
                logger.warning("[Outbound] Webhook delivery failed for %s: %s",
                               str(entry)[:60], exc)

        return sent_count

    # ── Email ─────────────────────────────────────────────────────────────────

    @retry_with_backoff(max_retries=2, base_delay=1.0)
    def _send_email(
        self,
        title: str,
        message: str,
        severity: str,
        incident_id: Optional[Union[int, str]],
        jira_url: Optional[str],
    ) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{severity}] {title}"
        msg["From"] = self.email_config["from_email"]
        msg["To"] = self.email_config["to_email"]

        id_display = str(incident_id).strip() if incident_id not in (None, "") else "N/A"
        color = "red" if severity in ("CRITICAL", "HIGH") else "orange"
        jira_link = f'<p><a href="{jira_url}" style="color:#0052CC;">View Jira Ticket</a></p>' if jira_url else ""
        deep_link = self._build_deep_link(incident_id)
        incident_link = (
            f'<p><a href="{deep_link}" style="color:#6366f1;">View Incident in Prism →</a></p>'
            if deep_link else ""
        )

        html_body = f"""
        <html>
          <body style="font-family:Arial,sans-serif;">
            <h2 style="color:#333;">🚨 Error Alert: {title}</h2>
            <table style="border-collapse:collapse;margin:20px 0;">
              <tr>
                <td style="padding:8px;font-weight:bold;">Severity:</td>
                <td style="padding:8px;color:{color};">{severity}</td>
              </tr>
              <tr>
                <td style="padding:8px;font-weight:bold;">Incident ID:</td>
                <td style="padding:8px;">{id_display}</td>
              </tr>
            </table>
            <h3>Error Details:</h3>
            <pre style="background:#f5f5f5;padding:15px;border-radius:5px;overflow-x:auto;">{message}</pre>
            {jira_link}
            {incident_link}
          </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(self.email_config["smtp_host"], self.email_config["smtp_port"]) as server:
            server.starttls()
            server.login(self.email_config["from_email"], self.email_config["password"])
            server.send_message(msg)


# ── Convenience wrappers ──────────────────────────────────────────────────────

def send_slack_alert(
    incident_id: Union[int, str],
    title: str,
    message: str,
    severity: str = "HIGH",
    jira_url: Optional[str] = None,
    app_name: Optional[str] = None,
    environment: Optional[str] = None,
    project_id: Optional[str] = None,
) -> bool:
    """Send a Slack alert for a project. Returns True if delivered."""
    try:
        full_title = f"[{app_name}] {title}" if app_name else title
        if environment:
            full_title = f"{full_title} ({environment})"
        client = NotificationClient(project_id=project_id)
        successful = client.send_alert(
            title=full_title,
            message=message,
            channels=["slack"],
            severity=severity,
            incident_id=incident_id,
            jira_url=jira_url,
        )
        return "slack" in successful
    except Exception as exc:
        logger.error("send_slack_alert failed: %s", exc)
        return False


def send_teams_alert(
    incident_id: Union[int, str],
    title: str,
    message: str,
    severity: str = "HIGH",
    jira_url: Optional[str] = None,
    app_name: Optional[str] = None,
    environment: Optional[str] = None,
    project_id: Optional[str] = None,
) -> bool:
    """Send a Teams alert for a project. Returns True if delivered."""
    try:
        full_title = f"[{app_name}] {title}" if app_name else title
        if environment:
            full_title = f"{full_title} ({environment})"
        client = NotificationClient(project_id=project_id)
        successful = client.send_alert(
            title=full_title,
            message=message,
            channels=["teams"],
            severity=severity,
            incident_id=incident_id,
            jira_url=jira_url,
        )
        return "teams" in successful
    except Exception as exc:
        logger.error("send_teams_alert failed: %s", exc)
        return False


def send_outbound_webhook_event(
    incident_id: Union[int, str],
    event: str,
    title: str,
    message: str,
    severity: str = "HIGH",
    jira_url: Optional[str] = None,
    project_id: Optional[str] = None,
) -> bool:
    """Fire a specific named event to all configured outbound webhooks. Returns True if any delivered."""
    try:
        client = NotificationClient(project_id=project_id)
        successful = client.send_alert(
            title=title,
            message=message,
            channels=["outbound"],
            severity=severity,
            incident_id=incident_id,
            jira_url=jira_url,
            event=event,
        )
        return "outbound" in successful
    except Exception as exc:
        logger.error("send_outbound_webhook_event failed: %s", exc)
        return False
