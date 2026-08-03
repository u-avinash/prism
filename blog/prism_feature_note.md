# PRISM — Feature & Technology Note

**PRISM** is an autonomous, AI-powered incident management platform. It ingests OpenTelemetry (OTLP) logs — primarily from MuleSoft/Anypoint applications but from any OTLP-compatible source — classifies errors by severity, generates AI-assisted Root Cause Analysis (RCA) and code fixes, and drives a human-in-the-loop approval workflow that culminates in a Jira ticket and a GitHub Pull Request, all with a single human approval click.

---

## 1. Overview

| Layer | Technology | Port |
|-------|------------|------|
| Ingestion API | FastAPI + OpenTelemetry | 8000 |
| Dashboard UI | FastAPI + Jinja2 + Server-Sent Events | 8080 |
| Workflow Engine | LangGraph (stateful agent graph) | — |
| Database | SQLite (via SQLAlchemy) | — |
| LLM | Pluggable: OpenAI / Anthropic / Azure OpenAI / Google Gemini / Groq / Ollama | — |

---

## 2. Features in Actual Usable Condition

These are features that are implemented and functioning in the codebase today (not aspirational):

### Ingestion & Detection
- **OTLP log ingestion API** (`/v1/logs`) that parses OpenTelemetry log records into structured incidents.
- **Error deduplication** via SimHash fingerprinting to suppress duplicate/repeated errors.
- **Severity classification** using OTLP signal data plus keyword/heuristic analysis.
- **Telemetry log storage** independent of incident creation, viewable via the Log Viewer UI.

### AI-Driven Incident Workflow (LangGraph, 11 steps)
- **Severity assessment** — classifies incoming errors and fires an "Incident Created" notification.
- **AI Root Cause Analysis (RCA) generation** — LLM-generated 400–500 word RCA, enriched with live source code fetched from GitHub and runtime context from MuleSoft Anypoint (CloudHub/ARM). Includes a self-scored confidence value from a second LLM call.
- **AI code fix generation** — proposes a concrete code fix with a human-readable explanation.
- **PDF RCA report generation** — auto-generated report saved for download/audit.
- **Quality reflection** — scores the proposed fix on correctness, safety, code quality, and completeness, with safe-defaults so it never blocks the pipeline.
- **Patch file generation** — produces a unified `.patch` file available for download before approval.
- **Human approval gate** — workflow pauses; reviewer inspects RCA, fix diff, PDF, and patch before approving/rejecting/requesting regeneration with feedback.
- **Notification dispatch** — Slack and/or Microsoft Teams alerts on workflow events.
- **Jira ticket creation** — creates an issue, attaches the patch, and syncs branch/commit/PR data into Jira's Development panel.
- **GitHub PR creation** — creates a branch, commits the fix, and opens a Pull Request.
- **Finalization** — persists final status, timestamps, and all integration artefact URLs.
- **Retry handling** — RCA/fix/PDF/patch steps are retried automatically (2 retries, 5-second delay) before failing gracefully to a `FAILED` state.

### Human-in-the-Loop Governance
- Workflow explicitly pauses before any downstream delivery action (Jira/PR).
- Reviewers can approve, reject, or request a regenerated fix with feedback injected into the next LLM call.
- Jira and GitHub actions only fire **after** explicit human approval — no unattended production changes.

### Integrations (all configurable per-project)
- **LLM providers:** OpenAI, Anthropic Claude, Azure OpenAI, Google Gemini, Groq, and local Ollama — swappable without code changes.
- **GitHub:** code fetching for RCA context, branch/commit/PR creation.
- **Jira:** issue creation, patch attachment, DevInfo (branch/commit/PR) sync.
- **Slack / Microsoft Teams:** webhook-based incident and workflow notifications.
- **MuleSoft Anypoint Platform:** live runtime context (CloudHub/ARM) used to enrich RCA accuracy.

### Multi-Tenancy & Access Control
- **Project-scoped incidents** — every incident belongs to a Project with its own integrations.
- **Role-based access:** `admin` (platform-wide), `team_admin` (project-scoped integration/team management), `user` (view/approve/comment).
- **Automatic project resolution** from incoming OTLP `app_name` via exact match, repo-URL match, configured repo mappings, or fallback.
- **Encrypted credential storage** — all integration secrets (LLM keys, Jira tokens, GitHub tokens, webhooks, Anypoint credentials) are AES/Fernet-encrypted at rest in SQLite.

### Dashboard & Observability UI
- Incident list and detail pages with **live workflow progress via Server-Sent Events (SSE)**.
- Approve/reject/regenerate actions with reviewer notes and comment threads.
- Bulk approve/reject (up to 100 incidents at once).
- CSV export of incidents.
- Observability hub: telemetry log viewer, distributed trace viewer, API metrics dashboard, API analytics, audit trail.
- Admin dashboard: project onboarding, Team Admin assignment.
- Team Admin dashboard: integration configuration, connectivity testing, app→repo mapping, team/user management.
- Application health overview page.

### Persistence & Data Management
- SQLite database with four core tables: `incidents`, `telemetry_logs`, `project_integration_configs`, `incident_comments`.
- Auto-schema creation and column migration on startup (no manual migration step needed for new fields).
- Operational scripts for DB init/reset, patch/PDF regeneration, and code-context backfill.

---

## 3. Capabilities Summary

PRISM connects **observability signals → AI-assisted diagnosis and remediation drafting → human approval → engineering-system integration** in a single governed workflow:

- Converts raw production error telemetry into structured, triaged incidents automatically.
- Produces an evidence package (RCA + fix + PDF + patch + quality scores) for every qualifying incident without manual engineering effort.
- Keeps humans in control of every irreversible action (ticket creation, PR creation) via an explicit approval gate.
- Fits into existing delivery processes rather than replacing them — Jira, GitHub, Slack/Teams integrations are optional and project-configurable.
- Supports multiple LLM backends so organizations can choose cloud or local/on-prem inference.
- Scales to multiple teams/projects with isolated, encrypted configuration per project.
- Does **not** deploy code to production automatically — it accelerates preparation and review, retaining human decision authority at the most critical point.

---

## 4. Full Technology Stack

| Category | Technology |
|----------|------------|
| **Language** | Python 3.11+ |
| **Agent Orchestration** | LangGraph, LangChain (`langchain`, `langchain-openai`, `langchain-anthropic`, `langchain-google-genai`, `langchain-groq`, `langchain-community`) |
| **Web Framework** | FastAPI, Uvicorn (ASGI server), Jinja2 (server-rendered templates), Pydantic v2, python-multipart |
| **Database / ORM** | SQLite, SQLAlchemy, Alembic (migrations) |
| **GitHub Integration** | PyGithub |
| **Jira Integration** | atlassian-python-api |
| **Slack Integration** | slack-sdk |
| **HTTP Client** | requests |
| **Observability / Telemetry** | OpenTelemetry API & SDK, opentelemetry-exporter-otlp, opentelemetry-instrumentation-fastapi, OpenTelemetry Collector (`otelcol-contrib`) |
| **PDF Generation** | ReportLab, pypdf |
| **Error Deduplication / Fingerprinting** | simhash, datasketch |
| **Code & Markup Parsing** | tree-sitter, tree-sitter-language-pack, lxml, BeautifulSoup4, xmltodict, javatools |
| **Configuration & Utilities** | python-dotenv, PyYAML, tenacity (retry logic), pydantic-settings |
| **Security** | Fernet/AES encryption (`cryptography`) for stored integration credentials |
| **Frontend** | Vanilla JavaScript, CSS (`ui/static/app.js`, `app.css`, `components.css`), Server-Sent Events for real-time UI updates |
| **Testing** | pytest, pytest-asyncio, pytest-cov, httpx |
| **Development Tooling** | black (formatting), ruff (linting), mypy (type checking), pre-commit (git hooks) |
| **Deployment / Ops** | Windows batch script (`restart_prism_app.bat`), standalone Python operational scripts (`scripts/`, `tools/`) |

---

*This note reflects the platform's implemented and verifiably functioning capabilities as of the current codebase state, based on `README.md`, `requirements.txt`, and the architecture defined in `agents/`, `ingestion/`, `integrations/`, `storage/`, and `ui/`.*
