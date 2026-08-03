"""Shared validation and outbound HTTP helpers for Team Admin integrations."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 15
settings = get_settings()

# Most LLM SDKs use httpx/OpenSSL directly rather than requests. Expose the
# same enterprise CA bundle to those libraries before they construct clients.
if settings.trusted_ca_bundle:
    _configured_ca_bundle = str(Path(settings.trusted_ca_bundle).expanduser())
    os.environ.setdefault("SSL_CERT_FILE", _configured_ca_bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _configured_ca_bundle)


class IntegrationVerificationError(ValueError):
    """A safe, user-facing integration verification error."""


def validate_https_url(
    value: str,
    *,
    integration: str,
    allowed_hosts: Iterable[str] | None = None,
) -> str:
    """Validate an externally supplied integration endpoint before connecting."""
    url = (value or "").strip()
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise IntegrationVerificationError(f"{integration} URL must use HTTPS.")
    if not parsed.hostname:
        raise IntegrationVerificationError(f"{integration} URL must include a valid host.")
    if parsed.username or parsed.password:
        raise IntegrationVerificationError(f"{integration} URL must not contain user credentials.")

    if allowed_hosts:
        host = parsed.hostname.lower()
        normalized_hosts = tuple(item.lower() for item in allowed_hosts)
        if not any(host == item or host.endswith(f".{item}") for item in normalized_hosts):
            allowed = ", ".join(normalized_hosts)
            raise IntegrationVerificationError(
                f"{integration} URL must use an approved host ({allowed})."
            )

    return url


def tls_verify_value() -> bool | str:
    """Return Requests' verification value using the configured enterprise CA bundle."""
    ca_bundle = (settings.trusted_ca_bundle or "").strip()
    if ca_bundle:
        candidate = Path(ca_bundle).expanduser()
        if not candidate.is_file():
            raise IntegrationVerificationError(
                "The configured PRISM_TRUSTED_CA_BUNDLE file does not exist or is not a file."
            )
        return str(candidate)

    # Certificate validation remains enabled unless an administrator explicitly
    # enables the emergency compatibility switch for a TLS-intercepting proxy.
    return not settings.allow_unverified_tls


def httpx_client(*, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> httpx.Client:
    """Build an HTTPX client that follows Prism's enterprise TLS policy.

    OpenAI-compatible LLM SDKs use HTTPX instead of Requests.  Supplying this
    client ensures their Team Admin verification uses the same CA bundle or
    administrator-enabled Zscaler compatibility policy as Jira, GitHub, Slack,
    Teams, and Anypoint.
    """
    verify = tls_verify_value()
    if verify is False:
        logger.warning(
            "Outbound LLM verification is using unverified TLS because "
            "ALLOW_UNVERIFIED_TLS is enabled."
        )
    return httpx.Client(verify=verify, timeout=timeout)


def request(
    method: str,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> requests.Response:
    """Send an outbound verification request with one consistent TLS policy."""
    verify = tls_verify_value()
    if verify is False:
        logger.warning(
            "Outbound integration verification is using unverified TLS because "
            "PRISM_ALLOW_UNVERIFIED_TLS is enabled."
        )
        # Avoid noisy warning output only when the administrator opted into this.
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    kwargs.setdefault("timeout", timeout)
    kwargs.setdefault("verify", verify)
    return requests.request(method, url, **kwargs)


def connection_error(integration: str, exc: requests.SSLError) -> IntegrationVerificationError:
    """Convert TLS errors into configuration guidance without leaking credentials."""
    if settings.allow_unverified_tls:
        return IntegrationVerificationError(
            f"Unable to verify {integration}: TLS negotiation failed even with the configured "
            f"compatibility setting. Check the endpoint and network proxy."
        )

    bundle_hint = (
        " Configure PRISM_TRUSTED_CA_BUNDLE with your organization’s PEM root/intermediate "
        "CA bundle, then restart Prism. As a temporary administrator-only compatibility "
        "option, set PRISM_ALLOW_UNVERIFIED_TLS=true and restart Prism."
    )
    return IntegrationVerificationError(
        f"Unable to verify {integration} because the TLS certificate could not be validated."
        f"{bundle_hint}"
    )


def sanitized_response_text(response: requests.Response, limit: int = 300) -> str:
    """Return a bounded response excerpt suitable for displaying in the UI."""
    text = (response.text or "").strip().replace("\r", " ").replace("\n", " ")
    return text[:limit] if text else "Unknown response"
