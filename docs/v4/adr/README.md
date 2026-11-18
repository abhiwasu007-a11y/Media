# ADR index (`docs/v4/adr/`)

Format of every ADR: header table (status, decider, dependencies, directive sections, research IDs, MVP scope 3A/3B/3C, enterprise tier) → Context → Options considered with evidence → Decision → Consequences → Status → Revisit triggers → Cited RESEARCH_LOG IDs. Facts come only from `RESEARCH_LOG.md` IDs; unknown values are marked **REQUIRES REVIEW (Phase 1)**. Decisions follow directive §3.2a: the simplest option that meets the requirement wins.

| ADR | Decision | File | Status | MVP scope | Research IDs |
|---|---|---|---|---|---|
| ADR-001 | Job queue: own Postgres table vs Procrastinate vs PgQueuer (vs Redis/Celery) | [ADR-001_queue.md](ADR-001_queue.md) | **Proposed** | 3A | INF-01, INF-05, INF-06, INF-11 |
| ADR-002 | Tenancy model + RLS | — | Not started | — | — |
| ADR-003 | Auth library / identity service | — | Not started | — | — |
| ADR-004 | Dashboard stack | — | Not started | — | — |
| ADR-005 | Storage interface (S3-compatible, local disk first, off-server backup from day one) | [ADR-005_storage.md](ADR-005_storage.md) | **Proposed** | 3A (interface, local disk, backup prerequisite); 3C (object storage) | INF-01 |
| ADR-006 | Monitoring stack | — | Not started | — | — |
| ADR-007 | LLM provider adapter and model routing | — | Not started | — | — |
| ADR-008 | TTS provider | — | Not started | — | — |
| ADR-009 | Stock footage / music libraries | — | Not started | — | — |
| ADR-010 | Payment gateway | — | Not started | — | — |
| ADR-011 | n8n | — | Not started | — | — |
| ADR-012 | Render worker placement (dev environment or VPS night window; movable; never in market hours) | [ADR-012_render_worker_placement.md](ADR-012_render_worker_placement.md) | **Proposed** | 3A; 3C (separate server if needed) | INF-01, INF-02, INF-03, INF-04, INF-09 |
| ADR-013 | Not defined in `00_EXECUTION_PLAN.md` §3.1 (which lists ADR-001 … ADR-012). **REQUIRES REVIEW (Phase 1): lead to assign the subject.** | — | Not started | — | — |

ADR titles 002–011 are taken from `00_EXECUTION_PLAN.md` step 3.1.

Status values for ADRs: `Not started` · `Proposed` · `Accepted` (owner approved) · `Superseded by ADR-NNN`. Software status of the component stays separate (directive rule 6).

## Cross-links among the written ADRs
- ADR-012 depends on ADR-001 (claim through `amw_queue_claim`, capability routing) and ADR-005 (a render worker on another machine needs the object-storage backend or an approved access path).
- ADR-005 revisit trigger 1 fires when ADR-012 places the render worker off the machine that holds the storage root.
