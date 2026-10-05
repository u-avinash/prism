# I Built an AI-Assisted Incident Workflow That Keeps Humans in Control

### *How Prism turns OTLP error logs into governed, reviewable engineering actions with LangGraph*

**By Upadhyayula Avinash**

---

Production incident response often begins with repeatable work: interpret the error, find the relevant code, understand the deployment context, draft a fix, document it, and connect the outcome to the team’s Jira, GitHub, and notification tools.

That work still needs engineering judgment. But much of the preparation can be automated.

I built **Prism**, an open-source AI-assisted incident-management platform, to connect observability signals to a structured engineering response—without allowing an AI model to decide whether code should be delivered.

## What Prism does

Prism accepts OpenTelemetry (OTLP) logs directly or through an OpenTelemetry Collector. For qualifying error signals, it:

1. Persists the telemetry and resolves the owning project.
2. Deduplicates repeated errors with project-scoped SimHash fingerprints.
3. Assesses severity and starts a stateful LangGraph workflow for qualifying incidents.
4. Generates an AI-assisted Root Cause Analysis using available GitHub code and MuleSoft/Anypoint runtime context.
5. Produces a proposed fix, test suggestion, quality reflection, downloadable patch, and RCA PDF.
6. Pauses for a human reviewer.
7. After explicit approval, can send notifications, create a Jira issue, and create a GitHub branch and Pull Request.

The objective is not unattended remediation. It is a more consistent evidence package and a shorter path from an error signal to an informed engineering decision.

## The approval gate is the design center

The workflow pauses before Jira and GitHub delivery actions. Reviewers can inspect:

- Root-cause analysis and confidence information
- Proposed code change and explanation
- Quality evidence for correctness, safety, code quality, and completeness
- A downloadable `.patch` file to validate locally
- An RCA PDF, comments, and reviewer feedback

A reviewer can approve, reject, or request a regenerated fix with feedback. Prism does not deploy code to production. The platform prepares and routes work; accountable engineers retain control of the decision.

## Security and operations are part of the workflow

Recent work focused on making the operational boundary more explicit:

- **Project API keys for ingestion:** In production, ingestion requests require `Authorization: Bearer <project-api-key>`. The authenticated key resolves project ownership directly.
- **Fail-closed production configuration:** The production profile rejects insecure authentication, unassigned-ingestion, CORS, secure-cookie, and CSRF settings.
- **Per-project isolation:** Incidents, telemetry, workflow history, access checks, and integration configuration are project scoped.
- **Encrypted integration secrets:** LLM, GitHub, Jira, notification, and Anypoint credentials are encrypted at rest. Ingestion keys are held as non-reversible digests and returned only once when issued.
- **Workflow execution evidence:** Durable workflow-run history and bounded node-event records show whether work is active, retrying, failed, or complete without duplicating sensitive prompt, source, or generated-fix data.
- **Audited recovery:** Admins and Team Admins can resume incomplete approved post-approval work with a required reason. Recovery honors the execution lease and never repeats RCA generation, fix generation, or the approval decision.

## Technology choices

Prism is built with Python, FastAPI, LangGraph, SQLAlchemy/SQLite, Jinja2, Server-Sent Events, OpenTelemetry, and pluggable LLM providers including OpenAI, Anthropic, Azure OpenAI, Gemini, Groq, and Ollama.

The architecture is intentionally straightforward for a single-instance deployment: two FastAPI services, SQLite persistence, filesystem artifacts, and optional collector-mediated OTLP delivery. Teams with high availability or multi-instance requirements should evaluate a networked database, managed gateway, and deployment architecture suited to their environment.

## Clear current boundary

Prism persists logs and the incidents derived from them. Its OTLP trace and metric endpoints currently validate and acknowledge payloads but do not persist, correlate, or render live trace or metric data. The UI states this limitation explicitly rather than presenting sample data as production observability.

## Getting started responsibly

The repository includes a credential-free local Postman regression suite for authentication, tenant isolation, ingestion-key lifecycle, OTLP boundaries, workflow-history access, security-audit evidence, and CSV export.

For production, Prism should be deployed behind trusted TLS infrastructure. OTLP should be routed through a collector or API gateway that injects a per-project key and applies gateway-level limits. The README includes the production security baseline and a collector-mediated demonstration flow.

The core principle remains simple:

> **AI prepares; humans decide; the system executes approved work.**

Full source: [github.com/u-avinash/prism](https://github.com/u-avinash/prism)

---

*Upadhyayula Avinash — Software Engineer | AI Systems | Platform Engineering*

*#AI #DevOps #SRE #LangGraph #OpenTelemetry #IncidentManagement #AIOps #Python*
