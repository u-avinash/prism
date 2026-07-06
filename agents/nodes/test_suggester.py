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
"""
Test case suggestion node — generates a unit test alongside the proposed fix.

This node runs after `generate_fix` and before `generate_pdf`.  It produces a
suggested unit test that would have caught the bug, in the detected language
and framework.  The test is:
  - Stored in the incident metadata for display in the UI
  - Shown to the reviewer in the approval tab
  - NOT committed automatically — the reviewer can include it in the PR optionally

The node is best-effort: failure here never blocks the workflow.
"""
import logging
from agents.state import AgentState

logger = logging.getLogger(__name__)

# Language-to-test-framework mapping
_TEST_FRAMEWORK_MAP = {
    "java":       "JUnit 5 + Mockito",
    "kotlin":     "JUnit 5 + MockK",
    "scala":      "ScalaTest",
    "groovy":     "Spock",
    "mulesoft":   "MUnit (MuleSoft unit testing framework)",
    "python":     "pytest",
    "nodejs":     "Jest",
    "javascript": "Jest",
    "typescript": "Jest + TypeScript",
    "dotnet":     "xUnit + Moq",
    "csharp":     "xUnit + Moq",
    "go":         "Go testing package (go test)",
    "ruby":       "RSpec",
    "php":        "PHPUnit",
    "rust":       "Rust built-in test module (#[test])",
    "unknown":    "the appropriate test framework for the language",
}


def generate_test_suggestion_node(state: AgentState) -> AgentState:
    """
    Generate a unit test suggestion for the proposed fix.

    This node:
    1. Extracts technology context from metadata
    2. Calls LLM to generate a unit test that would have caught the bug
    3. Stores the suggestion in incident metadata
    4. Appends a note to the workflow messages

    The node is non-blocking — any failure is caught and logged.
    """
    incident_id = state.get("incident_id", "")
    logger.info("[Test Suggester] Generating test suggestion for incident %s", incident_id)

    try:
        # Only generate if we have a fix and RCA
        if not state.get("proposed_fix") or not state.get("rca_text"):
            logger.info("[Test Suggester] Skipping — no fix or RCA available")
            return state

        metadata = state.get("metadata") or {}
        source_technology = metadata.get("source_technology", "unknown")
        detected_framework = metadata.get("detected_framework") or ""
        test_framework = _TEST_FRAMEWORK_MAP.get(source_technology, _TEST_FRAMEWORK_MAP["unknown"])

        error_title = state.get("error_title", "")
        error_file = state.get("error_file_path", "") or ""
        error_line = state.get("error_line_number") or "N/A"
        rca_summary = (state.get("rca_text") or "")[:600]
        fix_summary = (state.get("fix_explanation") or "")[:400]

        tech_display = source_technology
        if detected_framework:
            tech_display += f"/{detected_framework}"

        from integrations.llm_provider import LLMProvider
        llm = LLMProvider(project_id=state.get("project_id"))

        prompt = f"""You are a senior software engineer writing a unit test that would have caught a production bug.

LANGUAGE / FRAMEWORK: {tech_display}
TEST FRAMEWORK: {test_framework}
ERROR: {error_title}
FILE: {error_file}  LINE: {error_line}

ROOT CAUSE SUMMARY:
{rca_summary}

FIX APPLIED:
{fix_summary}

Write a concise unit test in {tech_display} using {test_framework} that:
1. Tests the SPECIFIC code path that failed (the one identified by the root cause)
2. Verifies the FIX is correct (i.e., the test would PASS with the fix, FAIL without it)
3. Uses clear naming: test_<what>_when_<condition>_should_<expected_outcome>
4. Includes a brief comment explaining what bug this test prevents

Output ONLY the test code — no explanations, no markdown headers, just the code block.

```{source_technology}
// Your test here
```"""

        response = llm.invoke(
            prompt=prompt,
            system_message=(
                f"You are a TDD expert in {tech_display}. "
                "Write a minimal, focused unit test. Output only the code block."
            ),
            temperature=0.2,
        )

        # Store in metadata for UI display
        existing_meta = dict(metadata)
        existing_meta["suggested_test"] = response.strip()
        existing_meta["suggested_test_framework"] = test_framework
        existing_meta["suggested_test_technology"] = tech_display
        state["metadata"] = existing_meta

        # Persist to DB
        try:
            from storage.database import get_session
            from storage.incident_repository import IncidentRepository
            with get_session() as session:
                repo = IncidentRepository(session)
                repo.update(incident_id=incident_id, incident_metadata=existing_meta)
        except Exception as db_exc:
            logger.warning("[Test Suggester] Could not persist to DB: %s", db_exc)

        state["messages"] = state.get("messages", []) + [
            f"✓ Unit test suggestion generated ({test_framework})"
        ]
        logger.info("[Test Suggester] ✓ Test suggestion generated for %s", incident_id)

    except Exception as exc:
        logger.warning("[Test Suggester] Test suggestion failed (non-critical): %s", exc)
        state["messages"] = state.get("messages", []) + [
            f"ℹ️ Test suggestion skipped: {exc}"
        ]

    return state
