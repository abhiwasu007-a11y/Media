# Deterministic golden dataset — Agent 01 admission, fair sharing and drain

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 01 CEO & Master Orchestrator |
| Depends on | blueprint `agents/agent_01_ceo_orchestrator.md` §6.3, §6.4, §10.4; ADR-012 §3.3; 07 §4, §8; 04 §5.1 controls, §5.4 queue; GLOSSARY §4, §6.6; RESEARCH_LOG YT-01, YT-02, YT-03 |
| Why this dataset exists | Admission is deterministic (no LLM step in Agent 01, blueprint §5) and enforces owner decision D1 (no render in market hours) and the §1 production window. |
| MVP scope | **3A**: AD-01…AD-25 (window cases AD-05…AD-14 apply only when the VPS placement is approved, ADR-012 §3.2), AD-31, AD-32 · **3C**: AD-26…AD-30 (AD-26…AD-28 enforced from Tier 1) |
| Files | `cases.jsonl` (32 cases; no judge) |

## 1. Case format
evals/README §2 with `input = {component, fixture}`; components `AdmissionPolicy`, `FairShareOrdering`, `DrainPlanner` (part of `NightScheduler`). Times are **local IST clock strings without dates** (operational settings only, owner rule C.4); the market session state and the time left to 07:00 are **precomputed** fields, so no exchange hours are encoded (their source is REQUIRES REVIEW, 3A_SLICE_SPEC R9). Fixture values are test values, not defaults.

## 2. Coverage
| Cases | Rule (blueprint §6.3 order) |
|---|---|
| AD-01…04 | A9–A10 market-hours guard on any placement; fail closed on a missing calendar; AI_IO not affected |
| AD-05…14 | A11–A13 VPS window: boundaries 00:00 (inclusive) / 06:30 / 07:00 (exclusive), remaining-time rule, provisional class coverage (06 decides) |
| AD-15…19, AD-25 | A1–A5 controls and tenant status; precedence |
| AD-20…24 | A6–A8, A14: breaker, capability, deadline, L2 pause |
| AD-26, AD-29, AD-30 | A15–A17 (3C): tenant concurrency, PT-day quota (YT-03), daily production limit |
| AD-27, AD-28 | §6.4 fair-share ordering: no starvation of a small tenant or of the platform owner |
| AD-31, AD-32 | drain path: `DRAIN` control, T09 with `wait_reason = DRAIN`, never killed mid-write |
Category counts: 2 ANSWER_KEY (directive §1 06:30 rule, D1 market hours), 3 POSITIVE, 9 HARD_NEGATIVE, 18 EDGE.

## 3. Assertions
Result equals `expected` on every listed key: `admit`, `reason` (blueprint §6.3 values), `not_before` kind, and where given `error_code` (07 §2), `attempt_consumed`, `controls`, `next_claim_org`. AD-27 / AD-28 assert only the next claim, not the 05 formula's internal numbers.

## 4. Thresholds
100 % pass; any failure blocks the PR. AD-02, AD-03, AD-09 are also run as integration tests against `amw_queue_claim` (a claim attempt in market hours or from 06:30 returns no `HEAVY_CPU` rows; ADR-012 §4 tests).

## 5. Open points
- AD-11…AD-14 encode the provisional default for window class coverage on the VPS (blueprint §6.3 note); 06_NIGHT_SCHEDULING.md decides and may change them.
- AD-26…AD-28 numeric weights and limits are owned by 05_RESOURCE_MANAGEMENT.md.
