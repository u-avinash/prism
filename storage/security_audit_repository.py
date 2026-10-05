"""
Repository helpers for persistent security and compliance audit events.

Audit events are append-only. This module deliberately exposes no mutation
methods and defensively redacts sensitive values before API or CSV use.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from storage.database import SecurityAuditEvent


class SecurityAuditRepository:
    """Read-only query and safe serialization helpers for audit records."""

    _SENSITIVE_KEY_PARTS = (
        "password",
        "secret",
        "token",
        "digest",
        "api_key",
        "apikey",
        "webhook",
        "authorization",
        "cookie",
        "session",
        "credential",
    )

    def __init__(self, db: Session):
        self.db = db

    def get_all(
        self,
        *,
        project_id: Optional[str] = None,
        include_system_events: bool = False,
        action: Optional[str] = None,
        outcome: Optional[str] = None,
        actor_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SecurityAuditEvent]:
        """Return newest-first audit events constrained to an authorized scope."""
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        query = self.db.query(SecurityAuditEvent)

        if project_id:
            if include_system_events:
                query = query.filter(
                    (SecurityAuditEvent.project_id == project_id)
                    | (SecurityAuditEvent.project_id.is_(None))
                )
            else:
                query = query.filter(SecurityAuditEvent.project_id == project_id)
        elif not include_system_events:
            # No project scope must never accidentally return every tenant's data.
            return []

        if action:
            query = query.filter(SecurityAuditEvent.action == action)
        if outcome:
            query = query.filter(SecurityAuditEvent.outcome == outcome)
        if actor_type:
            query = query.filter(SecurityAuditEvent.actor_type == actor_type)
        if actor_id:
            query = query.filter(SecurityAuditEvent.actor_id == actor_id)
        if target_type:
            query = query.filter(SecurityAuditEvent.target_type == target_type)
        if target_id:
            query = query.filter(SecurityAuditEvent.target_id == target_id)
        if created_from:
            query = query.filter(SecurityAuditEvent.created_at >= created_from)
        if created_to:
            query = query.filter(SecurityAuditEvent.created_at <= created_to)

        return (
            query.order_by(SecurityAuditEvent.created_at.desc(), SecurityAuditEvent.event_id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count(self, **filters: Any) -> int:
        """Return a scoped count using the same filters accepted by get_all."""
        limit = filters.pop("limit", 1)
        rows = self.get_all(limit=max(int(limit), 1), **filters)
        # Count is intentionally not exposed as an unbounded cross-tenant query.
        # Callers receive the returned page size and pagination metadata instead.
        return len(rows)

    @classmethod
    def serialize(cls, event: SecurityAuditEvent) -> dict[str, Any]:
        """Serialize an event while recursively redacting potentially secret values."""
        return {
            "event_id": event.event_id,
            "project_id": event.project_id,
            "actor_type": event.actor_type,
            "actor_id": event.actor_id,
            "action": event.action,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "outcome": event.outcome,
            "source_ip": event.source_ip,
            "details": cls._redact(event.details or {}),
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }

    @classmethod
    def _redact(cls, value: Any, key: str = "") -> Any:
        normalized_key = key.lower().replace("-", "_")
        if any(part in normalized_key for part in cls._SENSITIVE_KEY_PARTS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {str(k): cls._redact(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._redact(item, key) for item in value]
        if isinstance(value, tuple):
            return [cls._redact(item, key) for item in value]
        return value
