"""Tests for project-aware, non-sequential incident identifiers."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.database import Base
from storage.incident_repository import IncidentRepository
from storage.models import IncidentCreate
from utils.id_generator import generate_incident_id, validate_incident_id


def _incident(project_id: str) -> IncidentCreate:
    return IncidentCreate(
        app_name="ordering-service",
        environment="production",
        error_title="Order submission failed",
        error_description="The downstream service timed out.",
        stack_trace="TimeoutError: downstream service",
        raw_log='{"message": "The downstream service timed out."}',
        metadata={"project_id": project_id},
    )


def test_project_name_becomes_a_four_character_prefix() -> None:
    incident_id = generate_incident_id(project_name="Zoff Ordering")

    assert incident_id.startswith("ZOFF")
    assert len(incident_id) == 8
    assert validate_incident_id(incident_id)


def test_short_project_names_receive_a_random_suffix_up_to_eight_characters() -> None:
    incident_id = generate_incident_id(project_name="A-1")

    assert incident_id.startswith("A1")
    assert len(incident_id) == 8
    assert validate_incident_id(incident_id)


def test_ids_are_unique_and_collision_safe() -> None:
    existing_ids = {"ZOFFAAAA"}
    generated_ids = set()

    # Reserve each generated value before requesting the next one.
    while len(generated_ids) < 20:
        generated_ids.add(
            generate_incident_id(existing_ids | generated_ids, project_name="Zoff Ordering")
        )

    assert "ZOFFAAAA" not in generated_ids
    assert len(generated_ids) == 20
    assert all(incident_id.startswith("ZOFF") for incident_id in generated_ids)


def test_legacy_and_new_id_formats_validate_while_invalid_values_do_not() -> None:
    assert validate_incident_id("A7CB")
    assert validate_incident_id("ZOFFAT1X")
    assert not validate_incident_id("")
    assert not validate_incident_id("ZOFFAT1XY")
    assert not validate_incident_id("zoffat1x")
    assert not validate_incident_id("ZOFF-1X")


def test_repository_uses_the_resolved_project_name(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    repository = IncidentRepository(session)

    monkeypatch.setattr(
        "storage.incident_repository.get_project",
        lambda project_id: {"id": project_id, "name": "Zoff Ordering"},
    )

    created = repository.create(_incident("PRJ-ZOFF"), project_id="PRJ-ZOFF")

    assert created.incident_id.startswith("ZOFF")
    assert len(created.incident_id) == 8
    assert created.project_id == "PRJ-ZOFF"
