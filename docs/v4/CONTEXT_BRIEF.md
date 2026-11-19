# CONTEXT BRIEF — digest of MASTER_DIRECTIVE (read this, then only the sections you need)

Binding source: `docs/v4/MASTER_DIRECTIVE.md` (§ numbers below). Owner decisions D1+ in `IMPLEMENTATION_PROGRESS.md` amend it where stated. Facts: cite `RESEARCH_LOG.md` IDs only.

## Product
AMW AI Media Factory: a multi-tenant AI video production platform (research → script → fact-check → voice → visuals → edit → thumbnail → SEO → publish → analytics → revenue). It serves (1) the owner's channels and (2) paying clients, on one codebase. Enterprise-grade design, low cost, minimum human effort, but never at the cost of quality or compliance (§0).

## Current phase
DOCUMENTATION AND DESIGN ONLY (rule 1). No code, migrations, configs, deployment or VPS changes. Status values: Planned / In Development / Implemented / Tested / Production Ready (rule 7). Documentation status is reported separately from software status (rule 6).

## Binding rules (§0)
- Never touch the trading app or BagMitra. VPS: read-only commands only (rule 2).
- Every external fact has an official URL and date (rule 3). Label ESTIMATE / MEASURED / PROJECTION. Never fabricate (rule 4).
- Never publish an unapproved video. No infinite retries, no silently dropped jobs, no uncontrolled agent loops. No hard-coded keys/models/providers. A Claude subscription ≠ API access (rule 5).
- No mock data presented as working features (rule 7). No spend without the owner (rule 8).
- **Tenant isolation is absolute** (rule 9): `org_id` everywhere; RLS is the second line of defence.
- After baseline approval, new ideas go to `CHANGE_REQUESTS.md` (rule 11). Contract gaps go to `CONTRACT_CHANGE_REQUESTS.md`, never local variants.
- This repo is PUBLIC: no secrets, book content, private method, private data or server details.

## Key constraints (§1, verified)
- Shared VPS (KVM 2: 2 vCPU / 8 GB, INF-01; Ubuntu 26.04, cgroup v2, INF-02). Own Compose project under `/opt/amw-media-factory/`, own systemd slice with low weights and hard caps (INF-03/04). Sizing from measurement only (audit Part C pending).
- Night window 00:00–07:00 IST. Admission stops at 06:30; graceful stop at 07:00. YouTube quota day = US Pacific (YT-03).
- Postgres-backed queue (SKIP LOCKED, LISTEN/NOTIFY; INF-05/06). External APIs for AI. FFmpeg render worker is movable.
- YouTube: upload 1 unit, own bucket, 100/day (YT-01). Always set `privacyStatus=private` explicitly (YT-04). `containsSyntheticMedia` (YT-06). A/B test of titles/thumbnails is a human Studio step (YT-08).
- YPP inauthentic content enforced channel-level; no AI persona on finance (YT-09). Human editorial contribution + approval on every video. Uniqueness and originality are blocking gates.
- SEBI: education only. 30-day price-data lag (IN-02). No calls, levels, live sessions or return claims. **No forward-looking statements on named securities even in historical case studies** (IN-03). No regulated-entity association (IN-01).

## Quality (§1A)
Visual hierarchy: owner/real material → licensed stock → code-made motion graphics → AI video B-roll → AI stills last. Hook in 30 s; a visual change every 3–5 s. Audio −14 LUFS / −1 dBTP / 48 kHz / AAC-LC ≥384 kbps. Video ≥1080p H.264 High, VBR at YouTube's encoder target (8 Mbps at 1080p30; owner decision D10, ADR-014; no measured floor), CFR, SRT per language. Blocking FFmpeg QC (INF-09). 100-point score, publish at ≥85; any compliance failure rejects. Golden-sample pilot before scaling.

## Business (§1B, §1C, §1D, §1E)
First channel: Marathi-first trading **education**, funnel to the owner's course + ATP; no broker affiliate income. Enterprise tiers 0→3, each built only when a paying client needs it (§1C.15). Ads production line under the ASCI rules (IN-04/05). Growth lines are scored, not built.

## Architecture (§2, §3)
- 17 pipeline stages under a code-controlled orchestrator (a state machine, not LLM-to-LLM). §3.1 registry is binding. Shared services S1–S13 (S6→16, S7→01, S8→01; plan Q4).
- Contracts and state machine: `03_COMMUNICATION_STANDARD.md`. Tables: `04_DATABASE_ARCHITECTURE.md`. IDs/enums: `GLOSSARY_AND_IDS.md`. Failures: `07`. Production types: `24`. Engineering/prompt/eval standards: `27`.
- Agent blueprints: 26 sections each (§4). Section 19 states tenant isolation; section 26 is the prompt & eval pack (≥20 golden cases).

## Build order (owner decision D1 replaces §5.7)
3A production line (minimum core + Agents 04–11 + Agent 16 gates; topic from the owner; files out; **no upload or OAuth**) → 3B three golden samples scored by the owner → 3C everything else. Paid calls only within owner-set provider limits; per-video and pilot budgets enforced; render never in market hours.

## Where things are
See `docs/REPO_MAP.md`. Progress and decisions: `docs/v4/IMPLEMENTATION_PROGRESS.md`.
