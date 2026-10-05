from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.database import Base
from storage.workflow_history_repository import WorkflowHistoryRepository


def _repository():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return session, WorkflowHistoryRepository(session)


def test_workflow_runs_are_project_scoped_and_newest_first():
    session, repo = _repository()

    first = repo.start_run(
        incident_id="INC-A",
        project_id="PRJ-A",
        run_type="full",
        trigger_source="ingestion",
    )
    first.started_at = datetime(2026, 1, 1)

    other_project = repo.start_run(
        incident_id="INC-B",
        project_id="PRJ-B",
        run_type="full",
        trigger_source="ingestion",
    )
    other_project.started_at = datetime(2026, 1, 2)

    newest = repo.start_run(
        incident_id="INC-C",
        project_id="PRJ-A",
        run_type="recovery",
        trigger_source="operator_recovery",
        triggered_by="operator-1",
        recovery_reason="Retry after an integration failure.",
    )
    newest.started_at = datetime(2026, 1, 3)
    session.commit()

    runs = repo.get_runs(project_id="PRJ-A", limit=10)

    assert [run.run_id for run in runs] == [newest.run_id, first.run_id]
    assert repo.get_runs(project_id=None, limit=10) == []
    assert other_project.run_id not in {run.run_id for run in runs}


def test_workflow_events_are_scoped_ordered_and_bounded():
    session, repo = _repository()
    run = repo.start_run(
        incident_id="INC-A",
        project_id="PRJ-A",
        run_type="full",
        trigger_source="ingestion",
    )

    first = repo.add_step_event(
        run_id=run.run_id,
        incident_id="INC-A",
        project_id="PRJ-A",
        step_name="generate_rca",
        event_type="started",
        message="a" * 1_100,
    )
    second = repo.add_step_event(
        run_id=run.run_id,
        incident_id="INC-A",
        project_id="PRJ-A",
        step_name="generate_rca",
        event_type="succeeded",
        attempt=2,
        duration_seconds=1.234,
    )
    first.created_at = datetime(2026, 1, 1)
    second.created_at = datetime(2026, 1, 2)
    session.commit()

    events = repo.get_step_events(project_id="PRJ-A", run_id=run.run_id)

    assert [event.event_id for event in events] == [first.event_id, second.event_id]
    assert events[0].message == "a" * 1_000
    assert events[1].attempt == 2
    assert repo.get_step_events(project_id="PRJ-B", run_id=run.run_id) == []


def test_workflow_health_reports_completed_runs_and_retries():
    session, repo = _repository()
    succeeded = repo.start_run(
        incident_id="INC-A",
        project_id="PRJ-A",
        run_type="full",
        trigger_source="ingestion",
    )
    succeeded.started_at = datetime(2026, 1, 1)
    session.flush()
    repo.finish_run(succeeded.run_id, status="SUCCEEDED")
    succeeded.duration_seconds = 2.0

    failed = repo.start_run(
        incident_id="INC-B",
        project_id="PRJ-A",
        run_type="recovery",
        trigger_source="operator_recovery",
    )
    failed.started_at = datetime(2026, 1, 2)
    session.flush()
    repo.finish_run(failed.run_id, status="FAILED", error_summary="x" * 3_000)
    failed.duration_seconds = 4.0

    repo.add_step_event(
        run_id=failed.run_id,
        incident_id="INC-B",
        project_id="PRJ-A",
        step_name="generate_fix",
        event_type="retrying",
    )
    session.commit()

    health = repo.get_health_summary(project_id="PRJ-A")
    failed_run = repo.get_runs(
        project_id="PRJ-A", incident_id="INC-B", limit=1
    )[0]

    assert health == {
        "total_runs": 2,
        "running": 0,
        "succeeded": 1,
        "failed": 1,
        "success_rate_pct": 50.0,
        "avg_duration_seconds": 3.0,
        "retry_events": 1,
    }
    assert failed_run.error_summary == "x" * 2_000
