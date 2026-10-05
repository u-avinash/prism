# PRISM — Feature & Technology Note

**PRISM** is an AI-assisted incident-management platform. It ingests OpenTelemetry (OTLP) logs—primarily from MuleSoft/Anypoint applications but from any OTLP-compatible source—classifies errors by severity, prepares AI-assisted Root Cause Analysis (RCA) and code fixes, and drives a human-in-the-loop approval workflow that can create a Jira ticket and GitHub Pull Request after approval.

---

## 1. Overview

| Layer | Technology | Port |
|---|---|---|
| Ingestion API | FastAPI + OpenTelemetry | 8000 |
| Dashboard UI | FastAPI + Jinja2 + Server-Sent Events | 8080 |
| Workflow Engine | LangGraph (stateful agent graph) | — |
| Database | SQLite (via SQLAlchemy) | — |
| LLM | Pluggable: OpenAI / Anthropic / Azure OpenAI / Google Gemini / Groq / Ollama | — |

---

## 2. Implemented Capabilities

### Secure Ingestion & Detection

- **OTLP log ingestion** through `/v1/logs`, plus CI/CD event intake through `/v1/events`.
- **Project API-key authentication:** Production requires `Authorization: Bearer <project-api-key>` for ingestion. A valid key resolves the target project directly and persists that ownership with the telemetry and incident records.
- **Fail-closed production posture:** Production configuration rejects insecure authentication, unassigned-ingestion, CORS, secure-cookie, and CSRF overrides.
- **SimHash error deduplication** scoped to `(project_id, error_fingerprint)`, preventing cross-project duplicate matching.
- **Severity classification** using OTLP signal data plus LLM-assisted analysis with a heuristic fallback.
- **Telemetry persistence independent of incident creation:** lower-severity signals remain operational telemetry even when they do not start an incident workflow.
- **Body-size and in-process rate-limit controls** for ingestion. A gateway or load balancer remains necessary for distributed rate enforcement.

### AI-Driven Incident Workflow

For qualifying incidents, PRISM runs a LangGraph workflow that provides:

- Severity assessment and SLA computation.
- AI-assisted RCA generation, enriched with available GitHub code and MuleSoft Anypoint runtime context.
- AI-assisted code-fix generation with a reviewer-readable explanation.
- Unit-test suggestions that do not block the workflow.
- RCA PDF report and downloadable unified `.patch` artifact generation.
- Automated reflection against correctness, safety, code quality, and completeness criteria.
- Bounded retries for selected generation nodes, with failure routing to a visible `FAILED` outcome rather than an indefinitely stalled workflow.
- A persistent execution lease that prevents concurrent active runs for the same incident.

### Human Approval, Recovery & Auditability

- **Human approval is mandatory before Jira or GitHub delivery actions.**
- Reviewers can approve, reject, comment on, or request regenerated fixes with feedback.
- Post-approval continuation preserves the existing RCA, generated fix, patch, and approval decision rather than re-running the pre-approval process.
- Durable `workflow_runs` records and bounded `workflow_step_events` provide operational evidence of full, post-approval, and recovery executions without storing prompts, source code, generated fixes, raw telemetry, or credentials in event records.
- Admins and Team Admins can initiate an audited recovery of incomplete approved post-approval work. Recovery requires an operator reason, respects the persistent execution lease, and never re-runs RCA, fix generation, or approval.

### Integrations

All external integrations are configured per project:

- **LLM providers:** OpenAI, Anthropic Claude, Azure OpenAI, Google Gemini, Groq, and local Ollama.
- **GitHub:** source retrieval for RCA context, branch/commit/PR creation.
- **Jira:** issue creation, patch attachment, and DevInfo branch/commit/PR synchronization.
- **Slack / Microsoft Teams:** webhook-based workflow notifications.
- **MuleSoft Anypoint Platform:** runtime context from CloudHub/ARM.
- **Outbound webhooks:** structured notifications to compatible automation tools.

### Multi-Tenancy, Security & Access

- Project-scoped incidents, telemetry, workflow history, integration configuration, and access checks.
- Role-based controls for `admin`, `team_admin`, and `user`.
- Encrypted integration-secret storage using Fernet.
- Ingestion keys are stored as non-reversible digests; plaintext `prism_...` values are returned once only at issuance.
- Append-only security audit records cover API-key issuance, use, revocation, and privileged operator actions.
- `workflow-health` and per-incident workflow-history APIs provide scoped reliability and execution visibility.

### Dashboard & Observability

- Incident list/detail views with live progress via Server-Sent Events.
- Approval, rejection, regeneration, bulk-approval, comment, artifact-download, and CSV-export capabilities.
- Admin and Team Admin capabilities for onboarding, integrations, application-to-repository mappings, runtime settings, and ingestion-key lifecycle management.
- Telemetry-log browsing and application health views.
- **Current trace/metric boundary:** `/v1/traces` and `/v1/metrics` validate and acknowledge OTLP requests with summary statistics, but PRISM does not yet persist, correlate, or render live trace or metric records. The corresponding Dashboard pages state this limitation.

### Persistence & Data Management

SQLite persistence includes:

| Table | Purpose |
|---|---|
| `incidents` | Incident state, workflow artefacts, approval decisions, and integration results |
| `telemetry_logs` | Raw OTLP log records and incident links |
| `project_integration_configs` | Per-project encrypted integrations and ingestion-key digests |
| `incident_comments` | Reviewer and system-generated incident comments |
| `security_audit_events` | Security lifecycle and privileged-operation evidence |
| `workflow_runs` | Execution lifecycle records |
| `workflow_step_events` | Bounded node-attempt operational evidence |

The schema is initialized and migrated on startup. Operational scripts support database initialization/reset, retention work, artifact regeneration, and local synthetic Postman fixtures.

---

## 3. Operating Model

PRISM connects:

**observability signals → AI-assisted diagnosis and remediation drafting → human approval → engineering-system integration**

It is designed to reduce manual incident-response preparation while maintaining governance:

- The system prepares an RCA, proposed fix, patch, PDF, test suggestion, and quality evidence.
- A human reviewer retains authority over whether delivery actions may proceed.
- PRISM can create engineering-system artefacts after approval, but it does **not** deploy code to production.
- Production deployments should route OTLP through a managed collector or gateway that injects a distinct project key, terminates TLS, and enforces distributed limits.
- The SQLite/filesystem deployment model is appropriate for a single-instance environment; teams should evaluate a networked database and deployment architecture when scale or high availability requires it.

---

## 4. Full Technology Stack

| Category | Technology |
|---|---|
| **Language** | Python 3.11+ |
| **Agent Orchestration** | LangGraph, LangChain |
| **Web Framework** | FastAPI, Uvicorn, Jinja2, Pydantic v2 |
| **Database / ORM** | SQLite, SQLAlchemy, Alembic |
| **GitHub Integration** | PyGithub |
| **Jira Integration** | atlassian-python-api |
| **HTTP / Notifications** | requests, httpx, Slack / Teams webhooks |
| **Observability / Telemetry** | OpenTelemetry API & SDK, OTLP exporter, OpenTelemetry Collector |
| **PDF Generation** | ReportLab, pypdf |
| **Error Deduplication** | SimHash, datasketch |
| **Security** | Fernet (`cryptography`), PBKDF2 password hashing, project ingestion-key digests, session/CSRF controls |
| **Frontend** | Vanilla JavaScript and CSS, Server-Sent Events |
| **Testing** | pytest, pytest-asyncio, pytest-cov, httpx |
| **Operations** | Windows restart helper, local Postman regression/demo suites, operational scripts |

---

*This note reflects the repository implementation and documentation as of the current working-tree state. Claims about business outcomes such as MTTR or cost reduction require deployment-specific measurement.*
