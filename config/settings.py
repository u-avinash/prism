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
"""Centralized configuration settings loader.

Only infrastructure-level settings live here.
All integration credentials (LLM API keys, Jira, GitHub, Slack, Teams, etc.)
are stored encrypted in the database and managed through the Team Admin
onboarding / project configuration pages.
"""
from functools import lru_cache
import os
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Only non-credential, infrastructure settings are defined here.
    Integration credentials are managed per-project in the DB.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Encryption key for secrets stored in DB ──────────────────────────────
    # This is the ONLY secret allowed here — it is the master key used to
    # encrypt/decrypt all other credentials stored in the database.
    integration_secret_key: Optional[str] = None
    integration_secret_key_file: str = "./data/.integration.key"

    # ── Outbound HTTP / TLS ──────────────────────────────────────────────────
    # Path to a PEM bundle containing corporate/private root CA certificates.
    # When unset, Python's standard verified CA store is used.
    trusted_ca_bundle: Optional[str] = None
    # Emergency compatibility switch for corporate TLS interception appliances
    # that present certificates which cannot be validated by any CA bundle.
    # Disabled by default: enable only via ALLOW_UNVERIFIED_TLS=true
    # (PRISM_ALLOW_UNVERIFIED_TLS is supported as an environment alias).
    allow_unverified_tls: bool = False

    # ── OpenTelemetry & Ingestion ─────────────────────────────────────────────
    otlp_collector_port: int = 4318
    otlp_endpoint: str = "http://localhost:4318/v1/logs"
    ingestion_api_host: str = "0.0.0.0"
    ingestion_api_port: int = 8000

    # ── Environment & application security ───────────────────────────────────
    # Development preserves Prism's local quick-start behaviour. Production
    # enables fail-closed settings for tenant-scoped automation.
    prism_environment: str = "development"
    ingestion_auth_required: Optional[bool] = None
    allow_unassigned_ingestion: Optional[bool] = None
    ingestion_allowed_origins: str = ""
    ui_allowed_origins: str = ""
    ui_cookie_secure: Optional[bool] = None
    csrf_enabled: Optional[bool] = None
    debug_endpoints_enabled: Optional[bool] = None
    max_ingestion_body_bytes: int = 1_048_576
    ingestion_rate_limit_per_minute: int = 60

    # ── Storage ───────────────────────────────────────────────────────────────
    database_path: str = "./data/incidents.db"
    pdf_output_dir: str = "./data/pdfs"
    patch_output_dir: str = "./data/patches"

    # ── Auto-Fix Behaviour ────────────────────────────────────────────────────
    auto_fix_enabled: bool = True
    auto_fix_severity_threshold: str = "HIGH"
    auto_fix_requires_approval: bool = True
    auto_fix_max_file_size_kb: int = 500
    auto_pr_create: bool = True
    auto_pr_label: str = "ai-generated,needs-review"

    # ── Error Detection & Deduplication ──────────────────────────────────────
    error_fingerprint_algorithm: str = "simhash"
    duplicate_threshold: float = 0.85
    error_burst_window_minutes: int = 10
    error_burst_threshold: int = 5

    # ── UI Deep-link Base URL ─────────────────────────────────────────────────
    # Used to generate clickable incident links in Slack/Teams notifications.
    ui_base_url: str = "http://localhost:8080"

    # ── Observability & Debugging ─────────────────────────────────────────────
    log_level: str = "INFO"
    langgraph_tracing: bool = True
    langchain_tracing_v2: bool = True
    langchain_api_key: Optional[str] = None
    langchain_project: str = "mule-monitor-poc"

    # ── Rate Limiting & Caching ───────────────────────────────────────────────
    llm_cache_enabled: bool = True
    llm_cache_ttl_hours: int = 24
    rate_limit_requests_per_minute: int = 10

    def _is_production(self) -> bool:
        return self.prism_environment.strip().lower() == "production"

    @property
    def effective_ingestion_auth_required(self) -> bool:
        return self._is_production() if self.ingestion_auth_required is None else self.ingestion_auth_required

    @property
    def effective_allow_unassigned_ingestion(self) -> bool:
        return (not self._is_production()) if self.allow_unassigned_ingestion is None else self.allow_unassigned_ingestion

    @property
    def effective_ui_cookie_secure(self) -> bool:
        return self._is_production() if self.ui_cookie_secure is None else self.ui_cookie_secure

    @property
    def effective_csrf_enabled(self) -> bool:
        return self._is_production() if self.csrf_enabled is None else self.csrf_enabled

    @property
    def effective_debug_endpoints_enabled(self) -> bool:
        return (not self._is_production()) if self.debug_endpoints_enabled is None else self.debug_endpoints_enabled

    def get_ingestion_allowed_origins(self) -> List[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.ingestion_allowed_origins.split(",")
            if origin.strip()
        ]

    def get_ui_allowed_origins(self) -> List[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.ui_allowed_origins.split(",")
            if origin.strip()
        ]

    def validate_security_policy(self) -> None:
        """Fail fast when an explicitly production deployment is unsafe."""
        if not self._is_production():
            return

        errors: List[str] = []
        if not self.effective_ingestion_auth_required:
            errors.append("INGESTION_AUTH_REQUIRED must be true in production")
        if self.effective_allow_unassigned_ingestion:
            errors.append("ALLOW_UNASSIGNED_INGESTION must be false in production")
        if not self.effective_ui_cookie_secure:
            errors.append("UI_COOKIE_SECURE must be true in production")
        if not self.effective_csrf_enabled:
            errors.append("CSRF_ENABLED must be true in production")
        if not self.get_ingestion_allowed_origins():
            errors.append("INGESTION_ALLOWED_ORIGINS must list trusted origins in production")
        if "*" in self.get_ingestion_allowed_origins():
            errors.append("INGESTION_ALLOWED_ORIGINS cannot include '*' in production")
        if errors:
            raise ValueError("Unsafe production Prism configuration: " + "; ".join(errors))

    def get_pr_labels(self) -> List[str]:
        """Parse PR labels from comma-separated string."""
        return [label.strip() for label in self.auto_pr_label.split(",") if label.strip()]

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        database_dir = Path(self.database_path).expanduser().resolve().parent
        pdf_dir = Path(self.pdf_output_dir).expanduser().resolve()
        patch_dir = Path(self.patch_output_dir).expanduser().resolve()

        database_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        patch_dir.mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    # Backward-compatible aliases used in deployment documentation. The native
    # Pydantic names remain supported as well.
    if (
        "PRISM_ALLOW_UNVERIFIED_TLS" in os.environ
        and "ALLOW_UNVERIFIED_TLS" not in os.environ
    ):
        os.environ["ALLOW_UNVERIFIED_TLS"] = os.environ["PRISM_ALLOW_UNVERIFIED_TLS"]
    if (
        "PRISM_TRUSTED_CA_BUNDLE" in os.environ
        and "TRUSTED_CA_BUNDLE" not in os.environ
    ):
        os.environ["TRUSTED_CA_BUNDLE"] = os.environ["PRISM_TRUSTED_CA_BUNDLE"]

    settings = Settings()
    settings.validate_security_policy()
    settings.ensure_directories()
    return settings
