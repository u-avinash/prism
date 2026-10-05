# PRISM Leadership Review Summary

**PRISM** is an AI-assisted incident-management platform that turns production error telemetry into a structured, governed engineering response. It accepts OpenTelemetry (OTLP) logs from MuleSoft/Anypoint applications and other OTLP-compatible services, persists operational telemetry, deduplicates repeated errors, classifies severity, and creates project-scoped incident records for investigation.

For incidents that meet the configured severity threshold, PRISM runs a stateful LangGraph workflow. The workflow assesses severity; produces an AI-assisted root-cause analysis using available GitHub code and MuleSoft runtime context; proposes a code fix and test suggestion; generates an RCA PDF and downloadable patch; and reflects on correctness, safety, code quality, and completeness. This creates a consistent evidence package before a team decides how to act.

## Governed remediation—not autonomous deployment

PRISM deliberately pauses before any downstream delivery action. Reviewers can inspect the RCA, proposed fix, generated patch, PDF report, quality scores, and comments; approve or reject the recommendation; or request a regenerated fix with reviewer feedback.

**Jira issue creation and GitHub branch/pull-request creation occur only after explicit approval.** PRISM does not deploy changes to production. It accelerates investigation and remediation preparation while retaining accountable human review and existing code-review controls.

After approval, PRISM can notify configured Slack or Microsoft Teams channels, create a Jira issue with the patch attached, and create a GitHub branch, commit, and pull request. These integrations are configured per project, allowing teams to use their established delivery toolchain.

## Enterprise control improvements

The current platform includes controls that make the ingestion and workflow boundary more operationally defensible:

- **Project ingestion API keys:** Production ingestion requires `Authorization: Bearer <project API key>`. A valid key resolves and persists the incident owner directly, rather than relying on log metadata to assign a tenant.
- **Fail-closed production profile:** Production configuration requires explicit ingestion origins and rejects insecure authentication, unassigned-ingestion, secure-cookie, and CSRF overrides.
- **Least-privilege project access:** Admin, Team Admin, and User roles operate within project-scoped data and configuration boundaries.
- **Encrypted integration configuration:** LLM, GitHub, Jira, notification, and Anypoint secrets are encrypted at rest. Ingestion-key values are returned only once at issuance; lifecycle records retain redacted metadata.
- **Operational auditability:** Durable workflow-run records and bounded node-event histories distinguish active, failed, retrying, and completed work without storing prompts, raw source, generated fixes, or credentials in operational event records.
- **Controlled recovery:** Admins and Team Admins can initiate an audited, reasoned recovery of incomplete approved post-approval work. Recovery honors the execution lease and never re-runs the RCA, fix-generation, or approval decision.

## Operational view

The Dashboard provides project-scoped incident and telemetry views, workflow progress, root-cause and fix artifacts, comments, approval decisions, workflow reliability summaries, security-audit evidence, and ingestion-key lifecycle management. It also includes trace and metric pages that clearly state the current support boundary: OTLP traces and metrics are validated and acknowledged, but they are not yet persisted, correlated, or rendered as live data.

## Leadership perspective

PRISM’s practical innovation is its connection of observability signals, AI-assisted diagnosis and remediation drafting, human approval, and engineering-system integration in a single governed workflow. Its intended value is reduced manual incident-response effort and more consistent evidence—not an unverified claim of a particular MTTR or cost reduction.

For production adoption, leadership should ensure deployment behind trusted TLS infrastructure, managed collector or gateway delivery with per-project key injection, durable management of the integration encryption key, and a planned path from the single-instance SQLite deployment model when scale or availability requirements demand it.

## PRISM Capability and Functioning Diagram

**Presentation-ready graphical version:** [Open the PRISM architecture diagram](prism_capability_architecture.svg)

![PRISM graphical capability and functioning architecture](prism_capability_architecture.svg)
