# agent_06_fact_checker

Claim extraction (`s06_claims`) and independent verification (`s06_verify`, `s06_chart`).
Blueprint: `docs/v4/agents/agent_06_fact_checker.md`. The model proposes; code decides.

## Code-only safety net
`detect.py` scans the script's own sentences with the rule-pack lexicon, independent of what the
model extracted: FIN detectors (R1-R8, R13), future markers (D11), URL / referral (D4), the chart
age of every chart (D3, also when no claim links it). A model that returns nothing, refuses, or is
wrong cannot lower what code found. The lexicon is **data**:
`src/agent_06_fact_checker/data/finance_sebi_in.provisional.json` (English, Marathi, Hindi,
Hinglish), **provisional, REQUIRES REVIEW (owner / counsel)**. An empty lexicon, or one without the
script's language, fails with `PERMANENT.CONFIG_INVALID` before any paid call.
All matching (text and lexicon entries) goes through `lexicon.normalise_for_matching`, which now
delegates to the shared `amw_core.text_normalise` (zero-width, bidi, variation-selector, tag and
combining characters, Cyrillic look-alikes, Devanagari canonical forms).

**Judgment:** a silent model with no code hits stays ALLOWED (needed for the allowed historical
AK-01 case); it is not escalated to NEEDS_HUMAN_REVIEW merely for having no claims.

## Time of the price-data lag
D0 is evaluated at **extraction time** (a snapshot). `price_age.recheck_lag_at(range_ends,
publish_date, lag_days)` is the publish-time evaluation for Agent 16's authorisation (13 5.5); the
caller (Agent 16 / orchestrator) must invoke it, nothing in this package does at publish time.
The last bar date lookup (`ChartRanges`) is required; a measured chart without a known date is
`UNKNOWN` (blocks).

## What the tests prove, and what they do not
- Extraction eval fixtures (`tests/.../recorded_extraction.py`) are **hand-authored**, not provider
  recordings. The verification responses are **derived from each case's `expected` block**, with
  placeholder discrepancy values; judge criteria J1-J4 are not run.
- The verification harness replaces the real conflict-pair finder with the fixture's pairs (the
  finder has its own unit tests).
- `test_code_only_net.py` is the acceptance test: with the model returning nothing the answer-key
  cases and the IN-03 cases get their verdicts from code (English, Marathi, Hinglish, evasions).
- Plumbing-only extraction cases (verdict equals the hand-authored flags): AK-02..04, EDGE-12,
  13, 16-19, 21-23, 25, HN-27, MIX-30, EDGE-31; ALLOWED cases where the fixture emits no flag:
  HN-05..09, HN-11, EDGE-20, 24, HN-28, EDGE-35.
- Plumbing-only verification cases (status = the synthesised assessment): AK-01, POS-05..09,
  CON-10..13, PAR-14..16, NF-17, HN-22..24, INT-27, INT-28, MIX-36, EXT-37, CH-34. Code-checked:
  AK-02..04, REJ-41, NF-18, SKIP-30, QT-31, CH-32, RG-33, CH-38, SUB-19, TIER-20, NUM-21,
  CONF-29, INJ-25, INJ-26, REF-35, REF-39, REF-40.
- SC-2 (no false VERIFIED) is not measured against a real model.

Coverage: see `.coveragerc` in this folder.
