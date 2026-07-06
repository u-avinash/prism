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
import sqlite3

conn = sqlite3.connect('incidents.db')
cursor = conn.cursor()

# Get incidents 2 and 5
cursor.execute("""
    SELECT incident_number, app_name, error_title, error_message, environment
    FROM incidents 
    WHERE incident_number IN (2, 5)
    ORDER BY incident_number
""")

for row in cursor.fetchall():
    inc_num, app_name, error_title, error_msg, env = row
    print(f"\n{'='*80}")
    print(f"INCIDENT #{inc_num}")
    print(f"{'='*80}")
    print(f"App: {app_name}")
    print(f"Environment: {env}")
    print(f"Error Title: {error_title}")
    print(f"\nError Message:")
    print(error_msg[:500])
    print(f"\n{'-'*80}\n")

conn.close()
