"""Entry point: generate the full Prism documentation pack.

Run from the project root:
    python docs/generate_documentation.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

# Make doc_gen importable when run from the project root
sys.path.insert(0, str(Path(__file__).parent))

from doc_gen import visuals, hld_doc, pptx_deck

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
SHOTS = DOCS / "screenshots"
INCIDENT = DOCS / "incident-evidence" / "NTTD6XI2"
for d in (ASSETS, SHOTS, INCIDENT):
    d.mkdir(parents=True, exist_ok=True)


def _load_incident():
    con = sqlite3.connect(ROOT / "data" / "incidents.db")
    con.row_factory = sqlite3.Row
    rec = con.execute(
        """select incident_id, app_name, environment, severity, status, rca_confidence,
        approval_status, approved_at, jira_ticket_key, jira_ticket_url, repo_full_name,
        error_file_path, error_line_number, pr_number, pr_url, commit_sha, commit_url,
        pdf_path, patch_path, created_at, updated_at
        from incidents where incident_id='NTTD6XI2'"""
    ).fetchone()
    record = dict(rec)
    events = [
        tuple(r)
        for r in con.execute(
            """select step_name, event_type, attempt, message, duration_seconds, created_at
            from workflow_step_events where incident_id='NTTD6XI2' order by created_at"""
        ).fetchall()
    ]
    con.close()
    return record, events


def _build_visuals(record, events):
    visuals.create_architecture(ASSETS)
    visuals.create_workflow(ASSETS)
    visuals.create_incident_timeline(ASSETS, record, events)
    visuals.create_roles_diagram(ASSETS)
    visuals.create_tech_stack(ASSETS)
    visuals.create_security_diagram(ASSETS)


def _build_hld(record, events):
    hld_doc.build(DOCS / "Prism_High_Level_Design.docx", ASSETS, record, events)


def _build_pptx(record, events):
    pptx_deck.build(DOCS / "Prism_Project_Overview.pptx", ASSETS, record, events)


def _build_screenshots():
    for src, dst in [
        ("01_prism_architecture.png", "01_architecture_overview.png"),
        ("02_incident_journey.png", "02_incident_workflow.png"),
        ("03_verified_incident_timeline.png", "03_verified_local_incident_timeline.png"),
        ("04_role_model.png", "04_role_and_tenant_model.png"),
        ("05_technology_stack.png", "05_technology_stack.png"),
        ("06_security_governance.png", "06_security_governance.png"),
    ]:
        shutil.copy2(ASSETS / src, SHOTS / dst)
    (SHOTS / "README.md").write_text(
        "# Prism Visual Inventory\n\n"
        "## Numbered visuals\n"
        "1. `01_architecture_overview.png` — Architecture based on verified source implementation.\n"
        "2. `02_incident_workflow.png` — The six-stage human-in-the-loop incident journey.\n"
        "3. `03_verified_local_incident_timeline.png` — Actual workflow evidence for local incident NTTD6XI2.\n"
        "4. `04_role_and_tenant_model.png` — Role hierarchy and project scoping.\n"
        "5. `05_technology_stack.png` — Full technology stack.\n"
        "6. `06_security_governance.png` — Security, governance, and reliability posture.\n\n"
        "## Live UI capture record\n"
        "The local Prism login and authenticated Admin Dashboard were visually confirmed at "
        "`http://127.0.0.1:8080` on 2026-10-14. Browser-session screenshots cannot be programmatically "
        "exported via the available controlled-browser interface, so this pack contains reproducible "
        "architecture and workflow visuals rather than fabricated UI screenshots.\n\n"
        "## External-system capture boundary\n"
        "GitHub PR, Jira issue, and Slack notification captures require authenticated access to those "
        "third-party systems. Their locally recorded references are in "
        "`../incident-evidence/NTTD6XI2/incident_evidence.json`.\n",
        encoding="utf-8",
    )


def _build_incident_bundle(record, events):
    evidence = {
        "provenance": (
            "Local Prism SQLite record and locally generated artifacts. "
            "External systems were not accessed during documentation generation."
        ),
        "incident": record,
        "workflow_events": [
            {"step_name": a, "event_type": b, "attempt": c, "message": d, "duration_seconds": e, "created_at": f}
            for a, b, c, d, e, f in events
        ],
        "external_references_recorded_by_prism": {
            "jira": record.get("jira_ticket_url"),
            "github_pull_request": record.get("pr_url"),
            "github_commit": record.get("commit_url"),
        },
    }
    (INCIDENT / "incident_evidence.json").write_text(
        json.dumps(evidence, indent=2, default=str), encoding="utf-8"
    )
    patch_src = ROOT / record["patch_path"].replace("\\", "/")
    pdf_src = ROOT / record["pdf_path"].replace("\\", "/")
    shutil.copy2(patch_src, INCIDENT / "01_generated_fix.patch")
    shutil.copy2(pdf_src, INCIDENT / "02_prism_rca_report.pdf")
    (INCIDENT / "03_RCA_summary.md").write_text(
        "# RCA Summary -- NTTD6XI2\n\n"
        "## Incident\n"
        "CRITICAL Production failure in `order-processing-service`. DataWeave tried to coerce "
        "`payload.orderDate` to a Date, but the field was absent (or the payload was a String).\n\n"
        "## Root cause\n"
        "The `validate-order-payload` sub-flow accessed `payload.orderDate` without first checking "
        "its existence or type. When the field was missing, the strict `as Date` coercion failed.\n\n"
        "## Proposed remediation (from generated patch)\n"
        "```dataweave\n"
        "parsedOrderDate: if (payload.orderDate?) payload.orderDate as Date {format: \"yyyy-MM-dd\"} else now()\n"
        "```\n\n"
        "## Review considerations\n"
        "- Verify the business-correct default: `now()` prevents the coercion crash but may not be "
        "  domain-correct for every order type.\n"
        "- Add MUnit tests for missing, null, and non-object `orderDate` inputs.\n"
        "- Consider enforcing a RAML/JSON-Schema contract before the transform.\n\n"
        "## Prevention\n"
        "- CI/CD DataWeave static analysis to flag unsafe coercions.\n"
        "- Structured logging for validation failures without exposing payload data.\n\n"
        "## Evidence limits\n"
        "This summary is derived from local Prism artifacts. Jira, GitHub, and Slack were not "
        "authenticated or independently captured during this documentation run.\n",
        encoding="utf-8",
    )
    rows = "\n".join(
        f"| {f} | {a} | {b} | {c} | {e or ''} |"
        for a, b, c, d, e, f in events
    )
    (INCIDENT / "04_workflow_evidence.md").write_text(
        "# Workflow Evidence -- NTTD6XI2\n\n"
        "| Timestamp | Step | Event | Attempt | Duration (s) |\n"
        "|-----------|------|-------|--------:|-----------:|\n"
        + rows
        + "\n\nThe local database records a successful full workflow (7 pre-approval steps) and "
        "a successful post-approval workflow. Human approval was recorded before post-approval "
        "execution. Recorded downstream references: Jira SCRUM-12 and GitHub PR #61.\n",
        encoding="utf-8",
    )
    (INCIDENT / "README.md").write_text(
        "# Incident Evidence Pack -- NTTD6XI2\n\n"
        "Self-contained local evidence for one complete Prism workflow.\n\n"
        "## Contents\n"
        "1. `incident_evidence.json` -- Sanitized incident metadata and step-level evidence from SQLite.\n"
        "2. `01_generated_fix.patch` -- Actual unified patch generated by Prism.\n"
        "3. `02_prism_rca_report.pdf` -- Actual Prism-generated RCA PDF report.\n"
        "4. `03_RCA_summary.md` -- Reviewer-oriented RCA summary and cautions.\n"
        "5. `04_workflow_evidence.md` -- Chronological operational workflow step evidence.\n\n"
        "## Verification boundary\n"
        "The local record contains links to Jira SCRUM-12, GitHub PR #61, and a commit SHA. "
        "Those are system-recorded outputs, not independently authenticated captures. "
        "Slack delivery is not asserted without a captured authenticated record.\n",
        encoding="utf-8",
    )


def _build_markdown(record):
    jira_key = record.get("jira_ticket_key", "SCRUM-12")
    pr_num = record.get("pr_number", 61)
    (DOCS / "Medium_Blog_Draft.md").write_text(
        "# From Telemetry to a Human-Approved Pull Request: Building Prism\n\n"
        "Production incidents rarely fail because teams lack tools. They fail because the work between "
        "a raw error and a safe remediation is fragmented: logs live in one place, source context in "
        "another, tickets in another, and the final decision depends on someone stitching the evidence "
        "together under pressure.\n\n"
        "That is the problem Prism was designed to solve.\n\n"
        "## The design principle: automate evidence, not accountability\n\n"
        "Prism is intentionally not a 'ship code automatically' system. Its workflow is built around "
        "a practical boundary:\n\n"
        "1. **Automation** receives a telemetry signal, removes noise, identifies context, and prepares an investigation.\n"
        "2. **AI assistance** creates an RCA, a proposed remediation, a quality review, a PDF report, and a unified patch.\n"
        "3. **A human reviewer** decides whether the recommendation is acceptable.\n"
        "4. **Post-approval automation** sends notifications and creates the configured delivery artifacts.\n\n"
        "This preserves accountability while removing repetitive coordination work.\n\n"
        "## What happens when an error arrives?\n\n"
        "An application sends OTLP logs to Prism's FastAPI ingestion service, usually through an "
        "OpenTelemetry Collector. Prism parses the record, detects technology context (MuleSoft, Java, "
        "Python, Node.js, .NET, Go, and more), fingerprints duplicate errors, classifies severity, and "
        "persists the resulting operational record.\n\n"
        "For HIGH and CRITICAL incidents, Prism starts an 11-step LangGraph workflow: severity "
        "assessment, RCA generation with code context, fix generation, PDF creation, quality reflection, "
        "patch generation, human approval pause, notifications, Jira ticket, GitHub PR, and finalization.\n\n"
        "## A verified local example\n\n"
        f"A local Prism record, `NTTD6XI2`, demonstrates the full path. A CRITICAL MuleSoft production "
        f"error in `order-processing-service`: DataWeave attempted to coerce a missing `orderDate` value "
        f"to a Date. Prism recorded an RCA confidence of 87.5%, generated a patch with null-safe handling, "
        f"captured human approval, and successfully completed the post-approval workflow. The local record "
        f"references Jira `{jira_key}` and GitHub PR #{pr_num}.\n\n"
        "The value is not 'AI generated text.' It is a connected, reviewable operational trail: signal, "
        "reasoning, suggested remediation, approval, and delivery artifacts.\n\n"
        "## Architecture in plain English\n\n"
        "- **Signal intake:** FastAPI receives OpenTelemetry logs.\n"
        "- **Workflow intelligence:** LangGraph coordinates analysis, generation, review, and recovery.\n"
        "- **Operations console:** FastAPI/Jinja2 dashboard with SSE live updates and approval controls.\n"
        "- **Trusted project data:** SQLite/SQLAlchemy preserves project-scoped incidents, telemetry, "
        "workflow history, and audit evidence.\n"
        "- **Integration adapters:** LLM, GitHub, Jira, Slack/Teams, and MuleSoft Anypoint, configured per project.\n\n"
        "The stack is deliberately pragmatic: Python, FastAPI, LangGraph/LangChain, OpenTelemetry, "
        "SQLite/SQLAlchemy, Server-Sent Events, and provider adapters. LLM providers are "
        "interchangeable: OpenAI, Anthropic, Azure OpenAI, Google Gemini, Groq, or local Ollama.\n\n"
        "## Governance is a feature, not an afterthought\n\n"
        "Prism applies project scoping and role separation. Integration configuration is encrypted per "
        "project. In production, authentication and tenant assignment are designed to fail closed. "
        "Workflow history records runs and node-level operational events so recovery is governed and "
        "explainable.\n\n"
        "## What Prism does not claim to do\n\n"
        "Prism persists telemetry logs and derived incidents. OTLP trace and metrics endpoints validate "
        "and acknowledge payloads, but raw traces and metrics are not yet persisted or rendered. External "
        "GitHub, Jira, Slack, Teams, Anypoint, and LLM actions require real project configuration.\n\n"
        "## Closing thought\n\n"
        "The useful future of incident automation is not a black box that acts alone. It is a transparent "
        "operational assistant that makes evidence easier to assemble, decisions easier to review, and "
        "delivery easier to coordinate. That is the role Prism is designed to play.\n",
        encoding="utf-8",
    )
    (DOCS / "LinkedIn_Announcement.md").write_text(
        "# LinkedIn Announcement\n\n"
        "I'm excited to share **Prism**, an AI-powered incident-management platform built to reduce "
        "the gap between a production error and a safe, reviewable remediation.\n\n"
        "Prism ingests OpenTelemetry logs, detects and prioritizes incidents, generates an AI-assisted "
        "Root Cause Analysis and proposed fix, produces a PDF report and a unified patch, and then "
        "pauses for **human approval** before creating downstream artifacts -- Jira issues and GitHub "
        "pull requests.\n\n"
        "What I value most about the design is the governance model: automation assembles evidence and "
        "accelerates coordination, while people retain the release decision. Project scoping, encrypted "
        "integration configuration, audit records, durable workflow history, and controlled recovery are "
        "first-class concerns.\n\n"
        "The platform brings together Python, FastAPI, LangGraph/LangChain, OpenTelemetry, "
        "SQLite/SQLAlchemy, Jinja2/SSE, and configurable integrations for LLM providers, GitHub, Jira, "
        "Slack/Teams, and MuleSoft Anypoint.\n\n"
        "I have written about the architecture, the human-in-the-loop model, and a verified local "
        "workflow example in the accompanying Medium article:\n\n"
        "**[Insert Medium article URL after publishing: "
        "From Telemetry to a Human-Approved Pull Request: Building Prism]**\n\n"
        "#IncidentManagement #AIOps #OpenTelemetry #LangGraph #MuleSoft "
        "#DevOps #PlatformEngineering #ResponsibleAI\n",
        encoding="utf-8",
    )


def main():
    print("Loading incident data...")
    record, events = _load_incident()
    print("Generating visuals...")
    _build_visuals(record, events)
    print("Building High-Level Design document...")
    _build_hld(record, events)
    print("Building PowerPoint presentation...")
    _build_pptx(record, events)
    print("Building screenshot inventory...")
    _build_screenshots()
    print("Building incident evidence bundle...")
    _build_incident_bundle(record, events)
    print("Building publication drafts...")
    _build_markdown(record)
    print("Documentation pack generated under docs/")


if __name__ == "__main__":
    main()
