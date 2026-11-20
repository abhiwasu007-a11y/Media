# Dry run 2: the real agents behind the real driver (PLUMBING TEST - NOT QUALITY)

Date: 2026-11-19. Branches `claude/v4-dryrun-real-agents` (run), `claude/v4-chain-complete` (CCR-283, 288, 289), `claude/v4-marathi-quotes` (this update: Marathi run, exact-quote wiring, CCR-302). Tests: `tests/dryrun/` (`harness.py`, `real_world.py`,
`test_real_agents.py`, `test_fixes.py`). No paid call, no network, no key; the content is an invented
three-sentence-style script about the shortness of time (not book text, D12). Job: non-finance
philosophy sample shape (D13), language `en-IN` (see "Not exercised").

## What runs for real

`GraphRunner`, `TaskExecutor`, every input builder, `TaskIo`, `ApprovalWorker` and the PostgreSQL task
tables; the global payload registry (38 names, nothing registered by the test); one shared
`LocalDiskStorage`; the real entry points of agent_04, agent_05, agent_06 (extraction and verification),
agent_07 (voice and master), agent_09, agent_08, agent_10 (render, subtitles, QC), agent_11, agent_16
(gate and score), the S2 uniqueness check and agent_13. Each runs over its own fakes (the agent's canned
model-response shape, tone TTS, descriptor-driven FFmpeg stubs, in-memory ports).

## How far the real chain gets today

| Result | Value |
|---|---|
| Stages COMPLETED through the driver | 19 of 19 (`s04_research` ... `s13_deliver`); job status `DELIVERED` |
| Stages run by real agents | 17 (`s04_research` ... `s16_score` and `s13_deliver`); `s16_auth` has a stand-in body (real builder and input model), `a_final` is the real `ApprovalWorker` over a test desk |
| First failing stage | none for the `en-IN` chain and none for the `mr-IN` chain (19 of 19, job `DELIVERED`; see "Marathi run") |
| Approval | `a_final` suspends (`AWAITING_APPROVAL`, payload state `PENDING`), the test desk reports the decision, the task resumes (second attempt) and its output validates against the registered `svc_s07.request_approval.output` model |
| Measured | 15 real entry points plus agent_13's delivery stage, 16 real task runs before the approval (agent_06 verification runs twice), 1 attempt per stage (2 for `a_final`), about 3.7 s wall for the whole `en-IN` chain, 157 blobs written; `tests/dryrun`: 14 passed, no xfail |

## Breaks found

| # | Break | Where | Status |
|---|---|---|---|
| F1 | agent_04 wrote `attempts/<att>/output.json` itself; the driver writes the same write-once path and crashed with a raw `InputInvalidError` | agent_04 vs `TaskIo.put_output` | FIXED in agent_04 (replay copy under `checkpoints/`), CCR-285 |
| F2 | `TaskIo.put_payload` raised `IndexError` for the real agent_10 render output (all refs under `renders/`) | orchestrator | FIXED (content-addressed copy under `cache/agent_01/`), CCR-286 |
| F3 | no caller bound `DocumentGateFactExtractor` to the job and render: `MISSING_DEPENDENCY ... no tenant transaction or scope` | agent_16 assembler | FIXED (assembler binds), CCR-287 |
| F4 | builder `voice_ref` (narration timeline) has no `voice` block: `SCHEMA_INVALID voice_ref document does not match its slice` | builder agent_16 vs agent_16 slice | FIXED (`s07_voice` payload copy), CCR-287 |
| F5 | builder `render_qc_ref` (QC report rows) is not the `technical_qc.output` payload the slice requires | builder agent_16 vs agent_16 slice | FIXED (`s10_qc` payload copy), CCR-287 |
| O1 | `svc_s07.request_approval.*` not registered: the driver could not pass `a_final` | registry | FIXED, PROVISIONAL (CCR-283 proposal registered in `amw_orchestrator.payloads`, allow-list entry `amw_orchestrator -> svc_s07`; the builder sends `{subject{kind,id,sha256}, approval_kind, workflow_key}`; the desk output is `{approval_id, approval_kind, state, subject_sha256, evidence_ids, parsed_target_stage_id}`; models, builder, round trip and fail-closed tests). The chain now reaches `DELIVERED`. Not verified: a real S7 desk (it does not exist) |
| O2 | `channels.category` value: builders sent the label `non_finance`, agent_16 compares with the stored column (`philosophy`): `INPUT_INVALID channel_category differs from channels.category` | builder vs agent_16 | FIXED for the comparison, PROVISIONAL (CCR-288 / CCR-295: `JobFacts.channel_category_row`, sent verbatim by the Agent 16 builder; a finance row on a non-finance job is refused). OPEN: what a free-text category MEANS stays fail closed (`philosophy` loads the finance pack: verdict BLOCKED in the dry run); the owner must store `non-finance` or list the category (PR 102, not merged: this change does not depend on it) |
| O3 | agent_04 hardcodes `library_languages=()`: PL11 refuses English queries for a non-English video | agent_04 | FIXED, PROVISIONAL (CCR-289: `CollectionView.languages` = distinct languages of the INDEXED sources, read in memory and in SQL, feeds `library_languages`); remainder: see "Marathi run" |
| O4 | job-level documents (brand kit, profile, rule packs, uniqueness template) have no registered schema; three consumers read three brand-kit shapes through ports | contracts | OPEN, CCR-290 (not verified by this run) |
| O5 | `TaskIo.put_input` / `put_output` failures escape `GraphRunner.run` as raw exceptions (job stays `RUNNING`) | orchestrator | OPEN, hardening ticket (see CCR-285) |
| O6 | the canned model responses of the real agents' fakes are English: the Marathi run of the whole chain stopped at `s05_script` (`a05.plan.lang`); after that the test box font had no Devanagari glyph (`s11_thumbs`) | test fixtures | FIXED in the fixtures only (SYNTHETIC invented Marathi, `tests/dryrun/marathi.py`; pinned Mukta with the Noto fallback as brand font). The strict xfail is replaced by passing tests. Product code unchanged for this break. Quality of the Marathi text is NOT shown (plumbing) |
| O7 | agent_06 `ClaimVerificationStep` sent `QUOTED_THIRD_PARTY` claims with a citation to the model for a verdict (no exact-quote check in the stage: fail OPEN) | agent_06 | FIXED, PROVISIONAL (CCR-291 verifier wired by CCR-302): a quote claim is decided by code against the library text and never by the model; with no quote check configured the task ends with a typed `MISSING_DEPENDENCY` before any paid call; `LibraryQuoteCheckFactory` builds the check from the job's library path and full commit SHA; an unreadable or modified library leaves the quote `UNVERIFIABLE` (human review). OPEN: no production loader of the private library index and records (the dry run has none: it does not exercise the quote path); agent_16 does not consume `quote_credits.json` yet (needs Agent 12 metadata, CCR-278): the credit data only reaches the gate input as a context ref |

Test-adapter gaps (not product breaks, fixed in `real_world.py`): the agent_06 `MemoryClaims` double kept
the extraction verdict only through `register_extraction`; the agent_10 asset catalog double dropped
`attributes.template_id`; template assets need media files; the agent_16 policy double had no paraphrase
reply; its pack source loaded the finance pack for every category (the production `PackSource` must pick
by category, CCR-273 CAT-05). In this update the `ApprovalDesk` test doubles (`TestDesk`) emit the CCR-283
output shape with a real approval ID and evidence ID, and the job allows two attempts for the resumed
approval task (resume = second attempt of the suspended task).

## Marathi run (`mr-IN`, synthetic content)

`run_hybrid(..., language="mr-IN")` over the real chain (`test_the_whole_real_chain_runs_for_a_marathi_job`, module fixture
`marathi_chain`): job `DELIVERED`, 19 of 19 stages COMPLETED, the same 17 real agent stages as the `en-IN` run. The canned
model answers of the fakes are SYNTHETIC invented Marathi (`tests/dryrun/marathi.py`; generic sentences about time, no
book text, D12), so the real deterministic checks of agents 05 to 16 run on Devanagari text.

| Step | History |
|---|---|
| `s04_research` | COMPLETED with English queries over the English library (CCR-289: PL11 admits the library language) |
| `s05_script` | FAILED before the fixtures (`AGENT.QUALITY_REPEATED_FAILURE`, `a05.plan.lang`: the check refused the English canned text for an `mr-IN` job; the check works, the fixture was the gap). COMPLETED with Marathi plan, section and label fixtures |
| `s11_thumbs` | the next and last break: the test box font had no Devanagari glyph. COMPLETED with the pinned Mukta (brand font for agents 08, 10, 11) and the pinned Noto Sans Devanagari fallback in agent_11 |
| `s06_claims` ... `s13_deliver` | COMPLETED |

What is checked (`test_marathi_voice_subtitles_and_thumbnails_are_devanagari_and_covered`,
`test_glyph_check_refuses_a_devanagari_code_point_the_pinned_font_lacks_and_noto_supplies`): agent_07 receives `mr-IN`;
the subtitle SRT has `mr-IN` cues in Devanagari; every code point of them is in the pinned Mukta cmap
(`amw_core.font_coverage`); agent_11 produces 3 Marathi variants; U+0978 (absent from Mukta, present in Noto) is
refused with Mukta alone, covered with the fallback and drawn by it, and a code point in neither font stays uncovered.

What this does NOT show: any quality of Marathi text, TTS `mr-IN` (tone TTS stub), real FFmpeg rendering of
Devanagari, or shaping. The glyph check compares cmap code points only: it does not prove that a conjunct or matra
is shaped correctly (agent_11 renders with Raqm, but the dry run has no pixel check of Marathi text). Subtitle line
breaking (`agent_10` `CueBuilder`) splits at spaces only and counts code points, not grapheme clusters or rendered width:
no word is ever cut, so no conjunct or matra is split (`test_long_marathi_cue_is_split_at_spaces_and_never_inside_a_conjunct_or_matra`);
a word longer than the limit stays whole on its own line with an `OVERLONG_TOKEN` warning
(`test_marathi_token_longer_than_the_limit_is_kept_whole_with_a_warning`).

## Shapes verified end to end (real producer output read by the real consumer)

agent_04 pack to agent_05 (`ResearchPackView`); agent_05 script to agent_06 extraction, agent_07
(`ScriptDocument`), agent_09, agent_10 (`ScriptDocumentSlice`), agent_11 (promise and brief), agent_16
extractors; agent_06 extraction / verification documents to agent_07 and agent_16; agent_07 timeline to
agent_09; agent_09 plan (template IDs) to agent_08 and agent_10; agent_08 manifest, template assets and
licence ledger to agent_10 render and QC; agent_10 QC and evidence manifest to agent_16; agent_11 manifest
to the S2 check and agent_16; all real outputs to agent_13 (zip and manifest).

## Ports with no production implementation (the dry run uses in-memory adapters)

agent_05 `InputResolver`, `ScriptRowPort`; agent_06 `ClaimStore`, `ScriptRegistry`, `KnowledgeReader`;
agent_07 `FactsReader`, `NarrationRegistry`; agent_08 `BrandKitReader`, `JobDestinationReader`; agent_09
`PlanInputPorts`; agent_10 `AssetCatalog`, `LicenceReader`, `RenderRepository`, `QcResultRepository`;
agent_11 `ThumbnailRepository`; agent_16 `FactRowReader`, `PrivateChunkReader`, `PackSource`,
`ScoreStore`, `GroupRequestBuilder`, the approval repository; S7 `ApprovalDesk`.

## Not exercised / not verified

Marathi quality, real Devanagari TTS / FFmpeg / shaping (see "Marathi run"), the exact-quote path in the chain (the dry run script has no library quote), a real S7 approval desk (the output shape is the PROVISIONAL
CCR-283 proposal; the desk is a test double), the real meaning of a free-text channel category (CCR-295, PR 102),
chart scenes (`s06_chart` ran with zero chart facts), finance jobs, revision loops, Shorts, crash-resume, real
FFmpeg and TTS, the budget meter (each real agent used its own budget and ledger double, so the per-video cap of
D10 and the PostgreSQL cost ledger were not engaged), the body of `agent_16.publication_authorisation` (needs the S7
approval, owner-evidence and human-score rows), the real quality of any output.
