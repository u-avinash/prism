"""Structured error types and classification for outbound integrations.

Integration clients can expose these types to callers so retry policy and
operator messaging distinguish credentials, throttling, transient transport
failures, and permanent request failures.
"""

from __future__ import annotations

import requests


class IntegrationError(RuntimeError):
    """Base class for failures communicating with an external integration."""

    def __init__(self, integration: str, message: str, *, status_code: int | None = None):
        self.integration = integration
        self.status_code = status_code
        prefix = f"{integration}: " if integration else ""
        super().__init__(f"{prefix}{message}")


class IntegrationAuthError(IntegrationError):
    """The integration rejected credentials or authorization."""


class IntegrationTimeoutError(IntegrationError, TimeoutError):
    """The integration request timed out."""


class IntegrationRateLimitError(IntegrationError):
    """The integration throttled the request; retry after backoff."""


class IntegrationTransientError(IntegrationError):
    """A likely temporary network or server-side failure."""


def classify_integration_error(
    integration: str,
    error: BaseException | str,
    *,
    status_code: int | None = None,
) -> IntegrationError:
    """Convert common HTTP/transport errors to a stable integration taxonomy.

    HTTP 401/403 errors are permanent until credentials or permissions change.
    HTTP 429 and 5xx responses, timeouts, and connection failures are retryable.
    Other HTTP errors are surfaced as permanent integration errors.
    """
    response = getattr(error, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)

    if isinstance(error, requests.exceptions.Timeout) or status_code in (408, 504):
        return IntegrationTimeoutError(
            integration,
            str(error) or "External integration request timed out",
            status_code=status_code,
        )
    if isinstance(error, TimeoutError):
        return IntegrationTimeoutError(integration, str(error), status_code=status_code)
    if isinstance(error, (requests.exceptions.ConnectionError, ConnectionError)):
        return IntegrationTransientError(integration, str(error), status_code=status_code)

    message = str(error) or "External integration request failed"
    if status_code in (401, 403):
        return IntegrationAuthError(integration, message, status_code=status_code)
    if status_code == 429:
        return IntegrationRateLimitError(integration, message, status_code=status_code)
    if status_code is not None and status_code >= 500:
        return IntegrationTransientError(integration, message, status_code=status_code)

    # Recognize requests HTTPError instances even when the response did not
    # provide a status code (e.g. synthetic responses in tests).
    if isinstance(error, requests.exceptions.HTTPError):
        return IntegrationError(integration, message, status_code=status_code)

    return IntegrationError(integration, message, status_code=status_code)


def is_retryable_integration_error(error: BaseException) -> bool:
    """Whether an integration exception represents a potentially transient fault."""
    return isinstance(
        error,
        (
            IntegrationTimeoutError,
            IntegrationRateLimitError,
            IntegrationTransientError,
        ),
    )
