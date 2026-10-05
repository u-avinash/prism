"""
Apply Prism retention policy.

Use --dry-run before execution. Scheduling remains external (Windows Task
Scheduler or cron) so each deployment explicitly controls when deletion runs.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def apply_retention(
    days: int = 90,
    dry_run: bool = False,
    project_id: Optional[str] = None,
) -> dict:
    """Remove eligible terminal incidents and their managed dependent data."""
    if not 1 <= int(days) <= 3650:
        raise ValueError("days must be between 1 and 3650")

    from sqlalchemy import and_
    from storage.auth_store import record_security_audit_event
    from storage.database import Incident, IncidentComment, TelemetryLog, get_session
    from utils.artifact_paths import managed_artifact_paths

    cutoff = datetime.utcnow() - timedelta(days=int(days))
    eligible_statuses = {"COMPLETED", "PR_CREATED", "REJECTED", "FAILED"}
    summary = {
        "cutoff_date": cutoff.strftime("%Y-%m-%d %H:%M UTC"),
        "retention_days": int(days),
        "project_id": project_id,
        "dry_run": bool(dry_run),
        "incidents_found": 0,
        "comments_found": 0,
        "telemetry_logs_found": 0,
        "artifacts_found": 0,
        "incidents_deleted": 0,
        "comments_deleted": 0,
        "telemetry_logs_deleted": 0,
        "artifacts_deleted": 0,
        "errors": [],
    }

    try:
        with get_session() as session:
            filters = [
                Incident.created_at <= cutoff,
                Incident.status.in_(eligible_statuses),
            ]
            if project_id:
                filters.append(Incident.project_id == project_id)
            candidates = session.query(Incident).filter(and_(*filters)).all()
            incident_ids = [incident.incident_id for incident in candidates]
            summary["incidents_found"] = len(incident_ids)

            if incident_ids:
                summary["comments_found"] = (
                    session.query(IncidentComment)
                    .filter(IncidentComment.incident_id.in_(incident_ids))
                    .count()
                )
                telemetry_query = session.query(TelemetryLog).filter(
                    TelemetryLog.incident_id.in_(incident_ids)
                )
                telemetry_rows = telemetry_query.all()
                summary["telemetry_logs_found"] = len(telemetry_rows)
                artifacts = (
                    managed_artifact_paths(
                        [getattr(incident, "pdf_path", None) for incident in candidates],
                        "pdf",
                    )
                    + managed_artifact_paths(
                        [getattr(incident, "patch_path", None) for incident in candidates],
                        "patch",
                    )
                )
                summary["artifacts_found"] = len(artifacts)

                if not dry_run:
                    session.query(IncidentComment).filter(
                        IncidentComment.incident_id.in_(incident_ids)
                    ).delete(synchronize_session=False)
                    telemetry_query.delete(synchronize_session=False)
                    session.query(Incident).filter(
                        Incident.incident_id.in_(incident_ids)
                    ).delete(synchronize_session=False)

                    for artifact in artifacts:
                        try:
                            artifact.unlink()
                            summary["artifacts_deleted"] += 1
                        except OSError as exc:
                            summary["errors"].append(f"Could not delete artifact {artifact.name}: {exc}")

                    summary["incidents_deleted"] = len(incident_ids)
                    summary["comments_deleted"] = summary["comments_found"]
                    summary["telemetry_logs_deleted"] = summary["telemetry_logs_found"]
    except Exception as exc:
        summary["errors"].append(str(exc))

    action = "retention.previewed" if dry_run else (
        "retention.failed" if summary["errors"] else "retention.executed"
    )
    record_security_audit_event(
        action,
        project_id=project_id,
        target_type="retention_policy",
        outcome="failure" if summary["errors"] else "success",
        details={
            key: summary[key]
            for key in (
                "retention_days", "dry_run", "incidents_found", "comments_found",
                "telemetry_logs_found", "artifacts_found", "incidents_deleted",
                "comments_deleted", "telemetry_logs_deleted", "artifacts_deleted",
            )
        },
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Prism data retention policy")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--project-id", default=None, help="Restrict deletion to one project.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting.")
    args = parser.parse_args()

    result = apply_retention(args.days, args.dry_run, args.project_id)
    for key, value in result.items():
        if key != "errors":
            print(f"{key}: {value}")
    if result["errors"]:
        print("errors:", result["errors"], file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
