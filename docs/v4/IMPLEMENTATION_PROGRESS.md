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
| P1.5b | Research wave 2: vendor prices and licences (Anthropic, ElevenLabs, Storyblocks, others) | In progress | RESEARCH_LOG.md | — | — | R7 |
| P1.7 | Knowledge Library ingestion plan (generic) + owner needs K1–K8 | Done (2026-11-18) | KNOWLEDGE_LIBRARY_PLAN.md | self-review | Book location (K1) | R4 |
| W-A | Architecture Wave A (foundation docs) | In progress (1 agent) | branch `claude/v4-wave-a` | — | — | R6 |
| W-B | Architecture Wave B (17 blueprints + shared docs + ADRs) | Not started | — | — | W-A | R6 |
| W-C | Architecture Wave C (independent verification, backlog, completion report) | Not started | — | — | W-B | R6 |
| P1.6 | Technical feasibility | Not started | 00b_TECHNICAL_FEASIBILITY.md | — | P1.4 Part C, research wave 2 (prices) | R3, R7 |

## Owner inputs: status

| ID | Input | Status |
|---|---|---|
| A1 | VPS read-only output | **Waiting.** Script delivered; one consolidated command given. |
| A2 | `trade-data` + `atp-private` read access | **Received** (2026-11-18, read-only clones) |
| A3 | Research network access | **Received.** Owner switched to Custom access (2026-11-18). All research sources reachable except `github.com`, `copyright.gov.in`, `egazette.gov.in`, `indiacode.nic.in`. |
| A4 | Cloud Console quota screenshot | Waiting. Owner will send in a few days; not blocking until Agent 13 / 00b. |
| A5 | Channel Google account / Brand Account decision | Waiting (same as A4) |
| A6 | Business inputs | Partly covered: course outline found in `trade-data/research/course/`. Still needed: SEBI registration status, GST status, weekly review time, budget ceiling, narration choice, benchmark channels. |
| A7 | API keys | Not needed in this phase |

## Open questions (new since the plan; provisional default applies until the owner answers, per owner rule A.9)

| # | Question | Provisional default |
|---|---|---|
| Q21 | The Media repo is **public**. The detailed private-repo inventory, the knowledge index and the raw VPS output cannot live in it. Should the Media repo become private, or should the sensitive detail live elsewhere? | Keep Media public for now. Public docs carry only aggregates. Raw VPS output is shared privately in chat. Private knowledge is read at runtime from factory private storage. **Recommendation:** make the repo private before any client work. Owner decides. |
| Q22 | Which `trade-data` windows may the channel's charts use? Trade research seals data from 2024-04-01 ("never used"), but the course spec says the owner allowed **all** data for the course. | Channel charts use **the course `data_pack` under the same allowance as the course**, and only rows older than the SEBI price-data lag at publish time (lag per research log). The factory never reads the Trade research folders (IS/VAL/HOLDOUT tooling) and never writes to `trade-data`. |
| Q23 | `trade-data` README says the BANKNIFTY daily file is cut at 2024-03-31, but its manifest shows data to 2026-10. Is this intended? | Recorded as a fact only; no action in Media. Owner to confirm whether the README is stale. |
| Q24 | Use `research/course/` (25 chapters, Marathi, speaker notes) as the course map for the video funnel and as a first script source? | Yes, read-only. Each video's end pointer maps to a course chapter (§1B.2a). Speaker notes are treated as **owner-authored source material**, still passing all gates. |
| Q25 | Book licences: are the 13 PDF / 1 EPUB / 4 PPTX owned or licensed copies? Are the 1,349 extracted page images to be ingested? | The books are used **only as concept sources for original-words teaching** (directive §1B.2a). Extracted images are **excluded** from ingestion and never shown. Licence status goes into the compliance doc as an owner item. |
| Q26 | The channel must not reveal the owner's private method beyond what the owner chooses. Which parts of `atp-private/knowledge` may appear in public videos? | Nothing from `atp-private` appears in videos by default. "Our method" topics are written only from material the owner explicitly releases per topic (S7 approval). |

## Session log
| Date | Session | Work |
|---|---|---|
| 2026-11-18 | 1 | Phase 0 done; Phase 1: audit script (+ sudo usage fix), skeleton, ledger, CR register, audit Parts A/B/D, research wave 1 complete, Knowledge Library plan; architecture Wave A launched |
