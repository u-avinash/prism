"""Regression tests for Phase 0 environment security defaults."""

from config.settings import Settings
from storage import auth_store


def test_development_defaults_preserve_local_quick_start():
    settings = Settings(prism_environment="development")

    assert settings.effective_ingestion_auth_required is False
    assert settings.effective_allow_unassigned_ingestion is True
    assert settings.effective_ui_cookie_secure is False
    assert settings.effective_csrf_enabled is False
    assert settings.effective_debug_endpoints_enabled is True
    settings.validate_security_policy()


def test_production_defaults_are_fail_closed_when_origins_configured():
    settings = Settings(
        prism_environment="production",
        ingestion_allowed_origins="https://prism.example.test",
    )

    assert settings.effective_ingestion_auth_required is True
    assert settings.effective_allow_unassigned_ingestion is False
    assert settings.effective_ui_cookie_secure is True
    assert settings.effective_csrf_enabled is True
    assert settings.effective_debug_endpoints_enabled is False
    settings.validate_security_policy()


def test_production_rejects_missing_ingestion_origins():
    settings = Settings(prism_environment="production")

    try:
        settings.validate_security_policy()
    except ValueError as exc:
        assert "INGESTION_ALLOWED_ORIGINS" in str(exc)
    else:
        raise AssertionError("Unsafe production settings must fail validation")


def test_production_rejects_explicitly_insecure_overrides():
    settings = Settings(
        prism_environment="production",
        ingestion_allowed_origins="https://prism.example.test",
        ingestion_auth_required=False,
        allow_unassigned_ingestion=True,
        ui_cookie_secure=False,
        csrf_enabled=False,
    )

    try:
        settings.validate_security_policy()
    except ValueError as exc:
        message = str(exc)
        assert "INGESTION_AUTH_REQUIRED" in message
        assert "ALLOW_UNASSIGNED_INGESTION" in message
        assert "UI_COOKIE_SECURE" in message
        assert "CSRF_ENABLED" in message
    else:
        raise AssertionError("Unsafe production overrides must fail validation")


def test_session_contains_high_entropy_csrf_token(monkeypatch, tmp_path):
    sessions_path = tmp_path / "sessions.json"
    monkeypatch.setattr(auth_store, "_SESSIONS_FILE", str(sessions_path))

    token = auth_store.create_session(
        {
            "id": "USR-TEST",
            "username": "test-user",
            "role": "user",
            "email": "test@example.test",
        }
    )
    session = auth_store.get_session(token)

    assert session is not None
    assert isinstance(session["csrf_token"], str)
    assert len(session["csrf_token"]) >= 32
