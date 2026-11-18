# Deterministic golden dataset — `agent_13.file_delivery`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 13 Publishing & Delivery |
| Depends on | blueprint `agents/agent_13_publishing_delivery.md` §6.2, §6.3, §10.1–10.2; 3A_SLICE_SPEC §4; 03 §9, §11; 04 §5.21; 07 §2; GLOSSARY §6.23 |
| Why this dataset exists | Agent 13 has **no LLM step** (blueprint §5); this dataset is the regression gate of 27 §6 for its deterministic decisions |
| MVP scope | **3A**, Tier 0 (all cases); client acknowledgement (Tier 1) is tested in `verify_publication` EDGE-21 |
| Files | `cases.jsonl` (27 cases; no judge, no `rubric.md`) |

## 1. Case format
evals/README §2 with `input = {component, fixture}` (as the Agent 01 deterministic datasets). Fixtures are abstract: hashes are placeholder hex, org IDs synthetic, times relative (no calendar dates, owner rule C.4). No real channel, token or tenant data.

## 2. Coverage
| Cases | Rule |
|---|---|
| AK-01…EDGE-12 | publish guard G1–G6 (approval, editorial contribution, final ALLOWED verdict, disclosure resolved, QC_PASSED, tenant); `publishing_enabled` does not gate files |
| POS-13…EDGE-20 | bundle plan: required presets (D1 files), ≤ 3 thumbnails (YT-08), 9:16 only in the SHORTS child, S4 report present; hash and tenant checks on read |
| AK-21…EDGE-23 | idempotency `delivery.file`: replay returns stored bundle, conflict, stale key reconciled |
| AK-24, HN-25 | secret scanner (canary hit blocks; hashes and wire IDs are not secrets) |
| POS-26, EDGE-27 | disclosure statement in the QC report (13 §9 rule 2; manual Studio label note, 13 §3.3); read-back integrity |

Category counts: 6 ANSWER_KEY, 15 EDGE, 3 HARD_NEGATIVE, 3 POSITIVE.

## 3. Assertions
The component's result equals `expected` on every listed key (`result`, `error_code` per 07 §2, `disposition`, `wait_reason`, `publish_state`, `status_sent`, `plan`, `outcome`, `new_upload`, `api_calls`, `verification_state`, as present). A key absent from `expected` is not asserted. `api_calls: 0` asserts that the fake recorded no call.

## 4. Thresholds
**100 %** pass; any failure blocks the PR (27 §5). ANSWER_KEY cases encode directive and D1 rules and are mandatory.

## 5. Open points
- Presets `qc_report`, `cost_per_stage_report`, `delivery_manifest` are pending CCR-3A-2; `file_count` assumes them.
- QC/cost report file format is owner question Q-A13-1 (provisional JSON + HTML); no case depends on the format.
