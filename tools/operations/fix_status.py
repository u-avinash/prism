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
"""Fix incorrect status in database."""
from storage.database import get_db
from storage.incident_repository import IncidentRepository
from storage.models import IncidentStatus

db = next(get_db())
repo = IncidentRepository(db)

incidents = repo.get_all(limit=100)
print(f"Found {len(incidents)} incidents")

for incident in incidents:
    if incident.status == "rca_completed":
        print(f"Fixing incident #{incident.incident_id}: {incident.status} -> RCA_COMPLETE")
        repo.update_status(incident.incident_id, IncidentStatus.RCA_COMPLETE)
        print(f"  ✓ Updated")

print("\nDone!")
