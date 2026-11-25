# REPO MAP

Use this map instead of scanning. The 3A platform code is in `packages/`; the lean studio app (dashboard + production line, D15+) is in `apps/studio/`.

## Entry points
| Need | Read |
|---|---|
| What the project is, binding rules | `docs/v4/CONTEXT_BRIEF.md` (then specific § of `docs/v4/MASTER_DIRECTIVE.md`) |
| Session handover (studio app state, deploy, in-flight work) | `docs/v4/HANDOVER.md` |
| Current status, tasks, owner decisions (D1+), open questions | `docs/v4/IMPLEMENTATION_PROGRESS.md` |
| V4.0 Cinematic directive (verbatim) and its upgrade plan | `docs/v4/directives/V4_CINEMATIC_DIRECTIVE.md`, `docs/v4/CINEMATIC_UPGRADE_PLAN.md` |
| V5.0 feature film vision (verbatim, Marathi) and its plan | `docs/v4/directives/V5_FEATURE_FILM_VISION.md`, `docs/v4/FEATURE_FILM_PLAN.md` |
| Plan, phases, defaults Q1–Q20 | `docs/v4/00_EXECUTION_PLAN.md` |
| Index of every V4 document and its status | `docs/v4/README.md` |
| External facts (cite by ID) | `docs/v4/RESEARCH_LOG.md` |

## Contracts (Wave A, single source; never redefine elsewhere)
| Contract | File |
|---|---|
| IDs, units, time zones, all enums | `docs/v4/GLOSSARY_AND_IDS.md` |
| Task input/output/envelope schemas, error object, state machine | `docs/v4/03_COMMUNICATION_STANDARD.md` |
| Every table, RLS, roles | `docs/v4/04_DATABASE_ARCHITECTURE.md` |
| Failure taxonomy, retries, DLQ | `docs/v4/07_FAILURE_MANAGEMENT.md` |
| Production type registry | `docs/v4/24_PRODUCTION_TYPES.md` |
| Prompt/eval/code standards | `docs/v4/27_ENGINEERING_STANDARDS.md` |
| Contract change requests | `docs/v4/CONTRACT_CHANGE_REQUESTS.md` |
| Prompt and eval packs | `docs/v4/prompts/<agent>/<task>.v<N>.md`, `docs/v4/evals/<agent>/<task>/` |

## Other docs
`docs/v4/agents/agent_NN_*.md` (17 blueprints) · `docs/v4/adr/` · `docs/v4/0x_…`–`27_…` shared docs · `docs/v4/KNOWLEDGE_LIBRARY_PLAN.md` · `docs/v4/audit/vps_readonly_audit.sh`

## Private sources (read-only; never copy into this public repo)
| Source | How to use |
|---|---|
| `abhishekwasu-hue/trade-data` (1.5 GB) | Work from the one-time file index (path, size, type) kept **outside git** at `~/.amw_private/trade_data_index.tsv` (rebuild with `git -C <clone> ls-tree -r -l HEAD`). Never list or glob the tree. |
| `abhishekwasu-hue/atp-private` | Index at `~/.amw_private/atp_private_index.tsv`. Contains the owner's private method: do not use in public docs or videos without per-topic release (Q26). |
| Book collection | Location pending from the owner (`KNOWLEDGE_LIBRARY_PLAN.md` K1). |
