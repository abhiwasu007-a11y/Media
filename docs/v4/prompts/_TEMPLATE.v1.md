# <agent_id>/<task>.v<N> — <short title>

<!-- TEMPLATE v1. Copy to prompts/<agent package>/<task>.v<N>.md. Keep every section, in this order (27 §4.2). Delete these comments. -->

| Field | Value |
|---|---|
| Prompt ID | `<agent_id>/<task>.v<N>` |
| Task type | `<agent_id>.<task>` (24 §3.2) |
| Status | Draft / Released (immutable once released) |
| Owner | Agent NN |
| Input payload schema | `<agent_id>.<task>.input` `<semver>` |
| Output payload schema | `<agent_id>.<task>.output` `<semver>` (= the Output JSON Schema below = the Pydantic model) |
| Rule packs injected | `rp.<key>` … (by reference only) |
| Eval set | `evals/<agent package>/<task>/` |
| Config keys | `llm.<agent_id>.<task>.model_tier`, `.temperature`, `.max_output_tokens`, `.timeout_ms`, `.cost_budget_micros`, `.cache_system_prompt`, `.batch_eligible` |
| Deterministic pre/post checks | list the step code's checks that run before/after the model (they are not the model's job) |

## Role
<!-- One paragraph: who the model is acting as, inside which stage, and the authority boundary (what it may NOT decide). -->

## Objective
<!-- What a correct answer achieves, in 2–5 numbered points. Measurable where possible. -->

## Inputs
<!-- Every variable, with type and source. Only declared variables may appear in the prompt. -->
| Variable | Type | Source |
|---|---|---|
| `{{variable_name}}` | … | input payload field / rule pack store |

## Rules
<!-- Numbered, testable rules. Compliance rule packs by reference: {{rule_pack:rp.<key>}}. No dates or clock times (owner rule C.4). No model/provider names. -->
1. …

{{rule_pack:rp.<key>}}

## Output JSON Schema
<!-- JSON Schema 2020-12. Must equal the schema generated from the Pydantic model. Must include the `refusal` property (27 §4.3). -->
```json
{ "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:amw:schema:<agent_id>.<task>.output:<semver>", "type": "object" }
```

## Worked examples
<!-- 2–3 examples. Each: the input (as the model sees it) and the exact valid output JSON. At least one example must show a negative/blocked or refusal path. -->
### Example 1 — <name>
Input:
```json
{}
```
Output:
```json
{}
```

## Refusal and escalation
<!-- When to set `refusal` (reasons from GLOSSARY §6.51) and what to put in it. State that the model never invents missing inputs. -->
| Situation | Return |
|---|---|
| … | `refusal.reason = …` |

## Self-check
<!-- Checklist the model verifies before answering. Each item should be checkable by a deterministic assertion in the eval set where possible. -->
- [ ] Output is a single JSON object that validates against the schema.
- [ ] …
