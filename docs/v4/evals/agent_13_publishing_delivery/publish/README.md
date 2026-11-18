# Deterministic golden dataset — `agent_13.publish`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 13 Publishing & Delivery |
| Depends on | blueprint `agents/agent_13_publishing_delivery.md` §6.6, §6.8, §10.5; 13 §5.5; 03 §9, §11; 04 §5.21; 07 §2; GLOSSARY §6.23 |
| Why this dataset exists | Agent 13 has **no LLM step** (blueprint §5); this dataset is the regression gate of 27 §6 for its deterministic decisions |
| MVP scope | **3C**, Tier 0 |
| Files | `cases.jsonl` (21 cases; no judge, no `rubric.md`) |

## 1. Case format
evals/README §2 with `input = {component, fixture}` (as the Agent 01 deterministic datasets). Fixtures are abstract: hashes are placeholder hex, org IDs synthetic, times relative (no calendar dates, owner rule C.4). No real channel, token or tenant data.

## 2. Coverage
| Cases | Rule |
|---|---|
| AK-01…EDGE-07, EDGE-19, POS-21 | status merger: complete `status` part (A13-F4), `publishAt` rules (A13-F3), only stated targets |
| EDGE-08…HN-10 | lead time; publish time vs `evaluated_publish_date` (13 §5.5) |
| AK-11, AK-12, EDGE-15 | state precondition and guard at the `PUBLISHED`/`SCHEDULED` transition; publishing switch |
| POS-13, EDGE-14 | idempotency `publish.youtube` and reconciliation of a stale key |
| EDGE-16…EDGE-18, EDGE-20 | error mapping and quota |

Category counts: 6 ANSWER_KEY, 12 EDGE, 1 HARD_NEGATIVE, 2 POSITIVE.

## 3. Assertions
The component's result equals `expected` on every listed key (`result`, `error_code` per 07 §2, `disposition`, `wait_reason`, `publish_state`, `status_sent`, `plan`, `outcome`, `new_upload`, `api_calls`, `verification_state`, as present). A key absent from `expected` is not asserted. `api_calls: 0` asserts that the fake recorded no call.

## 4. Thresholds
**100 %** pass; any failure blocks the PR (27 §5). ANSWER_KEY cases encode directive and D1 rules and are mandatory.

## 5. Open points
- The publish mode default is owner question Q-A13-2.
