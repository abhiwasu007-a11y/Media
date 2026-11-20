"""Shared fixtures of the ``run_job`` tests: a seeded tenant (org, channel of a documented
non-finance category, project, workers, the per-video cap rows an owner would have created), the
settings and the request file. No network, no key, no paid call."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from amw_core.budget_guard.pg import PgBudgetBackend
from amw_core.config import AmwSettings, load_settings
from amw_core.contracts import OwnerTopic
from amw_core.ids import ActorRef
from amw_core.interfaces import TenantContext
from amw_core.tenancy import PgTenancy, dsn_connection_factory
from amw_orchestrator.run_request import JobRequest, LibraryInput
from amw_orchestrator.run_settings import DEFAULT_FILE
from amw_orchestrator.services import seed_cap_budgets
from tests.orchestrator.world import Seed, seed, set_channel_category

M = 1_000_000
SHA = "a" * 40
SATURDAY = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
"""A day without a market session: the render guard of the calendar does not close the run."""
PROVIDERS = ("fake_llm", "fake_tts", "anthropic", "elevenlabs")


@dataclass(frozen=True)
class World:
    dsn: str
    seed: Seed
    tmp: Path

    def env(self, **extra: str) -> dict[str, str]:
        return {
            "AMW_DATABASE__URL": self.dsn,
            "AMW_STORAGE__ROOT": str(self.tmp / "blobs"),
            "AMW_ENVIRONMENT": "development",
            **extra,
        }

    def settings(self) -> AmwSettings:
        return load_settings(environ=self.env())

    def run_entry_file(self) -> Path:
        data = json.loads(DEFAULT_FILE.read_text(encoding="utf-8"))
        data["worker_name_prefix"] = "orchtest-"  # only this suite's worker rows
        path = self.tmp / "run_entry.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def request(self, **over: object) -> JobRequest:
        topic = OwnerTopic.model_validate(
            {
                "schema_version": "1.0.0", "title": "Seneca on the shortness of life",
                "brief": None, "angle": None, "language": "mr-IN", "video_kind": "GENERAL",
                "course_chapter_pointer": None, "owner_references": [],
                "target_duration_ms": 60_000, "shorts_wanted": False,
            }
        )  # fmt: skip
        base: dict[str, object] = {
            "org_id": self.seed.org_id, "workspace_id": self.seed.workspace_id,
            "project_id": self.seed.project_id, "channel_id": self.seed.channel_id,
            "topic": topic,
            "library": LibraryInput(repo_path=self.tmp / "no-such-library", commit_sha=SHA),
        }  # fmt: skip
        return JobRequest.model_validate({**base, **over})

    def request_file(self, request: JobRequest | None = None) -> Path:
        path = self.tmp / "job.json"
        path.write_text((request or self.request()).model_dump_json(), encoding="utf-8")
        return path


def make_world(dsn: str, tmp: Path, *, category: str | None = "youtube_general") -> World:
    s = seed(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        # the claim is cross-tenant: rows left live by an earlier test must not reach this runner
        conn.execute(
            "UPDATE task_queue SET status = 'CANCELLED' WHERE status IN ('READY', 'CLAIMED')"
        )
    set_channel_category(dsn, s.channel_id, category)
    tenancy = PgTenancy(dsn_connection_factory(dsn, role="amw_app"))
    with tenancy.transaction(TenantContext(s.org_id, ActorRef(s.owner))) as tx:  # type: ignore[arg-type]
        seed_cap_budgets(
            PgBudgetBackend().create_budget, tx, org_id=s.org_id, per_video_cap_micros=5 * M,
            pilot_cap_micros=50 * M, currency="USD", minor_exponent=2, providers=PROVIDERS,
        )  # fmt: skip
    return World(dsn, s, tmp)
