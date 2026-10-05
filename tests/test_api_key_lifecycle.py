"""Regression tests for project-scoped ingestion API-key lifecycle controls."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import storage.auth_store as auth_store


def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(auth_store, "_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auth_store, "_AUTH_FILE", str(tmp_path / "auth_data.json"))
    monkeypatch.setattr(auth_store, "_SESSIONS_FILE", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(auth_store, "get_project_config", lambda project_id, mask_secrets=False: configs.setdefault(project_id, auth_store._default_project_config(project_id)))
    monkeypatch.setattr(
        auth_store,
        "update_project_config",
        lambda project_id, section, values: configs[project_id].__setitem__(section, values) or configs[project_id],
    )
    configs = {}
    return configs



def test_api_key_is_returned_once_and_persisted_only_as_digest(monkeypatch, tmp_path):
    configs = _isolated_store(monkeypatch, tmp_path)

    issued = auth_store.create_project_api_key("PRJ-1", "OTLP production")
    assert issued["key"].startswith("prism_")
    assert issued["digest"] != issued["key"]

    persisted = configs["PRJ-1"]["api_keys"]["api_keys"][0]
    assert persisted["digest"] == auth_store._api_key_digest(issued["key"])
    assert "key" not in persisted

    listed = auth_store.list_project_api_keys("PRJ-1")
    assert listed == [{k: v for k, v in issued.items() if k not in {"key", "digest"}}]


def test_api_key_verification_tracks_use_and_honors_revocation_and_expiry(monkeypatch, tmp_path):
    _isolated_store(monkeypatch, tmp_path)

    issued = auth_store.create_project_api_key("PRJ-1", "collector")
    verified = auth_store.verify_project_api_key("PRJ-1", issued["key"])
    assert verified and verified["id"] == issued["id"]
    assert "digest" not in verified and "key" not in verified
    assert auth_store.list_project_api_keys("PRJ-1")[0]["last_used_at"]

    assert auth_store.revoke_project_api_key("PRJ-1", issued["id"]) is True
    assert auth_store.verify_project_api_key("PRJ-1", issued["key"]) is None

    expired = auth_store.create_project_api_key(
        "PRJ-2",
        "expired",
        expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )
    assert auth_store.verify_project_api_key("PRJ-2", expired["key"]) is None
