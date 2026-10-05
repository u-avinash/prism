from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.database import Base, SecurityAuditEvent
from storage.security_audit_repository import SecurityAuditRepository


def _repository():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return session, SecurityAuditRepository(session)


def test_security_audit_is_project_scoped_and_newest_first():
    session, repo = _repository()
    session.add_all(
        [
            SecurityAuditEvent(
                event_id="one",
                project_id="PRJ-A",
                actor_type="admin",
                action="project.updated",
                outcome="success",
                created_at=datetime(2026, 1, 1),
            ),
            SecurityAuditEvent(
                event_id="two",
                project_id="PRJ-B",
                actor_type="admin",
                action="project.updated",
                outcome="success",
                created_at=datetime(2026, 1, 2),
            ),
            SecurityAuditEvent(
                event_id="three",
                project_id="PRJ-A",
                actor_type="team_admin",
                action="integration.saved",
                outcome="success",
                created_at=datetime(2026, 1, 3),
            ),
        ]
    )
    session.commit()

    events = repo.get_all(project_id="PRJ-A", limit=10)

    assert [event.event_id for event in events] == ["three", "one"]
    assert repo.get_all(limit=10) == []


def test_security_audit_serialization_redacts_nested_secret_values():
    session, repo = _repository()
    event = SecurityAuditEvent(
        event_id="event",
        project_id="PRJ-A",
        actor_type="admin",
        action="integration.saved",
        outcome="success",
        details={
            "configured_fields": ["token", "base_url"],
            "api_token": "must-not-leak",
            "nested": {"webhook_url": "https://private.example"},
            "ordinary": "visible",
        },
    )
    session.add(event)
    session.commit()

    serialized = repo.serialize(event)

    assert serialized["details"]["api_token"] == "[REDACTED]"
    assert serialized["details"]["nested"]["webhook_url"] == "[REDACTED]"
    assert serialized["details"]["ordinary"] == "visible"
