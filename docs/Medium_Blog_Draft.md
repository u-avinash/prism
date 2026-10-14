# From Telemetry to a Human-Approved Pull Request: Building Prism

Production incidents rarely fail because teams lack tools. They fail because the work between a raw error and a safe remediation is fragmented: logs live in one place, source context in another, tickets in another, and the final decision depends on someone stitching the evidence together under pressure.

That is the problem Prism was designed to solve.

## The design principle: automate evidence, not accountability

Prism is intentionally not a 'ship code automatically' system. Its workflow is built around a practical boundary:

1. **Automation** receives a telemetry signal, removes noise, identifies context, and prepares an investigation.
2. **AI assistance** creates an RCA, a proposed remediation, a quality review, a PDF report, and a unified patch.
3. **A human reviewer** decides whether the recommendation is acceptable.
4. **Post-approval automation** sends notifications and creates the configured delivery artifacts.

This preserves accountability while removing repetitive coordination work.

## What happens when an error arrives?

An application sends OTLP logs to Prism's FastAPI ingestion service, usually through an OpenTelemetry Collector. Prism parses the record, detects technology context (MuleSoft, Java, Python, Node.js, .NET, Go, and more), fingerprints duplicate errors, classifies severity, and persists the resulting operational record.

For HIGH and CRITICAL incidents, Prism starts an 11-step LangGraph workflow: severity assessment, RCA generation with code context, fix generation, PDF creation, quality reflection, patch generation, human approval pause, notifications, Jira ticket, GitHub PR, and finalization.

## A verified local example

A local Prism record, `NTTD6XI2`, demonstrates the full path. A CRITICAL MuleSoft production error in `order-processing-service`: DataWeave attempted to coerce a missing `orderDate` value to a Date. Prism recorded an RCA confidence of 87.5%, generated a patch with null-safe handling, captured human approval, and successfully completed the post-approval workflow. The local record references Jira `SCRUM-12` and GitHub PR #61.

The value is not 'AI generated text.' It is a connected, reviewable operational trail: signal, reasoning, suggested remediation, approval, and delivery artifacts.

## Architecture in plain English

- **Signal intake:** FastAPI receives OpenTelemetry logs.
- **Workflow intelligence:** LangGraph coordinates analysis, generation, review, and recovery.
- **Operations console:** FastAPI/Jinja2 dashboard with SSE live updates and approval controls.
- **Trusted project data:** SQLite/SQLAlchemy preserves project-scoped incidents, telemetry, workflow history, and audit evidence.
- **Integration adapters:** LLM, GitHub, Jira, Slack/Teams, and MuleSoft Anypoint, configured per project.

The stack is deliberately pragmatic: Python, FastAPI, LangGraph/LangChain, OpenTelemetry, SQLite/SQLAlchemy, Server-Sent Events, and provider adapters. LLM providers are interchangeable: OpenAI, Anthropic, Azure OpenAI, Google Gemini, Groq, or local Ollama.

## Governance is a feature, not an afterthought

Prism applies project scoping and role separation. Integration configuration is encrypted per project. In production, authentication and tenant assignment are designed to fail closed. Workflow history records runs and node-level operational events so recovery is governed and explainable.

## What Prism does not claim to do

Prism persists telemetry logs and derived incidents. OTLP trace and metrics endpoints validate and acknowledge payloads, but raw traces and metrics are not yet persisted or rendered. External GitHub, Jira, Slack, Teams, Anypoint, and LLM actions require real project configuration.

## Closing thought

The useful future of incident automation is not a black box that acts alone. It is a transparent operational assistant that makes evidence easier to assemble, decisions easier to review, and delivery easier to coordinate. That is the role Prism is designed to play.
