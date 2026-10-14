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
"""Unit tests for GitHub repository resolution."""

from github import GithubException

from integrations.github_client import GitHubClient


def _make_client(org: str = "avinash-ai-langchain") -> GitHubClient:
    client = GitHubClient.__new__(GitHubClient)
    client.project_id = "PRJ-TEST"
    client.org = org
    client.default_branch = "main"
    client.token = "test-token"
    client.client = None
    client._get_registered_application = lambda identifier: None  # type: ignore[method-assign]
    return client


def test_clean_repo_full_name_removes_github_prefixes() -> None:
    client = _make_client()

    assert client._clean_repo_full_name("https://github.com/acme/orders.git") == "acme/orders"
    assert client._clean_repo_full_name("git@github.com:acme/orders.git") == "acme/orders"
    assert client._clean_repo_full_name("acme/orders/") == "acme/orders"


def test_is_full_repo_name_rejects_org_only_values() -> None:
    client = _make_client()

    assert client._is_full_repo_name("acme/orders") is True
    assert client._is_full_repo_name("avinash-ai-langchain") is False
    assert client._is_full_repo_name("") is False
    assert client._is_full_repo_name(None) is False


def test_get_accessible_repo_full_name_returns_canonical_name() -> None:
    class FakeRepo:
        full_name = "avinash-ai-langchain/order-processing-service"

    class FakeGithub:
        def get_repo(self, full_name: str):
            assert full_name == "avinash-ai-langchain/order-processing-service"
            return FakeRepo()

    client = _make_client()
    client.client = FakeGithub()

    assert (
        client.get_accessible_repo_full_name(
            "https://github.com/avinash-ai-langchain/order-processing-service.git"
        )
        == "avinash-ai-langchain/order-processing-service"
    )


def test_get_accessible_repo_full_name_returns_none_when_token_cannot_access_repo() -> None:
    class FakeGithub:
        def get_repo(self, full_name: str):
            raise GithubException(404, {"message": "Not Found"})

    client = _make_client()
    client.client = FakeGithub()

    assert (
        client.get_accessible_repo_full_name(
            "avinash-ai-langchain/order-processing-service"
        )
        is None
    )


def test_extract_repo_from_log_prefers_explicit_repository_identifier() -> None:
    client = _make_client()

    repo = client.extract_repo_from_log(
        "Build failed; github.repository=avinash-ai-langchain/order-processing-service",
        "orders-worker",
    )

    assert repo == "avinash-ai-langchain/order-processing-service"


def test_extract_repo_from_log_uses_registered_application_repository() -> None:
    client = _make_client()
    client._get_registered_application = lambda identifier: {  # type: ignore[method-assign]
        "name": "Order Processing",
        "repository": "https://github.com/avinash-ai-langchain/order-processing-service.git",
    }

    repo = client.extract_repo_from_log("Error in orders-worker", "orders-worker")

    assert repo == "avinash-ai-langchain/order-processing-service"


def test_extract_repo_from_log_resolves_matching_repo_from_configured_org() -> None:
    """Organization-wide access works without a per-repository configuration."""

    class FakeRepo:
        full_name = "avinash-ai-langchain/order-processing-service"
        name = "order-processing-service"

    class FakeOrganization:
        def get_repo(self, name: str):
            assert name == "order-processing-service"
            return FakeRepo()

    class FakeGithub:
        def get_organization(self, name: str):
            assert name == "avinash-ai-langchain"
            return FakeOrganization()

    client = _make_client()
    client.client = FakeGithub()

    repo = client.extract_repo_from_log("Order processing failure", "order-processing-service")

    assert repo == "avinash-ai-langchain/order-processing-service"


def test_extract_repo_from_log_uses_fuzzy_organization_match() -> None:
    class FakeRepo:
        full_name = "avinash-ai-langchain/order-processing-service"
        name = "order-processing-service"

    class FakeOrganization:
        def get_repo(self, name: str):
            raise GithubException(404, {"message": "Not Found"})

        def get_repos(self):
            return [FakeRepo()]

    class FakeGithub:
        def get_organization(self, name: str):
            return FakeOrganization()

    client = _make_client()
    client.client = FakeGithub()

    repo = client.extract_repo_from_log("Order processing failure", "order-processing")

    assert repo == "avinash-ai-langchain/order-processing-service"


def test_extract_repo_from_log_direct_access_fallback_when_org_api_forbidden() -> None:
    """
    Tokens with only 'repo' scope get a 403 from get_organization().
    Step 4 must fall back to client.get_repo('org/app_name') directly.

    This reproduces the exact failure seen in production:
      [RCA Generation] Metadata repo 'order-processing-service' has no slash …
      GitHub organization search failed for 'avinash-ai-langchain': 403 Forbidden
      Could not resolve repo … 'order-processing-service' in 'avinash-ai-langchain'
    """

    class FakeRepo:
        full_name = "avinash-ai-langchain/order-processing-service"

    class FakeGithub:
        def get_organization(self, name: str):
            # Simulates a repo-scoped token that cannot read org membership
            raise GithubException(403, {"message": "Must have admin rights"})

        def get_repo(self, full_name: str):
            assert full_name == "avinash-ai-langchain/order-processing-service"
            return FakeRepo()

    client = _make_client()
    client.client = FakeGithub()

    repo = client.extract_repo_from_log(
        "Order processing failure",
        "order-processing-service",
    )

    assert repo == "avinash-ai-langchain/order-processing-service"


def test_extract_repo_from_log_raises_when_direct_access_also_fails() -> None:
    """Both org API and direct get_repo fail → ValueError is raised."""

    class FakeGithub:
        def get_organization(self, name: str):
            raise GithubException(403, {"message": "Forbidden"})

        def get_repo(self, full_name: str):
            raise GithubException(404, {"message": "Not Found"})

    client = _make_client()
    client.client = FakeGithub()

    try:
        client.extract_repo_from_log("Some failure", "unknown-service")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "Cannot resolve" in str(exc)
        assert "avinash-ai-langchain" in str(exc)
