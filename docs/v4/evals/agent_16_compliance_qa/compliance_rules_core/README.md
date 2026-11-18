# Deterministic golden set — Agent 16 rule checks (`compliance_rules_core`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [blueprint](../../../agents/agent_16_compliance_qa.md) §6.1 rows 2–7a, §6.4, §10 (F-04…F-09), §6.3 (V1–V3, V11a), 13 §3.2, §3.6, §5.5–§5.7, §5.10, §5.11, 27 §6.1 (function-level datasets), CCR-024 |
| Files | `cases.jsonl` (50 cases), `rubric.md` |
| LLM step | **none** — pure functions of the gate's deterministic path (C1); no prompt file exists |
| Case IDs | component prefix `RULE-NN` (2–5 capitals, declared here per 27 §6.1); `category` carries the `eval_case_category` value |
| Answer keys | none of the directive §1B.2 answer-key cases apply (they test the policy judge); the ANSWER_KEY cases here are the 13 §5.13 S6 and 13 §5.7, §5.11 must-pass cases |

## 1. Scope
Closes the coverage gap for the deterministic rules that have no LLM step: FIN-R4, FIN-R9, FIN-R10, FIN-R11 / YTG-R2 (persona), FIN-R12, YTG-R5, YTG-R6, the deterministic part of YTG-R7 (`channels.audience_kind`) and the YTG-R3 disclosure decision order. Each case names the pure function (`function`), its argument object (`input`) and the expected rule result (`expected`). Argument objects are the minimal facts the function reads, not database rows; unit tests cover how they are derived (blueprint U-06…U-19). Ages are relative day counts (no calendar dates). Verdict mapping follows blueprint §6.3: a deterministic FAIL of a BLOCKING rule ⇒ `BLOCKED` (V3); a missing or unparseable input ⇒ `NEEDS_HUMAN_REVIEW` with a `WARN` check row (V2, never `PASS` or `SKIPPED`); a precondition that is false ⇒ `SKIPPED` with no compliance verdict (V1).

| `function` | Rule | Cases |
|---|---|---|
| `price_lag` | FIN-R9 (F-05) | RULE-01…RULE-08 |
| `disclaimer` | FIN-R10 (F-06) | RULE-09…RULE-14 |
| `method_release` | FIN-R12 (F-07) | RULE-15…RULE-19 |
| `live_format` | FIN-R4 | RULE-20…RULE-23 |
| `persona` | FIN-R11, YTG-R2 (F-08) | RULE-24…RULE-30 |
| `licence` | YTG-R5, YTG-R6 (F-04) | RULE-31…RULE-39 |
| `audience` | YTG-R7 deterministic part (V11a, CCR-081) | RULE-40…RULE-43 |
| `method_release` | FIN-R12 with a release approved by state only (CCR-102) | RULE-44 |
| `disclosure` | YTG-R3 decision order (F-09, §6.4) | RULE-45…RULE-50 |

## 2. Input schema (`agent_16.compliance_rules_core.case_input` 1.0.0, validated in CI; the shape is chosen by `function`)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_16.compliance_rules_core.case_input:1.0.0",
  "title": "Argument object per function of the deterministic rule checks (case `input`, selected by the case's `function`)",
  "oneOf": [
    {
      "$comment": "function = price_lag (F-05, FIN-R9)",
      "type": "object",
      "additionalProperties": false,
      "required": ["lag_days", "charts", "text_prices"],
      "properties": {
        "lag_days": {"type": "integer", "minimum": 1},
        "charts": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["chart_id", "age_days"],
            "properties": {"chart_id": {"type": "string"}, "age_days": {"type": ["integer", "null"], "minimum": 0}}
          }
        },
        "text_prices": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["price_ref", "has_date", "age_days"],
            "properties": {"price_ref": {"type": "string"}, "has_date": {"type": "boolean"}, "age_days": {"type": ["integer", "null"], "minimum": 0}}
          }
        }
      }
    },
    {
      "$comment": "function = disclaimer (F-06, FIN-R10)",
      "type": "object",
      "additionalProperties": false,
      "required": ["spoken_present", "onscreen_present", "template_version", "metadata_present", "description_hash_matches"],
      "properties": {
        "spoken_present": {"type": "boolean"},
        "onscreen_present": {"type": "boolean"},
        "template_version": {"type": ["string", "null"]},
        "metadata_present": {"type": "boolean"},
        "description_hash_matches": {"type": ["boolean", "null"]}
      }
    },
    {
      "$comment": "function = method_release (F-07, FIN-R12)",
      "type": "object",
      "additionalProperties": false,
      "required": ["segments", "label_overlay_present"],
      "properties": {
        "segments": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["segment_ref", "cites_method_chunk", "labelled", "release_state"],
            "properties": {
              "segment_ref": {"type": "string"},
              "cites_method_chunk": {"type": "boolean"},
              "labelled": {"type": "boolean"},
              "release_state": {"enum": ["APPROVED", "APPROVED_UNVERIFIED", "PENDING", "REJECTED", "NONE"], "description": "state of the chunk's KNOWLEDGE_RELEASE approval as derived by code from its steps (blueprint §6.5 G2/G4, CCR-102); APPROVED_UNVERIFIED = approvals.state says APPROVED but a step fails the human-row re-check"}
            }
          }
        },
        "label_overlay_present": {"type": "boolean"}
      }
    },
    {
      "$comment": "function = live_format (FIN-R4)",
      "type": "object",
      "additionalProperties": false,
      "required": ["production_type_key", "format", "metadata_terms"],
      "properties": {
        "production_type_key": {"type": "string"},
        "format": {"enum": ["STANDARD", "LIVE"]},
        "metadata_terms": {"type": ["array", "null"], "items": {"type": "string"}}
      }
    },
    {
      "$comment": "function = persona (F-08, FIN-R11 / YTG-R2)",
      "type": "object",
      "additionalProperties": false,
      "required": ["channel_sensitive", "voice", "render_assets", "thumbnail_assets"],
      "properties": {
        "channel_sensitive": {"type": "boolean"},
        "voice": {
          "oneOf": [
            {"type": "null"},
            {
              "type": "object",
              "additionalProperties": false,
              "required": ["presenter_kind"],
              "properties": {"presenter_kind": {"enum": ["NEUTRAL_NARRATION", "OWNER_VOICE", "SYNTHETIC_PERSONA"]}}
            }
          ]
        },
        "render_assets": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["shows_person", "is_realistic_synthetic"],
            "properties": {"shows_person": {"type": "boolean"}, "is_realistic_synthetic": {"type": "boolean"}}
          }
        },
        "thumbnail_assets": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["shows_person", "is_realistic_synthetic"],
            "properties": {"shows_person": {"type": "boolean"}, "is_realistic_synthetic": {"type": "boolean"}}
          }
        }
      }
    },
    {
      "$comment": "function = licence (F-04, YTG-R5 / YTG-R6)",
      "type": "object",
      "additionalProperties": false,
      "required": ["assets", "evaluate_as_destination"],
      "properties": {
        "assets": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["asset_ref", "source_kind", "has_ledger_row", "licence_state", "covers_monetized_youtube", "third_party_permission"],
            "properties": {
              "asset_ref": {"type": "string"},
              "source_kind": {"enum": ["STOCK_LICENSED", "OWNER_MADE", "CODE_GENERATED", "AI_OUTPUT", "THIRD_PARTY_OTHER"]},
              "has_ledger_row": {"type": "boolean"},
              "licence_state": {"enum": ["PENDING_VERIFICATION", "ACTIVE", "EXPIRING", "EXPIRED", "REVOKED", "REJECTED", null]},
              "covers_monetized_youtube": {"type": ["boolean", "null"]},
              "third_party_permission": {"enum": ["KNOWN", "UNKNOWN", "NOT_APPLICABLE"]}
            }
          }
        },
        "evaluate_as_destination": {"enum": ["YOUTUBE"]}
      }
    },
    {
      "$comment": "function = audience (V11a, YTG-R7 deterministic part, CCR-081)",
      "type": "object",
      "additionalProperties": false,
      "required": ["audience_kind", "kids_pack_active"],
      "properties": {
        "audience_kind": {"enum": ["GENERAL", "KIDS", null], "description": "channels.audience_kind; null = not decided"},
        "kids_pack_active": {"type": "boolean", "description": "rp.kids is in the active pack set"}
      }
    },
    {
      "$comment": "function = disclosure (F-09, YTG-R3 decision order of blueprint §6.4)",
      "type": "object",
      "additionalProperties": false,
      "required": ["assets", "realism_shots", "voice_kind"],
      "properties": {
        "assets": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["asset_ref", "tier", "is_realistic_synthetic", "realistic_person"],
            "properties": {
              "asset_ref": {"type": "string"},
              "tier": {"enum": ["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO", "E_AI_STILL"]},
              "is_realistic_synthetic": {"type": ["boolean", "null"]},
              "realistic_person": {"type": "boolean"}
            }
          }
        },
        "realism_shots": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["shot_ref", "tier", "realistic_event_depiction", "schematic", "has_origin"],
            "properties": {
              "shot_ref": {"type": "string"},
              "tier": {"enum": ["A_OWNER_REAL", "B_LICENSED_STOCK", "C_CODE_MOTION", "D_AI_VIDEO", "E_AI_STILL"]},
              "realistic_event_depiction": {"type": "boolean"},
              "schematic": {"type": ["boolean", "null"]},
              "has_origin": {"type": "boolean"}
            }
          }
        },
        "voice_kind": {"enum": ["OWNER_VOICE", "OWNER_CLONE", "NEUTRAL_TTS", "OTHER_REAL_PERSON"]}
      }
    }
  ]
}
```

## 3. `expected`
The function's result object exactly: `rule_id`, `check_verdict` (`PASS` / `FAIL` / `WARN` / `SKIPPED`), `compliance_verdict` (`ALLOWED` / `BLOCKED` / `NEEDS_HUMAN_REVIEW` / null) plus the function's extras (`price_lag`: `days_until_compliant`, the earliest-compliant-publish-date input; `disclaimer`: `description_check`, `report_label` "DRAFT, not lawyer-approved" in 3A, 3A R5; `live_format`: `metadata_check`; `licence`: one result per rule `YTG-R5` / `YTG-R6` and `expiring_assets`; `disclosure`: `{rule_id: "YTG-R3", disclosure_decision, decided_by_order}` where `decided_by_order` is the first matching row 1–3 of blueprint §6.4; `audience`: the V11a result, which the judge part V11 can only make stricter).

## 4. Threshold
**100 %** (deterministic; any failure blocks the PR). Numeric values are test inputs, not rule thresholds (the lag of 30 days is the config default of IN-02).
