# Deterministic golden set — `svc_s02.uniqueness_check` (owner Agent 16)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 (S2 → 16, 24 §3.2); code package `s02_uniqueness_auditor` |
| Depends on | [blueprint](../../../agents/agent_16_compliance_qa.md) §8.3 (verdict rule), 13 §3.1 (YTG-R1), 3A_SLICE_SPEC §12 R7 |
| Files | `cases.jsonl` (20 cases), `rubric.md` |
| LLM step | **none** in 3A/3B (deterministic measures); any later LLM step needs its own prompt and dataset |

## 1. Case format
`input.fixture` gives the computed measures and context (identity flags, template text share, shot-type sequence identity, configured thresholds or null, prior-video count, comparator built, completeness, tenant flag). The harness feeds them to the verdict function; separate unit tests cover how each measure is computed from script and plan fixtures.

## 2. `expected`
`verdict` (`ALLOWED` / `BLOCKED` / `NEEDS_HUMAN_REVIEW`, or `FAILED_TASK` with the 07 code) and `checks` (check_id → expected `qc_results` verdict).

## 3. Rules exercised
Masked-structure identity ⇒ BLOCKED (YTG-R1 c); threshold null ⇒ measure WARN only; value strictly above a configured threshold ⇒ NEEDS_HUMAN_REVIEW (3A R7); cross-video `SKIPPED` below 3 prior videos, NEEDS_HUMAN_REVIEW after that until the comparator exists (13 §3.1); missing input ⇒ NEEDS_HUMAN_REVIEW; other-org reference ⇒ `PERMANENT.CROSS_TENANT_REF`; worst verdict wins.

## 4. Threshold
**100 %**. Numeric values in fixtures are test inputs, not proposed thresholds (thresholds are REQUIRES REVIEW (Phase 1), set from 3B data).
