<!--
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
-->
# Prism — AI-Powered Incident Management Platform

Prism is an autonomous incident management system that ingests OpenTelemetry logs, classifies errors by severity, generates AI-powered Root Cause Analysis (RCA) and code fixes, and orchestrates a human-in-the-loop approval workflow that ends with a Jira ticket and a GitHub Pull Request — all without manual intervention beyond a single approval click.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [The 11-Step Workflow](#the-11-step-workflow)
4. [Project & Role Model](#project--role-model)
5. [Integrations](#integrations)
6. [Directory Structure](#directory-structure)
7. [Quick Start](#quick-start)
8. [Quality Gates](#quality-gates)
9. [Configuration](#configuration)
10. [Production Security Baseline](#production-security-baseline)
11. [API Reference](#api-reference)
12. [Default Credentials](#default-credentials)

---

## Overview

| Layer | Technology | Port |
|-------|------------|------|
| Ingestion API | FastAPI + OpenTelemetry | 8000 |
| UI / Dashboard | FastAPI + Jinja2 + SSE | 8080 |
| Workflow Engine | LangGraph (stateful agent graph) | — |
| Database | SQLite (via SQLAlchemy) | — |
| LLM | Pluggable: OpenAI / Anthropic / Azure OpenAI / Google Gemini / Groq / Ollama | — |

Prism is designed primarily for **MuleSoft / Anypoint** applications, but works with any stack that can emit OTLP-formatted logs. Errors flow in as OTLP log records, are parsed and deduplicated, and then processed by the LangGraph agent workflow.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  MuleSoft / Anypoint App  (or any OTLP-compatible source)       │
└───────────────────────────┬─────────────────────────────────────┘
                            │  OTLP/HTTP  POST /v1/logs
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Ingestion API  (ingestion/api.py)  :8000                       │
│  • OTLP parsing (OTLPParser)                                    │
│  • Error deduplication (SimHash fingerprint)                    │
│  • Severity analysis                                            │
│  • Writes Incident + TelemetryLog to SQLite                     │
│  • Fires background task → LangGraph workflow                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │  async background task
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  LangGraph Workflow  (agents/workflow.py)                        │
│  assess_severity → generate_rca → generate_fix → generate_pdf  │
│  → reflect → generate_patch_file → await_approval ──────────── │
│                                         │ (pauses here)        │
│                                   Human clicks Approve          │
│                                         │                       │
│  send_notifications → create_jira_pr → finalize                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │  reads / writes
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  SQLite Database  (data/incidents.db)                           │
│  incidents • telemetry_logs • project_integration_configs       │
│  incident_comments                                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │  SSE + REST
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Dashboard UI  (ui/server.py)  :8080                            │
│  • Incident list & detail with live workflow progress           │
│  • Approve / reject fixes with reviewer notes                   │
│  • Fix re-generation with feedback injection                    │
│  • Observability: traces, metrics, logs, audit trail            │
│  • Admin: projects, teams, users, per-project integrations      │
└─────────────────────────────────────────────────────────────────┘
```

---

## The 11-Step Workflow

Each incident that meets the severity threshold (`HIGH` or `CRITICAL` by default) is processed through an 11-step LangGraph state machine.

| # | Step ID | LangGraph Node | Description |
|---|---------|----------------|-------------|
| 1 | `assess_severity` | `assess_severity` | Classify severity from OTLP signal or keyword analysis. Fires "Incident Created" notification. |
| 2 | `generate_rca` | `generate_rca` | LLM-generated Root Cause Analysis (400–500 words). Fetches live code from GitHub and Anypoint runtime context. Self-scores confidence via a second LLM call. |
| 3 | `generate_fix` | `generate_fix` | LLM-generated code fix for the identified root cause, with a human-readable explanation. |
| 4 | `generate_pdf` | `generate_pdf` | Generates a PDF RCA report saved to `data/pdfs/`. |
| 5 | `reflect` | `reflect` | Quality-scores the proposed fix on correctness, safety, code quality, and completeness. Safe-defaults on failure so it never blocks the pipeline. |
| 6 | `generate_patch` | `generate_patch_file` | Generates a unified `.patch` file saved to `data/patches/`, available for download before approval. |
| 7 | `await_approval` | `await_approval` | **Workflow pauses here.** The reviewer can inspect RCA, fix diff, and download the patch before deciding. |
| 8 | `send_notifications` | `send_notifications` | Sends Slack and/or Teams alerts. Webhooks are loaded from per-project DB config only. |
| 9 | `create_jira` | `create_jira_pr` | Creates a Jira issue, attaches the patch, and syncs branch/commit/PR into the Jira Development panel. |
| 10 | `create_pr` | `create_jira_pr` | Creates a GitHub branch, commits the fixed file, and opens a Pull Request. |
| 11 | `finalize` | `finalize` | Persists final status, timestamps, and all integration artefact URLs. |

**Retry logic:** Steps 2–4 and 6 are wrapped with `_make_retryable_node()` (2 retries, 5-second delay). On exhaustion the workflow routes directly to `finalize` with `status=FAILED`.

**Post-approval path:** After the user approves, `run_post_approval_workflow()` in `agents/workflow.py` runs steps 8–11 sequentially. Steps 1–7 are **not** re-run.

### Workflow Operations and Recovery

Every full, post-approval, and operator recovery execution receives a durable `workflow_runs` record. Retryable nodes also emit bounded `workflow_step_events` (`started`, `failed`, `retrying`, and `succeeded`) so operators can distinguish an external integration failure from a stalled execution without persisting prompts, raw telemetry, source code, generated fixes, or credentials.

- `GET /api/workflow-health` provides selected-project success rate, active runs, average completed duration, and retry count.
- `GET /api/incidents/{id}/workflow-runs` provides newest-first execution history for an incident.
- `GET /api/workflow-runs/{run_id}/events` provides chronological, tenant-scoped node events for one execution.
- `POST /api/incidents/{id}/recover-post-approval` queues a recovery run only for an **approved** incident that has not already completed PR processing.

Recovery is restricted to `admin` and `team_admin` users, requires a 3–500-character operator reason, honors the persistent 30-minute execution lease, is project-scoped, and records both an audit event and a recovery workflow run. Use it only after correcting the external blocker (for example, GitHub or Jira permissions). It resumes only post-approval work and never re-runs RCA, fix generation, or the approval decision.

---

## Project & Role Model

Prism is multi-tenant. Every incident is scoped to a **Project**, and every Project has its own encrypted integration credentials.

```
Admin
 └── creates Projects and assigns Team Admins
      Team Admin
       └── configures integrations (LLM, Jira, GitHub, Slack, Teams, Anypoint)
       └── manages team Users and their feature access
            User
             └── views incidents, approves/rejects fixes, adds comments
```

### Roles

| Role | Capabilities |
|------|--------------|
| `admin` | Platform-wide: create/delete projects and users, assign Team Admins |
| `team_admin` | Project-scoped: configure integrations, manage team members, set feature access |
| `user` | Project-scoped: view incidents, approve/reject fixes, comment |

### Project Resolution

When an OTLP log arrives with a valid project API key, the ingestion API resolves the owning project directly from that authenticated key. The resolved `project_id` is persisted on both the telemetry record and the incident.

Local development may explicitly permit unauthenticated ingestion through `ALLOW_UNASSIGNED_INGESTION=true`; those records are stored with `project_id=None` and must not be treated as tenant-owned. When unassigned intake is disabled—including the production default—the request is rejected unless it supplies a valid project API key. Duplicate detection is scoped to `(project_id, error_fingerprint)`, and workflow processing uses the stored owner rather than attempting to re-resolve a project.

---

## Integrations

All credentials are stored **encrypted** in SQLite (`data/incidents.db`, table `project_integration_configs`). The master encryption key lives in `data/.integration.key` (or `INTEGRATION_SECRET_KEY` env var).

| Integration | Purpose | Config Section |
|-------------|---------|----------------|
| LLM | RCA, fix, reflection generation | `llm` |
| GitHub | Code fetch, branch/commit/PR creation | `github` |
| Jira | Ticket creation, patch attachment, DevInfo sync | `jira` |
| Slack | Incident & workflow event notifications | `slack` |
| Microsoft Teams | Incident & workflow event notifications | `teams` |
| MuleSoft Anypoint | Live runtime context for RCA (CloudHub / ARM) | `anypoint` |

### Supported LLM Providers

| Provider | `provider` value |
|----------|-----------------|
| OpenAI | `openai` |
| Anthropic Claude | `anthropic` |
| Azure OpenAI | `azure_openai` |
| Google Gemini | `google_genai` |
| Groq | `groq` |
| Ollama (local) | `ollama` |

---

## Directory Structure

```
prism/
├── agents/                    # LangGraph workflow engine
│   ├── state.py               # AgentState TypedDict + workflow constants
│   ├── workflow.py            # Graph definition, project resolution, post-approval runner
│   └── nodes/                 # One module per workflow step
│       ├── severity_assessor.py
│       ├── rca_generator.py
│       ├── fix_generator.py
│       ├── pdf_report.py
│       ├── reflector.py
│       ├── patch_generator.py
│       ├── approval_handler.py
│       ├── jira_creator.py
│       ├── pr_creator.py
│       └── finalizer.py
│
├── ingestion/                 # OpenTelemetry ingestion server (:8000)
│   ├── api.py                 # FastAPI app — OTLP endpoints, incident CRUD
│   └── otlp_parser.py         # Parses OTLP/JSON → IncidentCreate models
│
├── ui/                        # Dashboard server (:8080)
│   ├── server.py              # FastAPI app — all HTML pages + JSON APIs
│   ├── static/                # CSS and JS assets
│   └── templates/             # Jinja2 HTML templates
│
├── integrations/              # External API clients
│   ├── llm_provider.py        # Unified LLM interface (multi-provider)
│   ├── github_client.py       # GitHub REST API (branch, commit, PR, code fetch)
│   ├── jira_client.py         # Jira REST + DevInfo APIs
│   ├── anypoint_client.py     # MuleSoft Anypoint Platform API
│   └── notification.py        # Slack / Teams webhook delivery
│
├── storage/                   # Data persistence layer
│   ├── database.py            # SQLAlchemy models + engine setup + migrations
│   ├── models.py              # Pydantic request/response models
│   ├── incident_repository.py # CRUD + stats queries for incidents
│   ├── telemetry_repository.py# CRUD for raw telemetry logs
│   ├── auth_store.py          # JSON-file auth: users, projects, sessions
│   └── customer_store.py      # Customer / environment management
│
├── config/
│   ├── settings.py                  # Pydantic settings (infrastructure only, no secrets)
│   ├── prompts.yaml                 # LLM prompt templates
│   └── otel-collector-config.yaml   # OpenTelemetry Collector config (otelcol-contrib 0.153.0)
│
├── utils/
│   ├── code_fetcher.py        # GitHub file fetching with line context
│   ├── error_deduplication.py # SimHash fingerprinting
│   ├── id_generator.py        # 4-character alphanumeric incident IDs
│   ├── pdf_generator.py       # ReportLab PDF generation helper
│   ├── retry_handler.py       # Tenacity retry utilities
│   ├── secret_crypto.py       # Fernet encryption for stored credentials
│   └── severity_analyzer.py   # Keyword + heuristic severity classification
│
├── scripts/                   # One-off operational scripts (DB init, reset, etc.)
├── tools/                     # Developer tools: checks, debug, tests, operations
│   └── README.md              # Full listing of all tool scripts
│
├── data/                      # Runtime data (gitignored except .gitkeep)
│   ├── incidents.db           # SQLite database
│   ├── .integration.key       # Master encryption key (auto-generated)
│   ├── auth_data.json         # User / project / session store
│   ├── pdfs/                  # Generated RCA PDF reports
│   └── patches/               # Generated .patch files
│
├── requirements.txt
├── restart_prism_app.bat      # Windows helper to restart both servers
└── README.md                  # This file
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### Quality Gates

Run the deterministic regression suite from the project root:

```bash
python -m pytest
```

The suite uses an in-memory SQLite database and verifies the critical safety guarantees without calling LLMs or external integrations:

- Error fingerprints cannot deduplicate incidents across projects.
- An incident workflow has one durable execution lease at a time.
- Only the lease owner can release the workflow for a later retry.

GitHub Actions runs the same compile and test gate for every pull request and every push to `main` (`.github/workflows/ci.yml`). Legacy scripts under `tools/` remain operational diagnostics and are intentionally excluded from automated pytest discovery.

### Local Postman regression suite

Prism includes a deterministic, credential-free Postman regression suite for local validation.

1. Start the Prism UI and ingestion services on their configured local ports. The generated environment defaults to `http://127.0.0.1:8080` and `http://127.0.0.1:8000`.
2. Seed synthetic local fixtures:

   ```bat
   py -3.14 scripts\seed_postman_data.py --reset
   ```

   This intentionally resets only local runtime database, authentication, and session data. Never run it against production.
3. Import `postman/Prism.postman_collection.json` and `postman/Prism.local.postman_environment.json` into Postman.
4. Select **Prism Local Synthetic**, then run **Prism Local Regression** in collection order.

The suite validates authentication and CSRF handling, role and tenant isolation, project ingestion-key lifecycle, OTLP authentication boundaries, incident comments, workflow-history access, security-audit evidence, and CSV export. It uses synthetic `example.test` identities and no external-integration credentials.

### Collector-mediated demo suite

`postman/Prism.Collector.Demo.postman_collection.json` is a guided demonstration of the intended production telemetry route. Unlike the local regression suite, it sends OTLP payloads to the OpenTelemetry Collector rather than directly to Prism:

```text
Postman → OpenTelemetry Collector (:4318) → Prism Ingestion API (:8000) → Prism Dashboard (:8080)
```

1. Start the Prism UI and ingestion services.
2. Seed the local demo identities, project, and project key:

   ```bat
   py -3.14 scripts\seed_postman_data.py --reset
   ```

3. Copy the seeded tenant-A `project_a_api_key` from `postman/Prism.local.postman_environment.json` and set it **only in the Collector process environment**:

   ```bat
   set PRISM_OTLP_EXPORT_API_KEY=prism_<seeded-project-a-key>
   otelcol-contrib.exe --config config/otel-collector-config.yaml
   ```

4. Import `postman/Prism.Collector.Demo.postman_collection.json` and `postman/Prism.Collector.Demo.postman_environment.json`.
5. Select **Prism Collector Demo (Local)** and run the requests in collection order.

The demo sends one batch of 12 OTLP logs through the Collector: 10 unique `ERROR`/`FATAL` records that create incidents and demonstrate MuleSoft, Java, Python, Node.js, .NET, Go, Ruby, PHP, Rust, and Kotlin/JVM detection; plus one `WARN` and one `INFO` record that are persisted as telemetry without creating incidents. This distinction is intentional: Prism’s incident workflow begins at OTLP severity `ERROR` (17) and creates `HIGH` incidents; `FATAL` (21+) creates `CRITICAL` incidents, while lower-severity signals remain operational telemetry.

The collection also forwards a trace and a metric through the Collector. Prism currently acknowledges these signals but does not persist or render their raw data. The final requests authenticate to the Dashboard and verify the collector-forwarded incidents are visible. Do not expect a real PR or Jira issue without valid per-project LLM, GitHub, and Jira integrations.

### Observability support boundary

`POST /v1/traces` and `POST /v1/metrics` currently validate and acknowledge OTLP payloads with summary statistics. Prism does **not** yet persist, correlate, or render trace or metric records in the dashboard. The `/traces` and `/metrics` pages clearly state this limitation; only telemetry logs and derived incident data are persisted.

### 2. Start the Ingestion API

```bash
uvicorn ingestion.api:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Start the OpenTelemetry Collector (optional but recommended)

Download **otelcol-contrib** (v0.153.0 or later) from the [OpenTelemetry releases page](https://github.com/open-telemetry/opentelemetry-collector-releases/releases) and run it with the bundled config:

```bash
# Windows
otelcol-contrib.exe --config config/otel-collector-config.yaml

# Linux / macOS
./otelcol-contrib --config config/otel-collector-config.yaml
```

The collector:
- Listens for **OTLP/HTTP** on port **4318** (your apps send logs/traces/metrics here)
- Forwards all signals to the **Prism Ingestion API** on `http://localhost:8000`
- Exposes a health check on port **13133** (`http://localhost:13133`)

Development mode permits local unauthenticated ingestion for quick start. Production mode requires every ingestion request to supply a project API key:

```bash
-H "Authorization: Bearer <project-api-key>"
```

Configure the collector's outbound request headers with that key rather than exposing Prism's ingestion port directly to untrusted clients.

#### Managing ingestion API keys

Platform admins and team admins can manage only their authorized project's keys through the authenticated Dashboard API:

- `POST /api/team-admin/api-keys` creates a key. The plaintext `prism_...` key is returned **once** in that response and must be placed immediately in the collector or API-gateway secret store.
- `GET /api/team-admin/api-keys?project_id=PRJ-...` lists lifecycle metadata only: label, creation, expiry, last use, and revocation timestamps. Key values and digests are never returned.
- `DELETE /api/team-admin/api-keys/{key_id}?project_id=PRJ-...` revokes a key without deleting its audit-relevant record.

For rotation, create and deploy a replacement key, verify collector delivery, then revoke the prior key. Set an ISO-8601 `expires_at` when issuing short-lived credentials. Each successful ingestion authentication updates `last_used_at`; create, use, and revoke lifecycle events are retained in the security audit log.

### 4. Start the Dashboard UI

```bash
uvicorn ui.server:app --host 0.0.0.0 --port 8080 --reload
```

Or use the Windows helper:

```bat
restart_prism_app.bat
```

### 5. Open the Dashboard

Navigate to **http://localhost:8080** and log in with the default admin credentials (see below).

### 6. Create a Project and Configure Integrations

1. Log in as **admin** → Admin Dashboard → **Onboard Project**
2. Create a project and assign a Team Admin email
3. Log in as the Team Admin → **Configure Integrations**
4. Set up at minimum: **LLM** (required for workflow) and optionally GitHub, Jira, Slack/Teams

### 7. Send a Test Log

```bash
curl -X POST http://localhost:8000/v1/logs \
  -H "Content-Type: application/json" \
  -d '{
    "resourceLogs": [{
      "resource": {"attributes": [
        {"key": "service.name", "value": {"stringValue": "my-app"}},
        {"key": "deployment.environment", "value": {"stringValue": "production"}}
      ]},
      "scopeLogs": [{
        "logRecords": [{
          "severityNumber": 17,
          "body": {"stringValue": "NullPointerException in OrderService.processOrder at line 142"},
          "attributes": []
        }]
      }]
    }]
  }'
```

---

## Configuration

Prism works **out of the box with zero configuration**. Every setting has a built-in default and no `.env` file is required. The application can be started immediately after installing dependencies.

If you need to override any infrastructure setting, you can either:
- Set it as an **environment variable** before starting the servers, or
- Create an optional **`.env` file** in the project root (it is gitignored and will be loaded automatically by `config/settings.py` via `pydantic-settings`)

> **Important:** Integration credentials (LLM API keys, Jira tokens, GitHub tokens, Slack/Teams webhooks, Anypoint credentials, etc.) are **never** configured via environment variables or a `.env` file. They are configured **per-project** through the **Team Admin onboarding page** (`/team-admin/onboarding`) and stored AES-encrypted in the SQLite database.

### Infrastructure Settings (`config/settings.py`)

All settings below are optional overrides. The defaults shown are what the application uses when nothing is set.

#### Encryption

| Variable | Default | Description |
|----------|---------|-------------|
| `INTEGRATION_SECRET_KEY` | *(auto-generated)* | Master Fernet key for encrypting per-project credentials stored in the DB. Set explicitly in multi-process or multi-instance deployments so all processes share the same key. |
| `INTEGRATION_SECRET_KEY_FILE` | `./data/.integration.key` | Path to the key file used when `INTEGRATION_SECRET_KEY` is not set directly. Auto-created on first boot. |

#### Ingestion API

| Variable | Default | Description |
|----------|---------|-------------|
| `INGESTION_API_HOST` | `0.0.0.0` | Ingestion API bind host. |
| `INGESTION_API_PORT` | `8000` | Ingestion API listen port. |
| `OTLP_COLLECTOR_PORT` | `4318` | Port the OTLP HTTP collector listens on. |
| `OTLP_ENDPOINT` | `http://localhost:4318/v1/logs` | OTLP endpoint used internally. |
| `PRISM_ENVIRONMENT` | `development` | Runtime security profile. Set to `production` for deployed environments. |
| `INGESTION_ALLOWED_ORIGINS` | local origins in development | Comma-separated browser origins permitted by CORS. **Required** in production; never use `*`. |
| `INGESTION_AUTH_REQUIRED` | `false` development / `true` production | Require `Authorization: Bearer <project API key>` on all ingestion endpoints. Production rejects an insecure override. |
| `ALLOW_UNASSIGNED_INGESTION` | `true` development / `false` production | Whether events without a resolved project may be accepted. Production rejects an insecure override. |
| `MAX_INGESTION_BODY_BYTES` | `1048576` | Maximum declared ingestion request size in bytes. Requests above it return `413`. |
| `INGESTION_RATE_LIMIT_PER_MINUTE` | `60` | Per-client in-process intake cap. Use an API gateway/load balancer for distributed enforcement. |

#### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_PATH` | `./data/incidents.db` | SQLite database file path. |
| `PDF_OUTPUT_DIR` | `./data/pdfs` | Directory for generated RCA PDF reports. |
| `PATCH_OUTPUT_DIR` | `./data/patches` | Directory for generated `.patch` files. |

#### Workflow Behaviour

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_FIX_ENABLED` | `true` | Enable/disable the full LangGraph workflow on incident ingestion. |
| `AUTO_FIX_SEVERITY_THRESHOLD` | `HIGH` | Minimum severity that triggers the RCA + fix workflow (`HIGH` or `CRITICAL`). |
| `AUTO_FIX_REQUIRES_APPROVAL` | `true` | Require human approval before Jira/PR creation. |
| `AUTO_FIX_MAX_FILE_SIZE_KB` | `500` | Maximum source file size (KB) to fetch from GitHub for code context. |
| `AUTO_PR_CREATE` | `true` | Automatically create a GitHub PR after approval. |
| `AUTO_PR_LABEL` | `ai-generated,needs-review` | Comma-separated labels applied to created PRs. |

#### Error Detection & Deduplication

| Variable | Default | Description |
|----------|---------|-------------|
| `ERROR_FINGERPRINT_ALGORITHM` | `simhash` | Algorithm used to fingerprint errors for deduplication. |
| `DUPLICATE_THRESHOLD` | `0.85` | Similarity score above which an incoming error is treated as a duplicate. |
| `ERROR_BURST_WINDOW_MINUTES` | `10` | Rolling window (minutes) used to detect error bursts. |
| `ERROR_BURST_THRESHOLD` | `5` | Number of identical errors within the burst window before suppression. |

#### UI & Notifications

| Variable | Default | Description |
|----------|---------|-------------|
| `UI_BASE_URL` | `http://localhost:8080` | Used to build clickable incident links in Slack/Teams notification messages. |

#### Observability & Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `LANGGRAPH_TRACING` | `true` | Enable LangGraph internal tracing. |
| `LANGCHAIN_TRACING_V2` | `true` | Enable LangSmith tracing (requires `LANGCHAIN_API_KEY`). |
| `LANGCHAIN_API_KEY` | *(none)* | LangSmith API key for trace export (optional). |
| `LANGCHAIN_PROJECT` | `mule-monitor-poc` | LangSmith project name. |

#### Caching & Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_CACHE_ENABLED` | `true` | Cache identical LLM prompts to reduce API calls. |
| `LLM_CACHE_TTL_HOURS` | `24` | Time-to-live (hours) for cached LLM responses. |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `10` | Ingestion API rate limit per client. |

## Production Security Baseline

Prism’s production profile is intentionally **fail closed**. Start both services with explicit, reviewable environment settings:

```bash
PRISM_ENVIRONMENT=production
INGESTION_ALLOWED_ORIGINS=https://prism.example.com
INGESTION_AUTH_REQUIRED=true
ALLOW_UNASSIGNED_INGESTION=false
UI_COOKIE_SECURE=true
CSRF_ENABLED=true
DEBUG_ENDPOINTS_ENABLED=false
INTEGRATION_SECRET_KEY=<durable-shared-fernet-key>
```

On startup, production configuration validation rejects missing ingestion origins and explicitly insecure authentication, tenant-assignment, secure-cookie, or CSRF overrides. This prevents a deployment from silently retaining local-development behavior.

Operational requirements:

1. Terminate TLS at a trusted reverse proxy or load balancer and expose only HTTPS publicly.
2. Keep the UI, ingestion API, SQLite data directory, `auth_data.json`, and integration key file on private infrastructure with least-privilege filesystem access.
3. Send OTLP through a managed collector/API gateway, inject a distinct project API key, set gateway body/rate limits, and rotate keys during scheduled maintenance. The app-level rate limiter is process-local by design.
4. Do not publish `/debug/*` routes in production; Prism returns `404` for them under the production policy.
5. Use a durable, externally managed `INTEGRATION_SECRET_KEY` for every process that must read encrypted configurations. Back up the key separately from the database and test recovery.
6. Change the first-boot administrator password immediately and prevent the seeded defaults from being used in any internet-reachable deployment.

### First-Boot Admin Credentials

The default admin account is seeded from `storage/auth_store.py` only on the **very first boot** (when `data/auth_data.json` does not yet exist). These can be overridden via environment variables before the first run:

| Variable | Default | Description |
|----------|---------|-------------|
| `PRISM_DEFAULT_ADMIN_USERNAME` | `admin` | Default admin username. |
| `PRISM_DEFAULT_ADMIN_PASSWORD` | `ChangeMe123!` | Default admin password — **change immediately after first login**. |
| `PRISM_DEFAULT_ADMIN_EMAIL` | `admin@prism.local` | Default admin email. |

Once `data/auth_data.json` exists these variables have no effect; use the Admin Dashboard to manage users.

### GitHub source-code resolution

Configure one GitHub organization and token in **Team Admin → Project Configuration → GitHub** for each client/project. Prism resolves source code in this order:

1. An explicit `github.repository`, repository, or GitHub URL carried in telemetry.
2. The repository recorded for a registered application, including its telemetry aliases.
3. An exact repository-name match in the configured GitHub organization.
4. A best-effort repository-name match in that organization.

This allows a client such as NTT Data to run MuleSoft, Python, Go, and other applications under one client/project without configuring every repository. Register an application when its telemetry identifier differs from the repository name, when it needs aliases, or when deterministic repository selection is required.

---

## API Reference

### Ingestion API (:8000)

Port **8000 is machine-ingestion-only**. In production, requests require a
project API key (`Authorization: Bearer <project-api-key>`). Incident browsing,
approvals, telemetry views, and all other operator actions are available only
through the authenticated Dashboard UI on port 8080. Legacy management paths
on the ingestion service return `404`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/v1/logs` | **Primary** OTLP log ingestion endpoint |
| `POST` | `/v1/traces` | OTLP trace ingestion (acknowledged, not yet stored) |
| `POST` | `/v1/metrics` | OTLP metrics ingestion (acknowledged, not yet stored) |
| `POST` | `/v1/events` | CI/CD event ingestion endpoint |
| `POST` | `/ingest/log` | Direct incident creation (legacy) |
| `POST` | `/ingest/otlp` | Legacy OTLP endpoint (use `/v1/logs` instead) |
| `GET` | `/debug/last-requests` | Local diagnostics; unavailable in production |
| `GET` | `/debug/incident/{id}/raw` | Local diagnostics; unavailable in production |

### Dashboard UI (:8080)

#### HTML Pages

| Path | Description |
|------|-------------|
| `/login` | Login page |
| `/incidents` | Incident list with filters |
| `/incidents/{id}` | Incident detail (RCA, fix diff, workflow progress, timeline) |
| `/app-health` | Service health overview |
| `/observability` | Observability hub |
| `/logs` | Telemetry log viewer |
| `/traces` | Distributed trace viewer |
| `/metrics` | API metrics dashboard |
| `/api-analytics` | API analytics |
| `/audit` | Audit trail |
| `/settings` | User settings |
| `/admin/dashboard` | Admin landing (admin role) |
| `/admin/onboarding` | Create project + assign Team Admin |
| `/team-admin/dashboard` | Team Admin landing |
| `/team-admin/onboarding` | Configure integrations + manage team |

#### Key JSON APIs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/incidents` | Incident list (JSON) with project scoping |
| `GET` | `/api/incidents/{id}` | Incident detail (JSON) |
| `POST` | `/api/incidents/{id}/approve` | Approve or reject (SSE broadcast) |
| `POST` | `/api/incidents/{id}/continue-post-approval` | Resume post-approval workflow |
| `POST` | `/api/incidents/{id}/recover-post-approval` | Admin/team-admin audited recovery of an incomplete approved workflow |
| `POST` | `/api/incidents/{id}/trigger` | Re-trigger full workflow (guarded) |
| `POST` | `/api/incidents/{id}/regenerate-fix` | Re-generate fix with reviewer feedback |
| `POST` | `/api/incidents/bulk-approve` | Bulk approve/reject (up to 100) |
| `GET` | `/api/incidents/{id}/comments` | Get comment thread |
| `POST` | `/api/incidents/{id}/comments` | Add comment |
| `GET` | `/api/incidents/export.csv` | Export incidents as CSV |
| `GET` | `/api/analytics/trends` | Daily trend + MTTR stats |
| `GET` | `/api/stats` | Aggregate stats (efficient SQL) |
| `GET` | `/api/workflow-health` | Project-scoped workflow reliability summary (admin/team-admin) |
| `GET` | `/api/incidents/{id}/workflow-runs` | Incident workflow execution history |
| `GET` | `/api/workflow-runs/{run_id}/events` | Chronological workflow node operational evidence |
| `GET` | `/events` | Server-Sent Events stream |
| `POST` | `/api/switch-project` | Switch active project context |
| `POST` | `/api/team-admin/integration/{type}` | Save integration config |
| `POST` | `/api/team-admin/integration/{type}/test` | Test integration connectivity |
| `POST` | `/api/team-admin/runtime-config` | Save runtime configuration |
| `GET` | `/api/team-admin/api-keys` | List redacted project ingestion-key metadata |
| `POST` | `/api/team-admin/api-keys` | Issue a project ingestion key (plaintext returned once) |
| `DELETE` | `/api/team-admin/api-keys/{key_id}` | Revoke a project ingestion key |
| `POST` | `/api/admin/onboard-project` | Create project + Team Admin (API) |

---

## Default Credentials

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `ChangeMe123!` |
| Role | `admin` |

> **Change the default password immediately** via Admin Dashboard → Users after first login.  
> The default password is only used on the very first boot when no `data/auth_data.json` exists.

---

## AgentState Reference

The `AgentState` TypedDict (`agents/state.py`) carries all data through the LangGraph workflow. Key field groups:

| Group | Fields |
|-------|--------|
| Incident identity | `incident_id`, `project_id`, `app_name`, `environment` |
| Error details | `error_title`, `error_description`, `stack_trace`, `raw_log` |
| Severity & metadata | `fingerprint`, `severity`, `is_duplicate`, `metadata` |
| RCA outputs | `rca_text`, `rca_confidence` |
| GitHub code location | `repo_full_name`, `error_file_path`, `error_line_number`, `error_file_type` |
| Code context | `original_code`, `fix_type`, `proposed_fix`, `fix_explanation`, `affected_files` |
| Quality scores | `correctness_score`, `safety_score`, `code_quality_score`, `completeness_score`, `overall_quality_score`, `quality_concerns`, `quality_recommendation`, `reflection_failed` |
| Approval | `requires_approval`, `approval_status`, `approval_notes`, `approved_by`, `approved_at` |
| Integrations | `github_branch`, `github_pr_url`, `jira_ticket_key`, `jira_ticket_url`, `jira_issue_type`, `pdf_path`, `patch_path` |
| PR artefacts | `fixed_file_content`, `fix_branch`, `branch_name`, `pr_url`, `pr_number`, `commit_sha`, `commit_url` |
| Notifications | `slack_notified`, `email_notified` |
| Workflow control | `current_node`, `workflow_completed_steps`, `workflow_progress_pct`, `error_message`, `jira_error` |
| Audit trail | `messages` (`List[str]`, LangGraph-merged) |
| Timestamps | `created_at`, `updated_at`, `completed_at` |

---

## Database Schema Overview

The SQLite database at `data/incidents.db` contains workflow, audit, and incident persistence tables:

| Table | Description |
|-------|-------------|
| `incidents` | Core incident records with all workflow state, integration artefacts, and approval decisions |
| `telemetry_logs` | Raw OTLP log records (independent of incident creation) |
| `project_integration_configs` | Encrypted per-project integration credentials and non-reversible ingestion API-key digests |
| `security_audit_events` | Append-only security lifecycle events for API-key issuance, use, revocation, and privileged operator actions |
| `workflow_runs` | Tenant-scoped execution lifecycle records for full, post-approval, and recovery workflows |
| `workflow_step_events` | Append-only bounded operational evidence for each workflow node attempt |
| `incident_comments` | Comment threads on incidents |

Schema is auto-created by `init_database()` on startup. Column migrations for new fields are applied automatically via `PRAGMA table_info` checks in `storage/database.py`.

---

## Scripts

Operational scripts in `scripts/`. Run all from the **project root**:

```bash
python scripts/<script_name>.py [args]
```

| Script | Purpose |
|--------|---------|
| `init_db.py` | Initialize database schema and output directories |
| `reset_db.py` | Clear all rows from all tables (keeps schema intact) |
| `clear_incidents.py` | Delete all incidents (preserves other table data) |
| `wipe_auth.py` | Reset auth data to default admin only, clear all sessions |
| `fetch_code_for_incidents.py` | Backfill GitHub code context for incidents missing `fetched_code` |
| `regenerate_fix_and_patch.py` | Re-run fix generation + patch creation for a single incident |
| `regenerate_patch.py` | Re-generate the patch file only for a single incident |
| `regenerate_patches_proper.py` | Bulk re-generate patches for all incidents that have fixes |
| `regenerate_pdf_for_incident.py` | Re-generate the RCA PDF report for a single incident |

> For completing post-approval steps manually, use `tools/operations/complete_approved_workflow.py` which calls `run_post_approval_workflow()` correctly.

See `tools/README.md` for the full listing of developer check, debug, test, and operations tools.
