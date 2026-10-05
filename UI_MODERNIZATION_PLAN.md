# PRISM UI Modernization Plan

## 1. Current State Assessment

PRISM's UI (`ui/templates/*.html`, `ui/static/app.css`, `ui/static/components.css`, `ui/static/app.js`) is a server-rendered Jinja2 app with:

- **Styling**: Hand-rolled CSS (no framework), custom design tokens (`--prism-*`, `--gray-*`, spacing/shadow scale), ~1000+ lines across `app.css` + `components.css`. Reasonably consistent (sidebar, topbar, cards, badges, tables, modals, toasts) but entirely flat/light-mode, no dark mode, no CSS architecture (BEM/utility split is informal), heavy use of inline hex colors mixed with CSS vars (inconsistent token usage).
- **JS**: Vanilla IIFE (`app.js`), ~450 lines. Handles tabs, toasts, modals, polling, SSE, approval actions. No bundler, no component model, no state management — all DOM query/mutate per page. Functional but will not scale cleanly as more interactivity (live incident streams, charts, filters) is added.
- **Templates**: Server-rendered Jinja2, page-specific markup duplicated across `incidents.html`, `incident_detail.html`, `dashboard.html`, admin/team pages, etc. Good semantic structure already (cards, stat grids, timelines, workflow steps) — this is a strong foundation to build on rather than throw away.
- **No build pipeline**: raw CSS/JS served directly by `ui/server.py` (FastAPI/Starlette-style). No minification, no tree-shaking, no asset hashing/cache-busting.
- **Accessibility**: Already has `:focus-visible`, skip-link, `aria-live` toasts, reduced-motion media query — above-average baseline that should be preserved and extended, not regressed.
- **Responsiveness**: Already has breakpoints (1200/1100/1024/900/768/640/480) — mobile sidebar collapse exists. Decent but visually dated (light gray flat backgrounds, boxy cards, no depth/motion language).

**Verdict**: The underlying structure (design tokens, component classes, semantic sections) is solid. A full rip-and-replace (e.g., React SPA rewrite) would be high-risk/high-cost for a server-rendered incident-management console. The highest-leverage modernization is a **design-system refresh + light interactivity layer upgrade**, not a framework migration.

## 2. Goals

1. Give PRISM a modern, premium visual identity (depth, motion, better typography/color, dark mode) befitting an "AI incident management" product.
2. Improve perceived performance and polish of interactions (skeletons, micro-animations, live updates) without introducing a heavy SPA framework or breaking the existing server-rendered architecture.
3. Keep accessibility and responsiveness at or above current level.
4. Introduce a lightweight, modern build step so CSS/JS scale without becoming unmaintainable.
5. Ship incrementally (page-by-page) so there's no "big bang" rewrite risk.

## 3. Recommended Technology Choices

| Layer | Choice | Why |
|---|---|---|
| CSS | **Tailwind CSS v4** (via CLI, no Node framework needed) layered on top of existing design tokens, OR keep custom CSS but modernize tokens + adopt **CSS native nesting/`@layer`/`color-mix()`** | Tailwind v4 is zero-config, fast (Rust engine), works great with server-rendered Jinja templates, and lets us delete most of the current hand-written utility classes (`.flex`, `.gap-2`, `.mt-2`, etc. already resemble Tailwind-lite). If avoiding a new dependency is preferred, we modernize the hand-written system instead (details in §4). |
| Design tokens | Expand `:root` tokens to include dark-mode variants via `[data-theme="dark"]`, add elevation/surface tokens, motion tokens (`--ease-out`, `--duration-fast`) | Matches current approach, minimal risk, enables dark mode cleanly |
| Icons | Replace emoji icons (⚡✓✕ℹ) with **Lucide** or **Heroicons** (inline SVG, no icon-font dependency) | Crisper, scalable, theme-able via `currentColor`, no emoji rendering inconsistency across OS |
| Fonts | Keep **Inter** for UI text; add **JetBrains Mono** or **IBM Plex Mono** for code/diff blocks (currently generic `ui-monospace`) | Sharper code readability, modern feel |
| JS interactivity | Introduce **Alpine.js** (CDN, ~15KB, no build step) for declarative reactive bits (dropdowns, tabs, live filters) while keeping `app.js` for cross-cutting concerns (toasts, polling, SSE) | Avoids a full SPA rewrite; Alpine works beautifully with server-rendered HTML and reduces hand-written DOM-query JS |
| Charts | **Chart.js** (via CDN) for dashboard/metrics/analytics pages | Lightweight, no build step, modern animated charts for incident trend/severity visualizations |
| Build tooling (optional, if going Tailwind route) | **Tailwind CLI** + a simple `npm run build:css` script, output committed or built in CI | No Node runtime needed in production; FastAPI still just serves static files |
| Animation | **View Transitions API** (`document.startViewTransition`) for page nav where supported, CSS `@starting-style`/`transition-behavior: allow-discrete` for popovers/modals | Native, zero-dependency, modern "fade/slide" feel without a JS animation library |

> No framework migration (React/Vue/Svelte) is recommended — the app is server-rendered and incident-ops tooling benefits from simplicity/reliability over SPA complexity. Alpine.js + Tailwind gets 90% of the "modern app" feel with ~5% of the risk/cost of a rewrite.

## 4. Visual Design Direction

- **Color**: Move from flat `#eef0f5` background to a subtle layered surface system — e.g., `--surface-0` (page bg), `--surface-1` (card bg), `--surface-2` (elevated/hover) with soft gradients and `backdrop-filter: blur()` for topbar/sidebar glassmorphism accents.
- **Dark mode**: First-class `data-theme="dark"` toggle in topbar (persisted via `localStorage`), remapping all `--gray-*` tokens to a dark neutral scale (slate-900 → slate-50 inverted) and adjusting severity colors for sufficient contrast on dark backgrounds.
- **Depth & elevation**: Replace single flat `--shadow-sm/md/lg` with a more refined elevation scale, add subtle `border` + `shadow` combos on hover for cards/stat-cards (already partially present — extend consistently to all card types).
- **Typography**: Tighten the type scale, increase hierarchy contrast (bigger page titles, better letter-spacing on labels), ensure `clamp()`-based responsive font sizes for hero sections (`incident-detail-hero__title` etc.).
- **Severity/status visuals**: Keep existing semantic color system (critical/high/medium/low/info) — it's good — but add soft glow/pulse animation on `badge-critical`/`status-dot--online` for live/urgent states, and a subtle `severity-bar` gradient instead of flat fill.
- **Motion**: Add consistent transition tokens (150–200ms ease-out) for hover/focus states already defined, extend to: card hover lift (already on `.stat-card`, extend to `.card`, `.incident-row--card`), modal open/close with scale+fade, toast slide-in refinement, skeleton shimmer refinement, sidebar nav active-indicator slide (animated pill behind active link).
- **Empty/loading states**: Modernize `.empty-state`, `.skeleton` with on-brand illustrations/icons instead of plain opacity-dimmed icons.
- **Sidebar/topbar**: Add glass blur + gradient border accent, animated active-nav indicator, user menu as a proper dropdown (Alpine-powered) instead of static.

## 5. Phased Implementation Plan

### Phase 0 — Foundation (no visual change yet, de-risks everything after)
- [ ] Audit & consolidate `app.css` + `components.css` token usage (remove duplicate/unused tokens, fix inconsistent hardcoded hex vs var usage)
- [ ] Decide: Tailwind-assisted vs. pure hand-rolled modernization (recommend Tailwind CLI, no framework)
- [ ] Set up build step (`package.json` + Tailwind CLI) if chosen; otherwise expand `:root` tokens directly
- [ ] Add Alpine.js + Chart.js via CDN `<script>` tags in `base.html`

### Phase 1 — Design System & Dark Mode
- [ ] New token set: surfaces, elevation, motion durations, dark-mode palette
- [ ] Theme toggle button in topbar + `localStorage` persistence + `prefers-color-scheme` default
- [ ] Replace emoji icons with inline SVG icon set (Lucide) across templates
- [ ] Modernize buttons/badges/forms components with new tokens (keep class names stable to avoid template churn)

### Phase 2 — Shell (Sidebar + Topbar)
- [ ] Glassmorphism topbar/sidebar with blur + gradient border
- [ ] Animated active-nav pill indicator (Alpine or pure CSS `:has()`)
- [ ] Modernized user menu dropdown (avatar, role, logout) as proper popover
- [ ] Mobile sidebar transition polish

### Phase 3 — Dashboard & Metrics
- [ ] Replace static stat cards with animated count-up + trend sparklines (Chart.js)
- [ ] Add incident trend / severity distribution charts to `dashboard.html`, `metrics.html`, `api_analytics.html`
- [ ] Modern empty/loading skeleton states

### Phase 4 — Incidents List & Detail (highest-traffic pages)
- [ ] Modernize incident table/card rows with severity glow, hover-lift, inline quick actions
- [ ] Replace native `confirm()`/`alert()` dialogs with themed modal components
- [ ] Add live-updating badge counts via existing SSE/polling hooked into Alpine state
- [ ] Rebuild incident detail hero, timeline, and workflow-step visuals with new elevation/motion tokens
- [ ] Add animated RCA/patch diff viewer polish (syntax highlighting via a lightweight CDN lib, e.g. highlight.js)

### Phase 5 — Admin, Settings & Observability Pages
- [ ] Apply new design tokens/components to admin dashboard, teams, customers, projects, onboarding pages
- [ ] Modernize `log_viewer.html` output panel (sticky toolbar, level filter chips, improved scrollbar)
- [ ] Refresh `observability.html`/`metrics.html` charts with Chart.js, consistent legend/tooltip styling
- [ ] Polish `settings.html` and `login.html` forms with new input/focus states

### Phase 6 — Final Polish & QA
- [ ] Cross-browser/responsive pass (mobile sidebar, tables, modals)
- [ ] Accessibility re-audit (contrast in dark mode, focus order, reduced-motion compliance)
- [ ] Performance check (CSS/JS payload size, no layout thrash from animations)
- [ ] Remove any dead/duplicate CSS left over from the old flat design

## 6. Risk Mitigation

- **No backend changes required** — this is purely `ui/static/*` and `ui/templates/*`; FastAPI routes/data contracts stay untouched.
- **Incremental rollout** — each phase/page can ship independently behind no feature flag since it's a visual-only change; rollback is a simple git revert of the affected template/CSS file.
- **CDN-based additions (Alpine.js, Chart.js, Lucide, highlight.js)** avoid introducing a Node build dependency into the deployment pipeline — scripts are `<script defer src="...">` tags in `base.html`, matching the current no-bundler approach.
- **Existing accessibility baseline is preserved**, not discarded — skip-link, `:focus-visible`, `aria-live`, and reduced-motion handling are extended to new components rather than replaced.

## 7. Suggested Execution Order (first implementation session)

1. Phase 0 foundation + Phase 1 dark mode/token system (`app.css` token expansion, theme toggle, Lucide icon swap in `base.html`).
2. Phase 2 shell polish (sidebar/topbar glassmorphism, nav indicator, user menu).
3. Phase 3 dashboard charts/animated stats.
4. Phase 4 incidents list/detail modernization (highest user-facing impact).
5. Phase 5 remaining admin/settings/observability pages.
6. Phase 6 QA pass.

This plan can be executed sequentially in ACT MODE, page-by-page, with each phase validated (visual check via browser + no Python/template errors) before moving to the next.
