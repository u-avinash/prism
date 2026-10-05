# PRISM Leadership Review — Demo Video Package

**Target duration:** 4 minutes 30 seconds  
**Audience:** Business and technology leadership  
**Format:** 16:9, 1080p, narrated screen recording  
**Core message:** PRISM connects production telemetry to a reviewable remediation package, while preserving accountable human approval before any downstream engineering action.

---

## 1. Executive opening card

**Time:** 0:00–0:20  
**Visual:** Slide 1 of `Prism_Technical_Architecture.pptx`  
**On-screen action:** Fade in. Keep the title slide static for three seconds, then use a subtle zoom toward the subtitle.

**Narration**

> Production incidents create two simultaneous pressures: restore service quickly and make safe, accountable engineering decisions. PRISM is a governed AI-assisted incident-response platform that brings those needs together. It turns telemetry signals into an evidence package for review—not an autonomous production deployment.

**Caption:** `Governed AI-assisted incident response`

---

## 2. Leadership value proposition

**Time:** 0:20–0:50  
**Visual:** Slide 2, “Compress incident response”  
**On-screen action:** Reveal the four stages from left to right: Ingest, Reason, Govern, Deliver. Pause on the design-principle panel.

**Narration**

> The operating model is straightforward. PRISM ingests OTLP telemetry and creates project-scoped incidents. It uses AI to assess severity, investigate context, and prepare a proposed fix and test recommendation. A reviewer then makes an explicit decision. Only after approval can PRISM create delivery work in the team’s existing systems, such as Jira and GitHub. The central principle is simple: AI prepares the evidence; humans authorize the change.

**Caption:** `AI prepares evidence. Humans authorize change.`

---

## 3. Show the governed workflow

**Time:** 0:50–1:25  
**Visual:** Slide 3, “A governed path from signal to pull request”  
**On-screen action:** Animate/pan across stages 1–5, hold on “Approve,” then pan to delivery.

**Narration**

> The workflow provides a visible path from signal to pull request. PRISM parses, fingerprints, and deduplicates incoming errors; assesses severity; uses available source and runtime context to draft an RCA; and prepares a fix proposal, test idea, PDF report, and downloadable patch. The workflow pauses at the approval stage. This is the control point: no Jira issue or GitHub pull request is created until an accountable reviewer approves the recommendation.

**Caption:** `Approval is the control point`

---

## 4. Live dashboard: incident command

**Time:** 1:25–2:05  
**Visual:** Local PRISM dashboard, **Incidents** page  
**Precondition:** Seed synthetic fixtures only. Never display a live customer incident, production URL, API key, session cookie, integration token, or personally identifiable data.

**On-screen actions**

1. Open `http://localhost:8080/login`.
2. Log in using a pre-prepared **demo-only** account. Avoid recording typed credentials.
3. Open **Incidents**.
4. Select a synthetic **HIGH** or **CRITICAL** incident with a completed pre-approval workflow.
5. Briefly highlight project scope, severity, incident status, and workflow status.

**Narration**

> In the dashboard, responders begin with a project-scoped incident command view. Incoming telemetry is retained alongside derived incidents, while repeated errors are grouped using a fingerprint. This helps teams prioritize material failures instead of repeatedly triaging the same noise. The selected incident shows its severity, operational status, and the progress of its governed workflow.

**Caption:** `Project-scoped visibility and deduplicated incidents`

**Recording note:** Use browser zoom at 110–125% and collapse irrelevant browser chrome so incident status and severity are readable.

---

## 5. Live dashboard: inspect the evidence

**Time:** 2:05–2:55  
**Visual:** Synthetic incident detail page  
**On-screen actions**

1. Scroll to the RCA section; hold for five seconds.
2. Scroll to the proposed fix and test recommendation; hold for five seconds.
3. Show reflection/quality scores and reviewer comments, if present.
4. Show—but do not download—the PDF and patch artifact controls.

**Narration**

> The reviewer does not receive a black-box recommendation. PRISM makes the supporting evidence inspectable: the root-cause analysis, proposed code change, test recommendation, generated PDF report, downloadable patch, and quality reflection are all available before a decision. The goal is to reduce manual investigation effort and make evidence more consistent—not to claim that an AI-generated recommendation is automatically correct.

**Caption:** `Inspectable RCA, fix, tests, patch, and quality evidence`

---

## 6. Live dashboard: approval and downstream action

**Time:** 2:55–3:35  
**Visual:** Approval controls on the same synthetic incident  
**On-screen actions**

1. Focus the **Approve**, **Reject**, and **Regenerate fix** controls.
2. Add a pre-approved reviewer comment such as: `Demo review: evidence checked; route to standard code review.`
3. Do **not** press Approve if the demo environment is configured with real Jira, GitHub, Slack, or Teams credentials.
4. If integrations are safely mocked or disabled, show the approved state only after it has been prepared beforehand.

**Narration**

> At this stage, the reviewer can approve, reject, or request a regenerated fix with feedback. Approval is deliberate and auditable. If approved, PRISM can notify configured team channels and create a Jira issue and GitHub branch and pull request using the project’s configured integrations. PRISM does not deploy a change to production. Existing engineering review and release controls remain in force.

**Caption:** `Explicit approval before Jira or GitHub automation`

---

## 7. Trust and operational controls

**Time:** 3:35–4:05  
**Visual:** Slide 6, “Trust by design”  
**On-screen action:** Highlight each control in sequence.

**Narration**

> The platform’s controls are designed into the operating model. Production ingestion uses a project API key so tenant ownership is established by authenticated intake rather than untrusted log metadata. Access is project-scoped by role. Integration credentials are encrypted at rest. Workflow and approval records provide durable operational evidence, and authorized administrators can run audited recovery for incomplete post-approval work without regenerating the analysis or bypassing the approval decision.

**Caption:** `Secure intake • scoped access • encrypted secrets • audit evidence`

---

## 8. Current foundation and roadmap

**Time:** 4:05–4:20  
**Visual:** Slide 9, “Current foundation, next evolution”  
**On-screen action:** Show both columns; subtly emphasize “Evolution path.”

**Narration**

> PRISM is a practical single-instance foundation today, with FastAPI services, persistent incident evidence, and provider resilience. As adoption grows, the planned evolution is clear: PostgreSQL and a worker model for scale, repeatable container delivery, telemetry correlation for traces and metrics, and enterprise perimeter capabilities such as TLS gateways and SSO.

**Caption:** `Deployable foundation with a deliberate enterprise path`

---

## 9. Closing card

**Time:** 4:20–4:30  
**Visual:** Slide 10, “A faster path to responsible remediation”  
**On-screen action:** Hold static for the final ten seconds.

**Narration**

> PRISM creates a faster path to responsible remediation: from signal, to reason, to approval, to delivery—while keeping human accountability at the center.

**Caption:** `Signal → Reason → Approve → Deliver`

---

# Recording runbook

## A. Prepare a safe local demo

1. Use the local synthetic fixtures described in the repository README:

   ```bat
   py -3.14 scripts\seed_postman_data.py --reset
   ```

   This resets **local runtime** data only. Do not run it against any shared or production environment.

2. Start the services:

   ```bat
   restart_prism_app.bat
   ```

3. Verify the dashboard is reachable at `http://localhost:8080`.

4. Use a synthetic incident that is already in the desired review state. If the workflow needs external LLM, Jira, or GitHub credentials, do not record the creation process. Record the prepared synthetic incident and state clearly that external delivery occurs only after approval and configured integration validation.

5. Hide browser bookmarks, notifications, terminal windows, usernames, project keys, URLs outside localhost, and any external-system tokens.

## B. Recommended shot order

| Shot | Asset | Time | Purpose |
|---|---|---:|---|
| 1 | Deck slide 1 | 0:00–0:20 | Establish PRISM and the governance promise |
| 2 | Deck slide 2 | 0:20–0:50 | Frame value and operating model |
| 3 | Deck slide 3 | 0:50–1:25 | Explain the workflow and approval gate |
| 4 | Dashboard incident list | 1:25–2:05 | Demonstrate operational visibility |
| 5 | Incident detail | 2:05–2:55 | Demonstrate inspectable evidence |
| 6 | Approval controls | 2:55–3:35 | Demonstrate controlled delivery |
| 7 | Deck slide 6 | 3:35–4:05 | Reassure on security and auditability |
| 8 | Deck slide 9 | 4:05–4:20 | Present foundation and roadmap candidly |
| 9 | Deck slide 10 | 4:20–4:30 | Finish with the leadership outcome |

## C. PowerPoint recording and export (Windows)

1. Open `presentation/Prism_Technical_Architecture.pptx` in Microsoft PowerPoint.
2. Select **Record** → **From Beginning**.
3. Record narration for slides 1–3, 6, 9, and 10 using the timing above. Leave the live-dashboard sections as short placeholder slides or insert the recorded dashboard clip after capture.
4. Record dashboard clips with **Snipping Tool** → **Record**, or a corporate-approved screen recorder, at **1920 × 1080** and 30 frames per second.
5. Insert dashboard clips in PowerPoint using **Insert** → **Video** → **This Device**, set each to start **Automatically**, and trim to the stated shot duration.
6. Select **File** → **Export** → **Create a Video**:
   - Resolution: **Full HD (1080p)**
   - Timing: **Use Recorded Timings and Narrations**
   - Format: **MPEG-4 Video (.mp4)**
7. Save as `presentation/PRISM_Leadership_Demo_Review.mp4`.

## D. Final review checklist

- [ ] Runtime is limited to 4:15–4:45.
- [ ] All content is synthetic, local, and approved for sharing.
- [ ] No secrets, access tokens, API keys, passwords, customer data, browser tabs, or notifications are visible.
- [ ] The approval gate is stated twice: before workflow delivery and during live controls.
- [ ] The video does not claim autonomous production deployment, guaranteed MTTR reduction, or unimplemented trace/metric correlation.
- [ ] The current single-instance foundation and scale-out roadmap are presented transparently.
- [ ] Captions are included using `presentation/PRISM_Leadership_Demo_Review.srt`.
- [ ] The exported MP4 plays from start to finish with readable text and clear audio.
