"""Unit tests: CopyGuard, NoteValidator, ReliabilityScorer, TierScores, gate, TenantGuard (10.3-10.6)."""
# ruff: noqa: E501, PT018

from typing import Any

import pytest

from agent_04_research_knowledge.errors import (
    ConfigInvalid,
    CrossTenantRef,
    InputInvalid,
    MissingDependency,
    TenantInactive,
    TenantMismatch,
)
from agent_04_research_knowledge.guards.copy_guard import CopyGuard, longest_shared_run, normalise
from agent_04_research_knowledge.guards.restricted import (
    ApprovalView,
    ChunkMeta,
    RestrictedCollectionGate,
    TopicFlags,
    release_subject_sha256,
)
from agent_04_research_knowledge.guards.tenant import TenantGuard
from agent_04_research_knowledge.models.enums import (
    DomainClass,
    GateReason,
    NoteProblem,
    ReliabilityTier,
)
from agent_04_research_knowledge.models.notes import NoteCandidate
from agent_04_research_knowledge.models.pack_input import ResearchPackInput
from agent_04_research_knowledge.scoring.reliability import (
    DomainClassRegistry,
    ReliabilityScorer,
    SourceMeta,
    TierScores,
)
from agent_04_research_knowledge.steps.notes import NoteLimits, NoteValidator
from amw_core.contracts.task_input import TaskInput
from amw_core.enums import (
    ApprovalKind,
    ApprovalState,
    KnowledgeSourceKind,
    SourceOwnership,
    VideoKind,
)
from tests.agents.agent_04_research_knowledge.conftest import World, build_world, make_settings

pytestmark = pytest.mark.unit
SCORES = make_settings().tier_scores()
LIMITS = NoteLimits(300, 6, 0.5, 3)


def note(text: str, **over: object) -> NoteCandidate:
    base: dict[str, object] = {
        "note_ref": "n1",
        "passage_id": "p1",
        "statement_kind": "DEFINITION",
        "note": text,
        "time_reference_kind": "TIMELESS",
        "instruments": [],
        "numbers_in_note": [],
        "clarity": "CLEAR",
        "forward_looking": False,
    }
    base.update(over)
    return NoteCandidate.model_validate(base)


def test_normalise_and_longest_run() -> None:
    assert normalise("A Stop-Loss, ORDER!") == ["a", "stop", "loss", "order"]
    assert longest_shared_run(["a", "b", "c", "d"], ["x", "b", "c", "y"]) == 2
    assert longest_shared_run([], ["a"]) == 0


def test_copy_guard_symmetric_and_monotonic() -> None:
    guard = CopyGuard()
    a = "one two three four five six seven eight"
    for run_len in range(1, 8):
        b = " ".join(a.split()[:run_len]) + " zzz yyy xxx"
        res = guard.check(b, a, 3, 0.99, max_verbatim_words=20, passage_language="en")
        assert res.longest_shared_run == run_len
    r1 = guard.check(
        a, "five six seven nine", 2, 0.99, max_verbatim_words=20, passage_language="en"
    )
    r2 = guard.check(
        "five six seven nine", a, 2, 0.99, max_verbatim_words=20, passage_language="en"
    )
    assert r1.longest_shared_run == r2.longest_shared_run == 3


def test_copy_guard_overlap_ratio_fails_without_long_run() -> None:
    guard = CopyGuard()
    passage = "alpha beta gamma delta epsilon zeta eta theta"
    note_text = "alpha beta gamma. delta epsilon zeta. eta theta"
    res = guard.check(note_text, passage, 2, 0.5, max_verbatim_words=20, passage_language="en")
    assert res.longest_shared_run == 8
    res = guard.check(
        "alpha beta x delta epsilon y eta theta",
        passage,
        2,
        0.3,
        max_verbatim_words=20,
        passage_language="en",
    )
    assert not res.passed and res.longest_shared_run < 20


def test_copy_guard_cross_language_by_script_and_tag() -> None:
    guard = CopyGuard()
    mr = "स्टॉप-लॉस म्हणजे ठरावीक पातळीवर व्यवहार बंद करणारी ऑर्डर"
    assert (
        guard.check("a stop loss closes", mr, 3, 0.5, max_verbatim_words=6).skipped_reason
        == "CROSS_LANGUAGE"
    )
    res = guard.check(
        "a stop loss",
        "a stop loss",
        3,
        0.5,
        max_verbatim_words=6,
        note_language="en",
        passage_language="mr",
    )
    assert res.skipped_reason == "CROSS_LANGUAGE" and res.passed


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Open an account at example.org today.", NoteProblem.URL_OR_QUOTE),
        ("Write to me at name@example.com for tips.", NoteProblem.URL_OR_QUOTE),
        ("Use code SAVE now with the broker.", NoteProblem.URL_OR_QUOTE),
        ('The author says "cut losses" matters.', NoteProblem.URL_OR_QUOTE),
        ("It rose 45 percent in a year.", NoteProblem.NUMBER_NOT_IN_PASSAGE),
    ],
)
def test_note_validator_problems(text: str, problem: NoteProblem) -> None:
    verdict = NoteValidator().validate(
        note(text), "Prices moved over a long year with no fixed pattern.", "en", LIMITS
    )
    assert not verdict.passed and verdict.problem is problem and not verdict.usable


def test_note_validator_ambiguous_and_too_long_and_usable_flags() -> None:
    v = NoteValidator()
    passage = "Risk limits keep losses small over many trades."
    assert (
        v.validate(note("Limits help.", clarity="AMBIGUOUS"), passage, "en", LIMITS).problem
        is NoteProblem.AMBIGUOUS
    )
    long_note = note("x" * 10 + " " + "words " * 60)
    assert v.validate(long_note, passage, "en", LIMITS).problem is NoteProblem.AMBIGUOUS
    ok = v.validate(note("Small risk caps keep any loss modest."), passage, "en", LIMITS)
    assert ok.passed and ok.usable and ok.exclusion_reason is None
    future = v.validate(
        note("A cap may help later.", time_reference_kind="FUTURE"), passage, "en", LIMITS
    )
    assert future.passed and not future.usable and future.exclusion_reason is not None
    fwd = v.validate(note("A cap may help later.", forward_looking=True), passage, "en", LIMITS)
    assert not fwd.usable


@pytest.mark.parametrize(
    ("kind", "own", "domain", "library", "tier"),
    [
        (
            KnowledgeSourceKind.OFFICIAL_DOCUMENT,
            SourceOwnership.PUBLIC_OFFICIAL,
            None,
            True,
            ReliabilityTier.A_PRIMARY,
        ),
        (
            KnowledgeSourceKind.BOOK,
            SourceOwnership.OWNED_COPY,
            None,
            True,
            ReliabilityTier.B_PUBLISHED,
        ),
        (
            KnowledgeSourceKind.CLIENT_DOCUMENT,
            SourceOwnership.LICENSED,
            None,
            True,
            ReliabilityTier.B_PUBLISHED,
        ),
        (
            KnowledgeSourceKind.WEB_REFERENCE,
            None,
            DomainClass.OFFICIAL,
            False,
            ReliabilityTier.A_PRIMARY,
        ),
        (
            KnowledgeSourceKind.WEB_REFERENCE,
            None,
            DomainClass.REPUTABLE_SECONDARY,
            False,
            ReliabilityTier.C_SECONDARY,
        ),
        (KnowledgeSourceKind.WEB_REFERENCE, None, None, False, ReliabilityTier.D_UNVERIFIED),
        (
            KnowledgeSourceKind.BOOK,
            SourceOwnership.PUBLIC_OFFICIAL,
            None,
            True,
            ReliabilityTier.D_UNVERIFIED,
        ),
    ],
)
def test_reliability_tiers(kind, own, domain, library, tier) -> None:  # type: ignore[no-untyped-def]
    rel = ReliabilityScorer().score(SourceMeta(kind, own, domain, library), None, SCORES)
    assert rel.tier is tier
    assert not rel.excluded
    assert rel.tier is not None
    assert rel.score == SCORES.score(rel.tier)
    assert (rel.ownership_in_pack is None) == (not library)


def test_reliability_unknown_ownership_excluded_and_owner_authored() -> None:
    rel = ReliabilityScorer().score(
        SourceMeta(KnowledgeSourceKind.BOOK, SourceOwnership.UNKNOWN), None, SCORES
    )
    assert rel.excluded and rel.reason == "OWNERSHIP_UNKNOWN"
    own = ReliabilityScorer().score(
        SourceMeta(KnowledgeSourceKind.OWNER_NOTES, SourceOwnership.OWNER_AUTHORED), None, SCORES
    )
    assert own.owner_authored and own.tier is ReliabilityTier.B_PUBLISHED


def test_tier_scores_must_strictly_decrease() -> None:
    TierScores(0.9, 0.7, 0.5, 0.2)
    for bad in ((0.5, 0.7, 0.5, 0.2), (0.9, 0.9, 0.5, 0.2), (1.2, 0.7, 0.5, 0.2)):
        with pytest.raises(ConfigInvalid):
            TierScores(*bad)
    with pytest.raises(ConfigInvalid):
        TierScores.from_mapping({"A_PRIMARY": 0.9})


def test_domain_registry_subdomains() -> None:
    reg = DomainClassRegistry({"gov.example": DomainClass.OFFICIAL})
    assert reg.class_of_host("data.gov.example") is DomainClass.OFFICIAL
    assert reg.class_of_url("https://other.example/x") is None


# ---- restricted gate -----------------------------------------------------------------------
ORG = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f"


class Lookup:
    def __init__(
        self, approval: ApprovalView | None, released: frozenset[str] = frozenset()
    ) -> None:
        self.a, self.released = approval, released

    def approval(self, approval_id: str) -> ApprovalView | None:
        return self.a

    def released_chunk_ids(self, approval_id: str, collection_id: str) -> frozenset[str]:
        return self.released


def chunk(**over: object) -> ChunkMeta:
    base: dict[str, object] = {
        "chunk_id": "kch_1",
        "org_id": ORG,
        "collection_id": "kcl_1",
        "collection_key": "owner_method",
        "collection_restricted": True,
        "source_id": "ksr_1",
        "source_release_approval_id": "apr_1",
        "chunk_release_approval_id": None,
    }
    base.update(over)
    return ChunkMeta(**base)  # type: ignore[arg-type]


def apv(**over: object) -> ApprovalView:
    base: dict[str, object] = {
        "approval_id": "apr_1",
        "org_id": ORG,
        "kind": ApprovalKind.KNOWLEDGE_RELEASE,
        "state": ApprovalState.APPROVED,
    }
    base.update(over)
    return ApprovalView(**base)  # type: ignore[arg-type]


METHOD = TopicFlags(VideoKind.METHOD_TOPIC, "Our method topic")
GENERAL = TopicFlags(VideoKind.GENERAL, "Our method topic")


def test_gate_matrix() -> None:
    gate = RestrictedCollectionGate()
    ok = gate.evaluate(chunk(), METHOD, Lookup(apv()))
    assert ok.allowed and ok.method_labelled and ok.release_approval_id == "apr_1"
    assert gate.evaluate(chunk(collection_restricted=False), GENERAL, Lookup(None)).allowed
    cases = [
        (chunk(), GENERAL, Lookup(apv()), GateReason.NOT_METHOD_TOPIC),
        (chunk(), METHOD, Lookup(None), GateReason.RELEASE_MISSING),
        (chunk(source_release_approval_id=None), METHOD, Lookup(apv()), GateReason.RELEASE_MISSING),
        (chunk(), METHOD, Lookup(apv(kind=ApprovalKind.TOPIC)), GateReason.RELEASE_WRONG_KIND),
        (
            chunk(),
            METHOD,
            Lookup(apv(state=ApprovalState.PENDING)),
            GateReason.RELEASE_NOT_APPROVED,
        ),
        (
            chunk(),
            METHOD,
            Lookup(apv(state=ApprovalState.REJECTED)),
            GateReason.RELEASE_NOT_APPROVED,
        ),
        (
            chunk(source_release_approval_id="apr_9"),
            METHOD,
            Lookup(apv()),
            GateReason.RELEASE_NOT_COVERING,
        ),
    ]
    for meta, topic, lookup, reason in cases:
        res = gate.evaluate(meta, topic, lookup)
        assert not res.allowed and res.reason is reason
        assert res.restricted_pending == (reason is not GateReason.NOT_METHOD_TOPIC)


def test_gate_foreign_org_raises() -> None:
    other = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e90"
    with pytest.raises(CrossTenantRef):
        RestrictedCollectionGate().evaluate(chunk(), METHOD, Lookup(apv(org_id=other)))


def test_gate_source_subject_and_per_topic_hash() -> None:
    gate = RestrictedCollectionGate()
    by_subject = chunk(source_release_approval_id=None, chunk_release_approval_id=None)
    assert not gate.evaluate(by_subject, METHOD, Lookup(None)).allowed
    sa = apv(subject_kind="knowledge_source", subject_id="ksr_1")
    assert gate.evaluate(chunk(source_release_approval_id="apr_1"), METHOD, Lookup(sa)).allowed
    released = frozenset({"kch_1", "kch_2"})
    good = release_subject_sha256("Our method topic", "owner_method", released)
    per = chunk(source_release_approval_id=None, chunk_release_approval_id="apr_1")
    approval = apv(subject_kind="knowledge_release", subject_id="kcl_1", subject_sha256=good)
    assert gate.evaluate(per, METHOD, Lookup(approval, released)).allowed
    other_topic = TopicFlags(VideoKind.METHOD_TOPIC, "Another title")
    res = gate.evaluate(per, other_topic, Lookup(approval, released))
    assert res.reason is GateReason.RELEASE_NOT_COVERING
    assert not gate.evaluate(per, METHOD, Lookup(approval, frozenset({"kch_2"}))).allowed
    assert release_subject_sha256("t", "k", ["b", "a"]) == release_subject_sha256(
        "t", "k", ["a", "b"]
    )
    assert release_subject_sha256("t", "k", ["a"]) != release_subject_sha256("t2", "k", ["a"])


# ---- tenant guard --------------------------------------------------------------------------
def guard_for(w: World) -> TenantGuard:
    return TenantGuard(w.directory, w.library)


def parsed(w: World, **over: Any) -> tuple[TaskInput, ResearchPackInput]:
    return w.task_input(w.data(**over)), ResearchPackInput.model_validate(w.data(**over))


def test_tenant_guard_ok_and_each_failure() -> None:
    w = build_world()
    task, data = parsed(w)
    check = guard_for(w).check(task, data)
    assert check.scope.org_id == w.org and check.workspace_id == "wsp_x"
    with pytest.raises(TenantMismatch):
        guard_for(w).check(task, data, envelope_org_id="org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e90")
    w.directory.active = False
    with pytest.raises(TenantInactive):
        guard_for(w).check(task, data)
    w.directory.active = True
    w.directory.channels.clear()
    with pytest.raises(MissingDependency):
        guard_for(w).check(task, data)


def test_tenant_guard_input_rules() -> None:
    w = build_world()
    method = w.data(topic={**w.data()["topic"], "video_kind": "METHOD_TOPIC"})
    task, data = w.task_input(method), ResearchPackInput.model_validate(method)
    assert guard_for(w).check(task, data).collections  # a restricted collection exists
    w2 = build_world()
    w2.library._collections = {k: v for k, v in w2.library._collections.items() if not v.restricted}
    with pytest.raises(InputInvalid):
        guard_for(w2).check(w2.task_input(method), ResearchPackInput.model_validate(method))
    bad_key = w.data(library_scope={"collection_keys": ["nope_key"]})
    with pytest.raises(InputInvalid):
        guard_for(w).check(w.task_input(bad_key), ResearchPackInput.model_validate(bad_key))
    private = w.data(
        owner_references=[
            {
                "kind": "EXTERNAL_URL",
                "url": "https://127.0.0.1/x",
                "knowledge_source_id": None,
                "note": None,
            }
        ]
    )
    with pytest.raises(InputInvalid):
        guard_for(w).check(w.task_input(private), ResearchPackInput.model_validate(private))
    foreign = w.data(
        owner_references=[
            {
                "kind": "KNOWLEDGE_SOURCE",
                "url": None,
                "knowledge_source_id": "ksr_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e9f",
                "note": None,
            }
        ]
    )
    with pytest.raises(CrossTenantRef):
        guard_for(w).check(w.task_input(foreign), ResearchPackInput.model_validate(foreign))
    no_channel = w.task_input(channel_id=None)
    with pytest.raises(InputInvalid):
        guard_for(w).check(no_channel, data)
    no_project = w.task_input(project_id=None)
    with pytest.raises(MissingDependency):
        guard_for(w).check(no_project, data)


def test_tenant_guard_foreign_prior_pack_and_platform_ref() -> None:
    w = build_world()
    other = "org_0192f5a4-7c1e-7b3a-9d2e-4c5b6a7d8e90"
    rev = {"iteration": 1, "gaps": [], "prior_pack_ref": f"amw-blob://{other}/jobs/x/y.json"}
    data = ResearchPackInput.model_validate(w.data(revision=rev))
    with pytest.raises(CrossTenantRef):
        guard_for(w).check(w.task_input(w.data()), data)
    rev2 = {"iteration": 1, "gaps": [], "prior_pack_ref": "amw-blob://platform/templates/x.json"}
    data2 = ResearchPackInput.model_validate(w.data(revision=rev2))
    with pytest.raises(CrossTenantRef):  # a prior pack is always the tenant's own
        guard_for(w).check(w.task_input(w.data()), data2)
    platform_ctx = [{"uri": "amw-blob://platform/rules/rp.json", "purpose": "RULE_PACK"}]
    task = w.task_input(w.data(), context_refs=platform_ctx)
    assert (
        guard_for(w).check(task, ResearchPackInput.model_validate(w.data())).scope.org_id == w.org
    )


def test_settings_validation() -> None:
    with pytest.raises(ConfigInvalid):
        make_settings(
            **{
                "research.reliability.tier_scores": {
                    "A_PRIMARY": 0.1,
                    "B_PUBLISHED": 0.7,
                    "C_SECONDARY": 0.5,
                    "D_UNVERIFIED": 0.2,
                }
            }
        )
    with pytest.raises(ConfigInvalid):
        make_settings(**{"research.plan.max_concepts": 0})
    from agent_04_research_knowledge.settings import ResearchSettings

    with pytest.raises(ConfigInvalid):
        ResearchSettings.from_flat({})
