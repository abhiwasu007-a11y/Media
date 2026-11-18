"""Shared test helpers for Agent 16: config, lexicon, dataset loading, scripted LLM, IDs."""

import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_16_compliance_qa.config import Agent16Config
from amw_adapters.common import CallUsage
from amw_adapters.llm.protocol import LlmRequest, LlmResponse
from amw_core import ids
from amw_core.errors import BudgetExhaustedError
from amw_core.ids import BudgetId, CostEntryId, JobId, TaskId
from amw_core.interfaces.budget_guard import Budget as BudgetRow
from amw_core.interfaces.budget_guard import (
    BudgetStatus,
    CallCheck,
    Reservation,
    ReservationOutcome,
)
from amw_core.interfaces.cost_ledger import CostEntry, CostTotals, NewCostEntry
from amw_core.interfaces.tenancy_context import TenantTransaction

REPO = Path(__file__).resolve().parents[3]
EVALS = REPO / "docs/v4/evals/agent_16_compliance_qa"
PROMPTS = REPO / "docs/v4/prompts/agent_16_compliance_qa"
BLUEPRINT = REPO / "docs/v4/agents/agent_16_compliance_qa.md"

EN_LEXICON: dict[str, Any] = {
    "version": "lex.en.test.1",
    "future_markers": [
        "will",
        "should",
        "likely to",
        "target",
        "next move",
        "again",
        "repeat",
        "same setup now",
    ],
    "imperative_verbs": [
        "buy",
        "sell",
        "hold",
        "enter",
        "exit",
        "add",
        "accumulate",
        "avoid",
        "go long",
        "short",
    ],
    "level_words": ["target", "stop", "strike", "level"],
    "promotion_words": ["link", "code", "broker", "sponsor", "sponsored", "open an account"],
    "group_words": ["group", "membership", "members", "tips", "daily calls", "alerts"],
    "identity_markers": ["i am", "your host"],
    "child_markers": ["nursery", "cartoon", "kids", "children", "little friends"],
    "person_markers": ["i", "my", "you", "your", "we", "our", "students"],
    "live_format_terms": ["live trading", "live session", "live"],
}

# PROVISIONAL, REQUIRES REVIEW (Phase 1): Marathi / Hindi / Hinglish completeness and wording
# must be confirmed by the owner or a linguist (OI-6). Real words of each language, not copies of
# the English lexicon (review M5); config in production (compliance.prefilter.lexicon.<lang>).
MR_LEXICON: dict[str, Any] = {
    "version": "lex.mr.provisional.1",
    "future_markers": ["होईल", "वाढेल", "जाईल", "उद्या", "पुढच्या आठवड्यात", "लवकरच", "नक्की"],
    "imperative_verbs": [
        "खरेदी करा",
        "विकत घ्या",
        "विका",
        "होल्ड करा",
        "एन्ट्री घ्या",
        "बाहेर पडा",
        "टाळा",
    ],
    "level_words": ["टार्गेट", "लक्ष्य", "स्टॉप लॉस", "स्ट्राइक", "पातळी", "लेव्हल"],
    "promotion_words": ["लिंक", "कोड", "ब्रोकर", "प्रायोजित", "खाते उघडा"],
    "group_words": ["ग्रुप", "समूह", "सदस्यत्व", "टिप्स", "रोजचे कॉल"],
    "identity_markers": ["मी आहे", "तुमचा होस्ट", "मार्गदर्शक", "निवेदक", "सूत्रसंचालक"],
    "child_markers": ["मुलांसाठी", "मुलांनो", "बालगीत", "कार्टून", "बालमित्र"],
    "person_markers": ["मी", "माझा", "माझे", "आम्ही", "तुम्ही", "आमचे", "विद्यार्थी"],
    "live_format_terms": ["लाइव्ह ट्रेडिंग", "लाइव्ह"],
}
HI_LEXICON: dict[str, Any] = {
    "version": "lex.hi.provisional.1",
    "future_markers": [
        "होगा",
        "बढ़ेगा",
        "जाएगा",
        "अगले हफ्ते",
        "जल्द",
        "hoga",
        "badhega",
        "jayega",
        "pakka",
    ],
    "imperative_verbs": [
        "खरीदो",
        "खरीदें",
        "बेचो",
        "बेचें",
        "होल्ड करो",
        "kharid lo",
        "khareedo",
        "becho",
        "le lo",
    ],
    "level_words": ["टारगेट", "लक्ष्य", "स्टॉप लॉस", "स्ट्राइक", "स्तर", "लेवल"],
    "promotion_words": ["लिंक", "कोड", "ब्रोकर", "प्रायोजित", "खाता खोलें"],
    "group_words": ["ग्रुप", "सदस्यता", "टिप्स", "रोज़ के कॉल"],
    "identity_markers": ["मैं हूँ", "आपका होस्ट"],
    "child_markers": ["बच्चों", "बच्चो", "बाल गीत", "कार्टून"],
    "person_markers": ["मैं", "मेरा", "मेरे", "हम", "आप", "हमारा", "छात्र", "maine", "mera"],
    "live_format_terms": ["लाइव ट्रेडिंग", "लाइव"],
}

BASE_CONFIG: dict[str, Any] = {
    "quality.publish_min_score": 85,
    "quality.machine_scaling": "NONE",
    "quality.score_gate_mode": "REPORT_ONLY",
    "editorial.min_description_chars": 20,
    "approvals.accepted_channels": ["OWNER_CHAT_OPERATOR"],
    "approvals.review_code.length": 4,
    "compliance.finance_sebi_in.price_data_lag_days": 30,
    "compliance.watermark_visual.calibrated": False,
    "compliance.gate.max_items_per_judge_call": 8,
    "compliance.gate.max_llm_calls": 16,
    "uniqueness.cross_video.skip_below_prior_count": 3,
    "agent_16.llm.fallback_on_unavailable": False,
    "compliance.prefilter.lexicon.en": EN_LEXICON,
    "compliance.prefilter.lexicon.mr": MR_LEXICON,
    "compliance.prefilter.lexicon.hi": HI_LEXICON,
}
for _step in (
    "compliance_gate.policy",
    "compliance_gate.paraphrase",
    "compliance_gate.frames",
    "quality_score.judge",
):
    for _k, _v in {
        "model": "test-model-from-config",
        "max_output_tokens": 2000,
        "temperature": 0,
        "timeout_ms": 30000,
        "cache_system_prompt": True,
        "max_calls": 8,
        "worst_case_call_micros": 100,
        "max_cost_micros": 100000,
        "accepts_images": _step.endswith("frames") or _step.endswith("judge"),
    }.items():
        BASE_CONFIG[f"llm.agent_16.{_step}.{_k}"] = _v


def config(**overrides: Any) -> Agent16Config:
    return Agent16Config.from_mapping(BASE_CONFIG | overrides)


def cases(dataset: str) -> list[dict[str, Any]]:
    path = EVALS / dataset / "cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def case_ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(r["case_id"]) for r in rows]


class ScriptedLlm:
    """``LlmAdapter`` that returns queued texts (no network, no cost beyond fake micros)."""

    provider = "fake_llm"

    def __init__(self, texts: Iterator[str] | list[str], micros: int = 10) -> None:
        self._texts = iter(texts)
        self.requests: list[LlmRequest] = []
        self.keys: list[str] = []
        self._micros = micros

    def complete(self, request: LlmRequest, *, idempotency_key: str) -> LlmResponse:
        self.requests.append(request)
        self.keys.append(idempotency_key)
        text = next(self._texts)
        usage = CallUsage(
            provider="fake_llm",
            operation="llm.completion",
            model=request.model,
            tokens_in=10,
            tokens_out=5,
            amount_micros=self._micros,
            currency="USD",
            idempotency_key=idempotency_key,
        )
        return LlmResponse(text=text, stop_reason="end_turn", usage=usage)

    def count_tokens(self, request: LlmRequest, *, idempotency_key: str) -> Any:
        raise NotImplementedError


class Ledger:
    """In-memory ``CostLedger`` (one row per paid call, keyed by its idempotency key)."""

    def __init__(self) -> None:
        self.rows: list[str] = []
        self.entries: dict[str, CostEntry] = {}

    def record(self, tx: TenantTransaction, entry: NewCostEntry) -> CostEntry:
        self.rows.append(str(entry.idempotency_key))
        row = CostEntry(id=ids.COST_ENTRY.new(), org_id=tx.context.org_id, entry=entry)
        self.entries[str(row.id)] = row
        return row

    def get(self, tx: TenantTransaction, entry_id: CostEntryId) -> CostEntry | None:
        return self.entries.get(str(entry_id))

    def for_job(self, tx: TenantTransaction, job_id: JobId) -> Sequence[CostEntry]:
        return [e for e in self.entries.values() if e.entry.job_id == job_id]

    def for_task(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[CostEntry]:
        return [e for e in self.entries.values() if e.entry.task_id == task_id]

    def job_totals(self, tx: TenantTransaction, job_id: JobId) -> CostTotals:
        raise NotImplementedError  # not used by Agent 16


class Budget:
    """In-memory ``BudgetGuard`` parts the judge client uses (E2 / E3 and the provider gate)."""

    def __init__(self, *, gate_open: bool = True, remaining: int = 10**9) -> None:
        self.gate_open, self.remaining = gate_open, remaining
        self.checks: list[CallCheck] = []
        self.after: list[CostEntry] = []

    def check_provider_gate(self, tx: TenantTransaction, provider: str) -> None:
        if not self.gate_open:
            raise BudgetExhaustedError("no ACTIVE PROVIDER budget")

    def check_call(self, tx: TenantTransaction, check: CallCheck) -> None:
        self.checks.append(check)
        if check.estimated_cost_micros > self.remaining:
            raise BudgetExhaustedError("reservation exhausted")

    def after_call(self, tx: TenantTransaction, entry: CostEntry) -> Sequence[BudgetRow]:
        self.after.append(entry)
        self.remaining -= entry.entry.amount_micros
        return []

    # the rest of BudgetGuard is the worker's (E1 / T08 / T11), never Agent 16's
    def applicable_budgets(self, tx: TenantTransaction, job_id: JobId) -> Sequence[BudgetRow]:
        raise NotImplementedError

    def reserve(
        self, tx: TenantTransaction, task_id: TaskId, amount_micros: int, currency: str
    ) -> ReservationOutcome:
        raise NotImplementedError

    def consume(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[Reservation]:
        raise NotImplementedError

    def release(self, tx: TenantTransaction, task_id: TaskId) -> Sequence[Reservation]:
        raise NotImplementedError

    def status(self, tx: TenantTransaction, budget_id: BudgetId) -> BudgetStatus:
        raise NotImplementedError


class Breaker:
    def __init__(self, open_: bool = False) -> None:
        self.open = open_

    def is_open(self, provider: str) -> bool:
        return self.open


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def monotonic_ms(self) -> int:
        return 0


def blueprint_schema(heading: str) -> dict[str, Any]:
    """The JSON Schema block under a section heading of the blueprint (contract tests C-01)."""
    text = BLUEPRINT.read_text(encoding="utf-8")
    start = text.index(heading)
    block = text.index("```json", start) + len("```json")
    return dict(json.loads(text[block : text.index("```", block)]))


def validate_against_blueprint(payload: Any, heading: str) -> None:
    """JSON Schema check of a payload against the blueprint section, with ``amw.common`` from
    the amw_core registry (no network)."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from amw_core.contracts.registry import get_schema, schema_id

    common = get_schema("amw.common", "1.0.0")
    registry: Registry[Any] = Registry().with_resource(
        schema_id("amw.common", "1.0.0"), Resource.from_contents(dict(common))
    )
    Draft202012Validator(blueprint_schema(heading), registry=registry).validate(payload)


def evidence_mapping(**over: Any) -> Mapping[str, Any]:
    base = {
        "state": "CONFIRMED",
        "source_kind": "OWNER_CHAT_MESSAGE",
        "same_org": True,
        "on_behalf_of_matches": True,
        "subject_matches": True,
        "review_code_matches": True,
        "parsed_decision_matches": True,
        "message_after_request": True,
        "confirmation_after_message": True,
        "verifier_all_passed": True,
        "failed_tests": [],
        "refused_reason": None,
        "hash_recomputes": True,
        "mac_valid": True,
        "replay_free": True,
        "backs_only_this_record": True,
        "recorded_by_operator": True,
    }
    return base | over
