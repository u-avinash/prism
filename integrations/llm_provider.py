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
from __future__ import annotations

"""Multi-provider LLM wrapper — credentials loaded exclusively from project DB config."""

import json
import re
import logging
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import get_settings
from integrations.verification import httpx_client
from utils.retry_handler import retry_with_backoff, RateLimitError

logger = logging.getLogger(__name__)
settings = get_settings()


def _normalize_openai_compatible_base_url(
    base_url: Optional[str],
    provider: str,
) -> Optional[str]:
    """Return an OpenAI-compatible API root rather than an operation URL.

    OpenAI SDK clients append paths such as ``/chat/completions`` themselves.
    Team Admin users frequently paste a full operation URL or omit ``/v1`` when
    configuring NVIDIA NIM, both of which result in a provider-side 404.

    Only the known NVIDIA NIM host is forced to its documented API root. Other
    provider URLs retain their configured path after harmless duplicate-version
    and operation-suffix cleanup, so private OpenAI-compatible gateways remain
    supported.
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return None

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url

    host = (parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    operation_suffixes = (
        ("chat", "completions"),
        ("responses",),
        ("completions",),
        ("models",),
    )
    for suffix in operation_suffixes:
        if tuple(path_parts[-len(suffix):]) == suffix:
            path_parts = path_parts[:-len(suffix)]
            break

    while len(path_parts) >= 2 and path_parts[-2:] == ["v1", "v1"]:
        path_parts.pop()

    if host == "integrate.api.nvidia.com":
        path_parts = ["v1"]

    normalized_path = f"/{'/'.join(path_parts)}" if path_parts else ""
    return parsed._replace(path=normalized_path, params="", query="", fragment="").geturl()


def _normalize_response_content(content: Any) -> str:
    """Normalize provider-specific response content to a plain string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


class LLMProvider:
    """
    Multi-provider LLM wrapper with caching and retry logic.

    All credentials and model settings are loaded from the per-project DB config
    (stored encrypted).  No fallback to environment variables or settings.py.

    Supported providers: openai, azure_openai, anthropic, google_gemini,
    groq, grok/xai, together, ollama, mistral, cohere, deepseek, perplexity,
    hugging_face, bedrock, nvidia, custom.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        project_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        custom_provider_name: Optional[str] = None,
        seed: Optional[int] = None,
        model_kwargs: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialise LLM provider.

        At least one of `project_id` (to load config from DB) or explicit
        `provider` + `api_key` + `model` must be supplied.  If `project_id`
        is given, DB values are used as the primary source; explicit kwargs
        override them.

        ``custom_provider_name`` is the human-readable label used when
        ``provider == "custom"`` (e.g. "z-ai").  It is used only for display
        / logging purposes and does not affect the underlying API client.

        ``seed`` sets a deterministic seed for reproducible outputs (supported
        by OpenAI-compatible endpoints including NVIDIA NIM).

        ``model_kwargs`` passes additional keyword arguments to the underlying
        API, e.g. ``{"extra_body": {"chat_template_kwargs": {"enable_thinking": True}}}``
        for NVIDIA thinking models such as z-ai/glm-5.2.
        """
        self.project_id = project_id
        project_cfg = self._load_project_llm_config(project_id)

        resolved_provider = (
            provider
            or project_cfg.get("provider")
            or ""
        ).strip().lower()

        if not resolved_provider:
            raise ValueError(
                f"LLM provider is not configured"
                + (f" for project '{project_id}'" if project_id else "")
                + ". Configure it via Team Admin → Project Configuration → LLM."
            )

        _supported_providers = {
            "openai", "azure_openai", "anthropic", "google", "google_gemini",
            "groq", "xai", "grok", "x-ai", "x_ai", "together", "together_ai",
            "ollama", "mistral", "cohere", "deepseek", "perplexity",
            "hugging_face", "bedrock", "nvidia", "openrouter", "cerebras",
            "fireworks_ai", "sambanova", "custom",
        }

        # Resolve the custom provider display name (used in messages / logs).
        # Priority: explicit kwarg > DB config > inferred alias > fall back to "custom".
        _custom_name = (
            custom_provider_name
            or project_cfg.get("custom_provider")
            or project_cfg.get("custom_provider_name")
            or ""
        ).strip()

        # If the UI / API sends a provider label that is not one of Prism's
        # first-class providers (e.g. "meta", "microsoft", "z-ai") but a
        # base_url is supplied, treat it as a custom OpenAI-compatible provider.
        # This matches how NVIDIA NIM model namespaces are often entered in the UI:
        #   provider="microsoft", model="phi-4-mini-instruct"
        # becomes:
        #   provider="custom", custom_provider_name="microsoft",
        #   api_model="microsoft/phi-4-mini-instruct"
        if resolved_provider not in _supported_providers and (base_url or project_cfg.get("base_url")):
            _custom_name = _custom_name or resolved_provider
            resolved_provider = "custom"

        self.provider = resolved_provider
        self.custom_provider_name: Optional[str] = _custom_name if _custom_name else None

        self.model = model or project_cfg.get("model") or ""
        if not self.model:
            raise ValueError(
                f"LLM model is not configured for provider '{self.provider}'"
                + (f" in project '{project_id}'" if project_id else "")
                + ". Configure it via Team Admin → Project Configuration → LLM."
            )

        self.temperature = self._coerce_float(
            temperature if temperature is not None else project_cfg.get("temperature"),
            0.2,
        )
        self.max_tokens = self._coerce_int(
            max_tokens if max_tokens is not None else project_cfg.get("max_tokens"),
            4096,
        )
        # Default endpoints for OpenAI-compatible hosted providers.
        _default_base_urls = {
            "nvidia": "https://integrate.api.nvidia.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "cerebras": "https://api.cerebras.ai/v1",
            "fireworks_ai": "https://api.fireworks.ai/inference/v1",
            "sambanova": "https://api.sambanova.ai/v1",
        }
        _default_base_url: Optional[str] = _default_base_urls.get(resolved_provider)

        self.base_url = _normalize_openai_compatible_base_url(
            base_url
            or project_cfg.get("base_url")
            or _default_base_url,
            resolved_provider,
        )
        self.api_key = api_key or project_cfg.get("api_key") or None
        self.api_version = project_cfg.get("api_version") or None
        self.deployment_name = project_cfg.get("deployment_name") or None

        # Seed for deterministic outputs (NVIDIA NIM / OpenAI-compatible)
        self.seed: Optional[int] = (
            seed
            if seed is not None
            else (project_cfg.get("seed") if project_cfg.get("seed") is not None else None)
        )
        # Extra model kwargs (e.g. extra_body for thinking model parameters)
        _cfg_model_kwargs: dict = project_cfg.get("model_kwargs") or {}
        self.model_kwargs: Dict[str, Any] = {**_cfg_model_kwargs, **(model_kwargs or {})}

        # Validate that credential is present for providers that require it
        self._validate_configuration()

        if settings.llm_cache_enabled:
            set_llm_cache(InMemoryCache())

        self.llm = self._initialize_llm()

        # Load fallback provider chain from project config
        self._fallback_configs: list[dict] = self._load_fallback_configs(project_id, project_cfg)

        logger.info(
            "Initialized LLM: provider=%s model=%s project_id=%s fallbacks=%d",
            self.display_provider,
            self.model,
            self.project_id,
            len(self._fallback_configs),
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def display_provider(self) -> str:
        """Return the provider label used in log/error messages.

        When the provider is ``"custom"`` and a ``custom_provider_name`` has
        been set, that name is returned instead of the literal string
        ``"custom"`` so that error messages like
        ``"custom/glm-5.2: Connection error"`` correctly show
        ``"z-ai/glm-5.2: Connection error"`` instead.
        """
        if self.provider == "custom" and self.custom_provider_name:
            return self.custom_provider_name
        return self.provider

    @property
    def api_model(self) -> str:
        """Return the model identifier to pass to the underlying API client.

        For custom providers backed by OpenAI-compatible endpoints (e.g.
        NVIDIA NIM), many registries namespace models as
        ``"{provider}/{model}"`` — e.g. ``"z-ai/glm-5.2"``.  When a
        ``custom_provider_name`` is set and the model string does not already
        contain a ``/``, the provider prefix is prepended automatically so
        the API receives the correct fully-qualified model name.

        For all other providers the raw ``self.model`` value is returned
        unchanged.
        """
        if self.provider == "nvidia" and "/" not in self.model:
            # NVIDIA's authenticated model catalog uses fully-qualified IDs
            # (for example, ``nvidia/nemotron-3-ultra-550b-a55b``). Its
            # completion endpoint returns a generic 404 for an unqualified
            # name, even though the endpoint and API key are valid.
            return f"nvidia/{self.model}"

        if self.provider == "custom" and self.custom_provider_name:
            prefix = f"{self.custom_provider_name}/"
            if not self.model.startswith(prefix) and "/" not in self.model:
                return f"{self.custom_provider_name}/{self.model}"
        return self.model

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _load_fallback_configs(self, project_id: Optional[str], primary_cfg: dict) -> list:
        """
        Load ordered fallback LLM configurations from the project config.

        The project config may include an `llm_fallbacks` list:
        [
          {"provider": "anthropic", "model": "claude-3-haiku-20240307", "api_key": "..."},
          {"provider": "ollama",    "model": "llama3.2"}
        ]

        Falls back gracefully — invalid fallback entries are skipped with a warning.
        """
        if not project_id:
            return []
        try:
            from storage.auth_store import get_project_config
            config = get_project_config(project_id) or {}
            fallbacks = config.get("llm_fallbacks") or []
            if not isinstance(fallbacks, list):
                return []
            valid = []
            for fb in fallbacks:
                if isinstance(fb, dict) and fb.get("provider") and fb.get("model"):
                    valid.append(fb)
                else:
                    logger.debug("Skipping invalid fallback config: %s", fb)
            return valid
        except Exception as exc:
            logger.debug("Could not load fallback LLM configs: %s", exc)
            return []

    def _build_fallback_llm(self, cfg: dict) -> Optional[BaseChatModel]:
        """Build an LLM client from a fallback config dict."""
        try:
            fb_provider = (cfg.get("provider") or "").strip().lower()
            fb_model = (cfg.get("model") or "").strip()
            fb_api_key = cfg.get("api_key") or None
            fb_base_url = _normalize_openai_compatible_base_url(
                cfg.get("base_url")
                or ("https://integrate.api.nvidia.com/v1" if fb_provider == "nvidia" else None),
                fb_provider,
            )
            fb_temp = self._coerce_float(cfg.get("temperature"), self.temperature)
            fb_max_tokens = self._coerce_int(cfg.get("max_tokens"), self.max_tokens)

            if fb_provider in {"openai", "nvidia", "custom", "perplexity", "deepseek", "mistral", "cohere"}:
                from langchain_openai import ChatOpenAI
                kw: dict = {"model": fb_model, "temperature": fb_temp, "max_tokens": fb_max_tokens,
                            "api_key": fb_api_key, "timeout": 60.0, "max_retries": 1}
                if fb_base_url:
                    kw["base_url"] = fb_base_url
                fb_model_kwargs: dict = cfg.get("model_kwargs") or {}
                if fb_model_kwargs:
                    kw["model_kwargs"] = fb_model_kwargs
                if cfg.get("seed") is not None:
                    kw["model_kwargs"] = {**fb_model_kwargs, "seed": cfg["seed"]}
                # Keep normal fallback invocations consistent with the
                # enterprise TLS policy used by the connection test.
                kw["http_client"] = httpx_client(timeout=60.0)
                return ChatOpenAI(**kw)
            elif fb_provider == "anthropic":
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(model=fb_model, temperature=fb_temp, max_tokens=fb_max_tokens,
                                     api_key=fb_api_key, timeout=60.0, max_retries=1)
            elif fb_provider in {"google", "google_gemini"}:
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(model=fb_model, temperature=fb_temp,
                                              max_tokens=fb_max_tokens, google_api_key=fb_api_key, timeout=60)
            elif fb_provider == "groq":
                from langchain_groq import ChatGroq
                return ChatGroq(model=fb_model, temperature=fb_temp, max_tokens=fb_max_tokens, api_key=fb_api_key)
            elif fb_provider == "ollama":
                from langchain_ollama import ChatOllama
                return ChatOllama(model=fb_model, temperature=fb_temp,
                                  base_url=fb_base_url or "http://localhost:11434")
            else:
                logger.warning("Unsupported fallback provider: %s", fb_provider)
                return None
        except Exception as exc:
            logger.warning("Failed to build fallback LLM (%s/%s): %s",
                           cfg.get("provider"), cfg.get("model"), exc)
            return None

    def _load_project_llm_config(self, project_id: Optional[str]) -> dict:
        if not project_id:
            return {}
        try:
            from storage.auth_store import get_project_config
            config = get_project_config(project_id) or {}
            return config.get("llm") or {}
        except Exception as exc:
            logger.warning("Failed to load project LLM config for %s: %s", project_id, exc)
            return {}

    def _coerce_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _coerce_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _provider_requires_api_key(self, provider: str) -> bool:
        return (provider or "").strip().lower() not in {"ollama"}

    def _validate_configuration(self) -> None:
        if self._provider_requires_api_key(self.provider) and not self.api_key:
            raise ValueError(
                f"API key is not configured for LLM provider '{self.provider}'"
                + (f" in project '{self.project_id}'" if self.project_id else "")
                + ". Configure it via Team Admin → Project Configuration → LLM."
            )
        if self.provider == "azure_openai" and not self.base_url:
            raise ValueError(
                "Azure OpenAI requires a base_url (azure_endpoint). "
                "Configure it via Team Admin → Project Configuration → LLM."
            )

        # A provider change in the UI can leave the previous provider's URL in
        # place. Catch known public endpoint mismatches before calling /models
        # or a completion, which otherwise produces a misleading 404 response.
        host = (urlparse(self.base_url).hostname or "").lower() if self.base_url else ""
        known_endpoint_providers = {
            "api.openai.com": "openai",
            "integrate.api.nvidia.com": "nvidia",
            "openrouter.ai": "openrouter",
            "api.cerebras.ai": "cerebras",
            "api.fireworks.ai": "fireworks_ai",
            "api.sambanova.ai": "sambanova",
        }
        endpoint_provider = known_endpoint_providers.get(host)
        if endpoint_provider and self.provider not in {endpoint_provider, "custom"}:
            raise ValueError(
                f"Base URL '{self.base_url}' belongs to {endpoint_provider.replace('_', ' ').title()}, "
                f"but the selected provider is {self.display_provider.replace('_', ' ').title()}. "
                "Select the matching provider or clear the Base URL to use the selected provider's default endpoint."
            )

    def _initialize_llm(self) -> BaseChatModel:
        """Initialise the appropriate LLM client based on provider."""
        try:
            if self.provider in {
                "openai", "nvidia", "openrouter", "cerebras", "fireworks_ai",
                "sambanova", "custom", "perplexity", "deepseek", "mistral",
                "cohere", "hugging_face",
            }:
                from langchain_openai import ChatOpenAI
                # Build model_kwargs: merge seed + any extra kwargs
                _model_kwargs: dict = dict(self.model_kwargs)
                if self.seed is not None:
                    _model_kwargs["seed"] = self.seed
                kwargs: dict = {
                    "model": self.api_model,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "api_key": self.api_key,
                    "timeout": 60.0,
                    "max_retries": 2,
                }
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                if _model_kwargs:
                    kwargs["model_kwargs"] = _model_kwargs
                # ChatOpenAI otherwise builds its own HTTPX transport, which
                # bypasses PRISM_TRUSTED_CA_BUNDLE and fails behind enterprise
                # TLS-inspection proxies. The client remains owned by the LLM
                # instance for its full lifetime.
                kwargs["http_client"] = httpx_client(timeout=60.0)
                return ChatOpenAI(**kwargs)

            elif self.provider == "azure_openai":
                from langchain_openai import AzureChatOpenAI
                return AzureChatOpenAI(
                    model=self.model,
                    azure_deployment=self.deployment_name or self.model,
                    api_version=self.api_version or "2024-10-21",
                    azure_endpoint=self.base_url,
                    api_key=self.api_key,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=60.0,
                    max_retries=2,
                )

            elif self.provider == "anthropic":
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    api_key=self.api_key,
                    timeout=60.0,
                    max_retries=2,
                )

            elif self.provider in {"google", "google_gemini"}:
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    google_api_key=self.api_key,
                    max_retries=1,
                    timeout=60,
                )

            elif self.provider == "groq":
                from langchain_groq import ChatGroq
                return ChatGroq(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    api_key=self.api_key,
                )

            elif self.provider in {"xai", "grok", "x-ai", "x_ai"}:
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    api_key=self.api_key,
                    base_url=self.base_url or "https://api.x.ai/v1",
                    timeout=60.0,
                    max_retries=2,
                )

            elif self.provider in {"together", "together_ai"}:
                from langchain_together import ChatTogether
                return ChatTogether(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    api_key=self.api_key,
                )

            elif self.provider == "ollama":
                from langchain_ollama import ChatOllama
                return ChatOllama(
                    model=self.model,
                    temperature=self.temperature,
                    base_url=self.base_url or "http://localhost:11434",
                )

            else:
                raise ValueError(f"Unsupported LLM provider: '{self.provider}'")

        except ImportError as exc:
            logger.error("Missing package for provider '%s': %s", self.provider, exc)
            raise
        except Exception as exc:
            logger.error("Failed to initialise %s/%s: %s", self.provider, self.model, exc)
            raise

    # ── Public API ────────────────────────────────────────────────────────────

    def _invoke_single(
        self,
        llm: BaseChatModel,
        provider_name: str,
        model_name: str,
        prompt: str,
        system_message: Optional[str],
        temperature: Optional[float],
        json_mode: bool,
    ) -> str:
        """Invoke a specific LLM client and return the response string."""
        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=prompt))

        invoke_kwargs: dict = {}
        if temperature is not None:
            invoke_kwargs["temperature"] = temperature

        if json_mode and provider_name in {
            "openai", "nvidia", "custom", "perplexity", "deepseek", "mistral", "cohere", "hugging_face",
        }:
            invoke_kwargs["response_format"] = {"type": "json_object"}

        start = time.time()
        response = llm.invoke(messages, **invoke_kwargs)
        response_text = _normalize_response_content(getattr(response, "content", response))
        elapsed = time.time() - start
        logger.debug("LLM response from %s/%s in %.2fs, %d chars",
                     provider_name, model_name, elapsed, len(response_text))

        if not response_text:
            raise ValueError(f"Empty response from {provider_name}/{model_name}")
        return response_text

    @retry_with_backoff(max_retries=3, base_delay=2.0, exceptions=(RateLimitError, ConnectionError))
    def invoke(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
        **kwargs,
    ) -> str:
        """
        Invoke the LLM synchronously and return the response string.

        If the primary provider fails (rate limit, network, auth) and fallback
        providers are configured, each fallback is tried in order before raising.
        """
        logger.debug("LLM invoke: provider=%s model=%s json_mode=%s", self.provider, self.model, json_mode)

        # --- Attempt primary provider ---
        try:
            return self._invoke_single(
                self.llm, self.provider, self.model,
                prompt, system_message, temperature, json_mode,
            )

        except ConnectionResetError as exc:
            primary_error: Exception = ConnectionError(f"Connection reset by {self.provider}: {exc}")
        except OSError as exc:
            if "WinError 10054" in str(exc) or "connection" in str(exc).lower():
                primary_error = ConnectionError(f"Connection forcibly closed by {self.provider}: {exc}")
            else:
                raise
        except Exception as exc:
            error_msg = str(exc)
            lower_msg = error_msg.lower()
            is_rate_limited = any(t in lower_msg for t in (
                "rate", "429", "503", "resource_exhausted", "quota", "unavailable", "high demand", "overloaded",
            ))
            if is_rate_limited:
                logger.warning("Rate limit / quota exhaustion on %s/%s", self.provider, self.model)
                primary_error = RateLimitError(f"Rate limit / transient provider overload: {exc}")
            elif "connection" in lower_msg or "timeout" in lower_msg:
                primary_error = ConnectionError(f"Failed to connect to {self.provider}: {exc}")
            elif "auth" in lower_msg or "api key" in lower_msg or "401" in error_msg:
                raise ValueError(f"Authentication failed for {self.provider}: {exc}")
            else:
                raise

        # --- Try fallback providers ---
        if self._fallback_configs:
            logger.warning(
                "[LLM Fallback] Primary provider %s/%s failed (%s). Trying %d fallback(s)…",
                self.provider, self.model, primary_error, len(self._fallback_configs)
            )
            for i, fb_cfg in enumerate(self._fallback_configs, 1):
                fb_provider = fb_cfg.get("provider", "unknown")
                fb_model = fb_cfg.get("model", "unknown")
                fb_llm = self._build_fallback_llm(fb_cfg)
                if not fb_llm:
                    continue
                try:
                    result = self._invoke_single(
                        fb_llm, fb_provider, fb_model,
                        prompt, system_message, temperature, json_mode,
                    )
                    logger.info(
                        "[LLM Fallback] ✓ Fallback %d succeeded: %s/%s",
                        i, fb_provider, fb_model,
                    )
                    return result
                except Exception as fb_exc:
                    logger.warning(
                        "[LLM Fallback] Fallback %d failed (%s/%s): %s",
                        i, fb_provider, fb_model, fb_exc,
                    )

        # All providers exhausted — raise the original error
        raise primary_error

    async def ainvoke(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Async invoke."""
        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=prompt))
        response = await self.llm.ainvoke(messages, **kwargs)
        return _normalize_response_content(getattr(response, "content", response))

    def stream(self, prompt: str, system_message: Optional[str] = None):
        """Stream LLM response chunks."""
        messages = []
        if system_message:
            messages.append(SystemMessage(content=system_message))
        messages.append(HumanMessage(content=prompt))
        for chunk in self.llm.stream(messages):
            yield chunk.content

    def stream_with_reasoning(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        show_reasoning: bool = True,
    ):
        """Stream response chunks including reasoning/thinking content.

        Yields ``(chunk_type, text)`` tuples where ``chunk_type`` is either
        ``"reasoning"`` (thinking chain) or ``"content"`` (final answer).

        This method uses the raw OpenAI SDK directly so that
        ``reasoning_content`` deltas from thinking models (e.g. NVIDIA
        z-ai/glm-5.2) are exposed.  It is only meaningful for providers that
        support thinking mode (``nvidia``, ``custom`` with an appropriate
        ``extra_body`` in ``model_kwargs``).

        Example::

            llm = LLMProvider(
                provider="nvidia",
                model="z-ai/glm-5.2",
                api_key="nvapi-...",
                temperature=1,
                top_p=1,
                max_tokens=16384,
                seed=42,
                model_kwargs={
                    "extra_body": {
                        "chat_template_kwargs": {
                            "enable_thinking": True,
                            "clear_thinking": False,
                        }
                    }
                },
            )
            for chunk_type, text in llm.stream_with_reasoning("Explain entropy"):
                print(text, end="")
        """
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package is required for stream_with_reasoning. "
                "Install it with: pip install openai"
            ) from exc

        messages_payload = []
        if system_message:
            messages_payload.append({"role": "system", "content": system_message})
        messages_payload.append({"role": "user", "content": prompt})

        # Build extra_body from model_kwargs if present
        extra_body: Optional[Dict[str, Any]] = self.model_kwargs.get("extra_body") or None

        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url or "https://api.openai.com/v1",
        )

        create_kwargs: dict = {
            "model": self.api_model,
            "messages": messages_payload,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if self.seed is not None:
            create_kwargs["seed"] = self.seed
        if extra_body:
            create_kwargs["extra_body"] = extra_body

        completion = client.chat.completions.create(**create_kwargs)

        for chunk in completion:
            if not getattr(chunk, "choices", None):
                continue
            if not chunk.choices or getattr(chunk.choices[0], "delta", None) is None:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning and show_reasoning:
                yield "reasoning", reasoning
            content = getattr(delta, "content", None)
            if content:
                yield "content", content

    def test_connection(self) -> tuple[bool, str]:
        """Test LLM connection with a simple query."""
        try:
            response = self.invoke(
                prompt="Respond with only the word 'OK'",
                system_message="You are a test assistant. Respond with exactly 'OK'.",
                temperature=0.0,
            )
            if response and response.strip():
                return True, f"Successfully connected to {self.display_provider}/{self.model}"
            return False, f"Empty response from {self.display_provider}"
        except Exception as exc:
            return False, f"Connection test failed: {exc}"

    def test_connection_fast(self, timeout_seconds: float = 30.0) -> tuple[bool, str]:
        """Fast connectivity test without retry/backoff.

        For OpenAI-compatible providers (``openai``, ``nvidia``, ``custom``,
        ``azure_openai``, ``groq``, ``deepseek``, ``mistral``, ``cohere``,
        ``perplexity``, ``xai``, ``together_ai``, ``hugging_face``) this
        method creates a **fresh raw OpenAI SDK client** and calls the API
        directly — identical to the pattern used in standalone scripts.  This
        avoids the ``openai.APIConnectionError`` that LangChain's ``ChatOpenAI``
        raises when its httpx client is used from inside FastAPI's async
        context (e.g. called from a uvicorn worker thread).

        For all other providers (``anthropic``, ``google_gemini``, ``ollama``,
        ``groq``, ``bedrock``) the LangChain client is used via a
        ``ThreadPoolExecutor`` to enforce the wall-clock timeout without
        passing ``timeout`` as a kwarg to ``invoke()``.
        """
        _openai_compat = {
            "openai", "nvidia", "openrouter", "cerebras", "fireworks_ai",
            "sambanova", "custom", "azure_openai", "deepseek", "mistral",
            "cohere", "perplexity",
            "xai", "grok", "x-ai", "x_ai",
            "groq", "together_ai", "hugging_face",
        }
        # Known base URLs for OpenAI-compatible providers that don't
        # require the user to supply a base_url explicitly
        _default_base_urls = {
            "groq": "https://api.groq.com/openai/v1",
            "xai": "https://api.x.ai/v1",
            "grok": "https://api.x.ai/v1",
            "x-ai": "https://api.x.ai/v1",
            "x_ai": "https://api.x.ai/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "perplexity": "https://api.perplexity.ai",
            "together_ai": "https://api.together.xyz/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "cerebras": "https://api.cerebras.ai/v1",
            "fireworks_ai": "https://api.fireworks.ai/inference/v1",
            "sambanova": "https://api.sambanova.ai/v1",
        }

        if self.provider in _openai_compat:
            # ── Raw OpenAI SDK path (most reliable, no LangChain overhead) ──
            try:
                from openai import OpenAI, AzureOpenAI
            except ImportError as exc:
                return False, f"openai package not installed: {exc}"

            try:
                # OpenAI's SDK uses HTTPX. Inject Prism's shared TLS-aware
                # transport so corporate CA bundles and the explicit Zscaler
                # compatibility setting are honored during verification.
                with httpx_client(timeout=timeout_seconds) as http_client:
                    if self.provider == "azure_openai":
                        raw_client = AzureOpenAI(
                            api_key=self.api_key,
                            azure_endpoint=self.base_url,
                            api_version=self.api_version or "2024-10-21",
                            timeout=timeout_seconds,
                            max_retries=0,
                            http_client=http_client,
                        )
                    else:
                        effective_base_url = (
                            self.base_url
                            or _default_base_urls.get(self.provider)
                            or "https://api.openai.com/v1"
                        )
                        raw_client = OpenAI(
                            api_key=self.api_key,
                            base_url=effective_base_url,
                            timeout=timeout_seconds,
                            max_retries=0,
                            http_client=http_client,
                        )

                    # First verify endpoint reachability with a lightweight
                    # models listing call. This may be publicly readable on
                    # some gateways, so credential validation still requires
                    # the completion request below.
                    try:
                        raw_client.models.list()
                    except Exception as models_exc:
                        err = str(models_exc)
                        if self.api_key:
                            err = err.replace(self.api_key, "[REDACTED]")
                        return False, (
                            f"Fast connection test failed for {self.display_provider}/{self.model}: "
                            f"{err}"
                        )

                    # NVIDIA NIM authenticates its /models endpoint. Avoid a
                    # generation request during administration verification:
                    # large models can be queued or cold-started for longer
                    # than the request timeout despite a valid API key.
                    if self.provider == "nvidia":
                        return True, (
                            f"Credentials and NVIDIA endpoint verified for "
                            f"{self.display_provider}/{self.model}. "
                            "Model inference is validated when Prism first uses the model."
                        )

                    # Some other OpenAI-compatible gateways expose /models
                    # without authenticating the bearer token. A models listing
                    # alone must therefore not be treated as credential
                    # validation for those providers. Send the smallest
                    # possible inference request so the provider verifies that
                    # the supplied key is authorized to use the selected model.
                    try:
                        raw_client.chat.completions.create(
                            model=self.api_model,
                            messages=[{"role": "user", "content": "OK"}],
                            max_tokens=1,
                            temperature=0,
                        )
                    except Exception as completion_exc:
                        err = str(completion_exc)
                        if self.api_key:
                            err = err.replace(self.api_key, "[REDACTED]")
                        return False, (
                            f"Credential verification failed for "
                            f"{self.display_provider}/{self.model}: {err}"
                        )

                    return True, (
                        f"Credentials and endpoint verified for "
                        f"{self.display_provider}/{self.model}."
                    )

            except Exception as exc:
                err = str(exc)
                # Sanitise — remove key if it leaks into the message
                if self.api_key:
                    err = err.replace(self.api_key, "[REDACTED]")
                return False, f"Fast connection test failed for {self.display_provider}/{self.model}: {err}"

        # ── LangChain path for non-OpenAI-compatible providers ────────────
        import concurrent.futures

        messages = [
            SystemMessage(content="You are a test assistant. Respond with exactly 'OK'."),
            HumanMessage(content="Respond with only the word 'OK'"),
        ]

        def _do_invoke():
            return self.llm.invoke(messages)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_invoke)
            try:
                response = future.result(timeout=timeout_seconds)
                text = _normalize_response_content(getattr(response, "content", response))
                if text.strip():
                    return True, f"Successfully connected to {self.display_provider}/{self.model}"
                return False, f"Empty response from {self.display_provider}/{self.model}"
            except concurrent.futures.TimeoutError:
                return (
                    False,
                    f"Connection timed out after {int(timeout_seconds)}s for "
                    f"{self.display_provider}/{self.model}. "
                    "The endpoint may be slow — credentials may still be valid.",
                )
            except Exception as exc:
                return False, f"Fast connection test failed for {self.display_provider}/{self.model}: {exc}"

    def get_model_info(self) -> Dict[str, Any]:
        """Return metadata about the current model configuration."""
        return {
            "provider": self.provider,
            "display_provider": self.display_provider,
            "model": self.model,
            "api_model": self.api_model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "base_url": self.base_url,
            "seed": self.seed,
            "model_kwargs": self.model_kwargs,
            "project_id": self.project_id,
            "cache_enabled": settings.llm_cache_enabled,
        }
