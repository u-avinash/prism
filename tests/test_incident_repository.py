"""Deterministic repository tests for tenancy and workflow execution safety."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.database import Base
from storage.incident_repository import IncidentRepository
from storage.models import IncidentCreate


def _repository() -> IncidentRepository:
    """Create an isolated repository backed by a fresh in-memory database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    return IncidentRepository(session)


def _incident(project_id: str, fingerprint: str = "shared-fingerprint"):
    """Create a minimal incident fixture owned by the requested project."""
    return IncidentCreate(
        app_name="checkout-service",
        environment="production",
        error_title="Connection failure",
        error_description="Database connection refused.",
        stack_trace="ConnectionError: refused",
        raw_log='{"message": "Database connection refused"}',
        metadata={"project_id": project_id},
    )


def test_fingerprint_lookup_is_scoped_to_project() -> None:
    """The same error fingerprint must not deduplicate incidents across tenants."""
    repository = _repository()

    project_a = repository.create(
        _incident("project-a"),
        project_id="project-a",
        error_fingerprint="shared-fingerprint",
    )
    project_b = repository.create(
        _incident("project-b"),
        project_id="project-b",
        error_fingerprint="shared-fingerprint",
    )

    assert repository.get_by_fingerprint(
        "shared-fingerprint", "project-a"
    ).incident_id == project_a.incident_id
    assert repository.get_by_fingerprint(
        "shared-fingerprint", "project-b"
    ).incident_id == project_b.incident_id
    assert project_a.incident_id != project_b.incident_id
    assert repository.get_by_fingerprint("shared-fingerprint") is None


def test_workflow_lease_blocks_duplicates_and_requires_owner_to_release() -> None:
    """Only one runner can own an incident workflow lease at a time."""
    repository = _repository()
    incident = repository.create(_incident("project-a"), project_id="project-a")

    owner_token = repository.acquire_workflow_lease(incident.incident_id)
    assert owner_token is not None
    assert repository.acquire_workflow_lease(incident.incident_id) is None

    assert not repository.release_workflow_lease(incident.incident_id, "wrong-token")
    assert repository.release_workflow_lease(incident.incident_id, owner_token)

    next_owner_token = repository.acquire_workflow_lease(incident.incident_id)
    assert next_owner_token is not None
    assert next_owner_token != owner_token
