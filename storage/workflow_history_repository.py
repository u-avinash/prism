"""Persistence helpers for durable workflow execution history.

The repository stores operational metadata only: lifecycle state, node name,
attempt number, timing, and bounded error summaries. It intentionally does not
persist prompts, raw telemetry, source code, generated fixes, or credentials.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from storage.database import WorkflowRun, WorkflowStepEvent


class WorkflowHistoryRepository:
    """Create and query append-only workflow run evidence within tenant scope."""

    _MAX_MESSAGE_LENGTH = 1_000
    _MAX_REASON_LENGTH = 500
    _MAX_ERROR_LENGTH = 2_000

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _trim(value: Optional[str], limit: int) -> Optional[str]:
        if not value:
            return None
        return str(value).strip()[:limit] or None

    def start_run(
        self,
        *,
        incident_id: str,
        project_id: Optional[str],
        run_type: str,
        trigger_source: str,
        triggered_by: Optional[str] = None,
        recovery_reason: Optional[str] = None,
    ) -> WorkflowRun:
        run = WorkflowRun(
            run_id=str(uuid4()),
            incident_id=incident_id,
            project_id=project_id,
            run_type=run_type,
            trigger_source=trigger_source,
            triggered_by=self._trim(triggered_by, 255),
            status="RUNNING",
            recovery_reason=self._trim(recovery_reason, self._MAX_REASON_LENGTH),
            started_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.flush()
        return run

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        error_summary: Optional[str] = None,
    ) -> Optional[WorkflowRun]:
        run = self.db.query(WorkflowRun).filter(WorkflowRun.run_id == run_id).first()
        if not run:
            return None

        completed_at = datetime.utcnow()
        run.status = status
        run.completed_at = completed_at
        run.error_summary = self._trim(error_summary, self._MAX_ERROR_LENGTH)
        if run.started_at:
            run.duration_seconds = round(
                max(0.0, (completed_at - run.started_at).total_seconds()), 3
            )
        self.db.flush()
        return run

    def add_step_event(
        self,
        *,
        run_id: str,
        incident_id: str,
        project_id: Optional[str],
        step_name: str,
        event_type: str,
        attempt: int = 1,
        message: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> WorkflowStepEvent:
        event = WorkflowStepEvent(
            event_id=str(uuid4()),
            run_id=run_id,
            incident_id=incident_id,
            project_id=project_id,
            step_name=str(step_name)[:100],
            event_type=str(event_type)[:32],
            attempt=max(1, int(attempt)),
            message=self._trim(message, self._MAX_MESSAGE_LENGTH),
            duration_seconds=duration_seconds,
            created_at=datetime.utcnow(),
        )
        self.db.add(event)
        self.db.flush()
        return event

    def get_runs(
        self,
        *,
        project_id: Optional[str],
        incident_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkflowRun]:
        """Return newest-first runs only when an explicit tenant is supplied."""
        if not project_id:
            return []

        query = self.db.query(WorkflowRun).filter(WorkflowRun.project_id == project_id)
        if incident_id:
            query = query.filter(WorkflowRun.incident_id == incident_id)
        if status:
            query = query.filter(WorkflowRun.status == status)

        return (
            query.order_by(WorkflowRun.started_at.desc(), WorkflowRun.run_id.desc())
            .offset(max(0, int(offset)))
            .limit(max(1, min(int(limit), 500)))
            .all()
        )

    def get_step_events(
        self,
        *,
        project_id: Optional[str],
        run_id: str,
        limit: int = 500,
    ) -> list[WorkflowStepEvent]:
        """Return chronological step events after enforcing the run's tenant."""
        if not project_id:
            return []

        return (
            self.db.query(WorkflowStepEvent)
            .filter(
                WorkflowStepEvent.project_id == project_id,
                WorkflowStepEvent.run_id == run_id,
            )
            .order_by(WorkflowStepEvent.created_at.asc(), WorkflowStepEvent.event_id.asc())
            .limit(max(1, min(int(limit), 500)))
            .all()
        )

    def get_health_summary(self, *, project_id: Optional[str]) -> dict:
        """Return bounded, tenant-scoped workflow health indicators."""
        if not project_id:
            return {
                "total_runs": 0,
                "running": 0,
                "succeeded": 0,
                "failed": 0,
                "success_rate_pct": None,
                "avg_duration_seconds": None,
                "retry_events": 0,
            }

        run_rows = (
            self.db.query(WorkflowRun.status, func.count(WorkflowRun.run_id))
            .filter(WorkflowRun.project_id == project_id)
            .group_by(WorkflowRun.status)
            .all()
        )
        counts = {str(status).upper(): int(count) for status, count in run_rows}
        total_runs = sum(counts.values())
        succeeded = counts.get("SUCCEEDED", 0)
        failed = counts.get("FAILED", 0)
        completed = succeeded + failed
        avg_duration = (
            self.db.query(func.avg(WorkflowRun.duration_seconds))
            .filter(
                WorkflowRun.project_id == project_id,
                WorkflowRun.status.in_(("SUCCEEDED", "FAILED")),
                WorkflowRun.duration_seconds.isnot(None),
            )
            .scalar()
        )
        retry_events = (
            self.db.query(func.count(WorkflowStepEvent.event_id))
            .filter(
                WorkflowStepEvent.project_id == project_id,
                WorkflowStepEvent.event_type == "retrying",
            )
            .scalar()
            or 0
        )
        return {
            "total_runs": total_runs,
            "running": counts.get("RUNNING", 0),
            "succeeded": succeeded,
            "failed": failed,
            "success_rate_pct": (
                round((succeeded / completed) * 100, 1) if completed else None
            ),
            "avg_duration_seconds": (
                round(float(avg_duration), 3) if avg_duration is not None else None
            ),
            "retry_events": int(retry_events),
        }

    @staticmethod
    def serialize_run(run: WorkflowRun) -> dict:
        return {
            "run_id": run.run_id,
            "incident_id": run.incident_id,
            "project_id": run.project_id,
            "run_type": run.run_type,
            "trigger_source": run.trigger_source,
            "triggered_by": run.triggered_by,
            "status": run.status,
            "recovery_reason": run.recovery_reason,
            "error_summary": run.error_summary,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_seconds": run.duration_seconds,
        }

    @staticmethod
    def serialize_step_event(event: WorkflowStepEvent) -> dict:
        return {
            "event_id": event.event_id,
            "run_id": event.run_id,
            "incident_id": event.incident_id,
            "project_id": event.project_id,
            "step_name": event.step_name,
            "event_type": event.event_type,
            "attempt": event.attempt,
            "message": event.message,
            "duration_seconds": event.duration_seconds,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
