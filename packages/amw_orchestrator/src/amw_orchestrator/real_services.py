"""``BuildServices`` of a REAL run: the S4 cost report of the job and the delivery policy values.

The runner already serves ``read_json`` and ``payload_document`` itself (hash-verified through its
tenant-scoped ``TaskIo``); what it asks of this object is the two facts the delivery builder
refuses to decide:

* ``cost_report``: ``amw_core.cost.build_cost_stage_report`` over the job's own ledger rows, the
  job's task rows and the status of every budget in scope, read inside one tenant transaction
  (explicit org predicate plus RLS in the callees). An unknown value prints as REQUIRES REVIEW,
  never as zero (09 section 12).
* ``delivery_facts``: wording and limits from the run entry settings (``delivery``, D16 data, no
  literal here) and the FIN-R10 disclaimer text from the runtime data file of the configured
  version; its DRAFT status label is passed on, never dropped.

Tenant isolation: the transaction is opened for the job's own org; a job of another org than the
one this object was built for is refused before any read."""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from amw_core.budget_guard import BudgetGuardCore
from amw_core.contracts import TaskOutput
from amw_core.cost import JobHeader, TaskInfo, build_cost_stage_report
from amw_core.cost.pg import PgCostLedger
from amw_core.errors import TenantMismatchError
from amw_core.ids import ActorRef, JobId, OrgId, SystemActor
from amw_core.interfaces import TenancyContext, TenantContext
from amw_core.job_store.pg import PgJobStore
from amw_orchestrator.executor import DocRef, JobFacts
from amw_orchestrator.run_settings import DeliveryPolicySeed
from amw_runtime.disclaimer import Disclaimer


class ProductionBuildServices:
    def __init__(
        self,
        *,
        org_id: str,
        tenancy: TenancyContext,
        jobs: PgJobStore,
        ledger: PgCostLedger,
        guard: BudgetGuardCore,
        now: Callable[[], datetime],
        policy: DeliveryPolicySeed,
        disclaimer: Disclaimer,
        minor_exponents: Mapping[str, int],
        run_label: str,
    ) -> None:
        self._org = org_id
        self._tenancy, self._jobs, self._ledger, self._guard = tenancy, jobs, ledger, guard
        self._now, self._policy, self._disclaimer = now, policy, disclaimer
        self._exponents, self._run_label = dict(minor_exponents), run_label

    def read_json(self, uri: str, sha256: str) -> Mapping[str, Any]:
        raise NotImplementedError("document reads are served by the runner's own TaskIo")

    def payload_document(self, job: JobFacts, output: TaskOutput) -> DocRef:
        raise NotImplementedError("payload documents are served by the runner's own TaskIo")

    def _own(self, job: JobFacts) -> TenantContext:
        if job.org_id != self._org:
            raise TenantMismatchError("the job belongs to another tenant than these services")
        return TenantContext(OrgId(job.org_id), ActorRef(SystemActor.OPERATOR.value))

    def cost_report(self, job: JobFacts) -> Mapping[str, Any]:
        job_id = JobId(job.job_id)
        with self._tenancy.transaction(self._own(job)) as tx:
            rows = self._ledger.for_job(tx, job_id)
            tasks = {
                t.id: TaskInfo(t.task_type, t.stage_id, t.iteration)
                for t in self._jobs.list_tasks(tx, job_id)
            }
            statuses = [
                self._guard.status(tx, b.id, job_id)
                for b in self._guard.applicable_budgets(tx, job_id)
            ]
        header = JobHeader(
            job_id, job.production_type_key.value, job.production_type_version, None,
            self._run_label,
        )  # fmt: skip
        report = build_cost_stage_report(
            header, rows, tasks, statuses, self._now(), self._exponents
        )
        return report.model_dump(mode="json")

    def delivery_facts(self, job: JobFacts) -> Mapping[str, Any]:
        self._own(job)
        policy, disclaimer = self._policy, self._disclaimer
        limits = policy.limits
        return {
            "config_version": policy.config_version,
            "banner": policy.banner,
            "disclaimer": {
                "text": disclaimer.text,
                "version": disclaimer.version,
                "status_label": disclaimer.status,
            },
            "disclosure_note": policy.disclosure_note,
            "limits": {
                "max_file_bytes": limits.max_file_bytes,
                "max_total_bytes": limits.max_total_bytes,
                "max_thumbnail_bytes": limits.max_thumbnail_bytes,
            },
        }
