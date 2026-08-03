"""Regression tests for Prism's shared outbound TLS policy."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import integrations.github_client as github_module
import integrations.llm_provider as llm_module
from integrations.github_client import GitHubClient
from integrations.llm_provider import LLMProvider, _normalize_openai_compatible_base_url


def test_github_client_uses_shared_tls_verify_value(monkeypatch) -> None:
    """GitHub calls must use the enterprise CA/verification configuration."""
    captured: dict = {}

    class FakeGithub:
        def __init__(self, token, **kwargs) -> None:
            captured["token"] = token
            captured.update(kwargs)

    monkeypatch.setattr(
        GitHubClient,
        "_load_project_github_config",
        lambda _self, _project_id: {
            "token": "github-test-token",
            "org": "acme",
            "default_branch": "main",
        },
    )
    monkeypatch.setattr(github_module, "Github", FakeGithub)
    monkeypatch.setattr(github_module, "tls_verify_value", lambda: "corporate-ca.pem")

    GitHubClient(project_id="PRJ-TEST")

    assert captured == {
        "token": "github-test-token",
        "verify": "corporate-ca.pem",
    }


def test_nvidia_runtime_client_uses_shared_httpx_transport(monkeypatch) -> None:
    """Normal NVIDIA invocation must not bypass the TLS-aware HTTPX client."""
    captured: dict = {}
    tls_client = object()

    class FakeChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "httpx_client", lambda *, timeout: tls_client)
    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        SimpleNamespace(ChatOpenAI=FakeChatOpenAI),
    )

    provider = LLMProvider(
        provider="nvidia",
        model="meta/llama-3.1-8b-instruct",
        api_key="nvidia-test-key",
    )

    assert provider.llm is not None
    assert captured["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert captured["http_client"] is tls_client
    assert captured["timeout"] == 60.0


def test_fast_llm_verification_rejects_key_when_models_listing_is_public(monkeypatch) -> None:
    """A successful public /models endpoint must not verify an invalid API key."""

    class FakeHttpClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakeModels:
        def list(self) -> None:
            return None

    class FakeCompletions:
        def create(self, **_kwargs) -> None:
            raise RuntimeError("401 invalid API key: invalid-test-key")

    class FakeOpenAI:
        def __init__(self, **_kwargs) -> None:
            self.models = FakeModels()
            self.chat = SimpleNamespace(completions=FakeCompletions())

    provider = LLMProvider.__new__(LLMProvider)
    provider.provider = "openai"
    provider.model = "gpt-test"
    provider.api_key = "invalid-test-key"
    provider.base_url = "https://example.test/v1"
    provider.api_version = None
    provider.custom_provider_name = None

    monkeypatch.setattr(
        llm_module,
        "httpx_client",
        lambda *, timeout: FakeHttpClient(),
    )
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(OpenAI=FakeOpenAI, AzureOpenAI=FakeOpenAI),
    )

    verified, message = provider.test_connection_fast()

    assert verified is False
    assert "Credential verification failed" in message
    assert "invalid-test-key" not in message
    assert "[REDACTED]" in message


def test_nvidia_fast_verification_uses_authenticated_models_listing(monkeypatch) -> None:
    """NVIDIA verification must not wait for model cold-start inference."""
    completion_called = False

    class FakeHttpClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    class FakeModels:
        def list(self) -> None:
            return None

    class FakeCompletions:
        def create(self, **_kwargs) -> None:
            nonlocal completion_called
            completion_called = True
            raise AssertionError("NVIDIA verification must not invoke a completion")

    class FakeOpenAI:
        def __init__(self, **_kwargs) -> None:
            self.models = FakeModels()
            self.chat = SimpleNamespace(completions=FakeCompletions())

    provider = LLMProvider.__new__(LLMProvider)
    provider.provider = "nvidia"
    provider.model = "meta/llama-3.3-70b-instruct"
    provider.api_key = "nvidia-test-key"
    provider.base_url = "https://integrate.api.nvidia.com/v1"
    provider.api_version = None
    provider.custom_provider_name = None

    monkeypatch.setattr(
        llm_module,
        "httpx_client",
        lambda *, timeout: FakeHttpClient(),
    )
    monkeypatch.setitem(
        sys.modules,
        "openai",
        SimpleNamespace(OpenAI=FakeOpenAI, AzureOpenAI=FakeOpenAI),
    )

    verified, message = provider.test_connection_fast()

    assert verified is True
    assert "NVIDIA endpoint verified" in message
    assert completion_called is False


def test_llm_configuration_rejects_openai_with_nvidia_endpoint() -> None:
    """A stale NVIDIA endpoint must not be used with the OpenAI provider."""
    provider = LLMProvider.__new__(LLMProvider)
    provider.provider = "openai"
    provider.model = "gpt-4-turbo"
    provider.api_key = "openai-test-key"
    provider.base_url = "https://integrate.api.nvidia.com/v1"
    provider.project_id = None
    provider.custom_provider_name = None

    try:
        provider._validate_configuration()
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected a provider/endpoint mismatch error")

    assert "belongs to Nvidia" in message
    assert "selected provider is Openai" in message
    assert "clear the Base URL" in message


def test_new_openai_compatible_providers_use_canonical_default_urls(monkeypatch) -> None:
    """Catalog providers must be functional without requiring a manual Base URL."""
    captured: list[dict] = []

    class FakeChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(llm_module, "httpx_client", lambda *, timeout: object())
    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        SimpleNamespace(ChatOpenAI=FakeChatOpenAI),
    )

    expected_urls = {
        "openrouter": "https://openrouter.ai/api/v1",
        "cerebras": "https://api.cerebras.ai/v1",
        "fireworks_ai": "https://api.fireworks.ai/inference/v1",
        "sambanova": "https://api.sambanova.ai/v1",
    }
    for provider_name, expected_url in expected_urls.items():
        provider = LLMProvider(
            provider=provider_name,
            model="test-model",
            api_key="test-key",
        )
        assert provider.base_url == expected_url

    assert [kwargs["base_url"] for kwargs in captured] == list(expected_urls.values())


def test_nvidia_base_url_is_canonicalized_from_common_admin_inputs() -> None:
    """NVIDIA NIM configuration must always leave the SDK at the /v1 API root."""
    expected = "https://integrate.api.nvidia.com/v1"
    configured_urls = (
        "https://integrate.api.nvidia.com",
        "https://integrate.api.nvidia.com/",
        "https://integrate.api.nvidia.com/v1/",
        "https://integrate.api.nvidia.com/v1/v1",
        "https://integrate.api.nvidia.com/v1/chat/completions",
        "https://integrate.api.nvidia.com/chat/completions",
        "https://integrate.api.nvidia.com/v1/models",
    )

    for configured_url in configured_urls:
        assert _normalize_openai_compatible_base_url(configured_url, "nvidia") == expected


def test_openai_compatible_operation_url_is_converted_to_api_root() -> None:
    """The SDK must not append a second operation path to a pasted URL."""
    assert _normalize_openai_compatible_base_url(
        "https://gateway.example.test/openai/v1/chat/completions",
        "custom",
    ) == "https://gateway.example.test/openai/v1"


def test_nvidia_unqualified_model_is_sent_with_nvidia_namespace(monkeypatch) -> None:
    """NVIDIA returns 404 for unqualified catalog model names."""
    captured: dict = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "httpx_client", lambda *, timeout: object())
    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        SimpleNamespace(ChatOpenAI=FakeChatOpenAI),
    )

    provider = LLMProvider(
        provider="nvidia",
        model="nemotron-3-ultra-550b-a55b",
        api_key="nvidia-test-key",
    )

    assert provider.model == "nemotron-3-ultra-550b-a55b"
    assert provider.api_model == "nvidia/nemotron-3-ultra-550b-a55b"
    assert captured["model"] == "nvidia/nemotron-3-ultra-550b-a55b"

    qualified_provider = LLMProvider(
        provider="nvidia",
        model="meta/llama-3.1-8b-instruct",
        api_key="nvidia-test-key",
    )
    assert qualified_provider.api_model == "meta/llama-3.1-8b-instruct"


def test_nvidia_provider_passes_canonicalized_base_url_to_langchain(monkeypatch) -> None:
    """A persisted full NVIDIA completion URL cannot result in a 404 request."""
    captured: dict = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "httpx_client", lambda *, timeout: object())
    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        SimpleNamespace(ChatOpenAI=FakeChatOpenAI),
    )

    provider = LLMProvider(
        provider="nvidia",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        api_key="nvidia-test-key",
        base_url="https://integrate.api.nvidia.com/v1/chat/completions",
    )

    assert provider.base_url == "https://integrate.api.nvidia.com/v1"
    assert captured["base_url"] == "https://integrate.api.nvidia.com/v1"
