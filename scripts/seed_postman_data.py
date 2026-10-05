"""Create deterministic synthetic Prism data for the local Postman collection.

Usage:
    py -3.14 scripts/seed_postman_data.py --reset

This command is intentionally destructive only with --reset. It removes local
SQLite/auth/session data, creates synthetic tenants and users, and writes
postman/Prism.local.postman_environment.json. Never run it against production.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config.settings import get_settings
from storage.auth_store import (
    ALL_FEATURES,
    assign_user_to_project,
    create_project,
    create_project_api_key,
    create_user,
    get_user_by_username,
    record_security_audit_event,
    update_project_config,
)
from storage.database import (
    Incident,
    IncidentComment,
    SecurityAuditEvent,
    TelemetryLog,
    WorkflowRun,
    WorkflowStepEvent,
    get_session,
    init_database,
)


POSTMAN_DIR = os.path.join(ROOT, "postman")
AUTH_FILE = os.path.join(ROOT, "data", "auth_data.json")
SESSIONS_FILE = os.path.join(ROOT, "data", "sessions.json")

USERS = {
    "admin": {
        "username": "postman-admin",
        "email": "postman-admin@example.test",
        "password": "PostmanAdmin!2026",
        "role": "admin",
    },
    "team_admin_a": {
        "username": "postman-team-a",
        "email": "postman-team-a@example.test",
        "password": "PostmanTeamA!2026",
        "role": "team_admin",
    },
    "team_admin_b": {
        "username": "postman-team-b",
        "email": "postman-team-b@example.test",
        "password": "PostmanTeamB!2026",
        "role": "team_admin",
    },
    "user_a": {
        "username": "postman-user-a",
        "email": "postman-user-a@example.test",
        "password": "PostmanUserA!2026",
        "role": "user",
    },
}


def _clear_runtime_data() -> None:
    """Remove only local runtime state, then recreate the current schema."""
    settings = get_settings()
    for path in (settings.database_path, AUTH_FILE, SESSIONS_FILE):
        if os.path.exists(path):
            os.remove(path)
    for suffix in ("-wal", "-shm"):
        candidate = settings.database_path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    init_database()


def _incident(
    incident_id: str,
    project_id: str,
    *,
    status: str,
    approval_status: str | None = None,
    severity: str = "HIGH",
    title: str,
    app_name: str = "orders-api",
) -> Incident:
    now = datetime.now(UTC).replace(tzinfo=None)
    return Incident(
        incident_id=incident_id,
        project_id=project_id,
        app_name=app_name,
        environment="test",
        error_title=title,
        error_description="Synthetic Postman fixture. No customer telemetry is stored.",
        stack_trace="TimeoutError: synthetic downstream timeout",
        raw_log='{"fixture": "postman"}',
        error_fingerprint=f"fixture-{incident_id.lower()}",
        status=status,
        severity=severity,
        occurrence_count=2,
        last_occurrence_at=now,
        current_workflow_node="await_approval" if approval_status == "PENDING" else "finalize",
        workflow_completed_steps=["assess_severity", "generate_rca", "generate_fix"],
        workflow_progress_pct=60.0 if approval_status == "PENDING" else 100.0,
        rca_text="Synthetic RCA fixture for local API testing.",
        rca_confidence=0.91,
        proposed_fix="// Synthetic fix fixture\nreturn fallbackResponse();",
        fix_explanation="Synthetic fixture only; no external pull request is created.",
        fix_quality_score=0.88,
        approval_status=approval_status,
        fix_approved=True if approval_status == "APPROVED" else None,
        approved_by="postman-user-a" if approval_status == "APPROVED" else None,
        approved_at=now if approval_status == "APPROVED" else None,
        incident_metadata={"fixture": True, "project_id": project_id},
        source_technology="python",
        detected_framework="fastapi",
        is_primary_incident=True,
        created_at=now,
        updated_at=now,
    )


def _environment(values: dict[str, str]) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": "Prism Local Synthetic",
        "values": [
            {"key": key, "value": value, "type": "default", "enabled": True}
            for key, value in values.items()
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "_postman_exported_using": "Prism synthetic seed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete local database/auth/session runtime data before seeding.",
    )
    args = parser.parse_args()

    if not args.reset:
        parser.error("--reset is required because this command seeds test identities and fixtures")

    _clear_runtime_data()
    os.makedirs(POSTMAN_DIR, exist_ok=True)

    users = {}
    for key, payload in USERS.items():
        users[key] = create_user(
            {
                **payload,
                "features": ALL_FEATURES,
            }
        )

    project_a = create_project(
        {
            "name": "Postman Orders",
            "description": "Synthetic tenant A for collection validation",
            "app_names": ["orders-api"],
            "stack": "FastAPI",
            "environment": "test",
            "team_admin_id": users["team_admin_a"]["id"],
            "team_admin_email": USERS["team_admin_a"]["email"],
        }
    )
    project_b = create_project(
        {
            "name": "Postman Billing",
            "description": "Synthetic tenant B for isolation validation",
            "app_names": ["billing-api"],
            "stack": "FastAPI",
            "environment": "test",
            "team_admin_id": users["team_admin_b"]["id"],
            "team_admin_email": USERS["team_admin_b"]["email"],
        }
    )

    for user_key, project in (
        ("team_admin_a", project_a),
        ("user_a", project_a),
        ("team_admin_b", project_b),
    ):
        assign_user_to_project(users[user_key]["id"], project["id"])

    key_a = create_project_api_key(project_a["id"], "Postman tenant A key")
    key_b = create_project_api_key(project_b["id"], "Postman tenant B key")
    revoked_key = create_project_api_key(project_a["id"], "Postman revoked key")
    from storage.auth_store import revoke_project_api_key

    revoke_project_api_key(project_a["id"], revoked_key["id"])

    now = datetime.now(UTC).replace(tzinfo=None)
    pending = _incident(
        "PMA1",
        project_a["id"],
        status="AWAITING_APPROVAL",
        approval_status="PENDING",
        title="Synthetic order timeout awaiting approval",
    )
    recovery = _incident(
        "PMA2",
        project_a["id"],
        status="FAILED",
        approval_status="APPROVED",
        title="Synthetic approved incident awaiting recovery",
    )
    completed = _incident(
        "PMA3",
        project_a["id"],
        status="COMPLETED",
        approval_status="APPROVED",
        title="Synthetic completed order incident",
    )
    tenant_b = _incident(
        "PMB1",
        project_b["id"],
        status="DETECTED",
        severity="MEDIUM",
        title="Synthetic billing tenant incident",
        app_name="billing-api",
    )

    recovery_run_id = str(uuid.uuid4())
    completed_run_id = str(uuid.uuid4())
    with get_session() as session:
        session.add_all([pending, recovery, completed, tenant_b])
        session.add(
            TelemetryLog(
                log_id="TMA1",
                project_id=project_a["id"],
                app_name="orders-api",
                environment="test",
                severity="ERROR",
                severity_number=17,
                message="Synthetic order timeout",
                error_type="TimeoutError",
                error_message="Synthetic downstream timeout",
                trace_id="postman-trace-a",
                raw_payload='{"fixture":"postman"}',
                attributes={"fixture": True},
                incident_created=True,
                incident_id="PMA1",
            )
        )
        session.add(
            WorkflowRun(
                run_id=recovery_run_id,
                incident_id="PMA2",
                project_id=project_a["id"],
                run_type="recovery",
                trigger_source="operator",
                triggered_by=USERS["team_admin_a"]["username"],
                status="FAILED",
                recovery_reason="Synthetic blocked integration recovery",
                error_summary="Synthetic GitHub access failure",
                started_at=now - timedelta(minutes=5),
                completed_at=now - timedelta(minutes=4),
                duration_seconds=60.0,
            )
        )
        session.add(
            WorkflowRun(
                run_id=completed_run_id,
                incident_id="PMA3",
                project_id=project_a["id"],
                run_type="full",
                trigger_source="ingestion",
                status="COMPLETED",
                started_at=now - timedelta(minutes=30),
                completed_at=now - timedelta(minutes=29),
                duration_seconds=60.0,
            )
        )
        session.add_all(
            [
                WorkflowStepEvent(
                    event_id=str(uuid.uuid4()),
                    run_id=recovery_run_id,
                    incident_id="PMA2",
                    project_id=project_a["id"],
                    step_name="create_pr",
                    event_type="started",
                    attempt=1,
                    message="Synthetic recovery started",
                    created_at=now - timedelta(minutes=5),
                ),
                WorkflowStepEvent(
                    event_id=str(uuid.uuid4()),
                    run_id=recovery_run_id,
                    incident_id="PMA2",
                    project_id=project_a["id"],
                    step_name="create_pr",
                    event_type="failed",
                    attempt=1,
                    message="Synthetic GitHub access failure",
                    created_at=now - timedelta(minutes=4),
                ),
            ]
        )
        session.add(
            IncidentComment(
                comment_id="POSTMAN-CMT-001",
                incident_id="PMA1",
                author=USERS["user_a"]["username"],
                content="Synthetic fixture comment for Postman validation.",
                comment_type="comment",
            )
        )
        session.add(
            SecurityAuditEvent(
                event_id=str(uuid.uuid4()),
                project_id=project_a["id"],
                actor_type="system",
                action="postman.seeded",
                target_type="fixture",
                target_id="PMA1",
                outcome="success",
                details={"synthetic": True},
            )
        )

    record_security_audit_event(
        "postman.seed.completed",
        project_id=project_a["id"],
        target_type="fixture_set",
        target_id="postman-local",
        details={"synthetic": True},
    )

    values = {
        "ui_base_url": "http://127.0.0.1:8080",
        "ingestion_base_url": "http://127.0.0.1:8000",
        "admin_username": USERS["admin"]["username"],
        "admin_password": USERS["admin"]["password"],
        "team_admin_a_username": USERS["team_admin_a"]["username"],
        "team_admin_a_password": USERS["team_admin_a"]["password"],
        "user_a_username": USERS["user_a"]["username"],
        "user_a_password": USERS["user_a"]["password"],
        "project_a_id": project_a["id"],
        "project_b_id": project_b["id"],
        "project_a_api_key": key_a["key"],
        "project_b_api_key": key_b["key"],
        "revoked_api_key": revoked_key["key"],
        "revoked_api_key_id": revoked_key["id"],
        "pending_incident_id": "PMA1",
        "recovery_incident_id": "PMA2",
        "completed_incident_id": "PMA3",
        "tenant_b_incident_id": "PMB1",
        "workflow_run_id": recovery_run_id,
        "comment_id": "POSTMAN-CMT-001",
        "csrf_token": "",
        "issued_api_key": "",
        "created_incident_id": "",
    }
    environment_path = os.path.join(POSTMAN_DIR, "Prism.local.postman_environment.json")
    with open(environment_path, "w", encoding="utf-8") as handle:
        json.dump(_environment(values), handle, indent=2)

    print(json.dumps({
        "environment": environment_path,
        "project_a_id": project_a["id"],
        "project_b_id": project_b["id"],
        "pending_incident_id": "PMA1",
        "recovery_incident_id": "PMA2",
    }, indent=2))


if __name__ == "__main__":
    main()
