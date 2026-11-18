# agent_05_scriptwriter

Agent 05 (Scriptwriter): `agent_05.script_draft` and `agent_05.shorts_adaptation`
(blueprint `docs/v4/agents/agent_05_scriptwriter.md`). A library imported by the AI worker; fakes and
fixtures only in tests (no network, no paid call).

## Run the lane's tests with its own coverage floor (27 section 3: agents >= 80 %)
```
uv run pytest tests/agents/agent_05_scriptwriter \
  --cov=agent_05_scriptwriter --cov-config=packages/agents/agent_05_scriptwriter/pyproject.toml
```
The root `make ci` coverage source lists only `amw_core` and `amw_evals`; this package config is the
floor for this package until the root config adds it (shared change).

## What the tests prove, and what they do not
- `deterministic_core` (114 cases): real function-level checks, except that RM-01..06 only test the
  refusal mapping table (keys partly fixed by the harness) and SC-* run the step with a scripted
  LLM and in-memory ports.
- LLM-step datasets (plan 33, section 25, shorts 27 = 85 cases): **plumbing only.**
  - All 51 PLAN / SCENES / CUT cases only validate the case `input` against the Pydantic model and
    the prompt's JSON Schema. The datasets define no recorded model output, so no quality or
    behaviour of a model output is tested for them.
  - The 34 REFUSAL cases render the prompt, run the structured caller and the refusal mapper with a
    refusal synthesised from the case's own `expected` object. That proves wiring, not model
    behaviour. The step's own refusal code is covered by separate tests in `test_review_fixes.py`
    (plan, section and topic-verdict refusals through `ScriptDraftStep`).
- No LLM judge scores are produced; the datasets are not wired to the `amw_evals` runner (it needs
  recorded outputs, which do not exist yet).
- Worked example 1 of the plan prompt has a hook (h3) below the hook budget minimum and a
  glossary term without brackets; worked examples 1 of the section and shorts prompts use chart IDs
  outside the AK-01 case pool/parent. These are documentation findings (`docs/v4/prompts/`), not
  changed by this lane (pinned in `test_contracts_and_evals.py`).

## Package-local notes
- `ScriptDocument` follows blueprint 8.3 exactly. The omitted-concept list is not part of it: a
  partial revision needs `ResolvedInputs.prior_omitted` (from the prior task output, contract 8.2);
  without it the plan step is re-run.
- Scanner lexicons, near-copy thresholds, speech rates, pointer templates and the Shorts maximum
  duration have no defaults (REQUIRES REVIEW); `normalise_for_matching` is local until the shared
  `amw_core` text normaliser exists.
