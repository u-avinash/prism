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
"""Unit tests for project resolution during workflow startup."""

from agents.workflow import _resolve_project_id_for_incident


def _configure_projects(monkeypatch, projects: list[dict], configs: dict) -> None:
    """Mock client/project configuration and registered application aliases."""
    monkeypatch.setattr("storage.auth_store.list_projects", lambda: projects)
    monkeypatch.setattr(
        "storage.auth_store.get_project_config",
        lambda project_id: configs.get(project_id, {}),
    )


def test_resolve_project_id_prefers_registered_application_when_environment_differs(monkeypatch) -> None:
    projects = [
        {
            "id": "PRJ-FALLBACK",
            "name": "Fallback Project",
            "repo_url": "",
            "app_names": [],
            "environment": "production",
        },
        {
            "id": "PRJ-ORDER",
            "name": "Order Processing",
            "repo_url": "",
            "app_names": ["order-processing-service", "orders-worker"],
            "environment": "sandbox",
        },
    ]
    _configure_projects(
        monkeypatch,
        projects,
        {
            "PRJ-FALLBACK": {"llm": {"provider": "openai"}},
            "PRJ-ORDER": {"llm": {}},
        },
    )

    resolved = _resolve_project_id_for_incident(
        None, "order-processing-service", "production"
    )

    assert resolved == "PRJ-ORDER"


def test_resolve_project_id_uses_registered_alias_and_environment_alias(monkeypatch) -> None:
    projects = [
        {
            "id": "PRJ-ORDER",
            "name": "Order Processing",
            "repo_url": "",
            "app_names": ["order-processing-service", "orders-api-prod"],
            "environment": "production",
        }
    ]
    _configure_projects(monkeypatch, projects, {"PRJ-ORDER": {"llm": {}}})

    resolved = _resolve_project_id_for_incident(None, "orders-api-prod", "prod")

    assert resolved == "PRJ-ORDER"


def test_resolve_project_id_falls_back_only_when_no_application_match_exists(monkeypatch) -> None:
    projects = [
        {
            "id": "PRJ-FALLBACK",
            "name": "Fallback Project",
            "repo_url": "",
            "app_names": [],
            "environment": "production",
        },
        {
            "id": "PRJ-INVENTORY",
            "name": "Inventory",
            "repo_url": "",
            "app_names": ["inventory-service"],
            "environment": "production",
        },
    ]
    _configure_projects(
        monkeypatch,
        projects,
        {
            "PRJ-FALLBACK": {"llm": {"provider": "openai"}},
            "PRJ-INVENTORY": {"llm": {}},
        },
    )

    resolved = _resolve_project_id_for_incident(
        None, "order-processing-service", "production"
    )

    assert resolved == "PRJ-FALLBACK"


def test_resolve_project_id_uses_single_configured_github_org_for_any_repo(monkeypatch) -> None:
    projects = [
        {
            "id": "PRJ-NTT",
            "name": "NTT Data",
            "repo_url": "",
            "app_names": [],
            "environment": "production",
        }
    ]
    _configure_projects(
        monkeypatch,
        projects,
        {
            "PRJ-NTT": {
                "llm": {"provider": "nvidia"},
                "github": {"org": "avinash-ai-langchain"},
            }
        },
    )

    resolved = _resolve_project_id_for_incident(
        None, "order-processing-service", "production"
    )

    assert resolved == "PRJ-NTT"


def test_resolve_project_id_does_not_guess_between_multiple_github_org_projects(monkeypatch) -> None:
    projects = [
        {
            "id": "PRJ-A",
            "name": "Team A",
            "repo_url": "",
            "app_names": [],
            "environment": "production",
        },
        {
            "id": "PRJ-B",
            "name": "Team B",
            "repo_url": "",
            "app_names": [],
            "environment": "production",
        },
    ]
    _configure_projects(
        monkeypatch,
        projects,
        {
            "PRJ-A": {"github": {"org": "org-a"}},
            "PRJ-B": {"github": {"org": "org-b"}},
        },
    )

    resolved = _resolve_project_id_for_incident(
        None, "order-processing-service", "production"
    )

    # Ambiguous organization routing deliberately falls through to the stable
    # configured-project fallback rather than selecting an organization at random.
    assert resolved == "PRJ-A"
