"""``ScriptInputResolver`` and the per-source QUOTABLE / IDEAS_ONLY rule (synthetic library)."""

from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from agent_05_scriptwriter import InputResolver
from agent_05_scriptwriter.assemble.parts import DisclaimerTemplate
from agent_05_scriptwriter.errors import CrossTenantRef, InputInvalid, MissingDependency
from agent_05_scriptwriter.pre.tenant_guard import check_tenant
from agent_06_fact_checker.library.copyright import WorkKind
from agent_06_fact_checker.library.reader import CheckoutLibraryReader, LibraryRef
from agent_06_fact_checker.library.wiring import StaticLibraryIndex, WorkRef
from amw_core.contracts.common import ContextRef
from amw_orchestrator.script_inputs import (
    LibrarySourceClassifier,
    ScriptResolvedInputs,
    SourceUse,
)
from tests.script_inputs.world import (
    CIT,
    LIMITS,
    World,
    record,
)

pytestmark = pytest.mark.unit


def _resolve(w: World, **data: Any) -> ScriptResolvedInputs:
    ti = w.task(**data)
    out = w.resolver().resolve(_step_ctx(w), ti, w.data(ti))
    assert isinstance(out, ScriptResolvedInputs)
    return out


def _step_ctx(w: World) -> Any:
    return w.ctx


def test_resolver_conforms_to_the_agent_05_port(tmp_path: Path) -> None:
    assert isinstance(World(tmp_path).resolver(), InputResolver)


def test_non_finance_philosophy_job_resolves_the_inputs(tmp_path: Path) -> None:
    w = World(tmp_path)
    got = _resolve(w, language="mr-IN")
    assert got.finance_rules_apply is False
    assert got.disclaimer_template is None
    assert "disclaimer" not in w.documents.calls
    assert list(got.rule_packs) == ["rp.youtube_general"]
    assert got.profile_rule_packs == ["rp.youtube_general"]
    assert got.pack is not None
    assert [c.concept_id for c in got.pack.concepts] == ["c01", "c02", "c03"]
    assert got.tenant.tenant_status == "ACTIVE"
    check_tenant(got.tenant, lambda *_a: None)  # the agent's own pre-check accepts the facts
    assert got.new_script_id.startswith("scr_")


def test_each_cited_source_is_marked_quotable_or_ideas_only(tmp_path: Path) -> None:
    w = World(tmp_path)
    got = _resolve(w)
    assert got.sources[CIT[0]].use is SourceUse.QUOTABLE
    assert got.sources[CIT[0]].work_id == "w_pd"
    assert got.sources[CIT[1]].use is SourceUse.IDEAS_ONLY
    assert got.sources[CIT[1]].reason == "TRANSLATOR_NOT_YET_PUBLIC_DOMAIN"
    assert got.sources[CIT[2]].use is SourceUse.QUOTABLE
    assert set(got.sources) == set(CIT)


def test_only_public_domain_text_is_ever_read(tmp_path: Path) -> None:
    w = World(tmp_path)
    _resolve(w)
    assert set(w.library.reads) == {"works/pd.txt"}  # the modern work's text is never read


@pytest.mark.parametrize(
    ("death_year", "job_date", "use"),
    [
        (1965, date(2026, 11, 20), SourceUse.QUOTABLE),  # 61 years before the job year
        (1966, date(2026, 11, 20), SourceUse.IDEAS_ONLY),  # exactly 60: not MORE than 60
        (1966, date(2027, 1, 1), SourceUse.QUOTABLE),  # the next year's start moves it over
        (1966, date(2026, 12, 31), SourceUse.IDEAS_ONLY),
        (-300, date(2026, 1, 1), SourceUse.QUOTABLE),
        (None, date(2026, 6, 1), SourceUse.IDEAS_ONLY),  # unknown death year: fail closed
        (0, date(2026, 6, 1), SourceUse.IDEAS_ONLY),  # no year 0: implausible
        (2100, date(2026, 6, 1), SourceUse.IDEAS_ONLY),  # in the future: implausible
    ],
)
def test_sixty_year_rule_counts_from_the_job_year(
    tmp_path: Path, death_year: int | None, job_date: date, use: SourceUse
) -> None:
    w = World(tmp_path)
    w.records["w_pd"] = record("w_pd", "works/pd.txt", author_death_year=death_year)
    got = w.resolver()._classifier.classify([CIT[0]], library=w.library, job_date=job_date)
    assert got[CIT[0]].use is use


def test_translation_needs_both_death_years(tmp_path: Path) -> None:
    w = World(tmp_path)
    for translator, year, reason in (
        (None, None, "TRANSLATOR_UNKNOWN"),
        ("T", None, "TRANSLATOR_DEATH_YEAR_UNKNOWN"),
        ("T", 2010, "TRANSLATOR_NOT_YET_PUBLIC_DOMAIN"),
        ("T", 1900, "PUBLIC_DOMAIN"),
    ):
        w.records["w_pd"] = record(
            "w_pd", "works/pd.txt", work_kind=WorkKind.TRANSLATION, translator=translator,
            translator_death_year=year,
        )  # fmt: skip
        got = w.resolver()._classifier.classify(
            [CIT[0]], library=w.library, job_date=date(2026, 6, 1)
        )
        assert got[CIT[0]].reason == reason
        assert (got[CIT[0]].use is SourceUse.QUOTABLE) == (reason == "PUBLIC_DOMAIN")


def test_an_inconsistent_record_is_ideas_only(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.records["w_pd"] = record(
        "w_pd", "works/pd.txt", translator="Someone"
    )  # ORIGINAL + translator
    got = _resolve(w)
    assert got.sources[CIT[0]].use is SourceUse.IDEAS_ONLY
    assert got.sources[CIT[0]].reason == "RECORD_INCONSISTENT"


def test_unknown_citation_or_missing_record_refuses(tmp_path: Path) -> None:
    w = World(tmp_path)
    del w.records["w_modern"]  # a cited work with no copyright record
    with pytest.raises(MissingDependency) as err:
        _resolve(w)
    assert err.value.details["class"] == "work_record"
    w2 = World(tmp_path / "two")
    w2.index = StaticLibraryIndex({CIT[0]: WorkRef("w_pd", "1", ())})  # the others are unknown
    with pytest.raises(MissingDependency) as err2:
        _resolve(w2)
    assert err2.value.details["class"] == "library_source"


def test_public_domain_work_missing_from_the_pinned_commit_is_ideas_only(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.records["w_pd"] = record("w_pd", "works/not_there.txt")
    got = _resolve(w)
    assert got.sources[CIT[0]].use is SourceUse.IDEAS_ONLY
    assert got.sources[CIT[0]].reason == "TEXT_NOT_IN_PINNED_COMMIT"


def test_public_domain_source_without_a_library_refuses(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.library_for = lambda _t: None
    with pytest.raises(MissingDependency) as err:
        _resolve(w)
    assert err.value.details["class"] == "library"


def test_a_library_at_another_commit_refuses_the_job(tmp_path: Path) -> None:
    w = World(tmp_path)

    def other(_t: Any) -> Any:
        return CheckoutLibraryReader(LibraryRef(w.root, "d" * 40), LIMITS)

    w.library_for = other
    with pytest.raises(InputInvalid):  # HEAD is not the SHA the job names
        _resolve(w)


def test_external_references_are_ideas_only_and_need_no_library(tmp_path: Path) -> None:
    import json

    w = World(tmp_path)
    doc = json.loads(w.pack_doc)
    for cit in doc["citations_available"]:
        cit["kind"] = "EXTERNAL_REFERENCE"
    w.pack_doc = json.dumps(doc).encode()
    w.library_for = lambda _t: (_ for _ in ()).throw(AssertionError("library must not be needed"))
    got = _resolve(w)
    assert {s.use for s in got.sources.values()} == {SourceUse.IDEAS_ONLY}
    assert {s.reason for s in got.sources.values()} == {"NOT_A_LIBRARY_WORK"}
    assert all(s.work_id is None for s in got.sources.values())


# -- finance / non-finance --------------------------------------------------------------------
def test_finance_channel_needs_the_disclaimer_template(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.channels.category = "finance"
    with pytest.raises(MissingDependency) as err:
        _resolve(w, channel_category="finance")
    assert err.value.details["class"] == "disclaimer_template"
    w.documents.disclaimer = DisclaimerTemplate("amw-blob://platform/t.json", "v1", "TEST TEXT.")
    got = _resolve(w, channel_category="finance")
    assert got.finance_rules_apply is True
    assert got.disclaimer_template is not None


@pytest.mark.parametrize("category", [None, "", "philosophy_x", "finance", "advertising"])
def test_unknown_or_finance_category_is_finance(tmp_path: Path, category: str | None) -> None:
    w = World(tmp_path)
    w.channels.category = category
    w.non_finance = frozenset({"youtube_general", "finance", "advertising", "philosophy_x"})
    with pytest.raises(MissingDependency) as err:  # finance rules -> disclaimer needed, absent
        _resolve(w, channel_category=category or "youtube_general")
    assert err.value.details["class"] == "disclaimer_template"


def test_the_non_finance_list_can_only_be_narrowed(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.non_finance = "youtube_general"  # not a set: effective list is empty, every category finance
    with pytest.raises(MissingDependency):
        _resolve(w)


def test_input_category_must_equal_the_channels_own(tmp_path: Path) -> None:
    w = World(tmp_path)
    w.channels.category = "finance"
    with pytest.raises(InputInvalid):
        _resolve(w, channel_category="youtube_general")


# -- tenancy, references, refusals -------------------------------------------------------------
def test_research_pack_reference_is_required_and_unique(tmp_path: Path) -> None:
    w = World(tmp_path)
    ti = w.task(refs=[])
    with pytest.raises(MissingDependency):
        w.resolver().resolve(w.ctx, ti, w.data(ti))
    one = w.put(w.pack_doc, "a.json")
    two = w.put(w.pack_doc + b" ", "b.json")
    refs = [
        {**r, "purpose": "PRIOR_OUTPUT", "schema": "agent_04.research_pack.output",
         "schema_version": "1.0.0"} for r in (one, two)
    ]  # fmt: skip
    ti2 = w.task(refs=refs)
    with pytest.raises(MissingDependency):
        w.resolver().resolve(w.ctx, ti2, w.data(ti2))


def test_pack_of_another_tenant_is_cross_tenant(tmp_path: Path) -> None:
    from amw_core import ids

    w = World(tmp_path)
    ti = w.task()
    foreign = f"amw-blob://{ids.ORG.new()}/assets/pack.json"
    bad = ContextRef.model_validate(
        {
            "uri": foreign,
            "purpose": "PRIOR_OUTPUT",
            "sha256": "a" * 64,
            "schema": "agent_04.research_pack.output",
            "schema_version": "1.0.0",
        }
    )
    ti = ti.model_copy(update={"context_refs": (bad,)})  # bypasses the envelope validator
    with pytest.raises(CrossTenantRef):
        w.resolver().resolve(w.ctx, ti, w.data(ti))


def test_pack_with_a_wrong_hash_or_bad_shape_refuses(tmp_path: Path) -> None:
    w = World(tmp_path)
    ref = w.put(w.pack_doc)
    wrong = {**ref, "sha256": "b" * 64, "purpose": "PRIOR_OUTPUT",
             "schema": "agent_04.research_pack.output", "schema_version": "1.0.0"}  # fmt: skip
    ti = w.task(refs=[wrong])
    with pytest.raises(Exception) as err:  # noqa: PT011 - a typed amw error of the storage
        w.resolver().resolve(w.ctx, ti, w.data(ti))
    assert type(err.value).__module__.startswith("amw_core")
    w2 = World(tmp_path / "two")
    ref2 = w2.put(b'{"concepts": "no"}')
    ti2 = w2.task(
        refs=[
            {
                **ref2,
                "purpose": "PRIOR_OUTPUT",
                "schema": "agent_04.research_pack.output",
                "schema_version": "1.0.0",
            }
        ]
    )
    with pytest.raises(InputInvalid):
        w2.resolver().resolve(w2.ctx, ti2, w2.data(ti2))


def test_a_reference_whose_stored_hash_differs_fails_the_tenant_check(tmp_path: Path) -> None:
    w = World(tmp_path)
    other = w.put(b"{}", "kit.json")
    refs = [
        {**w.put(w.pack_doc), "purpose": "PRIOR_OUTPUT", "schema": "agent_04.research_pack.output",
         "schema_version": "1.0.0"},
        {**other, "sha256": "c" * 64, "purpose": "BRAND_KIT"},
    ]  # fmt: skip
    ti = w.task(refs=refs)
    got = w.resolver().resolve(w.ctx, ti, w.data(ti))
    with pytest.raises(InputInvalid):
        check_tenant(got.tenant, lambda *_a: None)


def test_inactive_tenant_and_missing_channel_are_refused(tmp_path: Path) -> None:
    from agent_05_scriptwriter.errors import TenantInactive

    w = World(tmp_path)
    w.channels.status = "SUSPENDED"
    got = _resolve(w)
    with pytest.raises(TenantInactive):
        check_tenant(got.tenant, lambda *_a: None)
    w.channels.gone = True
    with pytest.raises(MissingDependency):
        _resolve(w)


def test_revision_and_shorts_inputs_are_refused_not_guessed(tmp_path: Path) -> None:
    w = World(tmp_path)
    ti = w.task()
    with pytest.raises(MissingDependency) as err:
        w.resolver().resolve(w.ctx, ti, w.data(ti).model_copy(update={"iteration": 1}))
    assert err.value.details["class"] == "script_revision_inputs"
    from agent_05_scriptwriter.contracts import ShortsAdaptationInput

    shorts = cast(Any, ShortsAdaptationInput).model_construct()
    with pytest.raises(MissingDependency):
        w.resolver().resolve(w.ctx, ti, shorts)


def test_classifier_alone_needs_a_record_for_every_cited_work(tmp_path: Path) -> None:
    w = World(tmp_path)
    classifier = LibrarySourceClassifier(w.index, {})
    with pytest.raises(MissingDependency):
        classifier.classify([CIT[0]], library=w.library, job_date=date(2026, 1, 1))
    assert w.library.reads == []  # nothing was read for a work without a record
