"""Visual asset generation for the Prism documentation pack."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

NAVY = "#0B1020"
PANEL = "#151C2C"
PURPLE = "#7C5CFC"
CYAN = "#14B8A6"
AMBER = "#F2B84B"
WHITE = "#F4F7FF"
MUTED = "#A7B0C5"


def _font(size, bold=False):
    try:
        return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _box(draw, xy, title, lines, color=PURPLE, title_size=25, line_size=17):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=20, fill=PANEL, outline=color, width=3)
    draw.text((x1 + 22, y1 + 18), title, font=_font(title_size, True), fill=WHITE)
    y = y1 + title_size + 32
    for line in lines:
        draw.text((x1 + 22, y), line, font=_font(line_size), fill=MUTED)
        y += line_size + 8


def _arrow(draw, start, end, color=PURPLE, width=5):
    draw.line([start, end], fill=color, width=width)
    x, y = end
    draw.polygon([(x, y), (x - 14, y - 8), (x - 14, y + 8)], fill=color)


def _wrap(draw, text, max_width, fnt):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=fnt) > max_width and line:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def create_architecture(assets: Path) -> Path:
    img = Image.new("RGB", (1800, 1120), NAVY)
    d = ImageDraw.Draw(img)
    d.text((70, 42), "Prism | High-Level Architecture", font=_font(44, True), fill=WHITE)
    d.text((70, 98), "From telemetry signal to human-approved remediation", font=_font(23), fill=MUTED)
    _box(d, (75, 215, 385, 430), "1. Signal Sources", ["MuleSoft / Anypoint", "Applications & CI/CD", "OTLP logs, traces, metrics"], CYAN)
    _box(d, (500, 215, 855, 430), "2. Intake & Intelligence", ["FastAPI ingestion API", "OTLP parser + tech detection", "Deduplication + severity"], PURPLE)
    _box(d, (970, 175, 1380, 470), "3. Agent Workflow", ["LangGraph state machine", "RCA -> fix -> quality review", "PDF + unified patch", "Human approval checkpoint"], PURPLE)
    _box(d, (1475, 215, 1735, 430), "4. Outcomes", ["Jira issue", "GitHub PR", "Slack / Teams alert"], CYAN)
    _arrow(d, (385, 322), (500, 322), CYAN)
    _arrow(d, (855, 322), (970, 322), PURPLE)
    _arrow(d, (1380, 322), (1475, 322), CYAN)
    _box(d, (250, 670, 690, 915), "Operations Console", ["FastAPI + Jinja2 dashboard", "Live progress via SSE", "Incident review, approval, audit", "Admin / Team Admin / User roles"], PURPLE)
    _box(d, (900, 670, 1365, 915), "Trusted Project Data", ["SQLite + SQLAlchemy", "Incident & telemetry records", "Workflow history + audit events", "Encrypted integration configuration"], CYAN)
    _arrow(d, (1110, 470), (1110, 670), PURPLE)
    _arrow(d, (690, 792), (900, 792), PURPLE)
    d.text((75, 1040), "Boundary: source code and credentials are protected; only durable operational evidence is retained for workflow history.", font=_font(19), fill=MUTED)
    out = assets / "01_prism_architecture.png"
    img.save(out)
    return out


def create_workflow(assets: Path) -> Path:
    steps = [
        ("Receive", "OTLP log enters Prism"),
        ("Understand", "Parse, detect stack, dedupe, set severity"),
        ("Analyze", "AI produces RCA with confidence score"),
        ("Recommend", "AI proposes a fix and runs quality review"),
        ("Review", "Human examines RCA, patch, recommendation"),
        ("Deliver", "Approved work notifies, files Jira, opens PR"),
    ]
    img = Image.new("RGB", (1800, 620), NAVY)
    d = ImageDraw.Draw(img)
    d.text((65, 35), "Prism Incident Journey", font=_font(40, True), fill=WHITE)
    d.text((65, 88), "Automation accelerates investigation; people retain the release decision.", font=_font(21), fill=MUTED)
    x = 70
    for i, (title, text) in enumerate(steps, 1):
        w = 250
        outline = PURPLE if i != 5 else CYAN
        d.rounded_rectangle((x, 190, x + w, 470), radius=20, fill=PANEL, outline=outline, width=3)
        d.ellipse((x + 20, 215, x + 64, 259), fill=outline)
        d.text((x + 35, 223), str(i), font=_font(20, True), fill=WHITE)
        d.text((x + 20, 290), title, font=_font(25, True), fill=WHITE)
        y = 335
        for line in _wrap(d, text, w - 40, _font(17)):
            d.text((x + 20, y), line, font=_font(17), fill=MUTED)
            y += 25
        if i < len(steps):
            _arrow(d, (x + w, 330), (x + w + 45, 330), PURPLE)
        x += 295
    out = assets / "02_incident_journey.png"
    img.save(out)
    return out


def create_incident_timeline(assets: Path, record: dict, events: list[tuple]) -> Path:
    img = Image.new("RGB", (1800, 980), NAVY)
    d = ImageDraw.Draw(img)
    d.text((60, 40), "Verified local incident workflow | NTTD6XI2", font=_font(38, True), fill=WHITE)
    d.text((60, 95), "Local demonstration data. External URLs are referenced as recorded by Prism; no external pages are reproduced.", font=_font(18), fill=MUTED)
    d.text((70, 175), f"{record['severity']}  |  {record['app_name']}  |  {record['environment']}  |  Status: {record['status']}", font=_font(25, True), fill=CYAN)
    y = 280
    for name, typ, attempt, message, seconds, timestamp in events:
        dot = CYAN if typ == "succeeded" else PURPLE
        d.ellipse((85, y, 115, y + 30), fill=dot)
        d.line((100, y + 30, 100, y + 94), fill="#39445E", width=3)
        d.text((150, y - 2), f"{timestamp}  |  {name.replace('_', ' ').title()}  |  {typ.title()} (attempt {attempt})", font=_font(21, True), fill=WHITE)
        detail = f"Duration: {seconds if seconds is not None else 'not recorded'} seconds"
        if message:
            detail += f"  |  {message[:110]}"
        d.text((150, y + 33), detail, font=_font(17), fill=MUTED)
        y += 92
    d.text((150, y + 10), "Human approval recorded -> post-approval workflow succeeded -> Jira SCRUM-12 and GitHub PR #61 recorded.", font=_font(20, True), fill=WHITE)
    out = assets / "03_verified_incident_timeline.png"
    img.save(out)
    return out


def create_roles_diagram(assets: Path) -> Path:
    img = Image.new("RGB", (1800, 560), NAVY)
    d = ImageDraw.Draw(img)
    d.text((70, 35), "Prism Role & Project Model", font=_font(38, True), fill=WHITE)
    d.text((70, 88), "Every incident and credential is scoped to a project", font=_font(19), fill=MUTED)
    _box(d, (90, 170, 560, 400), "Admin", ["Create / delete projects", "Assign Team Admins", "Platform-wide user management"], CYAN)
    _box(d, (660, 170, 1130, 400), "Team Admin", ["Configure integrations per project", "Manage team users & access", "Issue / revoke ingestion keys"], PURPLE)
    _box(d, (1230, 170, 1710, 400), "User", ["View & triage incidents", "Approve / reject proposed fixes", "Add review comments"], CYAN)
    _arrow(d, (560, 285), (660, 285), MUTED)
    _arrow(d, (1130, 285), (1230, 285), MUTED)
    out = assets / "04_role_model.png"
    img.save(out)
    return out


def create_tech_stack(assets: Path) -> Path:
    groups = [
        ("Core Services", ["Python 3.11+", "FastAPI", "Uvicorn"], CYAN),
        ("Agent Orchestration", ["LangGraph", "LangChain"], PURPLE),
        ("Data & Persistence", ["SQLite", "SQLAlchemy"], CYAN),
        ("Experience Layer", ["Jinja2", "JavaScript", "Server-Sent Events"], PURPLE),
        ("Telemetry", ["OpenTelemetry OTLP/HTTP", "OTel Collector"], CYAN),
        ("AI Providers", ["OpenAI", "Anthropic", "Azure OpenAI", "Gemini", "Groq", "Ollama"], PURPLE),
        ("Delivery Integrations", ["GitHub REST", "Jira REST/DevInfo", "Slack/Teams", "Anypoint"], CYAN),
        ("Resilience & Security", ["ReportLab/PyPDF", "Tenacity retries", "Fernet encryption"], PURPLE),
    ]
    cols, rows = 4, 2
    cw, ch, gap = 420, 260, 30
    img = Image.new("RGB", (cols * cw + gap, rows * ch + 170), NAVY)
    d = ImageDraw.Draw(img)
    d.text((30, 30), "Prism Technology Stack", font=_font(38, True), fill=WHITE)
    d.text((30, 82), "A pragmatic, swappable stack centered on Python and FastAPI", font=_font(18), fill=MUTED)
    for idx, (title, items, color) in enumerate(groups):
        r, c = divmod(idx, cols)
        x = 15 + c * (cw) + (c * 10)
        y = 140 + r * (ch + gap)
        _box(d, (x, y, x + cw - 20, y + ch - 20), title, items, color, title_size=21, line_size=16)
    out = assets / "05_technology_stack.png"
    img.save(out)
    return out


def create_security_diagram(assets: Path) -> Path:
    img = Image.new("RGB", (1800, 640), NAVY)
    d = ImageDraw.Draw(img)
    d.text((70, 35), "Security, Governance & Reliability", font=_font(38, True), fill=WHITE)
    d.text((70, 88), "Fail-closed defaults protect production deployments by design", font=_font(19), fill=MUTED)
    _box(d, (70, 170, 540, 420), "Tenant Isolation", ["Project-scoped incidents & telemetry", "Per-project encrypted credentials", "Duplicate detection scoped per project"], CYAN)
    _box(d, (610, 170, 1080, 420), "Access Control", ["Admin / Team Admin / User roles", "Scoped ingestion API keys", "Audited privileged recovery actions"], PURPLE)
    _box(d, (1150, 170, 1730, 420), "Production Posture", ["Auth required, CSRF enabled", "Secure cookies, explicit CORS", "Fails closed on insecure overrides"], CYAN)
    d.text((70, 470), "Every workflow run and node-level event is retained as durable, bounded operational evidence --", font=_font(19), fill=WHITE)
    d.text((70, 505), "enough to diagnose and recover safely, without storing prompts, telemetry bodies, source code, or secrets.", font=_font(19), fill=MUTED)
    out = assets / "06_security_governance.png"
    img.save(out)
    return out
