# evals/ — Golden datasets for LLM steps

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Each LLM step's owning agent; standard owned by Agent 01 (27 §6) |
| Depends on | 27_ENGINEERING_STANDARDS.md §5, §6, §8; prompts/README.md; GLOSSARY_AND_IDS.md |
| Directive sections covered | §3.5.3 (≥ 20 cases incl. hard negatives, edge cases, every answer-key case; deterministic assertions; judge rubric; thresholds; CI gate; cost and latency per case), §3.5.4 (no paid calls in tests) |

## 1. Layout
```text
evals/<agent package>/<task>/
├── README.md        # scope, case categories, assertion list, thresholds, judge configuration
├── cases.jsonl      # one case per line (format §2)
└── rubric.md        # LLM-judge rubric (integer scores, anchors per score)
```
This phase: `docs/v4/evals/`; moved to the repo root by the first build ticket (plan Q3). Index: §5.

## 2. Case file format (`cases.jsonl`, UTF-8, one JSON object per line)
| Field | Type | Meaning |
|---|---|---|
| `case_id` | string, unique in the file | prefix by category: `AK-` answer key, `HN-` hard negative, `EDGE-`/`MIX-` edge, `REF-` refusal |
| `category` | `ANSWER_KEY` / `HARD_NEGATIVE` / `EDGE` / `REFUSAL` / `POSITIVE` | |
| `description` | string | what the case tests |
| `input` | object | the step's **input payload** (`<task_type>.input`), valid against its schema |
| `expected` | object | step-specific expectations (defined in the dataset README) |
| `judge_min` | object or null | minimum judge score per rubric criterion; `null` = deterministic-only case |
| `notes` | string | rationale, source of the expectation (directive section, research log ID) |
Rules: no real personal data, no tenant data, no copyrighted book text, no calendar dates in inputs (relative facts such as `data_age_vs_lag` are precomputed fields); every case input validates against the input schema (CI check).

## 3. Run procedure
1. Offline (free, every CI run): schema-validate every case input; re-run deterministic assertions on the stored outputs of the last accepted run.
2. Online (eval gate, 27 §5): only when a prompt file, an `llm.<task_type>.*` config key or an injected rule pack changes. Runs each case once through the real adapter under the per-run budget cap `evals.max_run_cost_micros` (owner-authorised, rule 8), then the deterministic post-checks of the step, then the assertions, then the judge.
3. Output: one run record per case (27 §6.4) with cost and latency; a summary with pass rates per category and the threshold decision.

## 4. Pass/fail logic
A case passes when every deterministic assertion passes and, if `judge_min` is set, every judge criterion meets its minimum. The dataset passes when every threshold in its README is met. Answer-key cases always require 100 %.

## 5. Index
| Dataset | Cases | Status |
|---|---|---|
| [agent_06_fact_checker/claim_extraction](agent_06_fact_checker/claim_extraction/README.md) | 30 (4 answer-key, 7 hard negatives, 18 edge, 1 refusal) | Draft (complete example) |
