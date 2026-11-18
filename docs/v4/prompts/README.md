# prompts/ — Versioned prompt files

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Each LLM step's owning agent; standard owned by Agent 01 (27 §4) |
| Depends on | 27_ENGINEERING_STANDARDS.md §4, GLOSSARY_AND_IDS.md, 03_COMMUNICATION_STANDARD.md, evals/README.md |
| Directive sections covered | §3.5.1, §3.5.2; plan Q3 (location in this phase), Q9 (one source for blueprint prompts), Q10 (one complete example step) |

## 1. Location and naming
- This phase: `docs/v4/prompts/`; first build ticket moves the folder to the repo root `prompts/` unchanged (plan Q3).
- Path: `prompts/<agent package>/<task>.v<N>.md`. Agent package names: 27 §7.2 (e.g. `agent_06_fact_checker`).
- Prompt ID: `<agent_id>/<task>.v<N>` (e.g. `agent_06/claim_extraction.v1`). Task type: `<agent_id>.<task>` (24 §3.2).
- A released version is immutable. Any change, including wording, is a new version file and runs the eval gate (27 §5).
- An agent blueprint's section 5 ("Full system prompt") is the v1 text of these files; there is one source (plan Q9): the blueprint links the file.

## 2. Format
Every file follows `_TEMPLATE.v1.md` exactly: header table, then the sections Role · Objective · Inputs · Rules · Output JSON Schema · Worked examples · Refusal and escalation · Self-check, in that order (§3.5.1; lint rules 27 §4.4).

Runtime substitution:
| Placeholder | Resolved by | Example |
|---|---|---|
| `{{name}}` | the step code, from the validated input payload | `{{segments}}` |
| `{{rule_pack:<key>}}` | `amw_core` from `rule_packs` (active version for the channel's compliance profile); version recorded in the call's cost/eval record | `{{rule_pack:rp.finance_sebi_in}}` |
| `{{config:<key>}}` | `amw_core.config` (non-secret values only) | not used in v1 files |

Model, temperature, maximum output tokens, timeout, cost budget, caching and batch eligibility are configuration keys `llm.<task_type>.*` (27 §4.2), never in these files.

## 3. Index
| Prompt ID | File | Status | Eval set |
|---|---|---|---|
| `agent_06/claim_extraction.v1` | [agent_06_fact_checker/claim_extraction.v1.md](agent_06_fact_checker/claim_extraction.v1.md) | Draft (complete worked example) | [evals/agent_06_fact_checker/claim_extraction/](../evals/agent_06_fact_checker/claim_extraction/) |
Other LLM steps are written by the Wave B agent blueprints using the template; each needs its own eval set (≥ 20 cases) per 27 §6.
