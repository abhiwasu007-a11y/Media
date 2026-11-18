# ADR-004 — Dashboard stack: server-rendered FastAPI + HTMX-type UI for Tier 0; Next.js + TypeScript only if the client portal needs it

| Field | Value |
|---|---|
| Status | **Draft - documentation**. Proposed decision below; the owner approves. Software: **Planned** |
| Owner agent / service | S8 Command Center (service S8, specified in 16_COMMAND_CENTER.md); backend `apps/api`, UI `apps/dashboard` (SOURCE_LAYOUT.md). Decider: owner (Abhi) |
| Depends on | 16_COMMAND_CENTER.md (§2 scope per phase, §3 architecture table "Stack" and "Live updates", §8 bundle download, §15 S8-Q2 and S8-Q6); 27_ENGINEERING_STANDARDS.md §1 (language table, Dashboard row); 05_RESOURCE_MANAGEMENT.md (LIGHT services, slices, RAM unknown until measured); 08_SECURITY.md §5.5 (HttpOnly session cookie, CSRF, model-produced text escaped); 00b_TECHNICAL_FEASIBILITY.md (API + dashboard row); 00_EXECUTION_PLAN.md (Q7, Q15); SOURCE_LAYOUT.md; ADR-001; ADR-005 (delivery download path); ADR-003 (auth, pending: session mechanism); ADR-012 (render never competes with the UI) |
| Directive sections covered | §3.2a (dashboard "Next.js + TypeScript, or a lighter server-rendered option if justified"; simplest option that meets the requirement wins; nothing added just because); §3.2 service S8 (mobile-first command center); §1C.15 (tiers, each built only when a paying client needs it); §1 Deployment isolation (shared VPS, RAM caps); owner decision D1 (3A has no dashboard requirement beyond files out) |
| Research IDs | No ID exists yet for this topic. Evidence is the official pages in §7 (read 2026-11-18); they are to be entered into RESEARCH_LOG.md by its owner (rule 3). No figure below is measured |
| MVP scope | **3A**: no web dashboard; the operator tool delivers the minimum view set (16 §2). **3B**: nothing new (owner scores samples from the delivered files). **3C**: web dashboard S8 (Tier 0), built per this ADR once the RAM measurement gate (§5) passes. |
| Enterprise tier | **Tier 0**: server-rendered UI inside the factory's own API process. **Tier 1-2**: client portal S11 (16 §2); Next.js is reconsidered here only if the §6 triggers fire. **Tier 3**: no change decided |

## 1. Context
- Directive §3.2a leaves the dashboard open: Next.js + TypeScript, or a lighter server-rendered option if justified. Plan Q15 expects the server-rendered option to win for Tier 0 and decides by RAM footprint on the shared VPS (00_EXECUTION_PLAN.md Q15).
- The server is shared: 2 vCPU / 8 GB with the owner's existing applications (INF-01). `api` and `dashboard` are LIGHT services in the factory's core slice; they must stay responsive while the render slice is saturated (16 §3 "Where it runs"; 05).
- **No resident-RAM figure of any candidate is measured, and the official sources below publish none** (Next.js memory page: strategies for build and heap debugging only, no running-server figure). Sizing therefore cannot be argued from numbers; it is argued from the number of resident processes the documentation requires, and fixed by measurement (§5).
- Scope per phase (16 §2): 3A has no web dashboard. The decision is needed before 3C; it is recorded now because it fixes the layout of `apps/` and the typed-client rule in 27 §1.
- 16 §3 lists the criteria ADR-004 must score: RAM and CPU of the UI process, build chain and dependencies, mobile-first rendering and accessibility, fit with the ADR-003 session (HttpOnly cookie), typed client if TypeScript is chosen, live-update method.

## 2. Requirements taken from the binding documents
| # | Requirement | Source |
|---|---|---|
| Q1 | Mobile-first: the phone layout is the primary design; wider screens add columns, never new meaning | 16 §5 |
| Q2 | Every behaviour is an HTTP command or query plus an HTML page that works on a phone | 16 §3 "Stack" |
| Q3 | Polling with a visible "as of" time is the default; push (SSE / WebSocket) only if its footprint is measured; failure shows "stale since hh:mm" | 16 §3 "Live updates", §15 S8-Q6 |
| Q4 | Authentication by HttpOnly session cookie; CSRF protection of state-changing requests; model-produced text escaped, never executed | 16 §3 and §13; 08 §5.5, §5.3 |
| Q5 | Delivery files are streamed by the API after a permission check; no unauthenticated or long-lived public link | 16 §8 |
| Q6 | Tenant isolation: the UI holds no tenant logic of its own; all data comes through API calls that run inside a tenant transaction | 16 §3 "Reads"; 16 §10; rule 9 |
| Q7 | Nothing added "just because"; no new language or build chain without a requirement | §3.2a |
| Q8 | `CLIENT_GUEST` users never reach S8; their surface is the client portal S11 (Tier 1-2) | 16 §5 |

## 3. Options considered (with evidence)
| Option | Resident processes added | Build chain added | Fit with Q1-Q8 | Evidence |
|---|---|---|---|---|
| **A. Server-rendered pages in the existing FastAPI app (Jinja2 templates) + HTMX for partial updates and polling** | **0 beyond `api`**: templates are rendered by the FastAPI process; htmx is a browser-side script | None: htmx is "a dependency-free, browser-oriented javascript library" used with a script tag, "no need for a build system" | Q1-Q7 met (responsive HTML/CSS is framework-independent); live updates by polling (htmx) or SSE | FastAPI documents `Jinja2Templates` (install jinja2 and render with the request); htmx docs (§7 E3, E4, E5) |
| B. A separate Node.js process serving a Next.js app (App Router) in front of FastAPI | **+1 Node.js server** (`next start`, or the standalone `server.js`) | Node.js (minimum 20.9) toolchain, `next build`, TypeScript, npm lockfile; a generated typed client (27 §1) | Q1-Q7 met, with a second runtime and language | Next.js installation and self-hosting guides (§7 E1, E2, E6) |
| C. Next.js static export (`output: 'export'`) served by FastAPI or the reverse proxy | 0 resident Node.js process | Same Node toolchain at build time | Fails Q4-Q5 as a whole: "Features that require a Node.js server, or dynamic logic that cannot be computed during the build process, are not supported"; all data would come from client-side calls to the API, with the session handled in browser code | Next.js static-exports guide (§7 E7) |
| D. Hand-written single-page app (React / Vue without a framework) | 0 resident (static files) | Node toolchain at build time | Adds a client-side application with no requirement for it (Q7); not researched further (owner rule A.5) | — |
| E. Grafana or another ready-made dashboard tool instead of S8 | +1 service | none | Cannot carry S8 commands (approve/reject, budgets, controls) with permission keys and audit rows; Grafana's documented floor of 512 MB for evaluation (INF-08) is already large for the shared host | INF-08; 16 §7, §9 |

Options D and E are recorded only to show they were weighed; neither is proposed.

## 4. Decision (Proposed)

### 4.1 Tier 0 (3C): option A
1. S8 is rendered on the server by the FastAPI application with Jinja2 templates. Pages are plain HTML first; htmx adds partial refresh (job list, queue depth, cost strip) and form posts without a page reload.
2. **One process.** At Tier 0 the dashboard routes are a router mounted in the `api` application (no `dashboard` process). 16 §3 describes `api` and `dashboard` as two LIGHT services; this ADR proposes one process until the measurement in §5 shows a reason to split (see contract request 1). The code stays separable: UI routes live in their own package and call the same service layer as the JSON API, never the database directly.
3. **API-first boundary.** Every command and query exists as a documented JSON endpoint of `api` (FastAPI generates its OpenAPI schema); the HTML routes are thin presentation over the same service functions. A later Next.js client portal, a mobile client or an integration API (Tier 2) can therefore reuse the API without a rewrite.
4. **htmx delivery.** The htmx file is vendored as a pinned static file served by the application itself (no third-party CDN at run time; supply-chain and availability reasons, 08). The exact version is pinned at build time from the project's dependency review; this ADR does not name one (REQUIRES REVIEW (Phase 1): pin the current htmx version from its official release page).
5. **Language.** Python and Jinja2 templates. No TypeScript at Tier 0, so 27 §1 "Dashboard: TypeScript only if ADR-004 chooses Next.js" resolves to "not applicable at Tier 0". Template quality gates (auto-escaping on; lint of templates in CI) are engineering standards to be added by 27's owner if the owner approves (see contract request 2).
6. **Live updates (Q3, S8-Q6).** Default: htmx polling with the visible "as of" time and a "stale since hh:mm" state on failure. Server-sent events are available from both FastAPI (`EventSourceResponse`) and the htmx SSE extension; they are enabled only if the footprint of one open stream per signed-in operator is measured and accepted (16 §3). A stream is never the only source of truth: a reload always shows the database state.
7. **Mobile-first.** Responsive CSS written for the phone layout first (16 §5 responsive layout). The sizes of touch targets and contrast are owned by 16 and 18, not set here. Phone-layout acceptance tests (overflow, contrast, cut-off text) are part of the 3C acceptance (owner rule D.3).
8. **Security fit.** Session cookie flags and CSRF protection follow 08 §5.5 and ADR-003. Template auto-escaping is on for all HTML templates, which also covers model-produced text (Q4). htmx's own documentation tells applications to escape untrusted content and to restrict where htmx attributes can appear; the security checklist of 08 must carry that point (§7 E5).

### 4.2 Client portal (Tier 1-2, S11): decided later
- The portal is a separate surface from S8 (16 §5; `CLIENT_GUEST` never reaches S8). It starts as the same option A (server-rendered, a second router and template set, same API) unless a **§6 trigger** fires.
- Next.js is adopted for the portal only by a new ADR revision that scores it against the measured RAM of the then-current host, the portal's requirements from a real paying client (§1C.15) and the extra build chain it adds. Until then no Node.js is installed on the production host.

### 4.3 What is not decided here
- The sign-in library and session mechanism (ADR-003); the file-download mechanism details (pre-signed URL vs API streaming) stay with ADR-005 and 16 §8.
- CSS approach and component set: not chosen here (REQUIRES REVIEW (Phase 1) at 3C start; plain CSS is the default consistent with Q7).

## 5. Measurement gate (the decision is fixed by Q15's own rule)
Plan Q15 decides by RAM footprint on the shared VPS. No official figure exists for either candidate, so the following is **REQUIRES REVIEW (Phase 1)**, executed in the 3A walking skeleton or at the start of 3C:
1. Measure the resident memory of the `api` process with and without the dashboard router mounted, under the factory slice, with a representative number of open pages (MEASURED).
2. If a Next.js prototype is considered at any time, measure its server process in the same way on the same host, with the same slice caps, so the two numbers are comparable.
3. Record both in RESEARCH_LOG.md (source: own measurement, date) and in 05's per-component table. Option A stays if its added RAM is within the slice's `MemoryHigh` headroom (05 §4 slice limits); the measurement never overrides the headroom rule of ADR-012 §1.1.
4. The measurement does not block 3A: 3A delivers files through the operator tool (16 §2).

## 6. Revisit triggers
1. The §5 measurement shows the `api` process with UI routes cannot stay inside its slice caps (then split the UI into a second process first, not change language).
2. A paying client at Tier 1-2 needs a portal behaviour that server-rendered pages cannot deliver with acceptable effort (for example rich client-side editing of the review surface); the requirement is written down by the owner first (§1C.15).
3. The plan moves to its own server (ADR-012 trigger) and RAM is no longer the binding constraint: option B can then be scored on build complexity and team fit alone.
4. Live-update needs outgrow polling and SSE (S8-Q6), for example bidirectional collaboration.
5. A major-version change of FastAPI, Jinja2 or htmx that changes the documented behaviour used here (re-verify the §7 pages; plan Q18).

## 7. Consequences
- **Positive.** No extra resident process or language at Tier 0; the shared host's RAM is spent on the factory's real work (render, queue). One authentication, one authorisation path and one set of tests for UI and API (rule 9: no UI-side tenant logic). The JSON API remains the contract for any later client.
- **Negative.** Rich client-side interactions are limited to what htmx and small vendored scripts provide; the Next.js ecosystem (component libraries, typed client generation) is not available at Tier 0. If a portal later needs it, a second UI stack will exist beside the first (cost accepted, decided only on a trigger).
- **Risks.** (a) HTML fragments returned to htmx must be escaped and permission-checked like any page; a missed check is a tenant leak (test: AC tenant matrix of 16 §13 and §14, run against UI routes too). (b) Polling load grows with open sessions; interval is configuration and measured. (c) Vendored script drift: pinned file with recorded hash.
- **Tests.** Phone-width layout checks (16 §5); stale-data state; unauthorised fragment request returns no data; CSRF negative test; tenant matrix against fragment routes; render-slice saturation does not stop the UI (05).

## 8. Status
**Draft - documentation** (proposed). Awaiting owner decision. Software: Planned.

## 9. Evidence (official pages, read 2026-11-18; to be entered in RESEARCH_LOG.md)
| Ref | Page | Fact used |
|---|---|---|
| E1 | https://nextjs.org/docs/app/getting-started/installation | System requirement: minimum Node.js version 20.9; `create-next-app` default setup enables TypeScript and Tailwind. |
| E2 | https://nextjs.org/docs/app/guides/self-hosting | Self-hosting runs a Node.js server (`next start`) or a Docker container; a reverse proxy in front of the Next.js server is recommended rather than exposing it directly. |
| E3 | https://htmx.org/docs/ | htmx is a dependency-free, browser-oriented JavaScript library added with a script tag; no build system needed; security section covers escaping untrusted content. |
| E4 | https://htmx.org/ | Library size stated by the project: about 16 kB minified and gzipped (browser download size, not server RAM). |
| E5 | https://htmx.org/docs/ (Security section) and https://htmx.org/essays/web-security-basics-with-htmx/ | Untrusted HTML injected into a page can carry htmx attributes; escape user content; use `SameSite` cookies as a CSRF layer. |
| E6 | https://nextjs.org/docs/app/guides/memory-usage | Memory page covers build and heap-profile techniques; no resident-memory figure for a running server is published. |
| E7 | https://nextjs.org/docs/app/guides/static-exports | Static export: features needing a Node.js server or dynamic logic not computable at build time are unsupported. |
| E8 | https://fastapi.tiangolo.com/advanced/templates/ | `Jinja2Templates` renders HTML templates inside a FastAPI app. |
| E9 | https://fastapi.tiangolo.com/tutorial/server-sent-events/ | Server-sent events via `EventSourceResponse` from `fastapi.sse`. |
| E10 | https://htmx.org/extensions/sse/ | htmx SSE extension: connects to an EventSource from HTML; described as a lightweight alternative to WebSockets over existing HTTP connections. |
| E11 | RESEARCH_LOG INF-01, INF-08 | Host plan (2 vCPU / 8 GB); Grafana evaluation floor 512 MB. |

Not found in any official source (stated, not guessed): resident RAM of a running Next.js server, of an htmx-based FastAPI app, or a comparison between them.
