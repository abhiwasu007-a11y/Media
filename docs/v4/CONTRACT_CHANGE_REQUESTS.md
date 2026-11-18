# Contract Change Requests (Wave A contracts)

| Field | Value |
|---|---|
| Status | Draft — documentation (process active from Wave B). Software: **Planned** |
| Owner | The integrator agent (one, named by the lead for Wave B); owner decision where a request changes scope |
| Depends on | GLOSSARY_AND_IDS.md, 03_COMMUNICATION_STANDARD.md, 04_DATABASE_ARCHITECTURE.md, 07_FAILURE_MANAGEMENT.md, 24_PRODUCTION_TYPES.md, 27_ENGINEERING_STANDARDS.md, prompts/, evals/ |
| Directive sections covered | §3.3 (one communication standard), §5.5 (compatibility audit: schemas consistent, unique IDs, one standard) |
| Not to be confused with | `CHANGE_REQUESTS.md` — V4.1+ ideas after the baseline freeze (rule 11). This register is for changes to Wave A contracts **during** the V4.0 documentation phase. |

## 1. What counts as a Wave A contract
Any of: a term, ID prefix, unit or enum value (GLOSSARY); a field, schema, version rule, URI form or idempotency scope (03); a state, transition, guard or audit event (03 §11); a table, column, type, key, index, constraint or RLS rule (04); an error code, retry policy, breaker key or hard cap (07); a production-type record field, canonical task type, approval workflow, export preset or QC profile key (24); a tooling, CI, prompt or eval rule (27, prompts/, evals/).

## 2. Rules for Wave B authors
1. **Never create your own variant** of a Wave A contract, table, field, enum value, task type or error code — not even "temporarily" or "locally". Use exactly what Wave A defines.
2. If you need something that does not exist or does not fit, file a request in the register (§4) and continue writing your section against the **current** contract, marking the dependent sentence `PENDING CCR-NNN`.
3. Agent-specific payload contents (fields inside `payload.data` of your task types) are yours to define in your blueprint, but only inside the envelope and naming rules of 03 and GLOSSARY §2.4; new task types, enum values used outside your payload, tables and columns need a CCR.
4. One request per need. State the smallest change that solves it.

## 3. Process
| Step | Who | Action |
|---|---|---|
| 1 File | requester (Wave B agent) | add a row: `Proposed` |
| 2 Check | integrator | duplicates, conflicts with other CCRs, directive conformance (§3.1 registry, §3.3 standards, tenancy rule 9), breaking vs additive per 03 §2.2 |
| 3 Decide | integrator for additive, in-scope changes; **owner** for anything that changes scope, a directive rule, tenancy, a compliance gate or adds a feature not stated (owner rule A.5) | `Approved` / `Rejected` (with reason) / `Needs owner` |
| 4 Apply | integrator only | edits the Wave A documents (all affected ones in one change), bumps schema versions per 03 §2, updates GLOSSARY first if a term/enum is involved |
| 5 Notify | integrator | sets `Applied`, lists the affected docs, and notifies every Wave B author whose doc is listed; each author removes the `PENDING CCR-NNN` marker and conforms |
| 6 Verify | Wave C auditor | checks that no document uses an unapplied or rejected CCR |

## 4. Register
| CCR ID | Date | Requester (agent/doc) | Needed item | Reason | Proposed change | Breaking? | Affected docs | Status | Decided by | Applied in |
|---|---|---|---|---|---|---|---|---|---|---|
| — | — | — | *(no requests yet)* | — | — | — | — | — | — | — |

Status values: `Proposed` · `Needs owner` · `Approved` · `Rejected` · `Applied`.
