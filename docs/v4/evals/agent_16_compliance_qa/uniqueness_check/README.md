# Deterministic golden set — `svc_s02.uniqueness_check` (owner Agent 16)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 (S2 → 16, 24 §3.2); code package `s02_uniqueness_auditor` |
| Depends on | [blueprint](../../../agents/agent_16_compliance_qa.md) §8.3 (verdict rule), §20 (`a16.uniq.*` check IDs), 13 §1.2, §3.1 (YTG-R1; 3A deterministic parts, 3C cross-video), 3A_SLICE_SPEC §12 R7, CCR-058 |
| Files | `cases.jsonl` (20 cases), `rubric.md` |
| Case IDs | component prefix `UQ-NN` (2 capitals, declared here per 27 §6.1); `category` carries the `eval_case_category` value |
| Answer keys | none of the directive §1B.2 answer-key cases apply (they test the policy judge); UQ-02 and UQ-03 are the 13 §3.1 must-pass identity cases |
| LLM step | **none** in 3A/3B (deterministic measures); any later LLM step needs its own prompt and dataset |

## 1. Case format
`input.fixture` gives the computed measures and context (identity flags, template text share, shot-type sequence identity, configured thresholds or null, prior-video count, comparator built, completeness, tenant flag). The harness feeds them to the verdict function; separate unit tests cover how each measure is computed from script and plan fixtures. The fixture schema is below and is validated in CI.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:svc_s02.uniqueness_check.fixture:1.0.0",
  "title": "Fixture of the uniqueness_check dataset (computed measures and context)",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "masked_structure_identical_to_template",
    "masked_structure_identical_to_prior_video",
    "template_text_share",
    "section_role_sequence_equal_to_template",
    "shot_type_sequence_identity",
    "thresholds",
    "prior_videos_on_channel",
    "cross_video_comparator_built",
    "inputs_complete",
    "refs_same_org"
  ],
  "properties": {
    "masked_structure_identical_to_template": {"type": "boolean"},
    "masked_structure_identical_to_prior_video": {"type": "boolean"},
    "template_text_share": {"type": "number", "minimum": 0, "maximum": 1},
    "section_role_sequence_equal_to_template": {"type": "boolean"},
    "shot_type_sequence_identity": {"type": "number", "minimum": 0, "maximum": 1},
    "thresholds": {
      "type": "object",
      "additionalProperties": false,
      "required": ["template_text_share", "shot_type_sequence_identity", "cross_video_similarity"],
      "properties": {
        "template_text_share": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "shot_type_sequence_identity": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "cross_video_similarity": {"type": ["number", "null"], "minimum": 0, "maximum": 1}
      }
    },
    "prior_videos_on_channel": {"type": "integer", "minimum": 0},
    "cross_video_comparator_built": {"type": "boolean"},
    "cross_video_max_similarity": {"type": "number", "minimum": 0, "maximum": 1},
    "inputs_complete": {"type": "boolean"},
    "refs_same_org": {"type": "boolean"}
  }
}
```

## 2. `expected`
`verdict` (`ALLOWED` / `BLOCKED` / `NEEDS_HUMAN_REVIEW`, or `FAILED_TASK` with the 07 code), `checks` (check_id → expected `qc_results` verdict; IDs are the `a16.uniq.*` IDs of blueprint §20; a result that routes to a human is `WARN` with `blocking: false`, 03 §5.3 rule 5) and, for `BLOCKED`, `remedy_stage_id` = the script stage (the gate's target).

## 3. Rules exercised
Masked-structure identity ⇒ BLOCKED (YTG-R1 c); threshold null ⇒ measure WARN only; value strictly above a configured threshold ⇒ NEEDS_HUMAN_REVIEW (3A R7); cross-video `SKIPPED` below 3 prior videos, NEEDS_HUMAN_REVIEW after that until the comparator exists (13 §3.1); missing input ⇒ NEEDS_HUMAN_REVIEW; other-org reference ⇒ `PERMANENT.CROSS_TENANT_REF`; worst verdict wins.

## 4. Threshold
**100 %**. Numeric values in fixtures are test inputs, not proposed thresholds (thresholds are REQUIRES REVIEW (Phase 1), set from 3B data).
