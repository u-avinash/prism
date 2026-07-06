# Prism: Building an Autonomous AI Incident Management System with LangGraph and OpenTelemetry

**By Upadhyayula Avinash**

*From a production error to a GitHub Pull Request — without waking anyone up at 3am*

---

> **TL;DR:** Prism is an open-source Python platform that ingests OpenTelemetry error logs, runs an 11-step LangGraph agentic workflow (RCA → code fix → quality scoring → patch file → PDF), pauses for a single human approval, then automatically creates the Jira ticket and GitHub PR. Zero config. Pluggable LLM. Multi-tenant. [github.com/u-avinash/prism](https://github.com/u-avinash/prism)

---

## The Problem Every Engineer Knows

It's 2:47 AM. Your phone buzzes. A `NullPointerException` is firing in the order processing service — production, hundreds of users affected. You stare at logs for twenty minutes, find the file, trace the stack, identify the cause. You write a fix. You open a Jira ticket, create a branch, push a PR, ping someone on Slack for a review, and finally go back to sleep around 4:15 AM.

The next morning you realize: almost everything you did last night was mechanical. Find the error. Understand the context. Propose a fix. Document it. Route it through the right channels.

Mechanical processes can be automated. That's the idea behind **Prism**.

---

## What Prism Does

Prism is an autonomous AI incident management platform. It sits as an OTLP/HTTP endpoint between your application and your engineers. When your service emits an error log, Prism:

1. Receives and parses the OTLP log record
2. Deduplicates it using SimHash fingerprinting
3. Classifies severity as LOW / MEDIUM / HIGH / CRITICAL
4. For HIGH and CRITICAL errors — kicks off an 11-step LangGraph agentic workflow that fetches the relevant source file from GitHub, generates an AI-powered Root Cause Analysis, proposes a code fix, scores the fix quality, generates a downloadable patch file and PDF report
5. **Pauses and asks a human to approve**
6. After approval — creates the Jira ticket, commits the fix to a new branch, and opens a GitHub Pull Request

The entire pipeline from error ingestion to PR-ready fix happens autonomously. The human makes exactly one decision: approve or reject.

> **On MTTR:** Engineering teams spend a disproportionate amount of their Mean Time to Resolution (MTTR) on the research phase — finding the root cause and drafting a fix. Prism compresses that phase from 30–60 minutes of manual work to a sub-2-minute automated pipeline, leaving humans to spend their time on the only part that actually requires judgment: *is this fix correct enough to ship?*

---

## Architecture

Prism runs as two FastAPI services:

```
┌─────────────────────────────────────────────────────────┐
│  Your Application  (MuleSoft, Node, Java, Python, etc.) │
└────────────────────────┬────────────────────────────────┘
                         │  OTLP/HTTP  POST /v1/logs
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Ingestion API  :8000                                   │
│  • OTLP parsing                                         │
│  • SimHash deduplication                                │
│  • Severity classification                              │
│  • Writes to SQLite                                     │
│  • Fires background LangGraph workflow                  │
└────────────────────────┬────────────────────────────────┘
                         │  async background task
                         ▼
┌─────────────────────────────────────────────────────────┐
│  LangGraph Workflow                                     │
│  assess → sla → rca → fix → test → pdf → reflect →     │
│  patch → await_approval ⏸️ ── human clicks Approve      │
│                              │                          │
│  notifications → jira+pr → finalize → pir              │
└────────────────────────┬────────────────────────────────┘
                         │  SSE + REST
                         ▼
┌─────────────────────────────────────────────────────────┐
│  Dashboard UI  :8080                                    │
│  • Live workflow progress                               │
│  • Approve / reject with reviewer notes                 │
│  • Download patch / PDF before deciding                 │
│  • Observability: traces, metrics, logs, audit trail    │
└─────────────────────────────────────────────────────────┘
```

**[SCREENSHOT: Incident dashboard — live list with severity badges and workflow status indicators]**

The backbone is a **LangGraph `StateGraph`** — a stateful directed graph that carries an `AgentState` TypedDict through each step. Every piece of data — the raw log, the RCA text, the proposed fix, quality scores, Jira URL, PR number — lives in this shared state object and is persisted to SQLite at each step.

> **Primary target stack:** Prism was originally designed for **MuleSoft / Anypoint Platform** applications, integrating with the Anypoint Runtime Manager API to pull live CloudHub/ARM deployment context into the RCA. It works with any stack that can emit standard OTLP-formatted logs.

---

## The 11-Step Workflow at a Glance

**[SCREENSHOT: Incident detail page — showing the 11-step workflow progress bar with completed steps highlighted]**

Before diving into each step, here's the full picture:

| # | Step | What It Does | Retryable |
|---|------|--------------|-----------|
| 1 | `assess_severity` | LLM + heuristic severity classification | — |
| 2 | `compute_sla` | Sets SLA resolution deadline | — |
| 3 | `generate_rca` | AI Root Cause Analysis with live GitHub code context | ✅ 2× |
| 4 | `generate_fix` | Language-aware code fix + explanation | ✅ 2× |
| 5 | `suggest_test` | Unit test suggestion (non-blocking) | — |
| 6 | `generate_pdf` | RCA PDF report saved to `data/pdfs/` | ✅ 1× |
| 7 | `reflect` | Quality scoring: correctness, safety, code quality, completeness | — |
| 8 | `generate_patch` | Unified `.patch` file saved to `data/patches/` | ✅ 1× |
| 9 | `await_approval` | ⏸️ **Workflow pauses — human reviews and decides** | — |
| 10 | `send_notifications` | Slack/Teams alerts post-approval | — |
| 11 | `create_jira_pr` | Jira ticket + GitHub branch + PR + DevInfo sync | — |
| ✓ | `finalize` | Persists final state, artefact URLs, PIR generation | — |

---

## Step-by-Step Breakdown

### Step 1 — Severity Assessment

The LLM is asked to classify the error as LOW, MEDIUM, HIGH, or CRITICAL based on the raw log and stack trace. A keyword-heuristic fallback ensures the step never fails even if the LLM call times out. Only HIGH and CRITICAL incidents proceed to the full workflow — LOW and MEDIUM are recorded and finalized immediately, preventing alert fatigue.

### Step 2 — SLA Timer

Based on severity, a resolution deadline is set (e.g., 1 hour for CRITICAL, 4 hours for HIGH). This drives the escalation check later in the workflow. If the SLA deadline passes with no resolution, the system escalates automatically.

### Steps 3 & 4 — RCA + Fix Generation

This is the heart of the system.

Prism doesn't just feed the error message to the LLM. It fetches the **actual source file from GitHub** — the file identified in the stack trace, with surrounding line context — and includes it in the prompt. The LLM generates a 400–500 word Root Cause Analysis: what broke, why it broke, and what the downstream impact is. A second LLM call self-scores the RCA confidence.

The fix generation step uses the same code context to produce a concrete, language-aware code change with a plain-English explanation. The LLM knows whether it's working on a Java Spring service, a Python FastAPI app, a MuleSoft DataWeave flow, or a Node.js handler — and adjusts its fix accordingly.

Both steps are wrapped in a retry decorator:

```python
def _make_retryable_node(node_fn, node_name, max_retries=2, retry_delay_seconds=5.0):
    def wrapped(state):
        for attempt in range(1, max_retries + 1):
            result = node_fn(state)
            if not result.get("error_message"):
                return result
            time.sleep(retry_delay_seconds)
        return result  # error_message still set → routes to finalize
    return wrapped
```

If all retries are exhausted, the workflow routes directly to `finalize` with `status=FAILED` — it never hangs or crashes.

**[SCREENSHOT: RCA panel — AI-generated root cause analysis with confidence score and code context references]**

### Step 5 — Test Suggestion

The LLM suggests a unit test that would have caught the bug. This step is deliberately non-blocking — it never fails the pipeline. Engineers can use the suggestion as a starting point when writing regression tests after the fix is merged.

### Step 6 — PDF Report

A PDF is generated using ReportLab and saved to `data/pdfs/`. It contains the full RCA, proposed fix, quality scores, metadata, and a timeline. The reviewer can download this before making an approval decision — useful for compliance documentation or post-incident reviews.

### Step 7 — Reflection / Quality Scoring

A second independent LLM call scores the proposed fix on four dimensions:

| Dimension | What It Measures |
|---|---|
| **Correctness** | Does the fix actually address the root cause? |
| **Safety** | Could the fix introduce regressions or security issues? |
| **Code Quality** | Is the fix idiomatic, clean, and maintainable? |
| **Completeness** | Does it handle edge cases and related paths? |

Each dimension is scored 0–10. The overall score, concerns, and recommendation are shown to the reviewer in the dashboard. This gives the human reviewer a fast signal on whether to inspect closely or approve with confidence.

**[SCREENSHOT: Fix diff view with quality scores panel showing correctness, safety, code quality, and completeness scores]**

### Step 8 — Patch File Generation

A unified `.patch` file is generated and saved to `data/patches/` **before** the approval gate. The reviewer can download it, apply it locally with `git apply`, and run the test suite against it before clicking Approve. This is a deliberate design choice: the reviewer should be able to *test* the fix, not just read it.

### Step 9 — ⏸️ The Human Approval Gate

**This is the most important design decision in Prism.**

The workflow pauses here. No code is committed. No Jira ticket is created. No branch exists. The reviewer has access to:

- The full RCA text
- The proposed fix diff
- Quality scores and concerns
- The downloadable `.patch` file
- The PDF report

Only after the reviewer clicks **Approve** — with optional reviewer notes — does the workflow resume.

**What if the fix is wrong?** The reviewer can **Reject** with written feedback. That feedback is injected directly into the fix-generation prompt, and the system regenerates the fix with the reviewer's context incorporated. This reject-and-regenerate loop can run until the reviewer is satisfied — or escalate the incident manually.

**[SCREENSHOT: Approval gate — Approve / Reject buttons with reviewer notes textarea and quality score summary]**

This design makes Prism a powerful co-pilot, not an autonomous actor. The AI handles the mechanical work; the engineer makes the judgment call.

### Steps 10 & 11 — Notifications, Jira, GitHub PR, Finalize

Post-approval, the workflow resumes from where it paused:

1. **Slack/Teams notifications** go out with a fix summary and deep-link to the incident
2. A **Jira ticket** is created with the patch attached
3. A **GitHub branch** is created, the fixed file is committed, and a **Pull Request** is opened with the AI-generated description
4. The **Jira Development panel** is updated with branch, commit, and PR links via the Jira DevInfo API — so the full traceability chain from incident → code change is visible in Jira
5. A **Post-Incident Review (PIR)** is generated as a comment on the incident record

**[SCREENSHOT: Completed incident — showing Jira ticket link, GitHub PR link, and post-incident review comment]**

---

## Key Engineering Decisions

### SimHash Deduplication — Fighting Alert Fatigue

A production service throwing a `NullPointerException` in a hot code path can generate thousands of identical log records per minute. Without deduplication, you'd have thousands of Jira tickets for one bug.

Prism uses **SimHash fingerprinting** on the error message and stack trace. Incoming errors are compared against recent fingerprints using a configurable similarity threshold (default: 0.85). Near-duplicates are suppressed — recorded in the database, but no new workflow is triggered. A burst detection window (default: 10 minutes, 5 identical errors) adds a second layer of suppression.

### Human-in-the-Loop is Non-Negotiable

AI-generated code fixes are good — but not perfect. The quality scoring step (Step 7) is honest about this: scores below a threshold surface a warning to the reviewer. The patch download (Step 8) means the reviewer can verify the fix works before approving.

The system is designed so that a reviewer who spends 90 seconds reading the RCA, glancing at the quality scores, and skimming the diff can make a confident, informed decision. The AI does the 45-minute research work; the human does the 90-second judgment call.

### Pluggable Multi-Provider LLM

Hard-coding to a single LLM vendor is a strategic risk. Models improve, pricing changes, rate limits bite. Prism supports six providers through a unified `LLMProvider` interface:

| Provider | Use Case |
|---|---|
| OpenAI (GPT-4o) | Default, best general quality |
| Anthropic Claude | Strong at code analysis |
| Azure OpenAI | Enterprise / data residency requirements |
| Google Gemini | Cost-effective at scale |
| Groq | Fast inference for low-latency needs |
| Ollama | Air-gapped / local deployment |

Switching providers is a one-field change in the project's integration settings — no workflow code changes required.

### Per-Project Encrypted Credentials

Prism is multi-tenant. Each project has its own LLM API key, GitHub token, Jira credentials, Slack webhook, and Anypoint credentials. All are stored **AES-encrypted (Fernet)** in SQLite. The master encryption key lives in `data/.integration.key`, auto-generated on first boot. The key can be set explicitly via `INTEGRATION_SECRET_KEY` for multi-process deployments.

This means the platform admin never sees another team's API keys, and a compromised database file without the key file is useless to an attacker.

### Conditional Routing — The Graph is Resilient by Design

The LangGraph graph isn't a simple chain. Every LLM-calling step has a conditional edge that routes to `finalize` on failure:

```python
def route_after_rca(state: AgentState) -> Literal["generate_fix", "finalize"]:
    if state.get("error_message"):
        logger.error("RCA failed after retries — stopping workflow")
        return "finalize"
    return "generate_fix"
```

The routing rules are:
- **Low/Medium severity** → skip straight to `finalize` (no RCA needed)
- **Duplicate incident** → skip entirely
- **RCA failed after 2 retries** → skip fix generation, go to `finalize` with `FAILED` status
- **Fix generation failed** → skip PDF, patch, approval — go straight to `finalize`

The graph always terminates cleanly. There are no hanging workflows, no orphaned states, no partial pipelines.

---

## How It Compares to Existing Tools

| Tool | Gap Prism Addresses |
|---|---|
| PagerDuty / OpsGenie | Alert routing and on-call management — but no AI RCA or code fix generation |
| Datadog / New Relic AIOps | Anomaly detection — but no code fix pipeline or approval workflow |
| GitHub Copilot | Code suggestions in the IDE — but no production signal integration or incident workflow |
| Rootly / Incident.io | Incident workflow coordination — but engineers still write the fix manually |

Prism's differentiator is the **end-to-end pipeline**: from raw production log to a reviewed, approved, committed code change — with no manual research work in between.

---

## Stack

| Layer | Technology |
|---|---|
| Ingestion API | FastAPI + OpenTelemetry |
| Workflow Engine | LangGraph (StateGraph) |
| LLM | OpenAI / Anthropic / Azure / Gemini / Groq / Ollama |
| Database | SQLite + SQLAlchemy |
| Dashboard UI | FastAPI + Jinja2 + Server-Sent Events |
| PDF Generation | ReportLab |
| Error Deduplication | SimHash |
| Credential Encryption | Fernet (AES-128) |
| Integrations | GitHub REST API, Jira REST + DevInfo API, Slack/Teams webhooks, MuleSoft Anypoint |

---

## Try It in 5 Minutes

**Prerequisites:** Python 3.11+

```bash
# Clone and install
git clone https://github.com/u-avinash/prism
cd prism
pip install -r requirements.txt

# Start both servers
uvicorn ingestion.api:app --host 0.0.0.0 --port 8000 --reload &
uvicorn ui.server:app --host 0.0.0.0 --port 8080 --reload
```

Open `http://localhost:8080`, log in (`admin` / `ChangeMe123!`), create a project, and add your LLM API key in the Team Admin settings.

Then send a test error:

```bash
curl -X POST http://localhost:8000/v1/logs \
  -H "Content-Type: application/json" \
  -d '{
    "resourceLogs": [{
      "resource": {"attributes": [
        {"key": "service.name", "value": {"stringValue": "order-service"}},
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

Within 60–120 seconds (depending on your LLM provider's latency) you'll see the 11 steps complete in the dashboard — RCA, proposed fix with quality scores, a downloadable patch file, and a PDF report — all waiting for your single approval click.

---

## What's Next

Prism is functional and production-tested, but there's a lot of interesting ground ahead:

- **Vector similarity search** on historical incidents to surface relevant past fixes during RCA generation
- **Multi-file fix generation** for bugs that require coordinated changes across services
- **Auto-merge paths** for classes of fixes that consistently score above a quality threshold (with explicit opt-in by the team)
- **Richer observability** — correlation of incidents with distributed traces and metrics for deeper root cause context
- **Broader OTLP coverage** — structured trace and metrics processing alongside log-based incident detection

---

## Closing Thoughts

The goal with Prism wasn't to replace engineers — it was to eliminate the mechanical, repeatable parts of incident response so engineers can focus on the judgment calls that actually require human expertise.

The approval gate isn't a limitation of the AI. It's an explicit architectural choice: AI generates, human decides, system executes. That separation of concerns is what makes it safe to run in production.

If you're building something similar or want to extend Prism for your own stack, the full source code is at **[github.com/u-avinash/prism](https://github.com/u-avinash/prism)**. ⭐ Stars, issues, and PRs are very welcome.

---

*— Upadhyayula Avinash*

**Medium tags to add when publishing:** `LangGraph` · `OpenTelemetry` · `AI` · `DevOps` · `Python`
