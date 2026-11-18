# Deterministic golden dataset — `agent_13.upload_private` and channel authorisation

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 13 Publishing & Delivery |
| Depends on | blueprint `agents/agent_13_publishing_delivery.md` §6.2–6.5, §10.4, §10.6, §12, §18.1; 03 §9, §11; 04 §5.21; 07 §2; GLOSSARY §6.23 |
| Why this dataset exists | Agent 13 has **no LLM step** (blueprint §5); this dataset is the regression gate of 27 §6 for its deterministic decisions |
| MVP scope | **3C**, Tier 0 design; ChannelAuthService cases live at Tier 1 for client channels |
| Files | `cases.jsonl` (38 cases; no judge, no `rubric.md`) |

## 1. Case format
evals/README §2 with `input = {component, fixture}` (as the Agent 01 deterministic datasets). Fixtures are abstract: hashes are placeholder hex, org IDs synthetic, times relative (no calendar dates, owner rule C.4). No real channel, token or tenant data.

## 2. Coverage
| Cases | Rule |
|---|---|
| AK-01…EDGE-07, HN-38 | request builder: explicit `privacyStatus=private` always (YT-04, A13-F3), disclosure copied (YT-06), made-for-kids from a human decision (pending CCR-A13-1), title limit |
| POS-08…AK-12 | quota plan from YT-02 prices, whole-plan reservation, PT-day boundary (YT-03) |
| POS-13…EDGE-17, HN-36 | resumable session lifecycle (A13-F1): store before bytes, 308 resume, 5xx resumable, 404 → reconcile |
| AK-18…EDGE-22 | reconciliation: FOUND / NOT_FOUND / INCONCLUSIVE; never a second video (07 §11) |
| POS-23…EDGE-26 | processing waits without a worker; rejection; poll cap |
| EDGE-27…EDGE-29 | error mapping (A13-F5) |
| AK-30…EDGE-33, HN-37 | token refresh, revocation, granted-scope and `state` checks (A13-F7, A13-F8) |
| EDGE-34, EDGE-35 | publishing switch and channel status (G7) |

Category counts: 8 ANSWER_KEY, 18 EDGE, 3 HARD_NEGATIVE, 9 POSITIVE.

## 3. Assertions
The component's result equals `expected` on every listed key (`result`, `error_code` per 07 §2, `disposition`, `wait_reason`, `publish_state`, `status_sent`, `plan`, `outcome`, `new_upload`, `api_calls`, `verification_state`, as present). A key absent from `expected` is not asserted. `api_calls: 0` asserts that the fake recorded no call.

## 4. Thresholds
**100 %** pass; any failure blocks the PR (27 §5). ANSWER_KEY cases encode directive and D1 rules and are mandatory.

## 5. Open points
- AK-18/POS-19 assume the marker method of blueprint §6.5 is proven on a test channel (REQUIRES REVIEW (a)(b)); until then EDGE-21 is the live behaviour.
- Quota numbers follow YT-02 defaults; the Console value (A4) may change limits, not costs.
