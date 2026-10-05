"""
╔══════════════════════════════════════════════════════════════════════╗
║                          P  R  I  S  M                               ║
║       Autonomous AI Incident Management System                       ║
╚══════════════════════════════════════════════════════════════════════╝

  Building an Autonomous AI Incident Management System
  with LangGraph and OpenTelemetry

  Author   : Upadhyayula Avinash
  GitHub   : https://github.com/u-avinash
  LinkedIn : https://www.linkedin.com/in/avinash
  Email    : uavinash.csit@gmail.com

  Copyright (c) 2026-2035 Upadhyayula Avinash. All rights reserved.
"""
"""Generate unique, project-aware alphanumeric incident IDs."""

import secrets
import string
from typing import Optional, Set

MAX_INCIDENT_ID_LENGTH = 8
MAX_PROJECT_PREFIX_LENGTH = 4
_ALPHANUMERIC_CHARACTERS = string.ascii_uppercase + string.digits


def _project_prefix(project_name: Optional[str]) -> str:
    """Return up to four uppercase alphanumeric characters from a project name."""
    if not isinstance(project_name, str):
        return ""

    normalized = "".join(
        character for character in project_name.upper() if character.isalnum()
    )
    return normalized[:MAX_PROJECT_PREFIX_LENGTH]


def generate_incident_id(
    existing_ids: Optional[Set[str]] = None,
    project_name: Optional[str] = None,
) -> str:
    """
    Generate a unique, non-sequential uppercase alphanumeric incident ID.

    IDs are at most eight characters. When a project name is supplied, its first
    four uppercase alphanumeric characters form the prefix and the remaining
    characters are cryptographically random. For example, ``Zoff Ordering``
    produces IDs such as ``ZOFFAT1X``. Unassigned or legacy incidents receive
    an eight-character random identifier.

    Args:
        existing_ids: Existing incident IDs to avoid collisions with.
        project_name: Optional project name used to derive the readable prefix.

    Returns:
        A unique uppercase alphanumeric incident ID with a maximum length of 8.

    Raises:
        ValueError: If a unique ID cannot be generated after repeated attempts.
    """
    existing_ids = existing_ids or set()
    prefix = _project_prefix(project_name)
    suffix_length = MAX_INCIDENT_ID_LENGTH - len(prefix)

    for _ in range(100):
        suffix = "".join(
            secrets.choice(_ALPHANUMERIC_CHARACTERS) for _ in range(suffix_length)
        )
        incident_id = f"{prefix}{suffix}"

        if incident_id not in existing_ids:
            return incident_id

    raise ValueError("Failed to generate a unique incident ID after maximum attempts")


def validate_incident_id(incident_id: str) -> bool:
    """
    Validate an incident ID.

    Legacy four-character identifiers remain supported, while newly generated
    IDs can be project-prefixed and contain up to eight uppercase alphanumeric
    characters.
    """
    if not isinstance(incident_id, str) or not incident_id:
        return False

    return (
        len(incident_id) <= MAX_INCIDENT_ID_LENGTH
        and incident_id.isalnum()
        and incident_id == incident_id.upper()
    )
