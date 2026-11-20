# 00 — Repository and Server Audit

| Field | Value |
|---|---|
| Status | **PARTIAL.** Parts A, B and D are complete. Part C (VPS) is PENDING the owner's run of the read-only script; the owner's summary of a 24 h audit is recorded in Part C-2 (D15), without the raw output. |
| Audit date | 2026-11-18 |
| Method | Read-only. Media: git inspection. Private repos: shallow read-only clone with file listing and counts only; nothing modified, nothing copied. VPS: not touched (directive rule 2). |

> **Public-repository rule.** `abhiwasu007-a11y/Media` is **public** (verified 2026-11-18 via the GitHub repository listing). This document therefore records only aggregate, non-sensitive facts about the private repositories and the server: no book titles or content, no method notes, no private data values, no container names, ports, IP addresses or hostnames. The detailed inventory and the raw VPS output stay outside git (see open question Q21 in `IMPLEMENTATION_PROGRESS.md`).

---

## Part A — Media repository (`abhiwasu007-a11y/Media`)

| Item | Finding (MEASURED 2026-11-18) |
|---|---|
| Visibility | Public |
| Commits on `main` | 1 (`Create README.md`, one line: "AMW AI Media Factory") |
| Existing code, agent registry or specs | None. The directive §3.1 registry is adopted unchanged (plan Q20). |
| Directive §5.1 claim "repo is EMPTY (no commits)" | Not exact: one README commit existed. Treated as effectively empty (plan Q1). |
| Working branch | `claude/zealous-johnson-ydffzn`, open docs-only PR [abhiwasu007-a11y/Media#1](https://github.com/abhiwasu007-a11y/Media/pull/1) |
| Added in Phase 1 | `.gitignore`, README status section, `docs/v4/README.md` (index), `SOURCE_LAYOUT.md`, `CHANGE_REQUESTS.md`, `IMPLEMENTATION_PROGRESS.md`, this audit, `RESEARCH_LOG.md`, `audit/vps_readonly_audit.sh` |

## Part B — Private repositories (read-only inventory)

### B.1 `abhishekwasu-hue/atp-private`
| Item | Finding (MEASURED 2026-11-18) |
|---|---|
| Size / files | 5.4 MB working tree, 302 tracked files (223 `.py`, 70 `.md`) |
| Main areas | engine/application package (234 files), tests (19), docs (20), `knowledge/` (17 private method/knowledge files) |
| Repo rules (its CLAUDE.md) | Private; method/engine/strategy content must never be copied to any public repository, issue, PR or chat; no secrets; no method changes without the owner's approval. |
| Relevance to Media Factory | `knowledge/` is the source for the **"our method"** topic (§1B.2a) and the shared glossary. It contains the owner's private method, so it must stay **outside** this public repo and outside any client tenant's index. |

### B.2 `abhishekwasu-hue/trade-data`
| Item | Finding (MEASURED 2026-11-18) |
|---|---|
| Size / files | 1.5 GB working tree, 9,716 tracked files (mostly PNG/JPG chart images, JSON, CSV, parquet, gz) |
| **Trading book collection** | Found at `research/books/`: **13 PDF, 1 EPUB, 4 PPTX** source documents (218 MB), plus 1,349 JPG images extracted from them into per-book `images/` folders and 26 Markdown index/notes files. |
| **Marathi course** | Found at `research/course/`: `COURSE_SPEC.md`, 25 chapter folders (`chNN_<topic>`), a chapter builder, and a `data_pack/` of NIFTY/BANKNIFTY CSVs. 2,478 files, 512 MB. This satisfies part of owner input A6 (course outline). |
| Course rules already in force (its `COURSE_SPEC.md`) | Plain Marathi with the English term in brackets; **own words only, never copy sentences or images from the books; no author/school/brand names on slides**; only own charts drawn from real data; no profit promises; disclaimer slide (education only, not advice); speaker notes "later used as video voice-over". These match directive §1B.2a and are reused as inputs for the channel's rule pack. |
| Historical market data | NIFTY and BANKNIFTY index OHLC (daily/weekly from 2015/2016; intraday windows), NIFTY F&O bhavcopy (options + futures, 2018-12 → 2024-03, 65 monthly files), futures 5-minute data with volume. |
| Data-use policy (its README) | Windows: IS 2015–2021, VAL 2022-01 → 2024-03, CONTAMINATED 2026-07-01 → 2026-10-06, **HOLDOUT (sealed) 2024-04-01 onward: "never fetched or used"** for Trade research. |
| Observed inconsistency (facts only) | The README says the BANKNIFTY daily file is "cut at 2024-03-31". However, `banknifty/manifest.json` lists daily data up to 2026-10-09 and weekly data up to 2026-10-05. The course spec also states the owner allowed **all** data, including previously held-out rows, **for the course**. Which windows the channel may use is open question Q22. |

### B.3 What the inventory does NOT show
- Whether the PDFs/EPUB are text-extractable or scanned (not opened, per plan Q19: inventory only).
- The licence or ownership status of each book (needed for the copyright posture in `13_COMPLIANCE_YOUTUBE_POLICY.md`; Q25).
- Course chapter content quality or completeness (not reviewed; out of scope for this audit).

## Part C — VPS (PENDING owner run)

**Status: PENDING.** Nothing on the server has been touched or measured by me.

| Will be recorded (from `docs/v4/audit/vps_readonly_audit.sh`) | Value |
|---|---|
| OS / kernel / cgroup version | PENDING |
| vCPU, RAM, swap, disk (measured) | PENDING. Owner-REPORTED: 2 vCPU / 8 GB RAM / 100 GB SSD / 8 TB bandwidth, Ubuntu 26.04 LTS. |
| Running services, containers, Compose projects | PENDING (recorded as counts and categories here; names kept private) |
| Ports in use | PENDING (kept private; used only to choose free ports) |
| Databases detected (by process, no connection) | PENDING |
| Reverse proxy present | PENDING |
| Existing per-container CPU/memory limits | PENDING |
| Peak usage, market hours (24 h sampling) | PENDING |
| Usage in the 00:00–07:00 IST window | PENDING |
| Memory/CPU/IO pressure (PSI), OOM history | PENDING |
| `/opt/amw-media-factory` exists? | PENDING (expected: absent) |
| **Headroom verdict** (measured total − peak of trading app + BagMitra − safety margin) | PENDING. This decides shared VPS vs a separate render-only worker (plan Q6), and is written in `00b_TECHNICAL_FEASIBILITY.md`. |

### C.1 How the script stays read-only
It never starts/stops/restarts anything, never connects to a DB, never prints environment variables or config contents, runs every command with `nice -n 19`/`ionice -c3` and a timeout, and writes only its own report files. It was tested in the development container on 2026-11-18 (all 11 sections produced, no errors).

## Part C-2 — Owner-run 24 h read-only audit (2026-11-20)

**Source = owner-run audit.** The owner ran a 24-hour read-only audit and reported the numbers below in the owner chat on 2026-11-20. The assistant did not see the raw output; only the owner's summary is recorded here. The raw output stays outside git. The measured items of Part C that this summary does not cover (OS and kernel, services, ports, databases, reverse proxy, existing limits, disk, `/opt` path) remain PENDING and are not inferred.

### C-2.1 Reported measurements (owner words, exactly)
| Item | Value (source = owner-run audit) |
|---|---|
| Host | 2 vCPU |
| Load average, night | 0.23 |
| Load average, market | 0.28 |
| Short load spikes | to about 3.3 ("ATP one-off jobs", as the owner wrote it; ATP is an unrelated trading app) |
| `mem_available` minimum, night | 3.7 GB |
| `mem_available` minimum, market | 3.0 GB |
| `mem_available` minimum, other | 2.4 GB |
| Swap, maximum | 376 MB |
| OOM / reboot | none |

### C-2.2 FIXED LIMITS for any VPS render (owner decision D15)
Binding as given by the owner. Night window 00:00-07:00 IST only.
| Limit | Value |
|---|---|
| Window | 00:00-07:00 IST only |
| systemd slice `MemoryHigh` | 1.5G |
| systemd slice `MemoryMax` | 2G |
| `CPUQuota` | 100% |
| `CPUWeight` / `IOWeight` | low |
| Process priority | nice 19 and ionice idle |
| Concurrency | one render at a time |
| Pause or abort | if `mem_available` < 1.5 GB, or PSI cpu `avg10` > 40 for 2 minutes |

The Seneca sample stays in the development environment; VPS rendering only after the sample passes. Nothing is changed or deployed on the VPS by this record (the slice and any deployment are a later ticket, VPS-RENDER-1).

### C-2.2a Update (D16): the limits above are DEFAULTS of settings
The owner decided on 2026-11-20 (D16) that these limits are dashboard settings the administrator can change when the VPS is upsized, and must not be hard-coded. The numbers in C-2.2 remain the audited defaults. Design note: `adr/ADR-016_vps_render_profile_settings.md` (PROPOSED, not built, discuss-then-build); contract question: CCR-298.

### C-2.3 Relation to existing documents (mismatches recorded, no numbers invented)
1. **Market-hours guard.** The runtime guard blocks 09:00 to 16:00 IST on trading days (regular session 09:15 to 15:30; `runtime/README.md`, item 8; the session hours themselves are in the research log, NSE-01). The owner window 00:00-07:00 IST lies outside that interval, so the two guards do not conflict. `06_NIGHT_SCHEDULING.md` section 11 deliberately states no session time and no relation to the window; each guard is evaluated on its own configuration.
2. **`render.max_duration_minutes`.** Shipped as `null` in the runtime configuration; the real-run preflight refuses until it is set from a measured skeleton render time (`runtime/README.md`, item 0). The owner gave no duration in D15, so this is **still open**. The whole render must also fit inside the window and clear the market-hours guard.
3. **Render time and CPU (ADR-014).** The ADR-014 render-time figures (a 10-minute 1080p30 render about 25 to 34 min for encode + reference, plus SSIM time) are **ESTIMATES**, extrapolated from short clips measured on a shared 4-CPU development box. `CPUQuota=100%` is one core, so a render in the VPS slice will be slower than those figures by a factor that has **not been measured**; no number is computed here. **REQUIRES REVIEW (Phase 1): measure on the VPS slice before the first VPS render.**
4. **Peak memory (ADR-014).** The only measured memory figure in the docs is RSS about 600-930 MB with split + FFV1 (about 290 MB for x264 alone), on short 1080p clips on the shared 4-CPU box, stated there as upper bounds, not for a long render. The docs state no peak for a long render. Whether a long render stays inside `MemoryMax` 2G and the `mem_available` < 1.5 GB pause threshold is **REQUIRES REVIEW (Phase 1): measure on the VPS slice**.
5. **Disk.** ADR-014 estimates up to about 4.6 GB of FFV1 per 60 s segment (30 fps). The audit summary reports no disk figure; the free-space pre-check is not built (ADR-014, REQUIRES REVIEW for the VPS placement).

---

## Part D — Conclusions so far (from Parts A–B only)
1. The Media repo is public, so private knowledge, the course, book material and market data must be read at runtime from **private factory storage**, never committed here. `.gitignore` already blocks the common forms.
2. Both private repos already enforce "own words, no book reproduction, education only, disclaimer". The channel's compliance rule pack can adopt these rules rather than invent new ones.
3. The trading-book library exists (14 text documents + 4 decks), so the Trading Knowledge Library (§1B.2a) is feasible in principle. Ingestion feasibility (text vs scans) is still unknown.
4. Server sizing cannot be concluded until Part C is measured (owner rule A.2: never assume live settings).
