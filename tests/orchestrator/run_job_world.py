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


EXPECTED_UNMET_PORTS = frozenset(
    {
        "agent_04.research_pack:directory",
        "agent_04.research_pack:library",
        "agent_04.research_pack:memory",
        "agent_04.research_pack:prompts",
        "agent_04.research_pack:resolver_factory",
        "agent_04.research_pack:settings",
        "agent_04.research_pack:web",
        "agent_05.script_draft:chunks",
        "agent_05.script_draft:control",
        "agent_05.script_draft:hook_history",
        "agent_05.script_draft:prompts",
        "agent_05.script_draft:resolver",
        "agent_05.script_draft:scanners_for",
        "agent_05.script_draft:settings",
        "agent_06.claim_extraction:chart_ranges",
        "agent_06.claim_extraction:claims",
        "agent_06.claim_extraction:prompts",
        "agent_06.claim_extraction:rule_packs",
        "agent_06.claim_extraction:scripts",
        "agent_06.claim_extraction:settings",
        "agent_06.claim_verification:claims",
        "agent_06.claim_verification:knowledge",
        "agent_06.claim_verification:prompts",
        "agent_06.claim_verification:quotes",
        "agent_06.claim_verification:scripts",
        "agent_06.claim_verification:settings",
        "agent_07.audio_master:backend",
        "agent_07.audio_master:config",
        "agent_07.audio_master:control",
        "agent_07.audio_master:facts",
        "agent_07.audio_master:scratch_root",
        "agent_07.audio_master:tools",
        "agent_07.voice_synthesis:breaker",
        "agent_07.voice_synthesis:config",
        "agent_07.voice_synthesis:control",
        "agent_07.voice_synthesis:facts",
        "agent_07.voice_synthesis:registry",
        "agent_07.voice_synthesis:scratch_root",
        "agent_07.voice_synthesis:tools",
        "agent_08.asset_sourcing:approvals",
        "agent_08.asset_sourcing:assets",
        "agent_08.asset_sourcing:brand_kits",
        "agent_08.asset_sourcing:fingerprints",
        "agent_08.asset_sourcing:licences",
        "agent_08.asset_sourcing:settings",
        "agent_09.shot_plan:cfg",
        "agent_09.shot_plan:prompts",
        "agent_09.shot_plan:recorder",
        "agent_09.shot_plan:worst_case_call_micros",
        "agent_10.render:admission",
        "agent_10.render:assets",
        "agent_10.render:cfg",
        "agent_10.render:licences",
        "agent_10.render:qc_results",
        "agent_10.render:renders",
        "agent_10.render:runner",
        "agent_10.render:scratch_root",
        "agent_10.render:timers",
        "agent_10.subtitles:admission",
        "agent_10.subtitles:assets",
        "agent_10.subtitles:cfg",
        "agent_10.subtitles:licences",
        "agent_10.subtitles:qc_results",
        "agent_10.subtitles:renders",
        "agent_10.subtitles:runner",
        "agent_10.subtitles:scratch_root",
        "agent_10.subtitles:timers",
        "agent_10.technical_qc:admission",
        "agent_10.technical_qc:assets",
        "agent_10.technical_qc:cfg",
        "agent_10.technical_qc:licences",
        "agent_10.technical_qc:qc_results",
        "agent_10.technical_qc:renders",
        "agent_10.technical_qc:runner",
        "agent_10.technical_qc:scratch_root",
        "agent_10.technical_qc:timers",
        "agent_11.thumbnail_variants:composer",
        "agent_11.thumbnail_variants:lexicons",
        "agent_11.thumbnail_variants:packs",
        "agent_11.thumbnail_variants:prompt",
        "agent_11.thumbnail_variants:repo",
        "agent_11.thumbnail_variants:settings",
        "agent_11.thumbnail_variants:templates",
        "agent_16.compliance_gate:assembler",
        "agent_16.compliance_gate:breaker",
        "agent_16.compliance_gate:config",
        "agent_16.compliance_gate:evidence",
        "agent_16.compliance_gate:pack_texts",
        "agent_16.compliance_gate:packs",
        "agent_16.compliance_gate:prompts",
        "agent_16.compliance_gate:writer",
        "agent_16.quality_score:breaker",
        "agent_16.quality_score:config",
        "agent_16.quality_score:extractor",
        "agent_16.quality_score:groups",
        "agent_16.quality_score:prompt",
        "agent_16.quality_score:renders",
        "svc_s02.uniqueness_check:config",
        "svc_s02.uniqueness_check:extractor",
        "svc_s02.uniqueness_check:source",
    }
)
# The exact inventory of ports with no production wiring (derived from the agents' own
# constructors): a change of an agent signature or of the wiring must change it on purpose.


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

    def run_entry_file(self, tts_provider: str | None = "elevenlabs") -> Path:
        data = json.loads(DEFAULT_FILE.read_text(encoding="utf-8"))
        data["worker_name_prefix"] = "orchtest-"  # only this suite's worker rows
        data["tts"] = {"provider": tts_provider}  # the owner's route: no default in the seed
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
