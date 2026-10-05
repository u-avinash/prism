"""Regression coverage for the ingestion service's machine-only boundary."""

from __future__ import annotations

from fastapi.testclient import TestClient

import ingestion.api as ingestion_api


def _direct_incident_payload() -> dict:
    return {
        "app_name": "orders-api",
        "environment": "production",
        "error_title": "Order submission failed",
        "error_description": "The downstream inventory service timed out.",
        "stack_trace": "TimeoutError: inventory request exceeded deadline",
        "raw_log": '{"message": "Order submission failed"}',
        "severity": "HIGH",
    }


def test_unassigned_ingestion_is_rejected_when_disabled(monkeypatch):
    monkeypatch.setattr(ingestion_api.settings, "ingestion_auth_required", False)
    monkeypatch.setattr(ingestion_api.settings, "allow_unassigned_ingestion", False)

    with TestClient(ingestion_api.app) as client:
        response = client.post("/ingest/log", json=_direct_incident_payload())

    assert response.status_code == 403
    assert "Unassigned ingestion is disabled" in response.json()["detail"]


def test_ingestion_requires_project_key_when_authentication_is_enabled(monkeypatch):
    monkeypatch.setattr(ingestion_api.settings, "ingestion_auth_required", True)
    monkeypatch.setattr(ingestion_api.settings, "allow_unassigned_ingestion", True)

    with TestClient(ingestion_api.app) as client:
        response = client.post("/v1/traces", json={"resourceSpans": []})

    assert response.status_code == 401
    assert "project API key" in response.json()["detail"]


def test_legacy_management_routes_are_not_exposed_by_ingestion_service():
    with TestClient(ingestion_api.app) as client:
        responses = [
            client.get("/incidents"),
            client.get("/incidents/AB12"),
            client.post(
                "/incidents/AB12/approve",
                json={"incident_id": "AB12", "approved": True},
            ),
            client.patch("/incidents/AB12", json={"status": "COMPLETED"}),
            client.get("/api/logs"),
            client.get("/api/logs/filters"),
            client.get("/stats"),
        ]

    assert all(response.status_code == 404 for response in responses)
    assert all(
        "machine ingestion only" in response.json()["detail"]
        for response in responses
    )
