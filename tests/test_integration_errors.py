"""Tests for structured integration error classification and retry policy."""

import requests

from integrations.errors import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationTransientError,
    classify_integration_error,
    is_retryable_integration_error,
)


def _http_error(status_code: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(f"HTTP {status_code}", response=response)


def test_authentication_failures_are_permanent_and_classified():
    for status_code in (401, 403):
        classified = classify_integration_error("Jira", _http_error(status_code))

        assert isinstance(classified, IntegrationAuthError)
        assert classified.status_code == status_code
        assert not is_retryable_integration_error(classified)


def test_rate_limit_and_server_errors_are_retryable():
    rate_limited = classify_integration_error("Jira", _http_error(429))
    server_error = classify_integration_error("Jira", _http_error(503))

    assert isinstance(rate_limited, IntegrationRateLimitError)
    assert is_retryable_integration_error(rate_limited)
    assert isinstance(server_error, IntegrationTransientError)
    assert is_retryable_integration_error(server_error)


def test_timeout_and_connection_errors_are_retryable():
    timeout = classify_integration_error(
        "GitHub",
        requests.exceptions.Timeout("request timed out"),
    )
    connection = classify_integration_error(
        "GitHub",
        requests.exceptions.ConnectionError("connection reset"),
    )

    assert isinstance(timeout, IntegrationTimeoutError)
    assert is_retryable_integration_error(timeout)
    assert isinstance(connection, IntegrationTransientError)
    assert is_retryable_integration_error(connection)


def test_other_client_errors_are_permanent_integration_errors():
    classified = classify_integration_error("Jira", _http_error(404))

    assert type(classified) is IntegrationError
    assert classified.status_code == 404
    assert not is_retryable_integration_error(classified)


def test_explicit_status_code_classification():
    classified = classify_integration_error("Anypoint", "throttled", status_code=429)

    assert isinstance(classified, IntegrationRateLimitError)
    assert "Anypoint" in str(classified)


def test_gateway_timeout_and_builtin_connection_error_are_retryable():
    timeout = classify_integration_error("Jira", "gateway timeout", status_code=504)
    connection = classify_integration_error("Jira", ConnectionError("reset"))

    assert isinstance(timeout, IntegrationTimeoutError)
    assert is_retryable_integration_error(timeout)
    assert isinstance(connection, IntegrationTransientError)
    assert is_retryable_integration_error(connection)


def test_jira_adapter_surfaces_authentication_error_without_retry():
    from integrations.jira_client import _handle_jira_error

    try:
        _handle_jira_error("ticket creation", _http_error(401), None)
    except IntegrationAuthError as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Expected Jira authentication error to be raised")


def test_jira_adapter_retries_transient_errors(monkeypatch):
    from integrations.jira_client import JiraClient
    import utils.retry_handler

    client = JiraClient.__new__(JiraClient)
    client.url = "https://jira.example.test"
    client.jira_project_key = "PRISM"

    class FailingJira:
        calls = 0

        def issue_create(self, fields):
            self.calls += 1
            raise _http_error(503)

    client.client = FailingJira()
    monkeypatch.setattr(utils.retry_handler.time, "sleep", lambda _delay: None)

    try:
        client.create_incident_ticket(
            incident_id="A123",
            app_name="demo",
            environment="test",
            error_title="failure",
            error_description="details",
            severity="HIGH",
        )
    except IntegrationTransientError as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("Expected transient Jira error to be raised")

    assert client.client.calls == 4
