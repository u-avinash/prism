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
"""SQLAlchemy database setup and models."""
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, Boolean, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from typing import Generator
from config.settings import get_settings
import logging

logger = logging.getLogger(__name__)

Base = declarative_base()
settings = get_settings()


class TelemetryLog(Base):
    """SQLAlchemy model for telemetry logs stored independently of incidents."""

    __tablename__ = "telemetry_logs"

    log_id = Column(String(4), primary_key=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    observed_timestamp = Column(DateTime, nullable=True)
    project_id = Column(String(64), nullable=True, index=True)
    app_name = Column(String(255), nullable=False, index=True)
    environment = Column(String(50), nullable=False, index=True)
    deployment_type = Column(String(50), nullable=True, index=True)
    severity = Column(String(20), nullable=False, index=True)
    severity_number = Column(Integer, nullable=True)
    message = Column(Text, nullable=False)
    error_type = Column(String(255), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    trace_id = Column(String(255), nullable=True, index=True)
    span_id = Column(String(255), nullable=True)
    flow_name = Column(String(255), nullable=True, index=True)
    logger_name = Column(String(255), nullable=True)
    service_name = Column(String(255), nullable=True, index=True)
    source_scope = Column(String(255), nullable=True)
    raw_payload = Column(Text, nullable=False)
    attributes = Column(JSON, nullable=True)
    incident_created = Column(Boolean, default=False, nullable=False, index=True)
    incident_id = Column(String(4), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Incident(Base):
    """SQLAlchemy model for incidents table."""
    __tablename__ = "incidents"

    # Primary key (4-character alphanumeric ID, e.g., A7CB)
    incident_id = Column(String(4), primary_key=True, nullable=False)

    # Tenant ownership. Legacy rows may remain NULL until explicitly backfilled.
    project_id = Column(String(64), nullable=True, index=True)

    # Basic info
    app_name = Column(String(255), nullable=False, index=True)
    environment = Column(String(50), nullable=False, index=True)
    error_title = Column(String(500), nullable=False)
    error_description = Column(Text, nullable=False)
    stack_trace = Column(Text, nullable=False)
    raw_log = Column(Text, nullable=False)

    # Error detection
    error_fingerprint = Column(String(64), nullable=True, index=True)
    is_duplicate = Column(Boolean, default=False)
    existing_incident_id = Column(String(4), nullable=True)
    occurrence_count = Column(Integer, default=1, nullable=False)
    last_occurrence_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    # Status and severity
    status = Column(String(50), nullable=False, default="DETECTED", index=True)
    severity = Column(String(20), nullable=True, index=True)

    # Workflow tracking
    current_workflow_node = Column(String(100), nullable=True)
    workflow_completed_steps = Column(JSON, nullable=True)
    workflow_progress_pct = Column(Float, nullable=True)
    # Active-run lease used to prevent duplicate asynchronous workflow execution.
    workflow_run_token = Column(String(64), nullable=True, index=True)
    workflow_started_at = Column(DateTime, nullable=True)

    # RCA
    rca_text = Column(Text, nullable=True)
    rca_confidence = Column(Float, nullable=True)
    pdf_path = Column(String(500), nullable=True)

    # Alerting
    alert_sent = Column(Boolean, default=False)
    alert_channels = Column(JSON, nullable=True)

    # Notification status
    slack_notification_sent = Column(Boolean, default=False, nullable=True)
    teams_notification_sent = Column(Boolean, default=False, nullable=True)
    notification_errors = Column(JSON, nullable=True)

    # Jira
    jira_ticket_key = Column(String(50), nullable=True, index=True)
    jira_ticket_url = Column(String(500), nullable=True)
    jira_error = Column(Text, nullable=True)

    # Auto-fix decision
    should_auto_fix = Column(Boolean, default=False)

    # Code fix
    proposed_fix = Column(Text, nullable=True)
    fix_explanation = Column(Text, nullable=True)
    patch_path = Column(String(500), nullable=True)
    fix_quality_score = Column(Float, nullable=True)
    fix_approved = Column(Boolean, nullable=True)
    fix_approval_comment = Column(Text, nullable=True)

    # Approval tracking
    approval_status = Column(String(20), nullable=True)
    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approval_notes = Column(Text, nullable=True)

    # GitHub metadata
    repo_full_name = Column(String(255), nullable=True)
    error_file_path = Column(String(500), nullable=True)
    error_line_number = Column(Integer, nullable=True)
    error_file_type = Column(String(50), nullable=True)
    fetched_code = Column(Text, nullable=True)

    # OTLP metadata
    incident_metadata = Column(JSON, nullable=True)

    # Technology detection
    source_technology = Column(String(50), nullable=True, index=True)   # java, python, nodejs, etc.
    detected_framework = Column(String(100), nullable=True)              # spring, django, express, etc.

    # Incident grouping (related errors grouped under a primary incident)
    incident_group_id = Column(String(4), nullable=True, index=True)
    is_primary_incident = Column(Boolean, default=True, nullable=True)

    # SLA tracking
    sla_acknowledged_at = Column(DateTime, nullable=True)
    sla_resolution_due_at = Column(DateTime, nullable=True)
    sla_status = Column(String(20), nullable=True)   # ON_TRACK, AT_RISK, BREACHED

    # Structured rejection feedback
    rejection_reason_code = Column(String(50), nullable=True)   # enum: wrong_root_cause, wrong_approach, etc.
    fix_attempt_count = Column(Integer, default=0, nullable=True)

    # Git operations
    repo_path = Column(String(500), nullable=True)
    fix_branch = Column(String(255), nullable=True)
    fix_committed = Column(Boolean, default=False)

    # Pull request
    pr_number = Column(Integer, nullable=True)
    pr_url = Column(String(500), nullable=True)
    commit_sha = Column(String(255), nullable=True)
    commit_url = Column(String(500), nullable=True)

    # Metadata
    processing_errors = Column(JSON, nullable=True)
    processing_duration_seconds = Column(Float, nullable=True)
    retries = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class IncidentComment(Base):
    """SQLAlchemy model for incident comment threads."""

    __tablename__ = "incident_comments"

    comment_id = Column(String(16), primary_key=True, nullable=False)
    incident_id = Column(String(4), nullable=False, index=True)
    author = Column(String(255), nullable=False, default="user")
    content = Column(Text, nullable=False)
    comment_type = Column(String(20), nullable=False, default="comment")  # "comment" | "system"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ProjectIntegrationConfig(Base):
    """Encrypted per-project integration configuration stored in SQLite."""

    __tablename__ = "project_integration_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), nullable=False, unique=True, index=True)
    llm = Column(JSON, nullable=True)
    jira = Column(JSON, nullable=True)
    github = Column(JSON, nullable=True)
    anypoint = Column(JSON, nullable=True)
    slack = Column(JSON, nullable=True)
    teams = Column(JSON, nullable=True)
    runtime = Column(JSON, nullable=True)
    # repo_mappings: dict of app_name -> {repo, branch, description}
    # No secret fields — stored as plain JSON
    repo_mappings = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


def get_engine():
    """Create and return database engine."""
    database_url = f"sqlite:///{settings.database_path}"
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        echo=settings.log_level == "DEBUG"
    )
    return engine


def get_session_factory():
    """Create and return session factory."""
    engine = get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session():
    """Context manager to get database session."""
    from contextlib import contextmanager

    @contextmanager
    def _session():
        SessionLocal = get_session_factory()
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _session()


def init_database():
    """Initialize database tables."""
    logger.info(f"Initializing database at {settings.database_path}")
    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    # Run any necessary ALTER TABLE migrations for columns added after initial creation
    with engine.begin() as connection:
        # --- project_integration_configs migrations ---
        pic_columns = [
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(project_integration_configs)"
            ).fetchall()
        ]
        if "runtime" not in pic_columns:
            connection.exec_driver_sql(
                "ALTER TABLE project_integration_configs ADD COLUMN runtime JSON"
            )
            logger.info("Added runtime column to project_integration_configs")

        if "repo_mappings" not in pic_columns:
            connection.exec_driver_sql(
                "ALTER TABLE project_integration_configs ADD COLUMN repo_mappings JSON"
            )
            logger.info("Added repo_mappings column to project_integration_configs")

        # --- telemetry_logs migrations ---
        telemetry_columns = [
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(telemetry_logs)"
            ).fetchall()
        ]
        if "project_id" not in telemetry_columns:
            connection.exec_driver_sql(
                "ALTER TABLE telemetry_logs ADD COLUMN project_id VARCHAR(64)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_telemetry_logs_project_id "
                "ON telemetry_logs (project_id)"
            )
            logger.info("Added project_id column to telemetry_logs")

        # --- incidents migrations ---
        inc_columns = [
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(incidents)"
            ).fetchall()
        ]

        new_incident_columns = [
            ("project_id",             "VARCHAR(64)"),
            ("workflow_run_token",     "VARCHAR(64)"),
            ("workflow_started_at",    "DATETIME"),
            ("source_technology",      "VARCHAR(50)"),
            ("detected_framework",     "VARCHAR(100)"),
            ("incident_group_id",      "VARCHAR(4)"),
            ("is_primary_incident",    "BOOLEAN DEFAULT 1"),
            ("sla_acknowledged_at",    "DATETIME"),
            ("sla_resolution_due_at",  "DATETIME"),
            ("sla_status",             "VARCHAR(20)"),
            ("rejection_reason_code",  "VARCHAR(50)"),
            ("fix_attempt_count",      "INTEGER DEFAULT 0"),
        ]

        for col_name, col_def in new_incident_columns:
            if col_name not in inc_columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE incidents ADD COLUMN {col_name} {col_def}"
                )
                logger.info("Added %s column to incidents", col_name)

        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_incidents_workflow_run_token "
            "ON incidents (workflow_run_token)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_incidents_project_id "
            "ON incidents (project_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_incidents_project_fingerprint "
            "ON incidents (project_id, error_fingerprint)"
        )

    logger.info("Database initialized successfully")
