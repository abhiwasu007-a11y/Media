# Dry run 2: the real agents behind the real driver (PLUMBING TEST - NOT QUALITY)

Date: 2026-11-19. Branches `claude/v4-dryrun-real-agents` (run), `claude/v4-chain-complete` (this update: CCR-283, 288, 289). Tests: `tests/dryrun/` (`harness.py`, `real_world.py`,
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
| First failing stage | none for the `en-IN` chain. For an `mr-IN` job the first failing stage is `s05_script` (see "Marathi run") |
| Approval | `a_final` suspends (`AWAITING_APPROVAL`, payload state `PENDING`), the test desk reports the decision, the task resumes (second attempt) and its output validates against the registered `svc_s07.request_approval.output` model |
| Measured | 15 real entry points plus agent_13's delivery stage, 16 real task runs before the approval (agent_06 verification runs twice), 1 attempt per stage (2 for `a_final`), about 3.7 s wall for the whole chain, 157 blobs written; `tests/dryrun`: 12 passed, 1 strict xfail |

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
| O6 | the canned model responses of the real agents' fakes are English: the Marathi run of the whole chain stops at `s05_script` | test fixtures | OPEN, strict xfail `test_the_whole_real_chain_runs_for_a_marathi_job` (CCR-289 remainder) |

Test-adapter gaps (not product breaks, fixed in `real_world.py`): the agent_06 `MemoryClaims` double kept
the extraction verdict only through `register_extraction`; the agent_10 asset catalog double dropped
`attributes.template_id`; template assets need media files; the agent_16 policy double had no paraphrase
reply; its pack source loaded the finance pack for every category (the production `PackSource` must pick
by category, CCR-273 CAT-05). In this update the `ApprovalDesk` test doubles (`TestDesk`) emit the CCR-283
output shape with a real approval ID and evidence ID, and the job allows two attempts for the resumed
approval task (resume = second attempt of the suspended task).

## Marathi run (`mr-IN`, synthetic content)

`run_hybrid(..., language="mr-IN")` over the real chain (`test_the_marathi_run_stops_where_the_report_says_it_stops`):

| Stage | Result |
|---|---|
| `s04_research` | COMPLETED with English queries over the English library (CCR-289: PL11 admits the library language; before the fix `OUTPUT_SCHEMA_INVALID plan failed the deterministic checks`) |
| `s05_script` | FAILED `AGENT.QUALITY_REPEATED_FAILURE: deterministic checks still fail after the repair`, checks `a05.plan.lang` and `a05.plan.selection`: agent_05's language check refuses the English text of its canned model response for an `mr-IN` job (the check works; the fixture is the gap) |
| `s06_claims` ... `s13_deliver` | not reached |

What this does and does not show: the `mr-IN` builder inputs of `s04_research` and `s05_script` validate, and agent_04
works with a non-English video over an English library. It does not show anything about Devanagari handling in agents
06 to 16, TTS `mr-IN`, Marathi subtitles or Marathi QC: those need Marathi canned responses (synthetic, not book text)
for every real agent, which the fakes do not have. Next step: Marathi fixtures per agent, one agent at a time, starting
with agent_05 (plan, sections), then 06, 07, 10.

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

Marathi beyond `s04_research` (see "Marathi run"), a real S7 approval desk (the output shape is the PROVISIONAL
CCR-283 proposal; the desk is a test double), the real meaning of a free-text channel category (CCR-295, PR 102),
chart scenes (`s06_chart` ran with zero chart facts), finance jobs, revision loops, Shorts, crash-resume, real
FFmpeg and TTS, the budget meter (each real agent used its own budget and ledger double, so the per-video cap of
D10 and the PostgreSQL cost ledger were not engaged), the body of `agent_16.publication_authorisation` (needs the S7
approval, owner-evidence and human-score rows), the real quality of any output.
