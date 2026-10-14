"""Regression tests for documented severity and secret-handling gaps."""

from contextlib import contextmanager

from agents.nodes import severity_assessor
from storage import auth_store
from utils.secret_crypto import SecretDecryptionError


def test_recent_error_count_uses_project_scoped_repository_query(monkeypatch):
    calls = {}
    incidents = [object(), object(), object()]

    class FakeRepository:
        def __init__(self, session):
            calls["session"] = session

        def get_recent_by_app(self, **kwargs):
            calls["query"] = kwargs
            return incidents

    @contextmanager
    def fake_session():
        session = object()
        yield session

    monkeypatch.setattr("storage.database.get_session", fake_session)
    monkeypatch.setattr("storage.incident_repository.IncidentRepository", FakeRepository)

    count = severity_assessor._get_recent_error_count(
        app_name="orders",
        project_id="project-7",
        window_minutes=12,
    )

    assert count == 3
    assert calls["query"] == {
        "app_name": "orders",
        "minutes": 12,
        "project_id": "project-7",
    }


def test_recent_error_count_degrades_to_zero_on_database_failure(monkeypatch):
    @contextmanager
    def failing_session():
        raise RuntimeError("database unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr("storage.database.get_session", failing_session)

    assert severity_assessor._get_recent_error_count("orders") == 0


def test_secret_decryption_failure_is_flagged_and_audited(monkeypatch):
    audit_events = []

    def fail_decryption(_value):
        raise SecretDecryptionError("key mismatch")

    monkeypatch.setattr(auth_store, "decrypt_secret", fail_decryption)
    monkeypatch.setattr(
        auth_store,
        "record_security_audit_event",
        lambda *args, **kwargs: audit_events.append((args, kwargs)),
    )

    result = auth_store._decrypt_section(
        "llm",
        {"api_key": "encrypted-value"},
        project_id="project-7",
    )

    assert result["api_key"] is None
    assert result["api_key_decryption_error"] is True
    assert audit_events == [
        (
            ("secret.decryption_failed",),
            {
                "project_id": "project-7",
                "actor_type": "system",
                "target_type": "integration_config",
                "target_id": "llm",
                "outcome": "failure",
                "details": {"field": "api_key"},
            },
        )
    ]
