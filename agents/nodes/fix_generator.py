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
"""Code fix generation node using LLM."""
import logging
from datetime import datetime
import yaml
import re
from agents.state import AgentState, WORKFLOW_TOTAL_STEPS
from integrations.llm_provider import LLMProvider
from utils.code_fetcher import CodeFetcher

logger = logging.getLogger(__name__)


def _trim_text(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    half = max(1, limit // 2)
    return f"{text[:half]}\n...\n{text[-half:]}"


def generate_fix_node(state: AgentState) -> AgentState:
    """
    Generate code fix using LLM.
    
    This node:
    1. Uses RCA summary to understand the issue
    2. Calls LLM to generate a code fix
    3. Parses the response for code and explanation
    4. Validates the fix for dangerous patterns
    
    Args:
        state: Current agent state with RCA
        
    Returns:
        Updated state with proposed fix and explanation
    """
    incident_id = state['incident_id']
    logger.info(f"[Fix Generation] Generating fix for incident {incident_id}")
    
    try:
        # Get file info from state (set by RCA generator)
        error_file_path = state.get('error_file_path')
        error_line_number = state.get('error_line_number')
        error_file_type = state.get('error_file_type')
        repo_full_name = state.get('repo_full_name')
        file_type_key = error_file_type or 'code'

        # Technology context (set by OTLP parser via metadata)
        metadata = state.get('metadata') or {}
        source_technology = metadata.get('source_technology', 'unknown')
        detected_framework = metadata.get('detected_framework') or ''
        tech_display = source_technology + (f'/{detected_framework}' if detected_framework else '')
        
        # Log metadata status
        logger.info(f"[Fix Generation] GitHub metadata from state:")
        logger.info(f"  - repo_full_name: {repo_full_name}")
        logger.info(f"  - error_file_path: {error_file_path}")
        logger.info(f"  - error_line_number: {error_line_number}")
        logger.info(f"  - error_file_type: {error_file_type}")
        
        # Persist GitHub metadata to database early for reliability
        if repo_full_name and error_file_path:
            try:
                from storage.database import get_session
                from storage.incident_repository import IncidentRepository

                with get_session() as session:
                    repo_db = IncidentRepository(session)
                    repo_db.update(
                        incident_id=incident_id,
                        repo_full_name=repo_full_name,
                        error_file_path=error_file_path,
                    )
                    logger.debug(f"[Fix Generation] ✓ Persisted GitHub metadata to database")
            except Exception as db_error:
                logger.warning(f"[Fix Generation] Failed to persist metadata (non-critical): {db_error}")
        else:
            logger.warning(f"[Fix Generation] ⚠️  GitHub metadata incomplete - some features may be limited")
        
        # Fetch actual code from GitHub using project context
        code_fetcher = CodeFetcher(project_id=state.get('project_id'))
        code_context = None
        
        # Load prompt template early (needed for both code fetch and fallback)
        with open('config/prompts.yaml', 'r', encoding='utf-8') as f:
            prompts = yaml.safe_load(f)
        
        # Initialize LLM provider early (needed for both approaches)
        llm_provider = LLMProvider(project_id=state.get('project_id'))
        logger.info(
            "[Fix Generation] Using LLM provider=%s model=%s project_id=%s",
            llm_provider.provider,
            llm_provider.model,
            llm_provider.project_id,
        )
        
        # Extract RCA summary early (needed for both approaches)
        rca_summary = state.get('rca_text', '')[:800] if state.get('rca_text') else 'No RCA available'
        
        if error_file_path and repo_full_name:
            logger.info(f"[Fix Generation] Fetching code: {repo_full_name}/{error_file_path}")
            try:
                code_context = code_fetcher.fetch_code_for_analysis(
                    repo_full_name=repo_full_name,
                    file_path=error_file_path,
                    line_number=error_line_number,
                    context_lines=30  # More context for fix generation
                )
                if code_context:
                    logger.info(f"[Fix Generation] ✓ Code fetched successfully ({code_context['line_count']} lines)")
                else:
                    logger.warning(f"[Fix Generation] ✗ Code fetch returned None — GitHub repo may be inaccessible or file path incorrect")
                    # Surface the GitHub access failure as a diagnostic message
                    if not code_fetcher.github_client:
                        github_diag = f"⚠️ GitHub not configured for project '{state.get('project_id')}' — fix generated without code context"
                    else:
                        github_diag = (
                            f"⚠️ GitHub repo access failed: could not fetch '{error_file_path}' "
                            f"from '{repo_full_name}'. "
                            f"Check GitHub token and repo/file path in Project Configuration."
                        )
                    state['messages'] = state.get('messages', []) + [github_diag]
                    logger.warning(f"[Fix Generation] {github_diag}")
            except Exception as fetch_error:
                logger.error(f"[Fix Generation] ✗ Code fetch failed: {fetch_error}")
                github_diag = (
                    f"⚠️ GitHub access error for '{repo_full_name}/{error_file_path}': {fetch_error}. "
                    f"Falling back to error-context-only fix."
                )
                state['messages'] = state.get('messages', []) + [github_diag]

        # Fetch MuleSoft project context only for MuleSoft/Java apps (all XML + DWL)
        project_files: dict = {}
        if repo_full_name and source_technology in ('mulesoft', 'java', 'unknown'):
            try:
                project_files = code_fetcher.fetch_mulesoft_project_context(repo_full_name)
                logger.info(f"[Fix Generation] ✓ Fetched {len(project_files)} MuleSoft project files")
            except Exception as ctx_err:
                logger.warning(f"[Fix Generation] Could not fetch project context: {ctx_err}")
        elif not repo_full_name:
            logger.warning(f"[Fix Generation] ✗ Missing GitHub metadata (repo={repo_full_name}, file={error_file_path})")
            if error_file_path:
                # File path was extracted from telemetry correctly — only the repo is
                # missing, which means the GitHub repo was inaccessible (404) or the
                # application has no registered owner/repository mapping.
                state['messages'] = state.get('messages', []) + [
                    f"⚠️ GitHub repository could not be resolved for '{state.get('app_name', 'unknown')}' "
                    f"(file path '{error_file_path}' was detected). "
                    f"Register the application with its owner/repository in Team Admin → Applications, "
                    f"or verify the GitHub token has Contents: Read access to the repository."
                ]
            else:
                state['messages'] = state.get('messages', []) + [
                    f"⚠️ GitHub metadata missing: repo_full_name='{repo_full_name}', "
                    f"error_file_path='{error_file_path}'. "
                    f"Ensure the incident telemetry includes repository information or "
                    f"register the application in Team Admin → Applications."
                ]

        if not code_context:
            logger.warning("[Fix Generation] Could not fetch code from GitHub, using fallback approach")
            # Generate fix based on error information alone
            return _generate_fallback_fix(
                state,
                prompts,
                llm_provider,
                error_file_path or '',
                error_line_number or 0,
                error_file_type or '',
                rca_summary,
            )
        
        assert code_context is not None
        code_context_data = code_context
        fix_prompt = prompts['code_fix_generation']
        
        # Technology-aware fix instructions
        file_type_instructions = {
            # MuleSoft / Java
            'dataweave':  "Fix the DataWeave transformation. Ensure proper null handling, type coercions, and default values.",
            'mule_xml':   "Fix the Mule flow XML. Ensure proper error handling, flow logic, and connector configuration.",
            'yaml':       "Fix the YAML configuration. Ensure proper indentation, syntax, and valid values.",
            'java':       "Fix the Java code. Ensure proper null checks, exception handling, and resource cleanup.",
            'kotlin':     "Fix the Kotlin code. Use idiomatic null-safety operators (?., ?:) and proper coroutine error handling.",
            'scala':      "Fix the Scala code. Use Option/Either for null safety and proper functional error handling.",
            'groovy':     "Fix the Groovy code. Use safe navigation operator (?.) and proper try/catch blocks.",
            # Other languages
            'python':     "Fix the Python code. Ensure proper exception handling with try/except, check for None values, and use context managers.",
            'javascript': "Fix the JavaScript/Node.js code. Add proper null/undefined checks, async error handling, and Promise rejection handling.",
            'typescript': "Fix the TypeScript code. Use strict null checks, proper type guards, and async/await error handling.",
            'csharp':     "Fix the C# code. Use null-conditional operators (?.), proper async/await patterns, and exception handling.",
            'go':         "Fix the Go code. Handle all error return values, check for nil pointers, and use defer for cleanup.",
            'ruby':       "Fix the Ruby code. Add proper rescue blocks, check for nil with &. safe navigation, and add guard clauses.",
            'php':        "Fix the PHP code. Add null coalescing operators (??), proper try/catch, and input validation.",
            'rust':       "Fix the Rust code. Use Result/Option properly, handle all match arms, and avoid unwrap() in production paths.",
        }
        specific_instruction = file_type_instructions.get(
            file_type_key,
            f"Fix the {tech_display} code. Follow language best practices for error handling and null safety."
        )
        
        full_code_for_storage = code_context_data["full_content"]
        prompt_code_context = _trim_text(code_context_data["full_content"], 12000)
        prompt_error_snippet = _trim_text(code_context_data.get("context_snippet", ""), 4000)

        # Build project-wide context section for the prompt (other XML/DWL files)
        project_context_section = ""
        if project_files:
            other_files = {
                p: c for p, c in project_files.items()
                if p != code_context_data.get("file_path")
            }
            if other_files:
                parts = []
                char_budget = 8000
                for path, content in other_files.items():
                    snippet = _trim_text(content, 1500)
                    entry = f"### {path}\n```xml\n{snippet}\n```\n"
                    if len('\n'.join(parts)) + len(entry) > char_budget:
                        break
                    parts.append(entry)
                if parts:
                    project_context_section = (
                        "\n## Full MuleSoft Project Context\n"
                        "The following files are part of the same MuleSoft project. "
                        "Use them to understand the full flow before proposing the fix.\n\n"
                        + "\n".join(parts)
                    )

        # Format comprehensive prompt with actual code - TARGETED FIX APPROACH
        formatted_prompt = f"""{fix_prompt}

## Error Context
**Error Title:** {state['error_title']}
**Technology Stack:** {tech_display}
**File:** {error_file_path}
**Line:** {error_line_number}
**File Type:** {error_file_type}

## Root Cause Analysis Summary
{rca_summary}

## Actual Code from Repository
**Repository:** {repo_full_name}
**Full File Path:** {error_file_path}

```{file_type_key}
{prompt_code_context}
```

## Error Location (highlighted)
```
{prompt_error_snippet}
```
{project_context_section}

## Your Task
{specific_instruction}

**CRITICAL INSTRUCTIONS - TARGETED FIX APPROACH:**
1. **Identify the EXACT lines that need to be changed** (usually just 1-10 lines around the error)
2. **Provide ONLY those specific lines with the fix applied** (not the entire file)
3. **Include enough context** (2-3 lines before and after) to locate the exact position
4. **Add clear comments** explaining what was changed
5. **Be minimal** - only change what's absolutely necessary to fix the error
6. **The fix must be production-ready and safe**

**WHY THIS MATTERS:** Large files can be truncated. We need only the changed lines to generate accurate patches.

**REQUIRED Output Format (MUST MATCH THIS EXACTLY):**

**Original Code (with context):**
```{error_file_type}
[Include 3-5 lines BEFORE the problematic code for context]
[The EXACT lines from the original file that contain the bug]
[Include 3-5 lines AFTER the problematic code for context]
```

**Fixed Code (with same context):**
```{error_file_type}
[Same 3-5 lines BEFORE]
[The FIXED version of the problematic lines]
[Same 3-5 lines AFTER]
```

**CRITICAL:**
- The "Original Code" block MUST contain lines that appear EXACTLY in the original file above
- Both blocks MUST have the SAME context lines before and after
- Only the problematic lines in the middle should differ between original and fixed
- Include enough context (3-5 lines) to uniquely identify the location

**Example:**
**Original Code (with context):**
```xml
    </flow>

    <sub-flow name="validate-order-payload" doc:name="Validate Order Payload">
        <logger level="INFO" message="Validating incoming order payload" category="com.enterprise.retail.orders"/>

        <!-- Keep a consistent structure for downstream processing -->
        <ee:transform doc:name="Normalize Order Payload">
            <ee:message>
                <ee:set-payload><![CDATA[%dw 2.0
output application/json
---
{{
  orderId: payload.orderId default "N/A",
  orderDate: payload.orderDate,
  items: payload.items default []
}}]]></ee:set-payload>
            </ee:message>
        </ee:transform>
```

**Fixed Code (with same context):**
```xml
    </flow>

    <sub-flow name="validate-order-payload" doc:name="Validate Order Payload">
        <logger level="INFO" message="Validating incoming order payload" category="com.enterprise.retail.orders"/>

        <!-- Keep a consistent structure for downstream processing -->
        <ee:transform doc:name="Normalize Order Payload">
            <ee:message>
                <ee:set-payload><![CDATA[%dw 2.0
output application/json
---
{{
  orderId: payload.orderId default "N/A",
  orderDate: payload.orderDate default now(),
  items: payload.items default []
}}]]></ee:set-payload>
            </ee:message>
        </ee:transform>
```

## Explanation
[Explain what was changed and why it fixes the issue]
"""
        
        # Generate fix — system message is technology-aware
        _tech_expertise = {
            'mulesoft':    'MuleSoft/Anypoint Platform, DataWeave, and Mule 4 flows',
            'java':        'Java/Spring Boot, JVM ecosystems',
            'python':      'Python, Django/FastAPI/Flask',
            'nodejs':      'Node.js/JavaScript/TypeScript, Express/NestJS',
            'dotnet':      'C#/.NET, ASP.NET Core',
            'go':          'Go, Gin/Echo/Fiber',
            'ruby':        'Ruby, Ruby on Rails',
            'php':         'PHP, Laravel/Symfony',
            'rust':        'Rust, Actix/Axum',
        }
        expertise = _tech_expertise.get(source_technology, 'multiple programming languages')
        system_msg = (
            f"You are an expert software engineer specializing in {expertise}. "
            "Generate safe, production-ready code fixes. "
            "Always use idiomatic patterns for the target language."
        )
        logger.info(f"[Fix Generation] Calling LLM ({llm_provider.provider}) for {tech_display}")
        fix_response = llm_provider.invoke(
            prompt=formatted_prompt,
            system_message=system_msg,
        )
        
        # Parse response to extract explanation but KEEP FULL RESPONSE for patch generation
        # The patch generator needs both Original and Fixed code blocks
        proposed_fix = fix_response  # Keep full response with both code blocks
        fix_explanation = _extract_explanation(fix_response)
        
        # Validate for dangerous patterns
        safety_check, concerns = _validate_fix_safety(proposed_fix)
        
        if not safety_check:
            logger.warning(f"[Fix Generation] Safety concerns detected: {concerns}")
        
        # Store the original code in STATE for patch generation (critical!)
        state['original_code'] = full_code_for_storage
        logger.info(f"[Fix Generation] ✓ Stored original_code in STATE ({len(full_code_for_storage)} chars)")
        
        # Also store in database for persistence
        try:
            from storage.database import get_session
            from storage.incident_repository import IncidentRepository
            
            with get_session() as session:
                repo_db = IncidentRepository(session)
                repo_db.update(
                    incident_id=state['incident_id'],
                    fetched_code=full_code_for_storage
                )
            logger.info(f"[Fix Generation] ✓ Stored fetched_code in DATABASE")
        except Exception as db_error:
            logger.error(f"[Fix Generation] Failed to store fetched code in DB: {db_error}")
        
        # Update state
        state['proposed_fix'] = proposed_fix
        state['fix_explanation'] = fix_explanation
        state['affected_files'] = [error_file_path] if error_file_path else []
        state['current_node'] = 'generate_fix'
        state['updated_at'] = datetime.utcnow().isoformat()
        
        # Update workflow tracking
        completed_steps = list(state.get('workflow_completed_steps') or [])
        if 'generate_fix' not in completed_steps:
            completed_steps.append('generate_fix')
        state['workflow_completed_steps'] = completed_steps
        
        state['workflow_progress_pct'] = len(completed_steps) / WORKFLOW_TOTAL_STEPS

        messages = [f"✓ Code fix generated successfully"]
        if not safety_check:
            messages.append(f"⚠️ Safety concerns: {', '.join(concerns)}")

        state['messages'] = state.get('messages', []) + messages

        # Send "Fix Generated" notification
        try:
            from agents.workflow import _send_event_notification
            _send_event_notification(
                event="Fix Generated",
                incident_id=state['incident_id'],
                severity=state.get('severity', 'HIGH'),
                app_name=state.get('app_name', ''),
                environment=state.get('environment', ''),
                details=(
                    f"Code fix generated for: {state.get('error_title', 'Unknown')}\n"
                    f"File: {error_file_path or 'N/A'}\n"
                    f"Explanation: {fix_explanation[:300]}{'...' if len(fix_explanation) > 300 else ''}"
                ),
                project_id=state.get('project_id'),
            )
        except Exception as _notify_err:
            logger.warning("[Fix Generation] Could not send fix-generated notification: %s", _notify_err)

        # Update database with workflow progress
        try:
            from storage.database import get_session
            from storage.incident_repository import IncidentRepository
            
            with get_session() as session:
                repo = IncidentRepository(session)
                repo.update(
                    incident_id=state['incident_id'],
                    current_workflow_node='generate_fix',
                    workflow_completed_steps=state['workflow_completed_steps'],
                    workflow_progress_pct=state['workflow_progress_pct'],
                    proposed_fix=proposed_fix,
                    fix_explanation=fix_explanation
                )
        except Exception as db_error:
            logger.warning(f"Failed to update workflow progress in DB: {db_error}")
        
        logger.info(f"[Fix Generation] Success for {state['incident_id']}")
        
    except Exception as e:
        logger.error(f"[Fix Generation] Failed for {state['incident_id']}: {str(e)}")
        error_text = str(e)
        if "Missing API key for provider" in error_text:
            error_text = (
                f"{error_text} "
                f"(incident={state['incident_id']}, app={state.get('app_name', 'unknown')}, project_id={state.get('project_id')})"
            )
        state['error_message'] = f"Fix generation failed: {error_text}"
        state['proposed_fix'] = None
        state['fix_explanation'] = f"Error generating fix: {error_text}"
        state['messages'] = state.get('messages', []) + [
            f"❌ Fix generation failed: {error_text}"
        ]
        
        # Update workflow tracking even on failure
        try:
            from storage.database import get_session
            from storage.incident_repository import IncidentRepository
            
            with get_session() as session:
                repo = IncidentRepository(session)
                repo.update(
                    incident_id=state['incident_id'],
                    current_workflow_node='generate_fix_failed',
                    workflow_progress_pct=state.get('workflow_progress_pct', 0.0)
                )
        except Exception as db_error:
            logger.warning(f"Failed to update failure status in DB: {db_error}")
    
    return state


def _extract_explanation(response: str) -> str:
    """
    Extract explanation section from LLM response.
    
    Args:
        response: Full LLM response
        
    Returns:
        Extracted explanation text
    """
    # Extract explanation section
    explanation_match = re.search(r'## Explanation\n(.*?)(?=##|$)', response, re.DOTALL)
    if explanation_match:
        return explanation_match.group(1).strip()
    
    # Try alternative heading
    explanation_match = re.search(r'\*\*Explanation\*\*:?\n(.*?)(?=##|\*\*|$)', response, re.DOTALL)
    if explanation_match:
        return explanation_match.group(1).strip()
    
    return "No explanation provided"


def _parse_fix_response(response: str, file_type: str) -> tuple[str, str]:
    """
    Parse LLM response to extract code and explanation.
    
    Expected format:
    ## Fixed Code
    ```filetype
    <code here>
    ```
    
    ## Explanation
    <explanation here>
    
    Returns:
        Tuple of (proposed_fix, explanation)
    """
    # Try to extract code block with file type
    patterns = [
        rf'```{file_type}\n(.*?)\n```',
        r'```(?:xml|java|python|yaml|dataweave)?\n(.*?)\n```',
        r'```\n(.*?)\n```'
    ]
    
    proposed_fix = None
    for pattern in patterns:
        code_match = re.search(pattern, response, re.DOTALL)
        if code_match:
            proposed_fix = code_match.group(1).strip()
            break
    
    if not proposed_fix:
        # Fallback: use entire response if no code block found
        proposed_fix = response
    
    # CRITICAL FIX: Remove markdown formatting that corrupts patch files
    # Remove markdown headers like "## Fixed Code", "## Code", etc.
    proposed_fix = re.sub(r'^##\s+.*$', '', proposed_fix, flags=re.MULTILINE)
    
    # Remove inline code block markers that might have been included
    proposed_fix = re.sub(r'^```\w*$', '', proposed_fix, flags=re.MULTILINE)
    
    # Remove leading/trailing whitespace from each line preservation
    lines = proposed_fix.split('\n')
    # Remove empty lines at start and end only
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    proposed_fix = '\n'.join(lines)
    
    # Extract explanation section
    explanation_match = re.search(r'## Explanation\n(.*?)(?=##|$)', response, re.DOTALL)
    explanation = explanation_match.group(1).strip() if explanation_match else "No explanation provided"
    
    return proposed_fix, explanation


def _validate_fix_safety(code: str) -> tuple[bool, list[str]]:
    """
    Validate generated code for dangerous patterns.
    
    Args:
        code: Generated code to validate
        
    Returns:
        Tuple of (is_safe, list_of_concerns)
    """
    concerns = []
    
    # Dangerous patterns to check
    dangerous_patterns = [
        (r'\beval\s*\(', 'Uses eval() function'),
        (r'\bexec\s*\(', 'Uses exec() function'),
        (r'os\.system\s*\(', 'Uses os.system()'),
        (r'subprocess\.call\s*\(', 'Uses subprocess without validation'),
        (r'rm\s+-rf\s+/', 'Contains dangerous shell command'),
        (r'DROP\s+TABLE', 'Contains SQL DROP statement'),
        (r'DELETE\s+FROM.*WHERE\s+1=1', 'Contains dangerous SQL DELETE'),
    ]
    
    for pattern, concern in dangerous_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            concerns.append(concern)
    
    is_safe = len(concerns) == 0
    return is_safe, concerns


def _generate_fallback_fix(
    state: AgentState,
    prompts: dict,
    llm_provider: LLMProvider,
    error_file_path: str,
    error_line_number: int,
    error_file_type: str,
    rca_summary: str
) -> AgentState:
    """
    Generate fix without GitHub code access using error information only.
    
    This fallback approach:
    1. Uses error message, stack trace, and RCA
    2. Generates conceptual fix with clear instructions
    3. Provides guidance for manual implementation
    
    Args:
        state: Current agent state
        prompts: Loaded prompts from YAML
        llm_provider: LLM provider instance
        error_file_path: Path to file with error
        error_line_number: Line number of error
        error_file_type: Type of file (dataweave, mule_xml, etc.)
        rca_summary: Root cause analysis summary
        
    Returns:
        Updated state with conceptual fix
    """
    logger.info(f"[Fix Generation] Using fallback approach - no code access")
    
    try:
        fix_prompt = prompts.get('code_fix_generation', '')

        # Build error context from metadata if available
        metadata = state.get('metadata') or {}
        source_technology = metadata.get('source_technology', 'unknown')
        detected_framework = metadata.get('detected_framework') or ''
        tech_display = source_technology + (f'/{detected_framework}' if detected_framework else '')

        # Create fallback prompt using the SAME targeted fix format as the main path.
        # The LLM can infer the problematic code from the error message / stack trace
        # and provide both an Original Code block and a Fixed Code block so the patch
        # generator and UI diff viewer can produce a real before-vs-after comparison.
        fallback_prompt = f"""You are an expert software engineer. Generate a targeted fix for this error.
The actual source file could not be fetched, so you must INFER what the buggy code looks like
from the error message and stack trace, then provide the fix.

## Error Details
**Application:** {state.get('app_name', 'Unknown')}
**Environment:** {state.get('environment', 'Unknown')}
**Error Title:** {state.get('error_title', 'Unknown')}
**Technology Stack:** {tech_display or 'Unknown'}
**File:** {error_file_path or 'Unknown'}
**Line:** {error_line_number or 'Unknown'}
**File Type:** {error_file_type or 'Unknown'}

## Error Message
{state.get('error_description', 'No description')}

## Stack Trace
```
{state.get('stack_trace', 'No stack trace')[:1500]}
```

## Root Cause Analysis
{rca_summary}

## Your Task
Infer the exact lines that caused this error from the stack trace / error message above,
then show the original buggy version alongside the fixed version.

**CRITICAL INSTRUCTIONS — TARGETED FIX APPROACH:**
1. **Infer the EXACT lines that are buggy** from the stack trace / error message
2. **Show ONLY those specific lines with context** (not the entire file)
3. **Include 3-5 context lines** before and after to locate the position
4. **The Original Code block MUST contain the actual buggy pattern** visible in the error
5. **Be minimal** — only change what is necessary to fix the error
6. **The fix must be production-ready and safe**

**REQUIRED Output Format (MUST MATCH THIS EXACTLY):**

**Original Code (with context):**
```{error_file_type or 'code'}
[3-5 lines of context BEFORE the buggy code]
[The EXACT buggy lines inferred from the error / stack trace]
[3-5 lines of context AFTER the buggy code]
```

**Fixed Code (with same context):**
```{error_file_type or 'code'}
[Same 3-5 context lines BEFORE]
[The FIXED version of the buggy lines]
[Same 3-5 context lines AFTER]
```

## Explanation
[Explain precisely what was wrong and why the fix resolves the issue]
"""

        # Generate fix
        logger.info(f"[Fix Generation] Calling LLM for fallback fix (targeted format)")
        fix_response = llm_provider.invoke(
            prompt=fallback_prompt,
            system_message=(
                f"You are an expert in {error_file_type or 'software engineering'} and {tech_display or 'software development'}. "
                "Generate precise, targeted fixes that show Original Code vs Fixed Code blocks. "
                "Always infer the buggy code pattern from the error message and stack trace."
            ),
            temperature=0.3,
        )

        # Keep the FULL LLM response as proposed_fix — same as the main path.
        # The patch generator and UI diff viewer need both Original and Fixed code blocks,
        # which are embedded in the full response.  Parsing/stripping them here destroys
        # the structure that downstream consumers depend on.
        proposed_fix = fix_response
        fix_explanation = _extract_explanation(fix_response)

        # Validate safety
        safety_check, concerns = _validate_fix_safety(proposed_fix)

        # Update state
        state['proposed_fix'] = proposed_fix
        state['fix_explanation'] = fix_explanation
        state['affected_files'] = [error_file_path] if error_file_path else []
        state['fix_type'] = 'conceptual'  # Mark as conceptual fix
        
        # Set placeholder original_code for patch generation compatibility
        # This allows patch/PR generators to handle conceptual fixes appropriately
        state['original_code'] = f"""# Original code not available (GitHub access failed)
# This is a conceptual fix based on error analysis
# File: {error_file_path or 'Unknown'}
# Error: {state.get('error_title', 'Unknown')}

# NOTE: Manual review required - apply fix template below to actual code
"""
        
        state['current_node'] = 'generate_fix'
        state['updated_at'] = datetime.utcnow().isoformat()
        
        # Update workflow tracking
        completed_steps = list(state.get('workflow_completed_steps') or [])
        if 'generate_fix' not in completed_steps:
            completed_steps.append('generate_fix')
        state['workflow_completed_steps'] = completed_steps
        
        state['workflow_progress_pct'] = len(completed_steps) / WORKFLOW_TOTAL_STEPS

        messages = [
            "⚠️ Conceptual fix generated (GitHub access not available)",
            "✓ Fix provides guidance and code templates"
        ]
        
        if not safety_check:
            messages.append(f"⚠️ Safety concerns: {', '.join(concerns)}")
        
        state['messages'] = state.get('messages', []) + messages

        # Send "Fix Generated" notification (fallback/conceptual fix)
        try:
            from agents.workflow import _send_event_notification
            _send_event_notification(
                event="Fix Generated (Conceptual)",
                incident_id=state['incident_id'],
                severity=state.get('severity', 'HIGH'),
                app_name=state.get('app_name', ''),
                environment=state.get('environment', ''),
                details=(
                    f"Conceptual fix generated for: {state.get('error_title', 'Unknown')}\n"
                    f"File: {error_file_path or 'N/A'} (GitHub access not available)\n"
                    f"Explanation: {fix_explanation[:300]}{'...' if len(fix_explanation) > 300 else ''}"
                ),
                project_id=state.get('project_id'),
            )
        except Exception as _notify_err:
            logger.warning("[Fix Generation] Could not send fallback fix notification: %s", _notify_err)

        # Update database
        try:
            from storage.database import get_session
            from storage.incident_repository import IncidentRepository
            
            with get_session() as session:
                repo = IncidentRepository(session)
                repo.update(
                    incident_id=state['incident_id'],
                    current_workflow_node='generate_fix',
                    workflow_completed_steps=state['workflow_completed_steps'],
                    workflow_progress_pct=state['workflow_progress_pct'],
                    proposed_fix=proposed_fix,
                    fix_explanation=fix_explanation
                )
        except Exception as db_error:
            logger.warning(f"Failed to update workflow progress in DB: {db_error}")
        
        logger.info(f"[Fix Generation] Fallback fix generated for {state['incident_id']}")
        
    except Exception as e:
        error_text = str(e)
        logger.error(f"[Fix Generation] Fallback approach failed: {error_text}")

        # Classify the error to give a more actionable message
        lower_err = error_text.lower()
        if any(t in lower_err for t in ("rate", "429", "quota", "too many requests", "overloaded", "resource_exhausted")):
            user_message = (
                f"Fix generation failed: LLM provider rate limit hit (429 Too Many Requests). "
                f"The provider is temporarily throttling requests. "
                f"Please wait a moment and try again, or configure a fallback LLM provider in "
                f"Team Admin → Project Configuration → LLM → Fallback Providers. "
                f"Detail: {error_text}"
            )
        elif any(t in lower_err for t in ("auth", "api key", "401", "403", "unauthorized")):
            user_message = (
                f"Fix generation failed: LLM authentication error. "
                f"Check the API key in Team Admin → Project Configuration → LLM. "
                f"Detail: {error_text}"
            )
        elif any(t in lower_err for t in ("timeout", "timed out", "connection")):
            user_message = (
                f"Fix generation failed: LLM provider connection timeout. "
                f"The provider may be temporarily unavailable. Please retry. "
                f"Detail: {error_text}"
            )
        else:
            user_message = f"Fix generation failed: {error_text}"

        state['proposed_fix'] = None
        state['fix_explanation'] = user_message
        state['error_message'] = user_message
        state['messages'] = state.get('messages', []) + [f"❌ {user_message}"]

        # Persist error state to DB so UI shows the correct error details
        try:
            from storage.database import get_session
            from storage.incident_repository import IncidentRepository
            with get_session() as session:
                repo = IncidentRepository(session)
                repo.update(
                    incident_id=state['incident_id'],
                    current_workflow_node='generate_fix_failed',
                    error_message=user_message,
                    fix_explanation=user_message,
                    proposed_fix=None,
                )
        except Exception as db_err:
            logger.warning(f"[Fix Generation] Failed to persist fallback error to DB: {db_err}")

    return state
