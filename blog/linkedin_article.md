# I Built an AI System That Responds to Production Incidents Automatically — Here's What I Learned

### *How an 11-step LangGraph agentic workflow goes from a raw error log to a GitHub Pull Request — with one human approval in between*

**By Upadhyayula Avinash**

---

I've been in enough 3am incident calls to recognize the pattern.

Someone gets paged. They open their laptop. They stare at logs for 20 minutes. They find the file, trace the stack, understand the cause. They write a fix. They open a Jira ticket, create a branch, push a PR, ping a colleague for review. They go back to sleep at 4am.

The next morning, with fresh eyes, the uncomfortable truth surfaces: almost everything that happened in those 90 minutes was *mechanical*. Predictable. Repeatable. The kind of work that, in any other domain, we'd have automated years ago.

So I built **Prism** — an autonomous AI incident management platform that handles that mechanical work, and then pauses to ask a human one question: *should we actually ship this fix?*

---

## What Prism Does

Prism connects to your application via OpenTelemetry — the open standard for observability data that most modern stacks now support. When your service emits an error log, Prism catches it, deduplicates it (so one bug doesn't generate 500 Jira tickets), and classifies it by severity.

For serious incidents — HIGH or CRITICAL — it kicks off an 11-step AI workflow:

| # | What Happens |
|---|---|
| 1–2 | Severity classification + SLA deadline set |
| 3 | AI Root Cause Analysis — using the *actual source file* fetched live from GitHub, not just the error message |
| 4 | Language-aware code fix with plain-English explanation |
| 5 | Unit test suggestion that would have caught the bug |
| 6 | PDF report (downloadable before approval — useful for compliance) |
| 7 | Quality scoring: correctness, safety, code quality, completeness (each 0–10) |
| 8 | Unified `.patch` file — downloadable and locally testable before approving |
| 9 | ⏸️ **Workflow pauses — human review and approval** |
| 10–11 | Post-approval: Slack/Teams alert, Jira ticket, GitHub branch + PR, Jira DevInfo sync |

After one approval click, everything in steps 10–11 happens automatically. The full traceability chain — from production error to committed code change — is visible in both the Prism dashboard and the Jira Development panel.

**[SCREENSHOT: The Prism dashboard showing a live incident with the 11-step workflow progress and an AI-generated RCA]**

> **On MTTR:** Most of the Mean Time to Resolution in a typical incident is spent on the research phase — finding the cause and drafting a fix. Prism compresses that from 30–60 minutes of manual work to a sub-2-minute automated pipeline. Engineers spend their time on what actually requires judgment: *is this fix correct enough to ship?*

---

## The Design Decision That Matters Most

Every conversation about AI autonomy eventually hits the same question: *how much do you trust it?*

My answer with Prism is precise: **trust it to do the research, not to make the call.**

Before any code is written to the repository, the workflow pauses. The reviewer sees:

- The full AI-generated Root Cause Analysis
- The proposed code change as a diff
- Quality scores with specific concerns flagged
- A downloadable `.patch` file they can apply locally and test before deciding
- A PDF report for documentation or compliance needs

**What if the fix is wrong?** The reviewer rejects it with written feedback. That feedback gets injected into the fix-generation prompt, and the system regenerates the fix — with the reviewer's context incorporated. This reject-and-regenerate loop continues until the reviewer is satisfied, or they escalate the incident manually.

The AI does the 45-minute research work. The engineer does a 90-second review. That's the right division of labor.

This isn't a technical limitation — it's a deliberate architectural choice. Autonomous code commits without human review introduce a category of risk that no quality score can fully mitigate. The approval gate is load-bearing, and I'm intentional about keeping it that way.

**[SCREENSHOT: Approval gate — Approve / Reject buttons with reviewer notes textarea, quality scores, and downloadable patch link]**

---

## Three Things I Learned Building It

### 1. Agentic workflows need graceful failure paths more than they need success paths

The happy path is easy to design. The hard part is everything else: the LLM times out, the GitHub API rate-limits you, the fix generation fails on retry 2. What happens then?

In Prism, every node that calls an LLM is either *retryable* (automatic retries with exponential delay, up to 2 attempts) or *safe-defaulting* (uses fallback values and never blocks the pipeline). When retries are exhausted, the workflow routes directly to a clean `FAILED` state — no hanging processes, no partial records, no silent corruption.

Building resilience into an AI workflow is the same discipline as building resilience into a distributed system: assume failure, design for it explicitly, and make sure every failure mode produces a clean, visible outcome.

### 2. LLM prompts are code — treat them that way

Prism's prompts live in `config/prompts.yaml`, versioned alongside the application code. The RCA prompt includes the raw log, the full stack trace, the actual source file content fetched from GitHub, and the runtime environment context (CloudHub deployment info for MuleSoft applications). The fix prompt includes all of that plus the RCA output.

The difference between a vague, generic RCA and a precise, actionable one is almost entirely about the quality of context you give the model. Prompt engineering is engineering. Version it, review it, and iterate on it like any other critical system component.

### 3. Human-in-the-loop is a feature, not a constraint

Early in the design I considered making the approval gate optional — a setting that confident teams could disable for low-risk fixes. I'm glad I didn't build it that way.

The approval gate is also where engineers *learn from the system*. They read the RCA, inspect the quality scores, see how the AI reasoned about the fix. That feedback loop — engineer reviewing AI output — builds understanding and trust over time. Teams that skip it are also skipping the part that makes the system's outputs get better.

---

## The Stack and the Enterprise Angle

Prism is built entirely in Python, runs with zero configuration out of the box, and is designed to be self-hostable:

- **FastAPI** for the ingestion API and the real-time dashboard
- **LangGraph** for the stateful agentic workflow
- **SQLite** for persistence (straightforward to migrate to Postgres for scale)
- **Multi-LLM**: OpenAI, Anthropic Claude, Azure OpenAI, Google Gemini, Groq, Ollama
- **Integrations**: GitHub, Jira, Slack, Microsoft Teams, MuleSoft Anypoint Platform

For enterprise teams, the multi-tenant model matters: every project has its own independently encrypted credentials — LLM API keys, GitHub tokens, Jira credentials, Slack webhooks. AES-encrypted (Fernet) at rest, with the master key separate from the database. Platform administrators cannot see other teams' secrets. Teams operate in full isolation.

The platform ships with three roles — Admin, Team Admin, and User — each scoped appropriately. Team Admins configure integrations and manage their team. Admins manage the platform. Users review and approve incidents.

**[SCREENSHOT: The Team Admin integration settings page — LLM provider selection, GitHub/Jira configuration, Slack webhook setup]**

---

## Try It in Under 5 Minutes

```bash
git clone https://github.com/u-avinash/prism
cd prism
pip install -r requirements.txt
uvicorn ingestion.api:app --port 8000 &
uvicorn ui.server:app --port 8080
```

Open `http://localhost:8080`, log in (`admin` / `ChangeMe123!`), create a project, add your LLM API key, and send a test OTLP error log. Within 60–120 seconds you'll see the full 11-step workflow run in real-time — RCA generated, fix proposed, quality scores calculated, patch file ready for download — all waiting for one approval click.

No `.env` file needed. No external services required to get started.

**Requirements:** Python 3.11+

---

## A Final Thought

The teams that will get the most value from AI over the next few years won't be the ones who automate the most decisions. They'll be the ones who identify exactly which decisions *should stay with humans* — and build tooling that makes those human decisions faster, better-informed, and easier to act on.

Prism is my attempt at that for incident response. The AI handles the mechanical 45-minute research job. The engineer handles the 90-second judgment call. That's a trade worth making.

Full source code is open at **[github.com/u-avinash/prism](https://github.com/u-avinash/prism)**.

If you're working on something similar, have built your own AIOps tooling, or have strong opinions about where the human-AI boundary should sit in incident response — I'd genuinely like to hear your perspective. Drop a comment below.

---

*Upadhyayula Avinash — Software Engineer | AI Systems | Platform Engineering*

*GitHub: [github.com/u-avinash/prism](https://github.com/u-avinash/prism)*

*#AI #DevOps #SRE #LangGraph #OpenTelemetry #IncidentManagement #AIOps #Python #SoftwareEngineering #MLOps*
