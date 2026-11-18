# 24 — Production Types Registry

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** (every production type below has feature status **Planned**) |
| Owner | Agent 01 (registry loader, graph execution); content owners: Agent 03 (owner channels), Agent 17 (client and ad types), S3 → 05 (dubbing) |
| Depends on | GLOSSARY_AND_IDS.md (§6.15, 6.37, 6.48–6.50), 03_COMMUNICATION_STANDARD.md (§11), 04_DATABASE_ARCHITECTURE.md (§5.2 production_types, org_production_types), 07_FAILURE_MANAGEMENT.md (§9), 18_PRODUCTION_QUALITY_STANDARD.md and 25_ADVERTISING_COMPLIANCE.md (not yet written; values pending), RESEARCH_LOG.md (INF-09, INF-10, YT-04, YT-06, YT-08, YT-15) |
| Directive sections covered | §3.4 (registry), §1A.1–1A.8 (sourcing, edit, audio/video spec, QC, formats), §1A.11 (AI B-roll budget), §1B.2 (finance rules), §1C.7 (rule packs), §1D (ad workflow and checks), §1E.3 (dubbing) |
| Tier | `CHANNEL_LONG_FORM` and `SHORTS`: Tier 0. 3A (D1) runs `CHANNEL_LONG_FORM` **v2** and, only where the owner asks for the 9:16 cut, `SHORTS` **v2** as a child job (§7.1a, §7.2a; CCR-003); a 9:16 cut "validated for upload" is 3C. `EXPLAINER_CORPORATE_TRAINING`, `DUBBING_LOCALISATION`: Tier 1. `AD_SPOT`, `ECOMMERCE_PRODUCT`: built when the first ad client is signed (directive §5.7; plan Q17), Tier 1+. |

---

## 1. Purpose
One registry defines every product the platform makes, so a new business line is configuration plus templates, not a new pipeline (§3.4). The orchestrator executes only graphs declared here (§2 of the directive: control flow in code). Each record is stored as an immutable row in `production_types` (04 §5.2), validated against the record schema `amw.production_type` 1.0.0 (§2).

## 2. Registry record format (`amw.production_type` 1.0.0)
| Field | Type | Required | Tenant-overridable | Meaning |
|---|---|---|---|---|
| `key` | `production_type_key` | yes | no | GLOSSARY §6.48 |
| `version` | int ≥ 1 | yes | no | a change is a new version |
| `display_name` | string | yes | yes (label only) | |
| `status` | `feature_status` | yes | no | rule 7 |
| `first_tier` | `tier` | yes | no | |
| `destinations` | array of `destination_kind` | yes | subset only | `YOUTUBE`, `FILE_DELIVERY` |
| `requires_channel` | bool | yes | no | job needs `channel_id` |
| `parent_input` | `NONE` / `PARENT_JOB` / `SOURCE_VIDEO` | yes | no | Shorts may derive from a long-form job; dubbing needs a source video |
| `duration_targets_ms` | object `{min, max}` or array of exact values | yes | within registry bounds | |
| `aspect_ratios` | array of `aspect_ratio` | yes | subset only | |
| `languages` | `SINGLE` / `MULTI` | yes | no | |
| `stages` | array of Stage (§3.1) | yes | only `optional` stages may be enabled/disabled | the task graph |
| `required_inputs` | array of `{key, description, input_schema, provided_by: OWNER/CLIENT/SYSTEM}` | yes | add only | job validation J02 |
| `approvals` | array of `{approval_kind, workflow_key, mandatory}` | yes | add steps/approvals; never remove `mandatory` | §3.4 |
| `templates` | array of template keys | yes | yes (tenant templates) | brand-consistent templates, content varies per video (§1A.1c) |
| `qc_profile` | QC profile key (§5) | yes | stricter only | |
| `rule_packs` | `{mandatory: [...], by_category: {...}}` | yes | add only | platform packs cannot be removed (§1C.7) |
| `deliverables` | array of export preset keys (§4) | yes | add only | |
| `cost_model` | array of cost components (§6) | yes | no | |
| `default_price` | `{amount_minor, currency, label: PROPOSAL}` | yes | per plan (T2) | **REQUIRES REVIEW (Phase 1): 21_PRICING_AND_PACKAGING** |
| `limits` | `{max_revision_loops}` | yes | lower only (ceiling 07 §9) | |

Capabilities (CCR-064): each stage lists the worker capabilities its task type needs (GLOSSARY §6.20); the v2 tables below state them. Stage `params` (CCR-075) used in v2: `s06_chart` `{"verify_mode": "CHART_FACTS"}`; `s08_assets` `{"script_stage_id": "s05_script"}` (`"s05_shorts"` in `SHORTS`), so a `DATA_WITHIN_LAG` result can name the script stage as `remedy_stage_id`.

Validation at load: schema valid; every `task_type` exists in the task-type catalogue (§3.2); the stage graph is a DAG; every gate's `on_fail` target and every `alt_target_stage_ids` entry precedes the gate (is a transitive dependency of it); every mandatory approval has a workflow; `rp.youtube_general` is mandatory whenever `YOUTUBE` is a destination.

### 2.1 Record schema (`amw.production_type` 1.0.0, CCR-057)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:amw:schema:amw.production_type:1.0.0",
  "title": "AMW production type record",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "key", "version", "display_name", "status", "first_tier", "destinations", "requires_channel",
               "parent_input", "duration_targets_ms", "aspect_ratios", "languages", "stages", "required_inputs",
               "approvals", "templates", "qc_profile", "rule_packs", "deliverables", "cost_model",
               "default_price", "limits"],
  "properties": {
    "schema_version": { "type": "string", "pattern": "^1\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$", "description": "version of this record schema (CCR-067); `version` is the record's own version" },
    "key": { "enum": ["CHANNEL_LONG_FORM", "SHORTS", "AD_SPOT", "EXPLAINER_CORPORATE_TRAINING", "ECOMMERCE_PRODUCT", "DUBBING_LOCALISATION"] },
    "version": { "type": "integer", "minimum": 1 },
    "display_name": { "type": "string", "minLength": 1, "maxLength": 120 },
    "status": { "enum": ["PLANNED", "IN_DEVELOPMENT", "IMPLEMENTED", "TESTED", "PRODUCTION_READY"] },
    "first_tier": { "enum": ["TIER_0", "TIER_1", "TIER_2", "TIER_3"] },
    "destinations": { "type": "array", "minItems": 1, "uniqueItems": true, "items": { "enum": ["YOUTUBE", "FILE_DELIVERY"] } },
    "requires_channel": { "type": "boolean" },
    "parent_input": { "enum": ["NONE", "PARENT_JOB", "SOURCE_VIDEO"] },
    "duration_targets_ms": {
      "oneOf": [
        { "type": "object", "additionalProperties": false, "required": ["min", "max"],
          "properties": { "min": { "type": ["integer", "null"], "minimum": 0 }, "max": { "type": ["integer", "null"], "minimum": 0 } } },
        { "type": "array", "minItems": 1, "uniqueItems": true, "items": { "type": "integer", "minimum": 1 } }
      ]
    },
    "aspect_ratios": { "type": "array", "minItems": 1, "uniqueItems": true, "items": { "enum": ["16:9", "9:16", "1:1", "4:5"] } },
    "languages": { "enum": ["SINGLE", "MULTI"] },
    "stages": { "type": "array", "minItems": 1, "maxItems": 64, "items": { "$ref": "#/$defs/stage" } },
    "required_inputs": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["key", "description", "input_schema", "provided_by"],
        "properties": {
          "key": { "type": "string", "pattern": "^[a-z0-9_]{2,48}$" },
          "description": { "type": "string", "maxLength": 500 },
          "input_schema": { "oneOf": [ { "type": "string", "pattern": "^[a-z0-9_]+(\\.[a-z0-9_]+)+$" }, { "type": "null" } ] },
          "provided_by": { "enum": ["OWNER", "CLIENT", "SYSTEM"] }
        }
      }
    },
    "approvals": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["approval_kind", "workflow_key", "mandatory"],
        "properties": {
          "approval_kind": { "$ref": "#/$defs/approval_kind" },
          "workflow_key": { "enum": ["owner_one_tap", "client_two_step", "owner_sensitive"] },
          "mandatory": { "type": "boolean" }
        }
      }
    },
    "templates": { "type": "array", "items": { "type": "string", "pattern": "^[a-z0-9_.]{2,64}$" } },
    "qc_profile": { "type": "string", "pattern": "^qc\\.[a-z_]{2,32}$" },
    "rule_packs": {
      "type": "object", "additionalProperties": false, "required": ["mandatory", "by_category"],
      "properties": {
        "mandatory": { "type": "array", "uniqueItems": true, "items": { "$ref": "#/$defs/rule_pack_key" } },
        "by_category": { "type": "object", "propertyNames": { "pattern": "^[a-z_]{2,32}$" },
                         "additionalProperties": { "type": "array", "items": { "$ref": "#/$defs/rule_pack_key" } } }
      }
    },
    "deliverables": { "type": "array", "minItems": 1, "items": { "type": "string", "pattern": "^[a-z0-9_<>]{2,64}$" } },
    "cost_model": {
      "type": "array",
      "items": {
        "type": "object", "additionalProperties": false, "required": ["component", "unit"],
        "properties": {
          "component": { "type": "string", "pattern": "^[a-z0-9_]{2,48}$" },
          "unit": { "type": "string", "maxLength": 32 },
          "note": { "type": "string", "maxLength": 300 }
        }
      }
    },
    "default_price": {
      "oneOf": [
        { "type": "null" },
        { "type": "object", "additionalProperties": false, "required": ["amount_minor", "currency", "label"],
          "properties": {
            "amount_minor": { "type": ["integer", "null"], "minimum": 0 },
            "currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
            "label": { "const": "PROPOSAL" } } }
      ]
    },
    "limits": {
      "type": "object", "additionalProperties": false, "required": ["max_revision_loops"],
      "properties": { "max_revision_loops": { "type": "integer", "minimum": 0, "maximum": 10 } }
    }
  },
  "$defs": {
    "stage_id": { "type": "string", "pattern": "^[a-z0-9_]{2,32}$" },
    "rule_pack_key": { "type": "string", "pattern": "^rp\\.[a-z0-9_]+$" },
    "approval_kind": { "enum": ["TOPIC", "BRIEF", "CONCEPT", "SCRIPT", "STORYBOARD", "VOICE_SAMPLE", "ROUGH_CUT", "FINAL_VIDEO",
                                "THUMBNAIL", "METADATA", "PUBLISH", "SPEND", "NEW_CHANNEL", "NEW_CATEGORY", "SENSITIVE_CLAIM",
                                "COPYRIGHT_DOUBT", "UNUSUAL_PUBLISH", "POLICY_CHANGE", "DLQ_REPLAY", "EXPERIMENT", "COMMENT_REPLY",
                                "KNOWLEDGE_RELEASE", "USAGE_RIGHTS"] },
    "stage": {
      "type": "object", "additionalProperties": false,
      "required": ["stage_id", "task_type", "required", "resource_class", "capabilities", "depends_on", "gate", "approval"],
      "properties": {
        "stage_id": { "$ref": "#/$defs/stage_id" },
        "task_type": { "type": "string", "pattern": "^(agent_(0[1-9]|1[0-7])|svc_s(0[1-9]|1[0-3]))\\.[a-z0-9_]+$" },
        "required": { "type": "boolean" },
        "enabled_by_default": { "type": "boolean" },
        "resource_class": { "enum": ["LIGHT", "AI_IO", "HEAVY_CPU", "PUBLISH"] },
        "capabilities": { "type": "array", "uniqueItems": true,
          "items": { "enum": ["llm", "tts", "image_gen", "video_gen", "stock_search", "music_search", "render_ffmpeg", "media_probe",
                              "doc_extract", "web_fetch", "publish_youtube", "file_delivery", "analytics_ingest", "notify_email"] } },
        "depends_on": { "type": "array", "uniqueItems": true, "items": { "$ref": "#/$defs/stage_id" } },
        "gate": {
          "oneOf": [
            { "type": "null" },
            { "type": "object", "additionalProperties": false, "required": ["blocking", "on_fail"],
              "properties": {
                "blocking": { "const": true },
                "on_fail": {
                  "oneOf": [
                    { "type": "object", "additionalProperties": false, "required": ["action", "target_stage_id"],
                      "properties": { "action": { "const": "REVISE" }, "target_stage_id": { "$ref": "#/$defs/stage_id" },
                                      "alt_target_stage_ids": { "type": "array", "uniqueItems": true, "items": { "$ref": "#/$defs/stage_id" } } } },
                    { "type": "object", "additionalProperties": false, "required": ["action"],
                      "properties": { "action": { "const": "STOP" } } }
                  ]
                }
              } }
          ]
        },
        "approval": {
          "oneOf": [
            { "type": "null" },
            { "type": "object", "additionalProperties": false, "required": ["approval_kind", "workflow_key"],
              "properties": { "approval_kind": { "$ref": "#/$defs/approval_kind" },
                              "workflow_key": { "enum": ["owner_one_tap", "client_two_step", "owner_sensitive"] } } }
          ]
        },
        "params": { "type": "object", "maxProperties": 16 }
      }
    }
  }
}
```
Rules not expressible in the schema are checked at load (validation list above): DAG, task types in §3.2, on_fail and alt targets are ancestors, mandatory approvals have workflows, `rp.youtube_general` mandatory with a `YOUTUBE` destination, `limits.max_revision_loops` ≤ the 07 §9 ceiling.

## 3. Task graph

### 3.1 Stage object
| Field | Meaning |
|---|---|
| `stage_id` | unique within the record (e.g. `s06_claims`) |
| `task_type` | canonical task type (§3.2) |
| `required` | false = optional stage, enabled per tenant/job |
| `resource_class` | `LIGHT` / `AI_IO` / `HEAVY_CPU` / `PUBLISH` |
| `capabilities` | worker capabilities needed (GLOSSARY §6.20) |
| `depends_on` | list of `stage_id` |
| `gate` | optional `{blocking: true, on_fail: {action: REVISE, target_stage_id, alt_target_stage_ids?: [stage_id, …]} | {action: STOP}}`. `alt_target_stage_ids` (CCR-002) lists the other stages a failing result may name as `remedy_stage_id` (03 §5.3 rule 4) |
| `approval` | optional `{approval_kind, workflow_key}`; the stage is then an S7 approval gate (03 §11.6) |
| `enabled_by_default` | optional stages only: whether the stage runs unless the tenant/job disables it (CCR-057) |
| `params` | optional small object of stage parameters that the orchestrator's input builder passes into the task payload (e.g. `{"verify_mode": "CHART_FACTS"}` for `s06_chart`; CCR-004/057) |

### 3.2 Canonical task types (names are contract-bound; payload schemas are defined in the agent blueprints)
| Task type | Owner | Purpose |
|---|---|---|
| `agent_02.trend_scan` | 02 | optional topic signals with evidence |
| `agent_03.topic_selection` | 03 | topic, angle, series slot, course-chapter pointer |
| `agent_04.research_pack` | 04 | sources, evidence, knowledge-chunk citations |
| `agent_04.knowledge_ingest` | 04 | ingest one registered source: extract, structure, chunk, index, QA (CCR-014; ADR-013); a system job (`NO_DELIVERABLE`), resource class `HEAVY_CPU`, capability `doc_extract`; in 3A a manual run in the development environment |
| `agent_05.script_draft` | 05 | scene-level script with ≥ 3 hook options (§1A.2) |
| `agent_05.shorts_adaptation` | 05 | 9:16 script cut from a parent script |
| `agent_06.claim_extraction` | 06 | claims + rule-pack flags (worked example: `prompts/agent_06_fact_checker/claim_extraction.v1.md`) |
| `agent_06.claim_verification` | 06 | independent verification, contradiction detection |
| `agent_07.voice_synthesis` | 07 | TTS or human narration intake, pronunciation dictionary |
| `agent_07.audio_master` | 07 | loudness, clipping, silence, noise, sync |
| `agent_08.asset_sourcing` | 08 | sourcing in hierarchy order §1A.1, licence ledger rows |
| `agent_09.shot_plan` | 09 | scene/shot plan, timeline, pacing |
| `agent_10.render` | 10 | FFmpeg render (resumable) |
| `agent_10.subtitles` | 10 | SRT per language, optional burned-in captions |
| `agent_10.technical_qc` | 10 | automated inspection (§1A.6) |
| `agent_11.thumbnail_variants` | 11 | 3 variants (YT-08 test needs up to 3) |
| `agent_12.metadata` | 12 | title, description, chapters, tags, SEO validation |
| `svc_s02.uniqueness_check` | S2 → 16 | originality / inauthentic-content gate input |
| `agent_16.compliance_gate` | 16 | rule packs, licence completeness, disclosure decision |
| `agent_16.quality_score` | 16 | 100-point rubric (§1A.7) |
| `svc_s07.request_approval` | S7 → 01 | human approval gate |
| `agent_16.publication_authorisation` | 16 | final `is_final` verdict (Q5) |
| `agent_13.upload_private` | 13 | resumable upload, `privacyStatus=private` (YT-04) |
| `agent_13.publish` | 13 | privacy change / schedule after authorisation |
| `agent_13.verify_publication` | 13 | read-back verification |
| `agent_13.file_delivery` | 13 | client masters + exports |
| `agent_14.analytics_ingest` | 14 | Analytics API + Reporting API (YT-14) |
| `agent_17.brief_intake` | 17 | brief, clarification questions |
| `agent_17.concept_variants` | 17 | concepts and 3–5 variants (§1D.4) |
| `agent_17.ad_script_storyboard` | 17 | ad script and storyboard per format; claim list to 06/16 |
| `svc_s03.translate_script` | S3 → 05 | translated script |
| `svc_s03.dub_timing_fit` | S3 → 05 | dubbed track timing fit |
| `svc_s03.native_speaker_qc` | S3 → 05 | human native-speaker check (approval gate) |
A blueprint that needs another task type files a CCR (CONTRACT_CHANGE_REQUESTS.md).

### 3.3 Gates and revision routing
1. A blocking gate that fails (03 §5.3 rule 4: a result with `gate: true`, `blocking: true`, verdict `FAIL`) or returns a compliance verdict `BLOCKED` (03 §5.3 rule 3) takes its `on_fail` route. For `REVISE` the target is chosen by code (CCR-002): the failing results' `remedy_stage_id` values that are the `target_stage_id` or listed in `alt_target_stage_ids` are collected, and the **earliest** of them in the graph's topological order is the target; if no failing result names an allowed stage, `target_stage_id` is used. The revision runs as a new iteration (new tasks, new idempotency keys) of the target stage **and of every stage that transitively depends on it**; stages that do not depend on the target keep their `COMPLETED` tasks. Revisions are counted per gate per job up to `limits.max_revision_loops` (07 §9); then the job completes with `outcome = BLOCKED_COMPLIANCE` (03 §11.5). It is never published.
2. `NEEDS_HUMAN_REVIEW` verdicts insert an S7 approval of kind `SENSITIVE_CLAIM` or `COPYRIGHT_DOUBT` before the job continues (CCR-123: `COPYRIGHT_DOUBT` for copy-guard, paraphrase, licence and third-party-material doubts; `SENSITIVE_CLAIM` for every other rule, uniqueness / YTG-R1 included).
3. A human `REJECTED` at a mandatory approval ends the job `REJECTED_BY_APPROVER`; `CHANGES_REQUESTED` routes to the stage named in the approval workflow.
4. Gates are deterministic-first (§3.3 Quality): QC, licence completeness, schema and rule checks run before any LLM judge.
5. `STOP` ends the job: with `outcome = BLOCKED_COMPLIANCE` when the cause is a compliance verdict `BLOCKED`; otherwise the gate task is treated as `FAILED` and escalated L3 (CCR-002).
6. **Revision context** (CCR-008). For an iteration > 0 the orchestrator gives the target stage a `PRIOR_OUTPUT` context ref to the previous iteration's output of the same stage and the revision feedback built from the failing results (rule 7). Agents never read the previous iteration through `TASK` memory (04 §5.10 rule 1). When the previous output records the hash of a dependency's output that has since changed (e.g. Agent 09's previous plan records `narration_timeline_sha256` and `s07_voice` ran a new iteration), the orchestrator also passes that **previous dependency output** as a second `PRIOR_OUTPUT` ref (CCR-115; Agent 09: `previous_timeline_ref`, the narration timeline the previous plan was made on, hash verified); when it is required and absent the task fails `PERMANENT.INPUT_INVALID` (detail `PREVIOUS_TIMELINE_MISSING`, a payload-local reason).
7. **Revision feedback mapping to the script stage** (CCR-009). The orchestrator builds `revision.feedback[]` of `agent_05.script_draft.input` / `agent_05.shorts_adaptation.input` (≤ 60 items, grouped per segment) from the failing upstream results:

   | Source (`revision_feedback_source`) | From | `segment_ref` | `rule_ids` | `instruction` | `suggested_citation_refs` |
   |---|---|---|---|---|---|
   | `CLAIM_EXTRACTION` | `agent_06.claim_extraction.output` claims with verdict `BLOCKED` / `NEEDS_HUMAN_REVIEW` | the claim's `segment_id` | the claim's `rule_flags[].rule_id` | `"REMOVE_OR_REWORD: " + evidence` | `[]` |
   | `CLAIM_VERIFICATION` | `agent_06.claim_verification.output` `revision_requests[]` (each carries `segment_id`) | `segment_id` | the claim's `rule_flags[].rule_id` (may be empty) | `"<revision_action>: " + detail` | the request's `suggested_citation_refs` |
   | `UNIQUENESS`, `COMPLIANCE`, `QUALITY_SCORE` | `svc_s02.uniqueness_check`, `agent_16.compliance_gate`, `agent_16.quality_score` failing results | the flagged segment, or `null` for whole-script items | the result's `rule_id` (or `[]`) | the result's `message` | `[]` |
   | `APPROVER` | an approval decided `CHANGES_REQUESTED` | the segment named by the approver, or `null` | `[]` | the approver's comment (verbatim) | `[]` |
   A `revision_action = PROVIDE_EVIDENCE` request whose `remedy_stage_id` is `s04_research` sends the revision to `s04_research` first (rule 1); the orchestrator then passes the open gaps to Agent 04 as `revision.gaps`.
7b. **Revision feedback to a non-script stage** (CCR-078). When the target is `s09_plan`, `s08_assets`, `s07_voice`, `s10_render` or `s11_thumbs`, the orchestrator passes `revision_feedback[]` built one item per failing gate result (`s08_assets`, `s06_chart`, `s10_qc`, `s16_comp`, `s16_score`) or `CHANGES_REQUESTED` approval: `{source_stage_id, check_id, shot_ids[] (from the result's evidence, may be empty), measured, threshold, message}`; an approver item carries `check_id = null` and the approver's comment verbatim as `message`. The target's input schema defines how it reads them.
8. **Shorts revision** (CCR-003): a `SHORTS` job revises like the long form, with `agent_05.shorts_adaptation` as the script stage (it accepts `revision.feedback[]` and the previous cut as `PRIOR_OUTPUT`).
9. **Optional stages** (CCR-065). A dependency on an optional stage that is disabled for the job counts as satisfied (the edge is dropped when the graph is materialised); an enabled optional stage must complete like a required one. A disabled stage is never a revise target; an `alt_target_stage_ids` entry naming one is skipped. A gate whose primary `target_stage_id` is a disabled optional stage is invalid: refused at load when the stage is disabled by default, and at job validation (J02 → J04, `PERMANENT.CONFIG_INVALID`) when the job disables it (CCR-092).
10. **Knowledge released after the pack** (CCR-071). A `KNOWLEDGE_RELEASE` approved after a job's `s04_research` completed never changes that job; the owner (through the operator) starts a new job for the topic, which reads the released material. The running job continues without it.

### 3.4 Approval workflows (`workflow_key`)
| Key | Steps (role per step) | Used by |
|---|---|---|
| `owner_one_tap` | 1: `REVIEWER_APPROVER` (the owner in Tier 0) | owner channel types |
| `client_two_step` (T2 portal; T1 via managed service) | 1: client reviewer (`CLIENT_GUEST` or `REVIEWER_APPROVER` of the client org) → 2: client final approver (`ORG_ADMIN` or `REVIEWER_APPROVER`) | client types |
| `owner_sensitive` | 1: `REVIEWER_APPROVER`; 2 (finance channel or financial claim): `ORG_OWNER` | `SENSITIVE_CLAIM`, `COPYRIGHT_DOUBT`, `KNOWLEDGE_RELEASE` |
Every `FINAL_VIDEO` approval requires at least one `editorial_contributions` row for the job before it can be `APPROVED` (§1A.7; enforced again by the publish guard, 04 §5.21).

## 4. Export and delivery presets
| Preset key | Spec | Source |
|---|---|---|
| `yt_master_1080p` | 1920×1080 minimum, H.264 High profile, video 15–25 Mbps (target; YouTube's 1080p SDR recommendation is 8 Mbps, used as floor), constant frame rate equal to the source, closed GOP; audio AAC-LC 48 kHz stereo ≥ 384 kbps | §1A.4, §1A.5, INF-10 |
| `yt_master_1440p` | 2560×1440 where render budget allows; H.264 High; bitrate target **REQUIRES REVIEW (18)** (YouTube's 1440p SDR recommendation 16 Mbps as floor, INF-10); audio as above | §1A.5, INF-10 |
| `srt_per_language` | one accurate SRT per language; optional burned-in styled captions | §1A.5 |
| `shorts_9x16` | 9:16 vertical; resolution, maximum duration and bitrate **REQUIRES REVIEW (Phase 1): official Shorts upload specs not yet in RESEARCH_LOG** | §1A.8 |
| `thumbnail_set` | up to 3 variants for the Studio A/B test (YT-08); size/format limits **REQUIRES REVIEW (Phase 1): thumbnail spec (YT-05 records a 50 MB maximum; dimensions not yet logged)** | YT-05, YT-08 |
| `ad_master_<ratio>_<seconds>` | one master per aspect (16:9, 9:16, 1:1, 4:5) × duration (6/15/30/60 s); codec settings as `yt_master_1080p` unless the destination spec differs; destination specs, safe zones and legal-super legibility **REQUIRES REVIEW (Phase 1): 25_ADVERTISING_COMPLIANCE + destination platform specs** | §3.4, §1D.1, §1D.4 |
| `client_master_mezzanine` | high-bitrate master for client archives; codec **REQUIRES REVIEW (18)** | §1D.1 |
| `dub_audio_track_<lang>` | dubbed audio track per language matching the source timeline; delivery as YouTube multi-language audio (YT-15: creator uploads own dubs; API support **NOT CONFIRMED → REQUIRES REVIEW (Phase 1)**; fallback: human-in-Studio upload step scheduled by S7) | §1E.3, YT-15 |
| `metadata_per_language` | title, description, chapters per language | §3.2 S3 |
| `qc_report` (CCR-043) | the QC report of the run: every `qc_results` row, the 100-point score per dimension (machine and human rows), compliance verdicts, licence summary, labelled DRAFT items (3A_SLICE_SPEC §4) | 18 §9, 3A_SLICE_SPEC §4 |
| `cost_per_stage_report` (CCR-043) | cost per stage and per provider from `cost_ledger` (ESTIMATE / VERIFIED shown apart) | 09 §12 |
| `delivery_manifest` (CCR-043) | list of delivered files with SHA-256, size and media type; its own SHA-256 is the `delivery.file` key material | 03 §9.2, 3A_SLICE_SPEC §4 |

## 5. QC profiles (values owned by 18; listed here as references)
| Profile | Checks (all blocking unless noted) | Thresholds |
|---|---|---|
| `qc.long_form` | ffprobe metadata vs preset; `ebur128` integrated loudness and true peak; `blackdetect`, `freezedetect`, `silencedetect` (INF-09); A/V and subtitle sync; duration vs script; no source watermark/logo; every shot has a licence-ledger row; visual hierarchy share (AI stills never the majority of screen time, §1A.1e); visual change every 3–5 s in explanatory stretches (§1A.2; WARN until calibrated) | −14 LUFS integrated, −1 dBTP true peak, music bed −15 to −20 dB under narration, 48 kHz (§1A.4); tolerances and detector parameters **REQUIRES REVIEW (18)** |
| `qc.shorts` | as `qc.long_form` for the vertical preset | 9:16 spec **REQUIRES REVIEW (Phase 1)** |
| `qc.ad_spot` | as `qc.long_form` + exact duration per spot, legal super/disclaimer legibility and on-screen time, safe zones, logo and pack-shot rules, brand kit applied (§1D.4) | duration tolerance, legibility, safe zones **REQUIRES REVIEW (25)** |
| `qc.corporate` | as `qc.long_form` | per client contract where stricter |
| `qc.dubbing` | loudness as above; dubbed-track timing within the source segment; per-language subtitle sync | timing tolerance **REQUIRES REVIEW (18 / S3)** |
Quality score: 100-point rubric, publish only at ≥ 85 (config `quality.publish_min_score`), any compliance failure rejects regardless of score (§1A.7).

## 6. Cost model structure
Each record lists the cost components that S4 (→ 15) estimates before admission (budget reservation, 03 T03) and records per call in `cost_ledger` (04 §5.14).

| Component | Unit (`unit_kind`) | Price source |
|---|---|---|
| LLM per stage | tokens in / out / cached; `billing_mode` | **REQUIRES REVIEW (Phase 1): vendor prices (research wave 2, 09)** |
| TTS | characters or `audio_ms` | **REQUIRES REVIEW (Phase 1)** |
| Stock footage / images | `items` | **REQUIRES REVIEW (Phase 1): ADR-009** |
| AI video B-roll | `video_ms` (budgeted per video, most expensive per second, §1A.11) | **REQUIRES REVIEW (Phase 1)** |
| Music / SFX | `items` or subscription share | **REQUIRES REVIEW (Phase 1)** |
| Render | `render_ms` (measured worker time) | MEASURED in pilot |
| Storage | `bytes` × time | **REQUIRES REVIEW (Phase 1)** |
| YouTube quota | `quota_units` (no money; capacity) | YT-02 |
| Human review | minutes (owner / client) | ESTIMATE until the pilot measures it |
Cost per finished video is reported per production type (§3.3 AI providers) and is ESTIMATE until measured.

---

## 7. Registry records

### 7.1 `CHANNEL_LONG_FORM` v1 — Tier 0 (MVP)
| Field | Value |
|---|---|
| destinations | `YOUTUBE` |
| requires_channel / parent_input | true / `NONE` |
| duration_targets_ms | from Agent 03's plan per niche benchmark (19); bounds **REQUIRES REVIEW (Phase 1): 19_NICHE_BENCHMARKS** |
| aspect_ratios / languages | `16:9` / `SINGLE` (MVP: one language) |
| required_inputs | topic plan entry (Agent 03, SYSTEM); channel compliance profile (SYSTEM); brand kit (OWNER, T0+; MVP uses a minimal kit); knowledge library sources for the channel (OWNER, §1B.2a) |
| approvals | `FINAL_VIDEO` / `owner_one_tap` (mandatory, with ≥ 1 editorial contribution); `SCRIPT` / `owner_one_tap` (optional, recommended for the finance channel); `SENSITIVE_CLAIM` / `owner_sensitive` (inserted on `NEEDS_HUMAN_REVIEW`) |
| templates | channel lower-thirds, chart templates (code-rendered from real historical data, §1A.1c, §1B.2a), end screen; brand sting only after the hook (§1A.8) |
| qc_profile | `qc.long_form` |
| rule_packs | mandatory `rp.youtube_general`; by category: finance → `rp.finance_sebi_in` (first channel), health → `rp.health`, kids → `rp.kids`, political/news → `rp.political_news`; tenant `rp.tenant_brand_safety` optional |
| deliverables | `yt_master_1080p` (or `yt_master_1440p`), `srt_per_language`, `thumbnail_set`, metadata (Agent 12) |
| cost_model | LLM (03, 04, 05, 06, 11, 12, 16), TTS or human narration, stock, AI B-roll (capped per video), music, render, storage, quota, human review |
| default_price | n/a for the owner's own channel; client channel price **REQUIRES REVIEW (21)** |
| limits | `max_revision_loops` 3 |

Stages:
| stage_id | task_type | req | class | depends_on | gate / approval |
|---|---|---|---|---|---|
| s02_trends | `agent_02.trend_scan` | no | AI_IO | — | — |
| s03_topic | `agent_03.topic_selection` | yes | AI_IO | s02_trends (if enabled) | finance rules applied at planning (Q5) |
| s04_research | `agent_04.research_pack` | yes | AI_IO | s03_topic | — |
| s05_script | `agent_05.script_draft` | yes | AI_IO | s04_research | — |
| s06_claims | `agent_06.claim_extraction` | yes | AI_IO | s05_script | blocking; on_fail REVISE → s05_script |
| s06_verify | `agent_06.claim_verification` | yes | AI_IO | s06_claims | blocking; on_fail REVISE → s05_script |
| a_script | `svc_s07.request_approval` | no | LIGHT | s06_verify | `SCRIPT` / `owner_one_tap` |
| s07_voice | `agent_07.voice_synthesis` | yes | AI_IO | s06_verify, a_script | — |
| s07_master | `agent_07.audio_master` | yes | HEAVY_CPU | s07_voice | blocking (loudness) ; on_fail REVISE → s07_voice |
| s09_plan | `agent_09.shot_plan` | yes | AI_IO | s06_verify, s07_voice (CCR-003: measured narration timeline) | — |
| s08_assets | `agent_08.asset_sourcing` | yes | AI_IO | s09_plan | licence row per shot (blocking downstream) |
| s10_render | `agent_10.render` | yes | HEAVY_CPU | s07_master, s08_assets | — |
| s10_subs | `agent_10.subtitles` | yes | HEAVY_CPU | s10_render | — |
| s10_qc | `agent_10.technical_qc` | yes | HEAVY_CPU | s10_subs | blocking; on_fail REVISE → s10_render |
| s11_thumbs | `agent_11.thumbnail_variants` | yes | AI_IO | s09_plan | — |
| s12_meta | `agent_12.metadata` | yes | AI_IO | s06_verify | — |
| s02u_unique | `svc_s02.uniqueness_check` | yes | AI_IO | s10_qc | blocking; on_fail REVISE → s05_script |
| s16_comp | `agent_16.compliance_gate` | yes | AI_IO | s02u_unique, s11_thumbs, s12_meta | blocking; on_fail REVISE → s05_script |
| s16_score | `agent_16.quality_score` | yes | AI_IO | s16_comp | blocking (≥ 85); on_fail REVISE → s09_plan |
| a_final | `svc_s07.request_approval` | yes | LIGHT | s16_score | `FINAL_VIDEO` / `owner_one_tap` |
| s16_auth | `agent_16.publication_authorisation` | yes | LIGHT | a_final | blocking; on_fail STOP |
| s13_upload | `agent_13.upload_private` | yes | PUBLISH | s16_auth | — |
| s13_publish | `agent_13.publish` | yes | PUBLISH | s13_upload | — |
| s13_verify | `agent_13.verify_publication` | yes | LIGHT | s13_publish | blocking; on_fail STOP (L3) |
Post-publish (separate jobs, not in this graph): `agent_14.analytics_ingest` and Agent 15 economics run as scheduled system jobs (`NO_DELIVERABLE`). Walking-skeleton subset: 27 §9.

### 7.1a `CHANNEL_LONG_FORM` v2 — Tier 0, 3A (CCR-003; CCR-3A-1 of 3A_SLICE_SPEC)
The 3A line (D1): the owner gives the topic, files are delivered, nothing is uploaded. Fields not listed are as v1.

| Field | Value |
|---|---|
| destinations | `FILE_DELIVERY` (YouTube destinations return in a later version, 3C) |
| requires_channel / parent_input | true (channel `DRAFT`, never `CONNECTED` in 3A) / `NONE` |
| duration_targets_ms | from `amw.owner_topic.target_duration_ms` (03 §3.4); bounds check `SKIPPED` (3A_SLICE_SPEC R13) |
| required_inputs | `owner_topic` (`amw.owner_topic` 1.0.0, OWNER, recorded by the operator tool, D5); channel compliance profile (SYSTEM); minimal brand kit (OWNER); knowledge library sources of the channel (OWNER) |
| approvals | `FINAL_VIDEO` / `owner_one_tap` (mandatory, with ≥ 1 editorial contribution); `SCRIPT` / `owner_one_tap` (optional); `SENSITIVE_CLAIM` / `COPYRIGHT_DOUBT` / `owner_sensitive` (inserted on `NEEDS_HUMAN_REVIEW`) |
| rule_packs | mandatory `rp.youtube_general` (the files are made for later YouTube use, 3A_SLICE_SPEC R3) + by category as v1 |
| deliverables | `yt_master_1080p`, `srt_per_language`, `thumbnail_set`, `qc_report`, `cost_per_stage_report`, `delivery_manifest` |
| music | no music bed in 3A technical runs; a licensed bed is a precondition for 3B scoring (D6, CCR-007): Agent 08 sources it (`MUSIC_BED` ledger rows, capability `music_search`), Agent 09 plans the cue, Agent 07 mixes it in `s07_master`. Enabled by a new record version once the owner has chosen the licensed source; in that version `s07_master` depends on `s07_voice`, `s09_plan` and `s08_assets` so Agent 07 can mix the planned, sourced bed (CCR-079) |
| limits | `max_revision_loops` 3 |
| child jobs | when `owner_topic.shorts_wanted = true`, the orchestrator creates one `SHORTS` v2 child job (`parent_job_id`) after the parent's `s06_verify` is `COMPLETED` and `a_script` (if enabled) is decided; cap `limits.max_child_jobs_per_job` |

Stages (dotted routes are gates; `alt` = `alt_target_stage_ids`, §3.3 rule 1):
| stage_id | task_type | req | class | capabilities | depends_on | gate / approval |
|---|---|---|---|---|---|---|
| s04_research | `agent_04.research_pack` | yes | AI_IO | `llm`, `web_fetch` | — (job input) | blocking; compliance `BLOCKED` topic → on_fail STOP (`BLOCKED_COMPLIANCE`) |
| s05_script | `agent_05.script_draft` | yes | AI_IO | `llm` | s04_research | — |
| s06_claims | `agent_06.claim_extraction` | yes | AI_IO | `llm` | s05_script | blocking; on_fail REVISE → s05_script |
| s06_verify | `agent_06.claim_verification` | yes | AI_IO | `llm` | s06_claims | blocking; on_fail REVISE → s05_script; alt s04_research |
| a_script | `svc_s07.request_approval` | no | LIGHT | — | s06_verify | `SCRIPT` / `owner_one_tap` |
| s07_voice | `agent_07.voice_synthesis` | yes | AI_IO | `tts`, `media_probe` | s06_verify, a_script | — |
| s07_master | `agent_07.audio_master` | yes | HEAVY_CPU | `render_ffmpeg`, `media_probe` | s07_voice | blocking gate (loudness, 18 §5); on_fail REVISE → s07_voice |
| s09_plan | `agent_09.shot_plan` | yes | AI_IO | `llm` | s06_verify, s07_voice | — (needs the measured narration timeline; no estimated-timing mode in 3A, CCR-051) |
| s08_assets | `agent_08.asset_sourcing` | yes | AI_IO | `llm`, `stock_search`, `media_probe` | s09_plan | blocking gate (unresolved shots, `shot_unresolved_reason`); on_fail REVISE → s09_plan; alt s05_script. Owner-material reasons (`NO_DATASET`, `NO_CHART_CASE`, `METHOD_NOT_RELEASED`) are not gate results: the task fails `PERMANENT.MISSING_DEPENDENCY` (L3, the owner supplies material) |
| s06_chart | `agent_06.claim_verification` (mode `CHART_FACTS`, CCR-004) | yes | AI_IO | `llm` | s08_assets | blocking; on_fail REVISE → s05_script; alt s08_assets. With no chart claim the task succeeds at once with mode `SKIPPED` and no LLM call. A chart claim with no chart facts (`NO_CHART_FACTS`) is a gate `FAIL` with `remedy_stage_id = s08_assets` (CCR-074), not `NEEDS_HUMAN_REVIEW` |
| s10_render | `agent_10.render` | yes | HEAVY_CPU | `render_ffmpeg` | s07_master, s08_assets, s06_chart | — |
| s10_subs | `agent_10.subtitles` | yes | HEAVY_CPU | `render_ffmpeg` | s10_render | — |
| s10_qc | `agent_10.technical_qc` | yes | HEAVY_CPU | `render_ffmpeg`, `media_probe` | s10_subs | blocking gate; on_fail REVISE → s10_render; alt s07_voice, s08_assets, s09_plan |
| s11_thumbs | `agent_11.thumbnail_variants` | yes | AI_IO | `llm` | s09_plan, s08_assets | blocking (compliance `BLOCKED`, e.g. no variant can be made without breaking a rule); on_fail REVISE → s05_script |
| s12_meta | `agent_12.metadata` | no (disabled in 3A, D1) | AI_IO | `llm` | s06_verify | — |
| s02u_unique | `svc_s02.uniqueness_check` | yes | AI_IO | `media_probe` | s10_qc | blocking; on_fail REVISE → s05_script (3A part only, 13 §3.1) |
| s16_comp | `agent_16.compliance_gate` | yes | AI_IO | `llm` | s02u_unique, s11_thumbs, s12_meta (if enabled) | blocking; on_fail REVISE → s05_script; alt s08_assets, s11_thumbs |
| s16_score | `agent_16.quality_score` | yes | AI_IO | `llm` | s16_comp | blocking gate declared; behaviour by config `quality.score_gate_mode` (CCR-085): provisional `REPORT_ONLY` until the 3B judge calibration — the score is computed and reported, a total below 85 is a `WARN` result (`blocking: false`), and delivery still needs the owner's `FINAL_VIDEO` approval; `BLOCKING` (≥ 85) after calibration, refused at startup while `quality.machine_scaling = NONE` (owner Q-O2); on_fail REVISE → s09_plan; alt s05_script, s07_voice, s10_render, s11_thumbs |
| a_final | `svc_s07.request_approval` | yes | LIGHT | — | s16_score | `FINAL_VIDEO` / `owner_one_tap`; `CHANGES_REQUESTED` routes to the stage given by the decision's stage word (`parsed_target_stage_id`, 03 §11.6 rule 7; allowed: s05_script, s09_plan, s11_thumbs) with the `REVISION_NOTE` as feedback (CCR-089) |
| s16_auth | `agent_16.publication_authorisation` | yes | LIGHT | — | a_final | blocking; on_fail STOP (authorises **delivery** in v2, deterministic checks only) |
| s13_deliver | `agent_13.file_delivery` | yes | LIGHT | `file_delivery` | s16_auth | — (idempotency `delivery.file`) |
### 7.2 `SHORTS` v1 — Tier 0 (after the MVP)
| Field | Value |
|---|---|
| destinations / requires_channel | `YOUTUBE` / true |
| parent_input | `PARENT_JOB` (optional; cut from the same research/script where it adds value, §1A.8) |
| duration / aspect | **REQUIRES REVIEW (Phase 1): Shorts maximum duration (official source)** / `9:16` |
| required_inputs | parent job's research pack and approved script, or a topic plan entry |
| approvals | `FINAL_VIDEO` / `owner_one_tap` (mandatory, with ≥ 1 editorial contribution) |
| templates | vertical captions, vertical lower-thirds |
| qc_profile | `qc.shorts` |
| rule_packs | as `CHANNEL_LONG_FORM` |
| deliverables | `shorts_9x16`, `srt_per_language`, metadata; thumbnails optional (YT-05: `thumbnails.set` supports Shorts); title/thumbnail A/B test not available for Shorts (YT-08) |
| cost_model / default_price | as long-form, shorter / **REQUIRES REVIEW (21)** |
Stages: `agent_05.shorts_adaptation` (depends on parent script) → `agent_06.claim_extraction` (blocking) → `agent_07.voice_synthesis` → `agent_07.audio_master` → `agent_09.shot_plan` → `agent_08.asset_sourcing` → `agent_10.render` → `agent_10.subtitles` → `agent_10.technical_qc` (blocking) → `agent_12.metadata` → `svc_s02.uniqueness_check` (blocking) → `agent_16.compliance_gate` (blocking) → `agent_16.quality_score` (blocking) → `svc_s07.request_approval` (`FINAL_VIDEO`) → `agent_16.publication_authorisation` → `agent_13.upload_private` → `agent_13.publish` → `agent_13.verify_publication`. `on_fail` targets as in §7.1 with `agent_05.shorts_adaptation` in place of `agent_05.script_draft`.

### 7.2a `SHORTS` v2 — Tier 0, 3A child job (CCR-003)
Created only by the parent rule of §7.1a. Fields not listed are as `CHANNEL_LONG_FORM` v2.

| Field | Value |
|---|---|
| destinations / parent_input | `FILE_DELIVERY` / `PARENT_JOB` (required) |
| required_inputs | the parent's research pack and its verified script (SYSTEM, `PRIOR_OUTPUT` refs); the parent's `owner_topic` |
| aspect / duration | `9:16` / bounds `SKIPPED` until the official Shorts spec is logged (3A_SLICE_SPEC R11) |
| approvals | `FINAL_VIDEO` / `owner_one_tap` (mandatory, with ≥ 1 editorial contribution) |
| qc_profile / deliverables | `qc.shorts` / `shorts_9x16`, `srt_per_language`, `qc_report`, `cost_per_stage_report`, `delivery_manifest` (thumbnails only if `s11_thumbs` is enabled) |
| script shape | a Shorts script has `scenes[]` and no `sections[]`: section-based items (chapters) do not apply and are emitted `SKIPPED`, `blocking: false` (03 §5.3 rule 5) |

| stage_id | task_type | req | class | capabilities | depends_on | gate / approval |
|---|---|---|---|---|---|---|
| s05_shorts | `agent_05.shorts_adaptation` | yes | AI_IO | `llm` | — (parent refs) | — |
| s06_claims | `agent_06.claim_extraction` | yes | AI_IO | `llm` | s05_shorts | blocking; on_fail REVISE → s05_shorts |
| s06_verify | `agent_06.claim_verification` | yes | AI_IO | `llm` | s06_claims | blocking; on_fail REVISE → s05_shorts (CCR-003: the cut is verified like the long form) |
| s07_voice | `agent_07.voice_synthesis` | yes | AI_IO | `tts`, `media_probe` | s06_verify | — |
| s07_master | `agent_07.audio_master` | yes | HEAVY_CPU | `render_ffmpeg`, `media_probe` | s07_voice | blocking gate; on_fail REVISE → s07_voice |
| s09_plan | `agent_09.shot_plan` | yes | AI_IO | `llm` | s06_verify, s07_voice | — |
| s08_assets | `agent_08.asset_sourcing` | yes | AI_IO | `llm`, `stock_search`, `media_probe` | s09_plan | blocking gate; on_fail REVISE → s09_plan; alt s05_shorts |
| s06_chart | `agent_06.claim_verification` (mode `CHART_FACTS`) | yes | AI_IO | `llm` | s08_assets | blocking; on_fail REVISE → s05_shorts; alt s08_assets |
| s10_render | `agent_10.render` | yes | HEAVY_CPU | `render_ffmpeg` | s07_master, s08_assets, s06_chart | — |
| s10_subs | `agent_10.subtitles` | yes | HEAVY_CPU | `render_ffmpeg` | s10_render | — |
| s10_qc | `agent_10.technical_qc` | yes | HEAVY_CPU | `render_ffmpeg`, `media_probe` | s10_subs | blocking gate; on_fail REVISE → s10_render; alt s07_voice, s08_assets, s09_plan |
| s11_thumbs | `agent_11.thumbnail_variants` | no (disabled by default) | AI_IO | `llm` | s09_plan, s08_assets | blocking; on_fail REVISE → s05_shorts |
| s02u_unique | `svc_s02.uniqueness_check` | yes | AI_IO | `media_probe` | s10_qc | blocking; on_fail REVISE → s05_shorts |
| s16_comp | `agent_16.compliance_gate` | yes | AI_IO | `llm` | s02u_unique, s11_thumbs (if enabled) | blocking; on_fail REVISE → s05_shorts; alt s08_assets |
| s16_score | `agent_16.quality_score` | yes | AI_IO | `llm` | s16_comp | as long-form v2 (`quality.score_gate_mode`); on_fail REVISE → s09_plan; alt s05_shorts, s07_voice, s10_render |
| a_final | `svc_s07.request_approval` | yes | LIGHT | — | s16_score | `FINAL_VIDEO` / `owner_one_tap` |
| s16_auth | `agent_16.publication_authorisation` | yes | LIGHT | — | a_final | blocking; on_fail STOP |
| s13_deliver | `agent_13.file_delivery` | yes | LIGHT | `file_delivery` | s16_auth | — |
### 7.3 `AD_SPOT` v1 — first ad client (Tier 1+)
| Field | Value |
|---|---|
| destinations | `FILE_DELIVERY` (+ `YOUTUBE` only if the client contracts upload to its own channel) |
| requires_channel / parent_input | false / `NONE` |
| duration_targets_ms | exact values 6000, 15000, 30000, 60000 |
| aspect_ratios | `16:9`, `9:16`, `1:1`, `4:5` |
| required_inputs | client brief (CLIENT); product category for sector rule packs (CLIENT); claim substantiation documents for every factual/comparative claim (CLIENT, §1D.3); product footage/photos (CLIENT, preferred, §1D.4); brand kit (CLIENT); signed releases/licences for any real person, celebrity, creator or competitor brand (CLIENT, §1D.3) |
| approvals | `CONCEPT` / `client_two_step` (mandatory); `SCRIPT` and `STORYBOARD` / `client_two_step` (mandatory); `FINAL_VIDEO` / `client_two_step` (mandatory, logged before delivery); `USAGE_RIGHTS` record (mandatory) |
| templates | client brand kit, pack-shot and logo templates, legal super templates |
| qc_profile | `qc.ad_spot` |
| rule_packs | mandatory `rp.advertising_asci_in`; by sector `rp.ad_sector_<sector>`; `rp.youtube_general` when published to YouTube; disclosure label decided by the risk test and recorded (§1D.2; IT Rules labelling) — rule content **REQUIRES REVIEW (Phase 1): IN entries for ASCI and IT Rules** |
| deliverables | `ad_master_<ratio>_<seconds>` per ordered combination, captions, disclosure label decision record, usage-rights record; 3–5 variants for testing (§1D.4) |
| cost_model / default_price | per spot length and variant count / **REQUIRES REVIEW (21)** |
Stages: `agent_17.brief_intake` → `agent_17.concept_variants` → approval `CONCEPT` → `agent_17.ad_script_storyboard` → `agent_06.claim_extraction` (blocking; every claim needs substantiation) → `agent_06.claim_verification` (blocking) → approval `SCRIPT`/`STORYBOARD` → `agent_07.voice_synthesis` → `agent_07.audio_master` → `agent_09.shot_plan` → `agent_08.asset_sourcing` → `agent_10.render` (per format) → `agent_10.subtitles` → `agent_10.technical_qc` (blocking) → `agent_16.compliance_gate` (blocking; ad pack) → `agent_16.quality_score` → approval `FINAL_VIDEO` → `agent_16.publication_authorisation` → `agent_13.file_delivery` (and optionally upload/publish/verify). Agents 02, 03, 04, 05, 11, 12, 14 are not used (17 replaces 03; §3.1).

### 7.4 `EXPLAINER_CORPORATE_TRAINING` v1 — Tier 1
| Field | Value |
|---|---|
| destinations | `FILE_DELIVERY` and/or `YOUTUBE` (client channel) |
| requires_channel | only for `YOUTUBE` |
| duration / aspect | per brief, bounds **REQUIRES REVIEW (21: plan limits)** / `16:9` (others on request) |
| required_inputs | client brief and learning objectives (CLIENT); client source documents/course material (CLIENT, into the client's own knowledge library); brand kit (CLIENT) |
| approvals | `BRIEF` (client confirms the clarified brief), `SCRIPT` / `client_two_step`, `FINAL_VIDEO` / `client_two_step` (all mandatory) |
| qc_profile | `qc.corporate` |
| rule_packs | `rp.youtube_general` when published to YouTube; `rp.tenant_brand_safety`; promotional content routes to `rp.advertising_asci_in` (decision rule **REQUIRES REVIEW (25)**) |
| deliverables | `yt_master_1080p` or `client_master_mezzanine`, `srt_per_language`; for YouTube also `thumbnail_set` and metadata |
| default_price | **REQUIRES REVIEW (21)** |
Stages: `agent_17.brief_intake` → approval `BRIEF` → `agent_04.research_pack` (client library only) → `agent_05.script_draft` → `agent_06.claim_extraction` → `agent_06.claim_verification` → approval `SCRIPT` → voice → master → shot plan → assets → render → subtitles → technical QC → (`agent_11.thumbnail_variants`, `agent_12.metadata` if YouTube) → `svc_s02.uniqueness_check` (YouTube only) → compliance gate → quality score → approval `FINAL_VIDEO` → authorisation → delivery or upload/publish/verify.

### 7.5 `ECOMMERCE_PRODUCT` v1 — first ad client (Tier 1+)
| Field | Value |
|---|---|
| destinations | `FILE_DELIVERY` |
| duration / aspect | per order (presets of `AD_SPOT` allowed) / `9:16`, `1:1`, `4:5`, `16:9` |
| required_inputs | product data and photos/footage (CLIENT); claims + substantiation (CLIENT); brand kit (CLIENT) |
| approvals | `SCRIPT` / `client_two_step`, `FINAL_VIDEO` / `client_two_step` (mandatory); `USAGE_RIGHTS` record |
| qc_profile / rule_packs | `qc.ad_spot` / `rp.advertising_asci_in` + sector packs (product videos are advertising, §1D) |
| deliverables | `ad_master_<ratio>_<seconds>` per order |
| default_price | **REQUIRES REVIEW (21)** |
Stages: as `AD_SPOT` without `agent_17.concept_variants` and the `CONCEPT` approval unless ordered; `agent_08.asset_sourcing` prefers the client's own product media (§1D.4).

### 7.6 `DUBBING_LOCALISATION` v1 — Tier 1
| Field | Value |
|---|---|
| destinations | `YOUTUBE` (multi-language audio on the source video) and/or `FILE_DELIVERY` |
| parent_input | `SOURCE_VIDEO` (an existing video: the tenant's own publication or a client-supplied master with rights confirmation) |
| languages | `MULTI` (target languages per order) |
| required_inputs | source video + transcript or script (CLIENT/SYSTEM); target languages (CLIENT); pronunciation dictionary per language (SYSTEM/CLIENT); rights confirmation for the source (CLIENT) |
| approvals | native-speaker QC per language (`svc_s03.native_speaker_qc`, mandatory human step); `FINAL_VIDEO` / `client_two_step` or `owner_one_tap` (mandatory) |
| qc_profile | `qc.dubbing` |
| rule_packs | the source video's packs + `rp.youtube_general` |
| deliverables | `dub_audio_track_<lang>`, `srt_per_language`, `metadata_per_language` |
| default_price | **REQUIRES REVIEW (21)** |
Stages (skips 02–05 per §3.4): `svc_s03.translate_script` → `agent_06.claim_extraction` on the translation (blocking: meaning must not change into a rule violation) → `svc_s03.native_speaker_qc` (approval) → `agent_07.voice_synthesis` → `svc_s03.dub_timing_fit` → `agent_07.audio_master` → `agent_10.subtitles` → `agent_10.technical_qc` → `agent_12.metadata` (per language) → `agent_16.compliance_gate` → approval `FINAL_VIDEO` → `agent_16.publication_authorisation` → `agent_13.upload_private`/`publish` path for audio tracks (API support REQUIRES REVIEW, see §4 `dub_audio_track_<lang>`) or `agent_13.file_delivery`.

## 8. Summary
| Key | First tier | Destinations | Mandatory approvals | Mandatory packs | Price |
|---|---|---|---|---|---|
| `CHANNEL_LONG_FORM` | Tier 0 (MVP) | YouTube | FINAL_VIDEO (+ editorial contribution) | youtube_general (+ category) | owner: n/a; client: REQUIRES REVIEW |
| `SHORTS` | Tier 0 | YouTube | FINAL_VIDEO | youtube_general (+ category) | REQUIRES REVIEW |
| `AD_SPOT` | Tier 1+ (first ad client) | File (+ YouTube) | CONCEPT, SCRIPT/STORYBOARD, FINAL_VIDEO, USAGE_RIGHTS | advertising_asci_in (+ sector) | REQUIRES REVIEW |
| `EXPLAINER_CORPORATE_TRAINING` | Tier 1 | File / YouTube | BRIEF, SCRIPT, FINAL_VIDEO | youtube_general if YouTube; brand safety | REQUIRES REVIEW |
| `ECOMMERCE_PRODUCT` | Tier 1+ (first ad client) | File | SCRIPT, FINAL_VIDEO, USAGE_RIGHTS | advertising_asci_in (+ sector) | REQUIRES REVIEW |
| `DUBBING_LOCALISATION` | Tier 1 | YouTube / File | native-speaker QC, FINAL_VIDEO | source packs + youtube_general | REQUIRES REVIEW |
