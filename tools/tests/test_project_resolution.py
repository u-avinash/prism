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


def test_resolve_project_id_prefers_repo_mapping_even_when_environment_differs(monkeypatch) -> None:
    projects = [
        {
            "id": "PRJ-04A0A733",
            "name": "Fallback Project",
            "repo_url": "",
            "app_names": [],
            "environment": "production",
        },
        {
            "id": "PRJ-ORDER",
            "name": "Order Processing",
            "repo_url": "",
            "app_names": [],
            "environment": "sandbox",
        },
    ]

    configs = {
        "PRJ-04A0A733": {"llm": {"provider": "openai"}, "repo_mappings": {}},
        "PRJ-ORDER": {
            "llm": {},
            "repo_mappings": {
                "order-processing-service": {
                    "repo": "avinash-ai-langchain/order-processing-service",
                    "branch": "main",
                }
            },
        },
    }

    monkeypatch.setattr("storage.auth_store.list_projects", lambda: projects)
    monkeypatch.setattr("storage.auth_store.get_project_config", lambda project_id: configs[project_id])

    resolved = _resolve_project_id_for_incident(None, "order-processing-service", "production")

    assert resolved == "PRJ-ORDER"


def test_resolve_project_id_uses_environment_alias_when_app_matches(monkeypatch) -> None:
    projects = [
        {
            "id": "PRJ-ORDER",
            "name": "Order Processing",
            "repo_url": "https://github.com/avinash-ai-langchain/order-processing-service.git",
            "app_names": [],
            "environment": "production",
        }
    ]

    configs = {
        "PRJ-ORDER": {"llm": {}, "repo_mappings": {}},
    }

    monkeypatch.setattr("storage.auth_store.list_projects", lambda: projects)
    monkeypatch.setattr("storage.auth_store.get_project_config", lambda project_id: configs[project_id])

    resolved = _resolve_project_id_for_incident(None, "order-processing-service", "prod")

    assert resolved == "PRJ-ORDER"


def test_resolve_project_id_falls_back_only_when_no_app_match_exists(monkeypatch) -> None:
    projects = [
        {
            "id": "PRJ-04A0A733",
            "name": "Fallback Project",
            "repo_url": "",
            "app_names": [],
            "environment": "production",
        },
        {
            "id": "PRJ-OTHER",
            "name": "Inventory",
            "repo_url": "https://github.com/acme/inventory-service.git",
            "app_names": ["inventory-service"],
            "environment": "production",
        },
    ]

    configs = {
        "PRJ-04A0A733": {"llm": {"provider": "openai"}, "repo_mappings": {}},
        "PRJ-OTHER": {"llm": {}, "repo_mappings": {}},
    }

    monkeypatch.setattr("storage.auth_store.list_projects", lambda: projects)
    monkeypatch.setattr("storage.auth_store.get_project_config", lambda project_id: configs[project_id])

    resolved = _resolve_project_id_for_incident(None, "order-processing-service", "production")

    assert resolved == "PRJ-04A0A733"


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
    configs = {
        "PRJ-NTT": {
            "llm": {"provider": "nvidia"},
            "github": {"org": "avinash-ai-langchain"},
        }
    }

    monkeypatch.setattr("storage.auth_store.list_projects", lambda: projects)
    monkeypatch.setattr("storage.auth_store.get_project_config", lambda project_id: configs[project_id])

    resolved = _resolve_project_id_for_incident(None, "order-processing-service", "production")

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
    configs = {
        "PRJ-A": {"github": {"org": "org-a"}},
        "PRJ-B": {"github": {"org": "org-b"}},
    }

    monkeypatch.setattr("storage.auth_store.list_projects", lambda: projects)
    monkeypatch.setattr("storage.auth_store.get_project_config", lambda project_id: configs[project_id])

    resolved = _resolve_project_id_for_incident(None, "order-processing-service", "production")

    assert resolved == "PRJ-A"
