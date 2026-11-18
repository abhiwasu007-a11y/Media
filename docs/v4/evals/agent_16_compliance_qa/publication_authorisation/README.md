# Deterministic golden set — `agent_16.publication_authorisation`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 16 Compliance & QA |
| Depends on | [blueprint](../../../agents/agent_16_compliance_qa.md) §6.5 (guards G0–G14, G9a), §6.6 (human-wins total, no scaling), §19.3, §23.3 (R14 evidence), §21 (SEC-R14 cases); 04 §5.16, §5.17, §5.21; 03 §11.6 rule 6; 18 §9.1; CCR-010 |
| Files | `cases.jsonl` (43 cases), `rubric.md` |
| LLM step | **none** — this task is deterministic (27 §9: "deterministic checks only"); no prompt file exists |
| Case IDs | component prefix `PA-NN` (2 capitals, declared here per 27 §6.1); `category` carries the `eval_case_category` value |
| Answer keys | none of the directive §1B.2 answer-key cases apply to this task (they test the policy judge); the cases marked ANSWER_KEY here are the R14 and §1A.7 must-pass cases |

## 1. Case format
Datasets of deterministic executors use `input = {"fixture": {…}}` (27 §6.1). The fixture below describes the **rows the guard functions read**: the approval, its steps, the contributions, the HUMAN score rows, the human verdict rows that resolve NHR items, and for each human-originated record its `approval_channel` and an `evidence` summary. The evidence summary holds the outcome of every check that guard G4 re-runs on the stored `owner_instruction_evidence` row (04 §5.16): `state`, `source_kind`, same org, `on_behalf_of` and subject match, review code, `parsed_decision` against the recorded step state, message later than the approval request, confirmation later than the message, the verifier result, the recomputed `evidence_sha256`, and the replay key. The harness materialises it as rows in a test org and runs `AuthorisationGuards.evaluate`. No calendar dates: ages are relative day counts. Machine rows respect the 3A caps (the machine owns D + J points only: 17, 12, 10, 12, 7, 8, 8, 5, total at most 79; the generator uses a base of 66); the owner's HUMAN rows complete the total (Q-O2 provisional default: no scaling).

## 2. Fixture schema (`agent_16.publication_authorisation.fixture` 1.0.0, validated in CI with the repository's JSON Schema tooling)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:agent_16.publication_authorisation.fixture:1.0.0",
  "title": "Fixture of the publication_authorisation dataset (rows the guards read)",
  "$defs": {
    "ev": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "state",
        "source_kind",
        "same_org",
        "on_behalf_of_matches",
        "subject_matches",
        "review_code_matches",
        "parsed_decision_matches",
        "message_after_request",
        "confirmation_after_message",
        "verifier_all_passed",
        "hash_recomputes",
        "replay_free"
      ],
      "properties": {
        "state": {"enum": ["PENDING_VERIFICATION", "VERIFIED", "CONFIRMED", "REFUSED"]},
        "source_kind": {"enum": ["OWNER_CHAT_MESSAGE", "TOOL_RESULT", "SUBAGENT_MESSAGE", "NOTIFICATION", "DOCUMENT"]},
        "same_org": {"type": "boolean"},
        "on_behalf_of_matches": {"type": "boolean"},
        "subject_matches": {"type": "boolean"},
        "review_code_matches": {"type": "boolean"},
        "parsed_decision_matches": {"type": ["boolean", "null"]},
        "message_after_request": {"type": "boolean"},
        "confirmation_after_message": {"type": "boolean"},
        "verifier_all_passed": {"type": "boolean"},
        "hash_recomputes": {"type": "boolean"},
        "replay_free": {"type": "boolean"}
      }
    }
  },
  "type": "object",
  "additionalProperties": false,
  "required": [
    "requested_action",
    "approval",
    "steps",
    "contributions",
    "scores",
    "gate",
    "disclosure_decision",
    "render",
    "licences",
    "fin_r9",
    "hashes_unchanged",
    "all_refs_same_org",
    "threshold"
  ],
  "properties": {
    "requested_action": {"enum": ["DELIVERY", "UPLOAD_PRIVATE", "PUBLISH"]},
    "approval": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "state", "subject_hash_matches_render", "review_code_present"],
      "properties": {
        "kind": {"enum": ["FINAL_VIDEO", "PUBLISH", "SENSITIVE_CLAIM", "COPYRIGHT_DOUBT", "SCRIPT"]},
        "state": {"enum": ["PENDING", "APPROVED", "REJECTED", "CHANGES_REQUESTED", "WITHDRAWN", "EXPIRED"]},
        "subject_hash_matches_render": {"type": "boolean"},
        "review_code_present": {"type": "boolean"}
      }
    },
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["step_no", "state", "decided_by_kind", "membership_active", "holds_required_role", "recorded_by_kind", "approval_channel", "evidence"],
        "properties": {
          "step_no": {"type": "integer", "minimum": 1},
          "state": {"enum": ["NOT_STARTED", "PENDING", "APPROVED", "REJECTED", "CHANGES_REQUESTED", "SKIPPED"]},
          "decided_by_kind": {"enum": ["HUMAN", "AGENT"]},
          "membership_active": {"type": "boolean"},
          "holds_required_role": {"type": "boolean"},
          "recorded_by_kind": {"enum": ["OPERATOR", "SELF", "AGENT"]},
          "approval_channel": {"enum": ["OWNER_CHAT_OPERATOR", "WEB_DASHBOARD", "CLIENT_PORTAL", null]},
          "evidence": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/ev"}]}
        }
      }
    },
    "contributions": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["type", "description_chars", "contributor_kind", "bound_to_this_approval", "approval_channel", "evidence"],
        "properties": {
          "type": {"enum": ["ANGLE", "EXAMPLE", "OPINION", "CORRECTION"]},
          "description_chars": {"type": "integer", "minimum": 0},
          "contributor_kind": {"enum": ["HUMAN", "AGENT"]},
          "bound_to_this_approval": {"type": "boolean"},
          "approval_channel": {"enum": ["OWNER_CHAT_OPERATOR", "WEB_DASHBOARD", "CLIENT_PORTAL", null]},
          "evidence": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/ev"}]}
        }
      }
    },
    "scores": {
      "type": "object",
      "additionalProperties": false,
      "required": ["machine", "human"],
      "properties": {
        "machine": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "RESEARCH_ACCURACY",
            "STORYTELLING",
            "AUDIENCE_VALUE",
            "VISUAL_QUALITY",
            "AUDIO_QUALITY",
            "EDITING_QUALITY",
            "THUMBNAIL_METADATA",
            "COMPLIANCE"
          ],
          "properties": {
            "RESEARCH_ACCURACY": {"type": "number", "minimum": 0},
            "STORYTELLING": {"type": "number", "minimum": 0},
            "AUDIENCE_VALUE": {"type": "number", "minimum": 0},
            "VISUAL_QUALITY": {"type": "number", "minimum": 0},
            "AUDIO_QUALITY": {"type": "number", "minimum": 0},
            "EDITING_QUALITY": {"type": "number", "minimum": 0},
            "THUMBNAIL_METADATA": {"type": "number", "minimum": 0},
            "COMPLIANCE": {"type": "number", "minimum": 0}
          }
        },
        "human": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["dimension", "points", "bound_to_render_hash", "approval_channel", "evidence"],
            "properties": {
              "dimension": {
                "enum": [
                  "RESEARCH_ACCURACY",
                  "STORYTELLING",
                  "AUDIENCE_VALUE",
                  "VISUAL_QUALITY",
                  "AUDIO_QUALITY",
                  "EDITING_QUALITY",
                  "THUMBNAIL_METADATA",
                  "COMPLIANCE"
                ]
              },
              "points": {"type": "number", "minimum": 0},
              "bound_to_render_hash": {"type": "boolean"},
              "approval_channel": {"enum": ["OWNER_CHAT_OPERATOR", "WEB_DASHBOARD", "CLIENT_PORTAL", null]},
              "evidence": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/ev"}]}
            }
          }
        }
      }
    },
    "gate": {
      "type": "object",
      "additionalProperties": false,
      "required": ["overall", "unresolved_nhr", "blocked_rows", "nhr_resolutions"],
      "properties": {
        "overall": {"enum": ["ALLOWED", "BLOCKED", "NEEDS_HUMAN_REVIEW"]},
        "unresolved_nhr": {"type": "integer", "minimum": 0},
        "blocked_rows": {"type": "integer", "minimum": 0},
        "nhr_resolutions": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["verdict_is_final", "decided_by_kind", "same_subject_hash", "approval_channel", "evidence"],
            "properties": {
              "verdict_is_final": {"type": "boolean"},
              "decided_by_kind": {"enum": ["HUMAN", "AGENT"]},
              "same_subject_hash": {"type": "boolean"},
              "approval_channel": {"enum": ["OWNER_CHAT_OPERATOR", "WEB_DASHBOARD", "CLIENT_PORTAL", null]},
              "evidence": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/ev"}]}
            }
          }
        }
      }
    },
    "disclosure_decision": {"enum": ["REQUIRED", "NOT_REQUIRED", "NEEDS_HUMAN_REVIEW"]},
    "render": {
      "type": "object",
      "additionalProperties": false,
      "required": ["status", "blocking_qc_fail"],
      "properties": {"status": {"enum": ["RENDERING", "COMPLETE", "QC_PASSED", "QC_FAILED", "SUPERSEDED"]}, "blocking_qc_fail": {"type": "integer", "minimum": 0}}
    },
    "licences": {
      "type": "object",
      "additionalProperties": false,
      "required": ["all_active", "expiring"],
      "properties": {"all_active": {"type": "boolean"}, "expiring": {"type": "integer", "minimum": 0}}
    },
    "fin_r9": {
      "type": "object",
      "additionalProperties": false,
      "required": ["latest_price_age_days_at_evaluation", "lag_days"],
      "properties": {"latest_price_age_days_at_evaluation": {"type": "integer", "minimum": 0}, "lag_days": {"type": "integer", "minimum": 0}}
    },
    "hashes_unchanged": {"type": "boolean"},
    "all_refs_same_org": {"type": "boolean"},
    "threshold": {"type": "number"}
  }
}
```

## 3. `expected`
`verdict` (`ALLOWED` / `BLOCKED`, always `is_final = true`), `failed_guards` (exact set, in guard order; G14 is `SKIPPED` in 3A and never listed), `authorised_action` (`DELIVERY` when ALLOWED, else null), `human_wins_total` (per dimension the HUMAN row **bound to the render hash** replaces the machine row; computed from the fixture by the generator, independent of G4).

Guard semantics used by the generator (blueprint §6.5): G0 requested action is `DELIVERY`; G1 approval `FINAL_VIDEO`, `APPROVED`, hash match, review code; G2 every step human, active, role, recorded by the operator or the human; G3 a contribution bound to this approval, ≥ 20 characters, human; **G4 every human-originated record used (steps, contributions bound to this approval, HUMAN scores bound to the hash, human NHR verdict rows) has channel `OWNER_CHAT_OPERATOR` and evidence that passes every check**; G5 gate `ALLOWED`, or `NEEDS_HUMAN_REVIEW` with every item resolved by a final human verdict row with valid evidence; G6 no `BLOCKED` row; G7 disclosure decided; G8 render `QC_PASSED`, no blocking QC FAIL; G9 total ≥ threshold; G9a at least one HUMAN row bound to the render hash; G10 licences active; G11 FIN-R9 age ≥ lag; G12 hashes unchanged; G13 same org.

## 4. Coverage
Positive paths (PA-01, 03, 18, 20, 23, 25), §1A.7 compliance-rejects-regardless (PA-04), approval binding (PA-05…07), contribution (PA-08, 09, 38), human-only steps (PA-10), **R14 negatives** — unconfirmed (PA-11), subagent / peer message (PA-12), document (PA-13), tool result (PA-14), no review code (PA-15), non-verbatim quote (PA-16), fabricated message (PA-29), another human (PA-30), failed confirmation (PA-31), HUMAN score without evidence (PA-32), NULL channel (PA-33), human NHR verdict without evidence (PA-34), replay (PA-35), decision mismatch (PA-36), two pending approvals on one render (PA-37), non-accepted channel (PA-42), one message for two steps (PA-43) — NHR and disclosure (PA-17…20), blocking QC (PA-21), licences (PA-22, 23), FIN-R9 boundary (PA-24, 25), subject changed (PA-26), cross-tenant (PA-27), threshold boundary (PA-02, 28), HUMAN score bound to an older hash (PA-39), requested action (PA-40), missing owner score (PA-41). The recording-side tests (event fetch, origin checks, append-only, org isolation) are integration tests with a fake session event store (blueprint §21 SEC-R14).

## 5. Threshold
**100 %** of cases (deterministic; any failure blocks the PR).
