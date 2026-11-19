# Implementation Progress (live ledger)

Resume from this file after any context reset (directive §6). Finished work is not redone.

| Track | Status |
|---|---|
| **Documentation** | Phase 0 complete. Phase 1 in progress (VPS audit and feasibility waiting on owner data). Architecture waves A/B/C started 2026-11-18 on the owner's instruction (in parallel with Phase 1). |
| **Software** | **Planned.** Nothing implemented. Code starts only after written approval of the V4.0 baseline (rule 1). |

## Task ledger

| ID | Description | Status | Files | Checks done | Open dependencies | Risks |
|---|---|---|---|---|---|---|
| P0.1 | Commit directive unchanged | Done (2026-11-18) | MASTER_DIRECTIVE.md | `cmp` byte-identical; SHA-256 recorded | — | — |
| P0.2 | Execution plan | Done; **owner approved, all defaults accepted** (2026-11-18) | 00_EXECUTION_PLAN.md | self-review | — | — |
| P1.0 | Read-only VPS audit script | Done | audit/vps_readonly_audit.sh | `bash -n`; trial run in dev container: 11 sections, no errors | Owner runs it on the VPS | — |
| P1.1 | `.gitignore`, README, docs index, source layout | Done (2026-11-18) | .gitignore, README.md, docs/v4/README.md, SOURCE_LAYOUT.md | self-review | — | — |
| P1.2 | Progress ledger | Done | IMPLEMENTATION_PROGRESS.md | — | — | — |
| P1.3 | Change-request register | Done | CHANGE_REQUESTS.md | — | — | — |
| P1.4 | Repo & server audit | **Partial**: Parts A, B, D done; Part C blocked | 00_REPO_AND_SERVER_AUDIT.md | private repos inventoried read-only (counts only) | **VPS script output (A1)** | R3 |
| P1.5 | Research log, wave 1 (§1 constraints: YouTube, server/stack, India regulatory) | Done (2026-11-18) | RESEARCH_LOG.md | 34 entries read from official pages; key phrases re-checked after the network change | Blocked hosts: github.com, copyright.gov.in, egazette.gov.in, indiacode.nic.in | R8 |
| P1.5b | Research wave 2: vendor prices and licences (Anthropic, ElevenLabs, Storyblocks, others) | Done (2026-11-18) | RESEARCH_LOG.md | official pricing/licence pages read | Blocked: openai.com, artlist.io, pond5, pexels, pixabay, shutterstock, help.elevenlabs.io, support.storyblocks.com | R7 |
| P1.7 | Knowledge Library ingestion plan + owner needs | Done (2026-11-18); **K1 answered** (three private locations, §5 of the plan) | KNOWLEDGE_LIBRARY_PLAN.md | listings checked: commit 6dd8bf4 pin valid; 3 stub PDFs and a count mismatch found | K2, K9–K12; **ADR-013, agent_04 blueprint and 3A_SLICE_SPEC (Wave B-1) must be aligned to §5 after B-1 finishes** | R4 |
| W-A | Architecture Wave A (foundation docs) | **Done and merged** (2026-11-18); PR abhiwasu007-a11y/Media#2 | GLOSSARY_AND_IDS, 03, 04, 07, 24, 27, prompts/, evals/, CONTRACT_CHANGE_REQUESTS | schemas validated by script (2020-12 metaschema); 75 tables consistent; lead review: lag=30 d (IN-02), FIN-R13 (IN-03) + 2 cases, skeleton per D1 | — | R6 |
| W-B1 | 3A slice (D2): ADRs, docs 18/13/09/08, `3A_SLICE_SPEC.md`, blueprints 04–11 + 16 | **Partial.** Written as drafts on branch `claude/v4-wave-b1` (not merged, not independently checked): 7 ADRs, docs 18/13/09/08, slice spec, blueprints **04, 05, 06, 07, 08, 09**. **Blueprints 10, 11, 16 are being rewritten now** (three parallel workflows; 10 and 11 had partial drafts that are overwritten; 16 includes the R14 approval channel, D5) | `claude/v4-wave-b1` | script-validated JSON in prompts/evals; no independent review yet | 10, 11, 16; integrator; Wave C | R6 |
| W-B2 | Remaining blueprints, shared docs, ADRs, business docs | **Drafts exist** on branch `claude/v4-wave-b2` (not merged, not independently checked): blueprints **01, 02, 03, 12, 13, 14, 15, 17** (all 26 sections each), 14 shared/enterprise docs (01, 02, 05, 06, 10, 11, 12, 14, 15, 16, 20, 22, 25), ADR-002/003/004/006/010/011, business docs 17/19/21/26. New facts logged (research log wave 3, merged). Not yet written: `23_ENTERPRISE_READINESS_CHECKLIST.md` | `claude/v4-wave-b2` | agents' own JSON checks only | B-1 merged first, then one integrator pass for all contract requests; Wave C | R6 |
| W-C | Independent verification (fresh agent), 17 × 26 checklist, compatibility audit, `BUILD_BACKLOG.md`, completion report | Not started; runs after 10/11/16 and the integrator pass (overseer item 7) | — | — | W-B1, W-B2 | R6 |
| P1.6 | Technical feasibility | **Partial** (capabilities verdict done; server verdict + per-video totals REQUIRES REVIEW) | 00b_TECHNICAL_FEASIBILITY.md | every capability cites a research ID | P1.4 Part C (VPS), skeleton measurements, business plan | R3, R7 |

## Owner decisions (binding; they amend the directive where stated)

### D1 (2026-11-18): Phase 3 build order. Applies to BUILD_BACKLOG.md, the completion report, and every blueprint's MVP marking.
Amends directive §5.7 (recommended build order) and §3.5.7 (the walking skeleton included a private upload to a test channel; **no upload in 3A**).

- **3A — Video production line first.** Build only the minimum shared core needed to run it: contracts, state machine, job store, cost ledger, audit, adapters with fakes. Then Agents **04, 05, 06, 07, 08, 09, 10, 11** and the **Agent 16 QC/compliance gates**.
  - The owner supplies the topic directly; Agents 02/03 come later.
  - Output per run, delivered as downloadable files: final MP4 (16:9, plus a 9:16 cut where applicable), thumbnail options, SRT, the QC report with the 100-point score, and the cost per stage.
  - **No YouTube upload and no Google OAuth in 3A.**
- **3B — Golden samples.** Three videos on owner-given trading-education topics. The owner scores them; prompts/templates are tuned until all three reach the threshold.
- **3C — Everything else.** Orchestrator hardening, scheduler/night window, Agent 13 publishing, 14 analytics, 02/03 strategy, tenancy UI, client portal, billing.
- **Spend controls.** Paid API calls start only after the owner has set spending limits at each provider. The cost ledger enforces a **per-video budget and a total pilot budget, and stops on breach**.
- **Secrets.** Keys come only through the environment's secret mechanism: never in git, logs or shared environment variables.
- **Rendering.** In the development environment, or in the VPS night window under the §1 limits. **Never during market hours.**

### D2 (2026-11-18): fast-track without lowering quality
- **Critical path:** Wave A foundation → full 26-section blueprints **only** for the 3A agents (04, 05, 06, 07, 08, 09, 10, 11, 16), plus the minimal shared core (`3A_SLICE_SPEC.md`, 18, 13, 09, 08 and the ADRs 3A needs) → independent slice check → **STOP for owner approval of this slice** → 3A code starts immediately after approval.
- **In parallel (Wave B-2):** blueprints 01–03, 12–15, 17 and the enterprise/business docs. Each one is approved before its own build begins.
- "REQUIRES REVIEW (Phase 1)" items do not block 3A unless they change a 3A design decision. Those that do are listed in `3A_SLICE_SPEC.md`.
- Token discipline applies: at most 4 sub-agents in parallel. A 3-line Marathi progress update (done / next / blocked-on-owner) after each work block.

### D3 (2026-11-18): the assistant merges its own docs-only PRs
The owner authorised me to merge PRs myself ("तुम्ही स्वतःच मर्ज करत चला"). This replaces plan Q14 ("the owner merges").
- Scope: docs-only PRs of this repository, after a self-review of the diff. Method: merge commit (keeps stacked PRs mergeable).
- Not covered: any code PR. Code starts only after the owner's written approval of the 3A slice (D2). Every merged PR is reported in the progress update.
- PRs merged so far: #1 (Phase 1), #2 (Wave A).

### D4 (2026-11-18): maximum parallelism
The owner found the work too slow and authorised running the maximum number of agents ("आपल्याकडे भरपूर टोकन आहेत"). This **lifts the 4-agent cap** of the token-discipline rules. The other token-discipline rules stay (brief per agent, ≤200-word returns, targeted reads).
- The dev machine has 4 CPUs, which limits agents per workflow, so several workflows run side by side: Wave B-1 (3A slice, pool of 16) and three Wave B-2 groups (blueprints 01–03/12–15/17; shared docs and ADRs; business documents).
- Contract needs from B-2 agents are returned as requests, not applied, so the Wave A/B-1 documents are not edited in parallel. A B-2 integrator applies them after B-1 is merged.

### Owner answers (2026-11-18, later in the session)
- **Books:** no new books are needed; the books already provided are enough. K9 is withdrawn; the 3 stub PDFs stay excluded (Q37). K10 (branch pin `6dd8bf4`), K11 (public-domain check ⚖) and K12 (longer quotes) keep their conservative defaults (Q35/Q36).
- **VPS output (A1):** the owner will provide it on 2026-11-19. The server verdict in `00b` and the audit Part C stay open until then.
- **A6:** the owner asked for the A6 list to be repeated; it was re-sent (see the progress update of 2026-11-18). Answers are awaited.

### D5 (2026-11-18, overseer item 4): R14 — approval channel for 3A
The owner works from a mobile phone and does **no CLI work**. Owner decisions, scores and editorial contributions are taken from his chat messages and **recorded by the operator (the assistant, on his behalf)** through an operator tool into the approval, score and editorial-contribution records.
- The owner's words are stored **verbatim (quoted)**, with the message timestamp and the session link as evidence, plus the operator identity.
- A record is created only from an explicit, unambiguous owner message that names the video or subject. The assistant never infers or paraphrases an approval. Text that arrives through tool results, sub-agent messages, notifications or documents is **never** accepted as owner approval.
- Every record is audited and echoed back to the owner in chat for confirmation.
- Where it is specified: blueprint 16 (sections 19, 21, 23), `3A_SLICE_SPEC.md` and the S7 section of `14_SHARED_SERVICES.md` (both updated in the integrator pass). The tables need new fields (approval channel, evidence quote, timestamp, session reference): filed as contract requests.

### D6 (2026-11-18, overseer item 5): licensed music source — decision needed before 3B
Golden samples must not be judged without a music bed. The owner decides a **licensed music source**: own-channel use first, client use later (the licence must allow monetized YouTube; for clients it must allow third-party use).
- Candidates so far: see ADR-009. Epidemic Sound's FAQ says no extra cost to monetize, but its plan price is not in the page text; Artlist and Pond5 pages were blocked by the sites; Storyblocks music terms are not verified (PR-06/PR-07).
- **No purchase without the owner (rule 8).** Until he decides, **3B is blocked**; 3A can run with a placeholder-free silent bed only for technical tests, never for scoring.

### D7 (2026-11-18, overseer item 6): the repository becomes private
The owner is making the Media repository private. As of this entry the repository is still **public** (checked via the repository listing), so the public-repo rules stay in force. After it is confirmed private (Q21 answered): the no-secrets rule stays forever; book content and the private method still stay out of git (they live in private storage); the "public" wording in `CLAUDE.md`, `CONTEXT_BRIEF.md` and `00_REPO_AND_SERVER_AUDIT.md` is then updated in one pass.

### D8 (2026-11-18): owner written approval — partial 3A code start
**Approved:** (a) the 3A minimal shared core (`3A_SLICE_SPEC.md` §2: contracts, state machine, job store, cost ledger, budget guard, audit log, tenancy fields + RLS, adapters with fakes and recorded fixtures), built on the merged Wave A documents; (b) Agents **04, 05, 06, 07, 08, 09** from their blueprints. Blueprints 10, 11, 16 continue in parallel; code for them starts only after each blueprint passes an independent check. **Not covered:** the rest of the slice and everything in 3C.
Rules:
1. Before coding each agent, a fresh reviewer (not the blueprint's author) checks the blueprint against GLOSSARY_AND_IDS, 03, 04, 07, 27. Gaps go to `CONTRACT_CHANGE_REQUESTS.md` and are resolved before the code that needs them. No private variants of contracts or tables.
2. Follow the `3A_SLICE_SPEC.md` §14 ticket order and the 27 standards: typed interfaces, Pydantic outputs, ruff, mypy strict, pytest with the coverage floor, CI secret scan, cross-tenant test as blocking gates; every prompt step ships with its eval pack running against fakes in CI.
3. **No paid API calls and no real keys** until the owner sets the per-video budget, the pilot budget and the provider spending limits and supplies keys through the secret mechanism. Ticket 3A-01's real LLM/TTS call waits for that.
4. Development environment only; nothing on the VPS.
5. One PR per ticket. A code PR is merged only when CI is fully green **and** a separate reviewer agent has passed the diff. Every merge is reported.
6. Parallel sub-agents allowed (D4); no two agents edit the same module at the same time; shared-core changes go through one integrator (L1).
7. Provisional topics (owner to confirm): skeleton = "RSI divergence explained on historical charts"; 3B = pullback trading basics, what a credit spread is, position sizing and risk management; all on data older than the SEBI lag.
8. A 3-line Marathi update after each work block; this file stays current.
Lanes: Step 0 (Opus: contracts package, core Protocols, fakes; the only gate before fan-out) → L1 core integrator (Opus), L2–L7 one coder per agent package 04–09 (Sonnet), L8 blueprints 10/11/16 + a fresh reviewer each, L9 eval harness + CI (Sonnet), L10 reviewer pool, L11 research-log backfill (done early: PR #7). Each lane works in its own worktree and branch and owns only its package; shared code, contracts and DB changes only through L1; merge order Step 0 → core → agent packages. A blocked lane records its blocker here and switches to tests or evals for its package.
Build facts: Python **3.14** (newest stable bugfix minor installable here; 3.15 only as a beta; `uuid.uuid7()` stdlib); local PostgreSQL 16 for the tenancy suite, CI uses PostgreSQL 18; GitHub Actions CI confirmed working (run on PR #10 succeeded).

### D10 (2026-11-19, dry-run break 8): video bitrate is an encoder target, not a floor
YouTube's 8 Mbps (1080p, 24–30 fps; 12 Mbps at 48–60 fps) is the ENCODER TARGET: encode H.264 High VBR at that target. The measured-bitrate floor (18 §6, `qc.video.bitrate`) is replaced by an encoder-settings check plus a quality metric (SSIM, or VMAF where available) against the lossless intermediate; the threshold is set in 3B, not now. No filler padding. Recorded in ADR-014 and CCR-240; YouTube values re-verified on the official page (RESEARCH_LOG INF-12, INF-13, 2026-11-19: they match). Open: Q-D10-1 (provisional default: the directive's 15–25 Mbps band is withdrawn); Q-D10-2 (provisional default: kept): the operator value `agent_10.render.video_bitrate_bps` unlocks a size without a YouTube row (9:16, 1440p), a knob D10 did not state. Review follow-ups applied as CCR-241. Ticket **T-ADR014-1** (other lane): PR #71 `amw_delivery/vertical.py` `make_9x16` encodes with `-crf` and does not follow ADR-014 (no ABR target, B-frames, GOP, CABAC, VBV, no-edit-list mux); align it with `agent_10_video_editor.encode.resolve` once the 9:16 target is set.

### Process rule R-SYNC (2026-11-18, after `main` went red when pass 3 changed the glossary)
Contract documents drive generated code (enums, ids, schemas, graphs, error catalogue) and their parsing tests are blocking gates. **A PR that changes GLOSSARY_AND_IDS.md, 03, 07, 24 or any other contract document must regenerate the code in the same PR** (or the code sync must be merged first or together). Contract integrator passes therefore ship with a code-sync follow-up PR opened at the same time; until it merges, other PRs may see a red `main`. First occurrence: contract pass 3 (PR #30) → code sync PR #34.

## Known corrections to apply in the integrator pass
- Agent 14 §12: the "approved projects only" restriction belongs to the `postId` filter, not `allThreadsRelatedToChannelId` (research log A14-F5).
- Agent 13: the resumable-upload init call returns `200`, the final upload `201` (A13-F1).
- Agent 15: the four deterministic eval sets (`budget_guard`, `cost_stage_report`, `unit_economics`, `stop_scale`) have expected outputs generated by the author's own scripts; they prove consistency only and need an independent read-through before CI trusts them.
- Evals written by agents have not been run against a model.

## Owner inputs: status

| ID | Input | Status |
|---|---|---|
| A1 | VPS read-only output | **Waiting; owner will provide on 2026-11-19.** Script delivered. |
| A2 | `trade-data` + `atp-private` read access | **Received** (2026-11-18, read-only clones) |
| A3 | Research network access | **Received.** Owner switched to Custom access (2026-11-18). All research sources reachable except `github.com`, `copyright.gov.in`, `egazette.gov.in`, `indiacode.nic.in`. |
| A4 | Cloud Console quota screenshot | Waiting. Owner will send in a few days; not blocking until Agent 13 / 00b. |
| A5 | Channel Google account / Brand Account decision | Waiting (same as A4) |
| A6 | Business inputs | Partly covered: course outline found in `trade-data/research/course/`. Still needed: SEBI registration status, GST status, weekly review time, budget ceiling, narration choice, benchmark channels. |
| A7 | API keys | Not needed in this phase |

## Open questions (new since the plan; provisional default applies until the owner answers, per owner rule A.9)

| # | Question | Provisional default |
|---|---|---|
| Q21 | **Owner is making the repo private (D7); not yet confirmed.** The Media repo is **public**. The detailed private-repo inventory, the knowledge index and the raw VPS output cannot live in it. Should the Media repo become private, or should the sensitive detail live elsewhere? | Keep Media public for now. Public docs carry only aggregates. Raw VPS output is shared privately in chat. Private knowledge is read at runtime from factory private storage. **Recommendation:** make the repo private before any client work. Owner decides. |
| Q22 | Which `trade-data` windows may the channel's charts use? Trade research seals data from 2024-04-01 ("never used"), but the course spec says the owner allowed **all** data for the course. | Channel charts use **the course `data_pack` under the same allowance as the course**, and only rows older than the SEBI price-data lag at publish time (lag per research log). The factory never reads the Trade research folders (IS/VAL/HOLDOUT tooling) and never writes to `trade-data`. |
| Q23 | `trade-data` README says the BANKNIFTY daily file is cut at 2024-03-31, but its manifest shows data to 2026-10. Is this intended? | Recorded as a fact only; no action in Media. Owner to confirm whether the README is stale. |
| Q24 | Use `research/course/` (25 chapters, Marathi, speaker notes) as the course map for the video funnel and as a first script source? | Yes, read-only. Each video's end pointer maps to a course chapter (§1B.2a). Speaker notes are treated as **owner-authored source material**, still passing all gates. |
| Q25 | Book licences: are the 13 PDF / 1 EPUB / 4 PPTX owned or licensed copies? Are the 1,349 extracted page images to be ingested? | The books are used **only as concept sources for original-words teaching** (directive §1B.2a). Extracted images are **excluded** from ingestion and never shown. Licence status goes into the compliance doc as an owner item. |
| Q26 | The channel must not reveal the owner's private method beyond what the owner chooses. Which parts of `atp-private/knowledge` may appear in public videos? | Nothing from `atp-private` appears in videos by default. "Our method" topics are written only from material the owner explicitly releases per topic (S7 approval). |

## Wave A open questions (provisional defaults accepted per owner rule A.9; the owner may override)
| # | Question | Default applied |
|---|---|---|
| Q27 | Publish guard strictness | Strict: approval + editorial contribution + Agent 16 authorisation even for private upload (and for 3A delivery) |
| Q28 | `FAILED` semantics | Non-terminal hand-off; exits only to DEAD_LETTER (auto) or CANCELLED (human) |
| Q29 | Approval waits | CHECKPOINTED + `wait_reason=AWAITING_APPROVAL`, no timeout (reminders only) |
| Q30 | Backtest success-rate / unstated sponsor status | NEEDS_HUMAN_REVIEW; doc 13 may tighten to BLOCKED via CCR |
| Q31 | Audit chain throughput | Serialised per tenant; measure in pilot |
| Q32 | Comment triage `UNCLASSIFIED` class | Kept (undecided comments go to a human, never dropped) |
| Q33 | Blocked hosts for Python/UUIDv7/PostgreSQL facts | Please allow devguide.python.org, docs.python.org, www.rfc-editor.org; until then REQUIRES REVIEW |

## Book-location answers (2026-11-18) — provisional defaults (details in KNOWLEDGE_LIBRARY_PLAN.md §5)
| # | Question | Default applied |
|---|---|---|
| Q34 | How to split the sources | Three per-tenant collections: `pd_books`, `owner_strategies_notes` (restricted), `owner_books` |
| Q35 | May public-domain books be quoted at length? | No: concept-only for all collections; short attributed quotes need reviewer approval |
| Q36 | Is public-domain status verified? | No (⚖ per book/edition); treated like Q35 until verified |
| Q37 | The 3 files of 133 bytes | Excluded until the real files are provided |

## Session log
| Date | Session | Work |
|---|---|---|
| 2026-11-18 | 1 | Phase 0 done; Phase 1: audit script (+ sudo usage fix), skeleton, ledger, CR register, audit Parts A/B/D, research wave 1 complete, Knowledge Library plan; architecture Wave A launched |

## Token usage per wave (sub-agent tokens as reported by the harness; main-session usage via /cost by the owner)
| Wave / step | Agents | Sub-agent tokens | Note |
|---|---|---|---|
| Phase 1 research (wave 1 + re-runs + wave 2) | 4 (Sonnet), 2 re-runs | ≈ 680k | 73.5k + 125.7k (YouTube), 154.4k (India), 97.5k + 121.3k (infra), 107.8k (prices) |
| Wave A | 1 (Opus) | 348k | 49 min |
| Wave B-1 (first run, stopped and split) | 16 agents | ≈ 6.0M (Opus: ADRs, slice spec; Sonnet: docs + blueprints 04–09) | harness totals not yet summed per agent |
| Wave B-2 groups | biz 4 agents 598k; shared 19 agents 2.70M; blueprints 8 agents ≈ 2.9M | ≈ 6.2M | |
| Research verification (re-runs, log wave 3) | 3 agents | ≈ 0.26M | 86.5k + 171.8k |
