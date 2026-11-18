# Deterministic golden dataset — `agent_13.verify_publication`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 13 Publishing & Delivery |
| Depends on | blueprint `agents/agent_13_publishing_delivery.md` §6.7, §8.4, §10.5; 03 J07; 03 §9, §11; 04 §5.21; 07 §2; GLOSSARY §6.23 |
| Why this dataset exists | Agent 13 has **no LLM step** (blueprint §5); this dataset is the regression gate of 27 §6 for its deterministic decisions |
| MVP scope | **3C**, Tier 0; POS-20 also covers the 3A file read-back; EDGE-21 Tier 1 |
| Files | `cases.jsonl` (21 cases; no judge, no `rubric.md`) |

## 1. Case format
evals/README §2 with `input = {component, fixture}` (as the Agent 01 deterministic datasets). Fixtures are abstract: hashes are placeholder hex, org IDs synthetic, times relative (no calendar dates, owner rule C.4). No real channel, token or tenant data.

## 2. Coverage
| Cases | Rule |
|---|---|
| AK-01…EDGE-12, HN-09, HN-14, EDGE-19 | field comparison: privacy, `publishAt` as instants, exact title, disclosure flag, made-for-kids, upload status |
| EDGE-13, EDGE-15, EDGE-16 | errors, phase validity, tenant |
| AK-17, POS-18 | job outcome `PUBLISHED` only after `VERIFIED` (03 J07) |
| POS-20, EDGE-21 | file delivery: `DELIVERED` on hash match; `VERIFIED` only on client acknowledgement (GLOSSARY §6.23) |

Category counts: 4 ANSWER_KEY, 11 EDGE, 2 HARD_NEGATIVE, 4 POSITIVE.

## 3. Assertions
The component's result equals `expected` on every listed key (`result`, `error_code` per 07 §2, `disposition`, `wait_reason`, `publish_state`, `status_sent`, `plan`, `outcome`, `new_upload`, `api_calls`, `verification_state`, as present). A key absent from `expected` is not asserted. `api_calls: 0` asserts that the fake recorded no call.

## 4. Thresholds
**100 %** pass; any failure blocks the PR (27 §5). ANSWER_KEY cases encode directive and D1 rules and are mandatory.

## 5. Open points
- Made-for-kids comparison depends on CCR-A13-1.
