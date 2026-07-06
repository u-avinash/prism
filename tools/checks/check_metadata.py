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
"""Check GitHub metadata in database."""
from storage.database import get_session
from storage.incident_repository import IncidentRepository

session = get_session().__enter__()
incidents = IncidentRepository(session).get_all()

print(f'Total incidents: {len(incidents)}')
print()

for i in incidents[:5]:
    print(f'ID: {i.incident_id}')
    print(f'  Repo: {i.repo_full_name}')
    print(f'  File: {i.error_file_path}')
    print(f'  Line: {i.error_line_number}')
    print(f'  Status: {i.status}')
    print()
