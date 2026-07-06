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
Apply incident data retention policy.

Deletes incidents (and their associated comments) older than the configured
retention threshold.  Safe to run as a scheduled cron job.

Usage:
    python scripts/apply_retention_policy.py [--days N] [--dry-run]

    --days N    Override retention threshold (default: 90 days)
    --dry-run   Print what would be deleted without actually deleting anything
"""
import argparse
import sys
import os
from datetime import datetime, timedelta

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def apply_retention(days: int = 90, dry_run: bool = False) -> dict:
    """
    Delete incidents older than `days` days.

    Terminal / approved incidents that are still open as reminders are preserved
    by default — only COMPLETED, PR_CREATED, REJECTED, and FAILED incidents
    older than the threshold are removed.

    Returns a summary dict.
    """
    from storage.database import get_session
    from storage.database import Incident, IncidentComment
    from sqlalchemy import and_

    cutoff = datetime.utcnow() - timedelta(days=days)
    eligible_statuses = {"COMPLETED", "PR_CREATED", "REJECTED", "FAILED"}

    summary = {
        "cutoff_date": cutoff.strftime("%Y-%m-%d %H:%M UTC"),
        "retention_days": days,
        "dry_run": dry_run,
        "incidents_found": 0,
        "comments_found": 0,
        "incidents_deleted": 0,
        "comments_deleted": 0,
        "errors": [],
    }

    try:
        with get_session() as session:
            # Find qualifying incidents
            candidates = (
                session.query(Incident)
                .filter(
                    and_(
                        Incident.created_at <= cutoff,
                        Incident.status.in_(eligible_statuses),
                    )
                )
                .all()
            )

            candidate_ids = [inc.incident_id for inc in candidates]
            summary["incidents_found"] = len(candidate_ids)

            if candidate_ids:
                # Count associated comments
                comment_count = (
                    session.query(IncidentComment)
                    .filter(IncidentComment.incident_id.in_(candidate_ids))
                    .count()
                )
                summary["comments_found"] = comment_count

                if not dry_run:
                    # Delete comments first (FK reference)
                    session.query(IncidentComment).filter(
                        IncidentComment.incident_id.in_(candidate_ids)
                    ).delete(synchronize_session=False)

                    # Delete incidents
                    session.query(Incident).filter(
                        Incident.incident_id.in_(candidate_ids)
                    ).delete(synchronize_session=False)

                    session.commit()
                    summary["incidents_deleted"] = len(candidate_ids)
                    summary["comments_deleted"] = comment_count

    except Exception as exc:
        summary["errors"].append(str(exc))

    return summary


def main():
    parser = argparse.ArgumentParser(description="Apply Prism incident retention policy")
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Retention threshold in days (default: 90). Incidents older than this are deleted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without actually deleting anything.",
    )
    args = parser.parse_args()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Applying retention policy: delete incidents older than {args.days} days...")

    result = apply_retention(days=args.days, dry_run=args.dry_run)

    print(f"  Cutoff date     : {result['cutoff_date']}")
    print(f"  Incidents found : {result['incidents_found']}")
    print(f"  Comments found  : {result['comments_found']}")

    if args.dry_run:
        print(f"  [DRY RUN] Would delete {result['incidents_found']} incident(s) and {result['comments_found']} comment(s).")
    else:
        print(f"  Incidents deleted : {result['incidents_deleted']}")
        print(f"  Comments deleted  : {result['comments_deleted']}")

    if result["errors"]:
        print(f"  Errors: {result['errors']}")
        sys.exit(1)
    else:
        print("Done.")


if __name__ == "__main__":
    main()
