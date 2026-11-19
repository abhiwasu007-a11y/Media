# Dry run 2: the real agents behind the real driver (PLUMBING TEST - NOT QUALITY)

Date: 2026-11-19. Branch `claude/v4-dryrun-real-agents`. Tests: `tests/dryrun/` (`harness.py`, `real_world.py`,
`test_real_agents.py`, `test_fixes.py`). No paid call, no network, no key; the content is an invented
three-sentence-style script about the shortness of time (not book text, D12). Job: non-finance
philosophy sample shape (D13), language `en-IN` (see "Not exercised").

## What runs for real

`GraphRunner`, `TaskExecutor`, every input builder, `TaskIo`, `ApprovalWorker` and the PostgreSQL task
tables; the global payload registry (36 names, nothing registered by the test); one shared
`LocalDiskStorage`; the real entry points of agent_04, agent_05, agent_06 (extraction and verification),
agent_07 (voice and master), agent_09, agent_08, agent_10 (render, subtitles, QC), agent_11, agent_16
(gate and score), the S2 uniqueness check and agent_13. Each runs over its own fakes (the agent's canned
model-response shape, tone TTS, descriptor-driven FFmpeg stubs, in-memory ports).

## How far the real chain gets today

| Result | Value |
|---|---|
| Stages COMPLETED by real agents | 16 of 19 (`s04_research` ... `s16_score`) |
| First failing stage | `a_final` (`svc_s07.request_approval`) |
| Exact error | `PERMANENT.SCHEMA_INVALID: unknown payload schema` (no `svc_s07.request_approval.input` / `.output` in the registry; CCR-283) |
| Behind the approval (run through the driver's own executor, builders and services) | `s16_auth` builder + input model real, body a stand-in; `s13_deliver` real agent_13: SUCCEEDED, bundle holds `.mp4`, `.srt`, `.png` |
| Measured | 15 real entry points, 16 task runs, 1 attempt each, about 3.9 s wall for the chain, 147 blobs written; `tests/dryrun`: 7 passed, 3 strict xfail |

## Breaks found

| # | Break | Where | Status |
|---|---|---|---|
| F1 | agent_04 wrote `attempts/<att>/output.json` itself; the driver writes the same write-once path and crashed with a raw `InputInvalidError` | agent_04 vs `TaskIo.put_output` | FIXED in agent_04 (replay copy under `checkpoints/`), CCR-285 |
| F2 | `TaskIo.put_payload` raised `IndexError` for the real agent_10 render output (all refs under `renders/`) | orchestrator | FIXED (content-addressed copy under `cache/agent_01/`), CCR-286 |
| F3 | no caller bound `DocumentGateFactExtractor` to the job and render: `MISSING_DEPENDENCY ... no tenant transaction or scope` | agent_16 assembler | FIXED (assembler binds), CCR-287 |
| F4 | builder `voice_ref` (narration timeline) has no `voice` block: `SCHEMA_INVALID voice_ref document does not match its slice` | builder agent_16 vs agent_16 slice | FIXED (`s07_voice` payload copy), CCR-287 |
| F5 | builder `render_qc_ref` (QC report rows) is not the `technical_qc.output` payload the slice requires | builder agent_16 vs agent_16 slice | FIXED (`s10_qc` payload copy), CCR-287 |
| O1 | `svc_s07.request_approval.*` not registered: the driver cannot pass `a_final` | registry | OPEN, CCR-283; strict xfail `test_the_real_chain_reaches_delivered` |
| O2 | `channels.category` value undefined: builders send `non_finance`, agent_16 compares with the stored column (`philosophy`): `INPUT_INVALID channel_category differs from channels.category` | builder vs agent_16 | OPEN, CCR-288; strict xfail |
| O3 | agent_04 hardcodes `library_languages=()`: PL11 refuses English queries for a non-English video | agent_04 | OPEN, CCR-289; strict xfail |
| O4 | job-level documents (brand kit, profile, rule packs, uniqueness template) have no registered schema; three consumers read three brand-kit shapes through ports | contracts | OPEN, CCR-290 (not verified by this run) |
| O5 | `TaskIo.put_input` / `put_output` failures escape `GraphRunner.run` as raw exceptions (job stays `RUNNING`) | orchestrator | OPEN, hardening ticket (see CCR-285) |

Test-adapter gaps (not product breaks, fixed in `real_world.py`): the agent_06 `MemoryClaims` double kept
the extraction verdict only through `register_extraction`; the agent_10 asset catalog double dropped
`attributes.template_id`; template assets need media files; the agent_16 policy double had no paraphrase
reply; its pack source loaded the finance pack for every category (the production `PackSource` must pick
by category, CCR-273 CAT-05).

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

Marathi (`mr-IN`): the canned responses are English, so the job language is `en-IN`; the Devanagari
language checks, TTS `mr-IN` and Marathi subtitles are not run. Chart scenes (`s06_chart` ran with zero
chart facts), finance jobs, revision loops, Shorts, crash-resume, real FFmpeg and TTS, the budget meter
(each real agent used its own budget and ledger double, so the per-video cap of D10 and the PostgreSQL
cost ledger were not engaged), the body of `agent_16.publication_authorisation` (needs the S7 approval,
owner-evidence and human-score rows), the real quality of any output.
