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
"""Severity analysis and auto-fix decision logic."""
import re
import json
import logging
from typing import Tuple, Optional
from storage.models import Severity
from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SeverityAnalyzer:
    """
    Analyze error severity and determine if auto-fix should be triggered.

    Uses an LLM-first approach (when a project_id is supplied) with a fast
    heuristic fallback so the pipeline never blocks on an LLM call.
    """

    # Fast-path critical heuristics — never blocked by LLM
    CRITICAL_KEYWORDS = [
        r'outofmemory', r'fatal', r'critical', r'security breach',
        r'database.*down', r'connection.*refused', r'unable to connect',
        r'service.*unavailable', r'deadlock', r'data corruption',
        r'disk full', r'out of disk', r'kernel panic',
    ]

    HIGH_KEYWORDS = [
        r'exception', r'error', r'failed', r'timeout',
        r'null.*(pointer|object|reference)', r'cannot access property',
        r'undefined.*object', r'nullpointerexception',
        r'resource.*exhausted', r'permission.*denied', r'access.*denied',
        r'invalid.*credentials', r'quota.*exceeded', r'cannot.*null',
    ]

    MEDIUM_KEYWORDS = [
        r'warning', r'deprecated', r'retry', r'slow', r'performance',
        r'rate.*limit', r'validation.*failed', r'bad.*request',
    ]

    def __init__(self, project_id: Optional[str] = None):
        """Initialize severity analyzer."""
        self.auto_fix_enabled = settings.auto_fix_enabled
        self.severity_threshold = Severity[settings.auto_fix_severity_threshold]
        self.burst_window = settings.error_burst_window_minutes
        self.burst_threshold = settings.error_burst_threshold
        self.project_id = project_id

    def analyze_severity(
        self,
        error_title: str,
        error_description: str,
        stack_trace: str,
        app_name: Optional[str] = None,
        environment: Optional[str] = None,
        source_technology: Optional[str] = None,
    ) -> Tuple[Severity, float]:
        """
        Analyze error severity.

        Strategy:
          1. Fast heuristic pre-check — if CLEARLY critical/high, skip LLM.
          2. LLM classification (if project_id available) — structured output.
          3. Fallback to heuristic keyword scoring if LLM fails or unavailable.

        Args:
            error_title:        Error title/message
            error_description:  Error description
            stack_trace:        Stack trace
            app_name:           Application name (optional)
            environment:        Deployment environment (optional, e.g. production)
            source_technology:  Detected technology (optional, e.g. java, python)

        Returns:
            Tuple of (Severity, confidence_score)
        """
        combined_text = f"{error_title} {error_description} {stack_trace}".lower()

        # --- Fast-path for obvious CRITICAL signals ---
        critical_score = self._calculate_keyword_score(combined_text, self.CRITICAL_KEYWORDS)
        if critical_score >= 0.5:
            logger.info("Fast-path CRITICAL (score: %.2f)", critical_score)
            return Severity.CRITICAL, min(critical_score, 1.0)

        # --- LLM classification (best-effort) ---
        if self.project_id:
            llm_result = self._llm_classify(
                error_title=error_title,
                error_description=error_description,
                stack_trace=stack_trace,
                environment=environment or "unknown",
                source_technology=source_technology or "unknown",
            )
            if llm_result:
                severity, confidence = llm_result
                logger.info("[LLM Severity] %s (confidence: %.2f)", severity.value, confidence)
                return severity, confidence

        # --- Heuristic fallback ---
        return self._heuristic_classify(combined_text)

    def _llm_classify(
        self,
        error_title: str,
        error_description: str,
        stack_trace: str,
        environment: str,
        source_technology: str,
    ) -> Optional[Tuple[Severity, float]]:
        """
        Call LLM for structured severity classification.

        Returns (Severity, confidence) on success, None on failure.
        """
        try:
            from integrations.llm_provider import LLMProvider

            llm = LLMProvider(project_id=self.project_id)

            prompt = f"""You are a software reliability engineer classifying the severity of a production error.

ERROR TITLE: {error_title}
TECHNOLOGY: {source_technology}
ENVIRONMENT: {environment}
DESCRIPTION: {error_description[:500]}
STACK TRACE (first 800 chars): {stack_trace[:800]}

Classify the severity. Rules:
- CRITICAL: system crash, data loss, security breach, total service outage, OOM kill
- HIGH:     unhandled exception that breaks a user flow, repeated failures, data integrity risk
- MEDIUM:   degraded functionality, non-critical failure, warning-level issue caught in catch block
- LOW:      informational, deprecation notice, single transient error that auto-recovered

Also set is_transient=true if the error looks like a momentary blip (e.g., one-time timeout that likely resolved).

Respond ONLY with valid JSON (no markdown):
{{"severity": "HIGH", "confidence": 0.85, "reasoning": "one sentence", "is_transient": false, "affected_component": "OrderService"}}"""

            response = llm.invoke(
                prompt=prompt,
                system_message="You are a reliability engineer. Respond ONLY with the JSON object.",
                temperature=0.1,
                json_mode=True,
            )

            # Strip markdown fences if present
            response = response.strip()
            response = re.sub(r'```json\s*', '', response)
            response = re.sub(r'```\s*$', '', response)

            match = re.search(r'\{.*\}', response, re.DOTALL)
            if not match:
                raise ValueError("No JSON found in LLM severity response")

            data = json.loads(match.group(0))
            severity_str = str(data.get('severity', 'HIGH')).upper()
            confidence = float(data.get('confidence', 0.75))
            reasoning = data.get('reasoning', '')
            is_transient = bool(data.get('is_transient', False))

            # Downgrade transient errors by one level
            if is_transient and severity_str in ('HIGH', 'CRITICAL'):
                severity_str = 'MEDIUM' if severity_str == 'HIGH' else 'HIGH'
                confidence = max(confidence - 0.1, 0.5)
                logger.info("[LLM Severity] Transient flag — downgraded to %s", severity_str)

            severity_map = {
                'CRITICAL': Severity.CRITICAL,
                'HIGH': Severity.HIGH,
                'MEDIUM': Severity.MEDIUM,
                'LOW': Severity.LOW,
            }
            severity = severity_map.get(severity_str, Severity.HIGH)

            logger.info(
                "[LLM Severity] %s | confidence=%.2f | transient=%s | %s",
                severity.value, confidence, is_transient, reasoning
            )
            return severity, round(confidence, 3)

        except Exception as exc:
            logger.warning("[LLM Severity] Classification failed (%s), falling back to heuristic", exc)
            return None

    def _heuristic_classify(self, combined_text: str) -> Tuple[Severity, float]:
        """Keyword-based fallback severity classification."""
        critical_score = self._calculate_keyword_score(combined_text, self.CRITICAL_KEYWORDS)
        if critical_score > 0:
            return Severity.CRITICAL, min(critical_score, 1.0)

        high_score = self._calculate_keyword_score(combined_text, self.HIGH_KEYWORDS)
        if high_score > 0.5:
            return Severity.HIGH, min(high_score, 1.0)

        medium_score = self._calculate_keyword_score(combined_text, self.MEDIUM_KEYWORDS)
        if medium_score > 0.3:
            return Severity.MEDIUM, min(medium_score, 1.0)

        logger.info("Heuristic: classified as LOW")
        return Severity.LOW, 0.5
    
    def _calculate_keyword_score(self, text: str, keywords: list) -> float:
        """
        Calculate keyword match score.
        
        Args:
            text: Text to analyze
            keywords: List of regex patterns
            
        Returns:
            Score between 0 and 1
        """
        matches = 0
        for pattern in keywords:
            if re.search(pattern, text, re.IGNORECASE):
                matches += 1
        
        # Normalize to 0-1 range (multiple matches increase confidence)
        return min(matches / len(keywords) * 3, 1.0)
    
    def should_auto_fix(
        self,
        severity: Severity,
        recent_error_count: int = 0,
        is_duplicate: bool = False
    ) -> Tuple[bool, str]:
        """
        Determine if auto-fix should be triggered.
        
        Args:
            severity: Error severity
            recent_error_count: Number of recent similar errors
            is_duplicate: Whether this is a duplicate error
            
        Returns:
            Tuple of (should_fix, reason)
        """
        if not self.auto_fix_enabled:
            return False, "Auto-fix is disabled in configuration"
        
        # Don't auto-fix duplicates
        if is_duplicate:
            return False, "Error is a duplicate of existing incident"
        
        # Check severity threshold
        severity_order = {
            Severity.LOW: 1,
            Severity.MEDIUM: 2,
            Severity.HIGH: 3,
            Severity.CRITICAL: 4
        }
        
        if severity_order[severity] < severity_order[self.severity_threshold]:
            return False, f"Severity {severity.value} is below threshold {self.severity_threshold.value}"
        
        # Check error burst (multiple occurrences in time window)
        if recent_error_count >= self.burst_threshold:
            return True, f"Error burst detected: {recent_error_count} errors in {self.burst_window} minutes"
        
        # High/Critical severity always triggers auto-fix
        if severity in [Severity.HIGH, Severity.CRITICAL]:
            return True, f"Severity is {severity.value}"
        
        return False, "No auto-fix trigger conditions met"
    
    def estimate_fix_complexity(self, stack_trace: str, error_description: str) -> str:
        """
        Estimate fix complexity based on error characteristics.
        
        Args:
            stack_trace: Stack trace
            error_description: Error description
            
        Returns:
            Complexity estimate: "LOW", "MEDIUM", or "HIGH"
        """
        combined = f"{stack_trace} {error_description}".lower()
        
        # HIGH complexity indicators
        if any(keyword in combined for keyword in [
            'concurrency', 'race condition', 'deadlock', 'memory leak',
            'security', 'authentication', 'encryption', 'database schema'
        ]):
            return "HIGH"
        
        # MEDIUM complexity indicators
        if any(keyword in combined for keyword in [
            'configuration', 'timeout', 'retry', 'validation',
            'parsing', 'serialization', 'format'
        ]):
            return "MEDIUM"
        
        # Default to LOW
        return "LOW"
    
    def get_priority_score(self, severity: Severity, recent_count: int) -> int:
        """
        Calculate priority score for incident triage.
        
        Args:
            severity: Error severity
            recent_count: Recent error count
            
        Returns:
            Priority score (higher = more urgent)
        """
        base_score = {
            Severity.CRITICAL: 100,
            Severity.HIGH: 75,
            Severity.MEDIUM: 50,
            Severity.LOW: 25
        }
        
        # Add points for frequency
        frequency_bonus = min(recent_count * 5, 25)
        
        return base_score[severity] + frequency_bonus


# Helper function for easy use
def analyze_severity(
    error_title: str,
    error_description: str = "",
    stack_trace: str = "",
    environment: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    """
    Analyze error severity (convenience function).

    Args:
        error_title:       Error title/message
        error_description: Error description (optional)
        stack_trace:       Stack trace (optional)
        environment:       Environment name (optional)
        project_id:        Project ID for LLM-based classification (optional)

    Returns:
        Severity string: "CRITICAL", "HIGH", "MEDIUM", or "LOW"
    """
    analyzer = SeverityAnalyzer(project_id=project_id)

    severity, confidence = analyzer.analyze_severity(
        error_title=error_title,
        error_description=error_description or "",
        stack_trace=stack_trace or "",
        app_name=None,
        environment=environment,
    )
    
    return severity.value
