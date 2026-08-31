"""
Regression test for the LLM timeout-classification bug reported via ingestion API logs:

    [RCA Generation] Failed for 8XGQ: Request timed out.
    [Workflow Retry] generate_rca failed (attempt 1/3) for incident 8XGQ: ...

Root cause: LLMProvider.invoke() classified transient timeout exceptions by checking
`"timeout" in lower_msg`. Provider SDKs (e.g. openai) raise messages phrased as
"Request timed out." — which does NOT contain the substring "timeout" — so the
exception fell through to the final `else: raise`, bypassing both the LLM-level
retry/backoff decorator (which only catches RateLimitError/ConnectionError) and the
configured fallback-provider chain. This forced the much more expensive
node-level workflow retry (re-fetching code, rebuilding prompts, 5s sleep, etc.)
instead of an immediate LLM-level retry.

This test locks in the fix: any exception message containing "timed out" (with
or without "timeout") must be classified as ConnectionError so it is retried by
the `retry_with_backoff` decorator and eligible for fallback providers.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import MagicMock

import integrations.llm_provider as llm_module
from utils.retry_handler import RateLimitError


def _make_provider_stub(fail_message: str, fail_times: int = 1):
    """Build a MagicMock standing in for a real LLMProvider instance."""
    provider = MagicMock()
    provider.provider = "openai"
    provider.model = "gpt-4"
    provider.project_id = None
    provider._fallback_configs = []

    call_count = {"n": 0}

    def fake_invoke_single(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] <= fail_times:
            raise Exception(fail_message)
        return "OK response"

    provider._invoke_single = fake_invoke_single
    provider._call_count = call_count
    return provider


def _bound_invoke(provider):
    """Bind the real (undecorated) LLMProvider.invoke logic to a mock instance."""
    raw_invoke = llm_module.LLMProvider.invoke.__wrapped__
    return raw_invoke.__get__(provider, type(provider))


@pytest.mark.parametrize(
    "timeout_message",
    [
        "Request timed out.",
        "Connection timed out",
        "The read operation timed out",
        "httpx.ReadTimeout: timed out",
        "deadline exceeded while waiting for response",
    ],
)
def test_timeout_variants_classified_as_connection_error(timeout_message):
    """All common timeout phrasing must raise ConnectionError, not fall through unclassified."""
    provider = _make_provider_stub(timeout_message, fail_times=99)
    bound_invoke = _bound_invoke(provider)

    with pytest.raises(ConnectionError):
        bound_invoke(provider, "test prompt")


def test_timeout_is_retryable_by_backoff_decorator():
    """
    With the classification fixed, the retry_with_backoff decorator (which only
    catches RateLimitError/ConnectionError) must actually retry a transient
    timeout and succeed on a later attempt — proving the LLM-level retry path
    (not the expensive node-level workflow retry) handles this case.
    """
    provider = _make_provider_stub("Request timed out.", fail_times=1)

    # Re-apply the real decorator around the raw function, bound to our stub,
    # with a near-zero delay so the test runs fast.
    raw_invoke = llm_module.LLMProvider.invoke.__wrapped__
    decorated = llm_module.retry_with_backoff(
        max_retries=3, base_delay=0.01, exceptions=(RateLimitError, ConnectionError)
    )(raw_invoke)
    bound_invoke = decorated.__get__(provider, type(provider))

    result = bound_invoke(provider, "test prompt")
    assert result == "OK response"
    assert provider._call_count["n"] == 2  # 1 failure + 1 success


def test_non_timeout_unrelated_error_still_raises_unclassified():
    """Sanity check: unrelated errors are still raised as-is (not silently swallowed)."""
    provider = _make_provider_stub("Some unexpected internal server crash", fail_times=99)
    bound_invoke = _bound_invoke(provider)

    with pytest.raises(Exception, match="Some unexpected internal server crash"):
        bound_invoke(provider, "test prompt")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
