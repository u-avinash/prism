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
"""Test database to see if incidents exist."""
from storage.database import get_db
from storage.incident_repository import IncidentRepository

db = next(get_db())
repo = IncidentRepository(db)

incidents = repo.get_all(limit=100)
print(f"Found {len(incidents)} incidents in database")

for incident in incidents[:10]:
    print(f"  #{incident.incident_id}: {incident.error_title} - {incident.severity} - {incident.status}")

if len(incidents) == 0:
    print("\n✗ No incidents found in database!")
    print("Database location: log_monitor.db")
    
    import os
    if os.path.exists("log_monitor.db"):
        size = os.path.getsize("log_monitor.db")
        print(f"Database file exists, size: {size} bytes")
    else:
        print("Database file does not exist!")
