"""Adapter-specific behaviour of the fakes (cost arithmetic, units, tenancy)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from amw_adapters.common import CallUsage, FixtureStore, fake_bytes
from amw_adapters.file_delivery import DeliveryFile, DeliveryRequest, FakeFileDeliveryAdapter
from amw_adapters.library import LibraryLicenseRequest
from amw_adapters.llm import FakeLlmAdapter, LlmMessage, LlmRequest
from amw_adapters.stock_footage import FakeStockFootageAdapter
from amw_adapters.tts import FakeTtsAdapter, TtsRequest, VoiceListRequest
from amw_core.enums import CostUnitKind
from amw_core.errors import CrossTenantRefError
from amw_core.ids import JOB, ORG, make_idempotency_key

ORG_ID = ORG.new()
K = make_idempotency_key(ORG_ID, "llm.call", ["tsk_x", "step", 1])


def test_llm_cost_is_tokens_times_configured_price() -> None:
    fake = FakeLlmAdapter(input_price_micros_per_token=3, output_price_micros_per_token=7)
    req = LlmRequest(
        model="m",
        system="x" * 40,
        messages=(LlmMessage(role="user", content="y" * 40),),
        max_output_tokens=2,
    )
    out = fake.complete(req, idempotency_key=K)
    assert out.usage.tokens_in == 20
    assert out.usage.tokens_out == 2  # capped by max_output_tokens
    assert out.usage.amount_micros == 20 * 3 + 2 * 7
    assert out.usage.model == "m"


def test_tts_bills_characters() -> None:
    fake = FakeTtsAdapter(price_micros_per_character=2)
    out = fake.synthesize(
        TtsRequest(text="नमस्कार", voice_ref="v", model="m", language="mr"), idempotency_key=K
    )
    assert out.usage.unit_kind is CostUnitKind.CHARACTERS
    assert out.usage.characters == len("नमस्कार")
    assert out.usage.amount_micros == 2 * len("नमस्कार")
    assert out.sample_rate_hz == 48_000
    voices = fake.list_voices(VoiceListRequest(language="xx"), idempotency_key=K)
    assert voices.voices == ()


def test_stock_license_cost_and_terms() -> None:
    fake = FakeStockFootageAdapter(price_micros_per_item=1234)
    out = fake.license(
        LibraryLicenseRequest(vendor_item_id="v1", licence_ref="lic_1"), idempotency_key=K
    )
    assert out.usage.amount_micros == 1234
    assert out.usage.units == 1
    assert out.terms_ref.endswith("v1")
    assert len(out.media) == 64


def _delivery(uri_org: str) -> DeliveryRequest:
    job = JOB.new()
    return DeliveryRequest(
        org_id=ORG_ID,
        job_id=job,
        deliverable_preset="qc_report",
        files=(
            DeliveryFile(
                name="qc.json",
                uri=f"amw-blob://{uri_org}/jobs/{job}/qc.json",
                sha256="ab" * 32,
                size_bytes=5,
                media_type="application/json",
            ),
        ),
    )


def test_delivery_manifest_and_bytes() -> None:
    fake = FakeFileDeliveryAdapter()
    receipt = fake.deliver(_delivery(ORG_ID), idempotency_key=K)
    assert receipt.usage.amount_micros == 0
    assert receipt.usage.units == 5
    assert len(receipt.manifest_sha256) == 64
    assert receipt.files[0].delivered_ref in fake.delivered


def test_delivery_refuses_other_tenant_files() -> None:
    with pytest.raises(CrossTenantRefError):
        FakeFileDeliveryAdapter().deliver(_delivery(ORG.new()), idempotency_key=K)


def test_usage_units_pair_rule() -> None:
    with pytest.raises(ValidationError):
        CallUsage(
            provider="p1",
            operation="a.b",
            units=1,
            amount_micros=0,
            currency="USD",
            idempotency_key=K,
        )


def test_fixture_store_without_folder(tmp_path: Path) -> None:
    assert FixtureStore(tmp_path).find("llm", "llm.completion", {}) is None


def test_fake_bytes_deterministic() -> None:
    assert fake_bytes("s", 100) == fake_bytes("s", 100)
    assert len(fake_bytes("s", 100)) == 100


def test_operations_are_the_glossary_cost_operations() -> None:
    from amw_core.enums import CostOperation

    with pytest.raises(ValidationError):
        CallUsage(provider="p1", operation="llm.chat", amount_micros=0, currency="USD",
                  idempotency_key=K)  # fmt: skip
    usage = CallUsage(provider="p1", operation="web.fetch", amount_micros=0, currency="USD",
                      idempotency_key=K)  # fmt: skip
    assert usage.operation is CostOperation.WEB_FETCH


def test_llm_and_tts_record_ccr_037_fields() -> None:
    llm = FakeLlmAdapter().complete(
        LlmRequest(
            model="m",
            system="abc",
            messages=(LlmMessage(role="user", content="de"),),
            max_output_tokens=8,
            language="mr",
        ),
        idempotency_key=K,
    )
    assert (llm.usage.chars_in, llm.usage.language, llm.usage.tokens_cache_write_in) == (5, "mr", 0)
    tts = FakeTtsAdapter().synthesize(
        TtsRequest(text="abcd", voice_ref="v", model="m", language="mr"), idempotency_key=K
    )
    assert (tts.usage.chars_in, tts.usage.language) == (4, "mr")


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://10.0.0.5/x",
        "https://[::1]/x",
        "https://metadata.internal/x",
        "https://not-allowed.example/x",
    ],
)
def test_web_fetch_refuses_private_and_unlisted_hosts(url: str) -> None:
    from amw_adapters.web_fetch import FakeWebFetchAdapter, WebFetchRequest
    from amw_core.errors import InputInvalidError

    with pytest.raises(InputInvalidError):
        FakeWebFetchAdapter().fetch(WebFetchRequest(url=url), idempotency_key=K)


def test_web_fetch_https_only_and_size_cap() -> None:
    from amw_adapters.web_fetch import FakeWebFetchAdapter, WebFetchRequest
    from amw_core.errors import InputInvalidError

    with pytest.raises(ValidationError):
        WebFetchRequest(url="http://example.org/x")
    with pytest.raises(InputInvalidError):
        FakeWebFetchAdapter().fetch(
            WebFetchRequest(url="https://example.org/x", max_bytes=3), idempotency_key=K
        )
    ok = FakeWebFetchAdapter().fetch(
        WebFetchRequest(url="https://example.org/x"), idempotency_key=K
    )
    assert ok.usage.unit_kind is CostUnitKind.BYTES
    assert ok.usage.amount_micros == 0


def test_tts_capabilities_and_style_controls() -> None:
    """CCR-130: ``capabilities()`` is declared; a style control the adapter lacks is refused."""
    from amw_adapters.tts import ControlSupport, TtsEmotion, TtsPace
    from amw_core.errors import InputInvalidError

    default = FakeTtsAdapter()
    assert default.capabilities().pace_control is ControlSupport.NONE  # conservative default
    assert default.capabilities().emotion_control is ControlSupport.NONE
    assert default.capabilities().phoneme_support is False
    full = FakeTtsAdapter(
        pace_control=ControlSupport.NATIVE,
        emotion_control=ControlSupport.NATIVE,
        markup_delimiters=("[", "]"),
    )
    caps = full.capabilities()
    assert caps.pace_control is ControlSupport.NATIVE
    assert caps.markup_delimiters == ("[", "]")
    assert caps.languages == ("en", "hi", "mr")
    styled = TtsRequest(
        text="x",
        voice_ref="v",
        model="m",
        language="mr",
        pace=TtsPace.SLOW,
        emotion=TtsEmotion.WARM,
    )
    assert full.synthesize(styled, idempotency_key=K).duration_ms > 0
    bare = FakeTtsAdapter(pace_control=ControlSupport.NONE, emotion_control=ControlSupport.NONE)
    assert bare.capabilities().emotion_control is ControlSupport.NONE
    with pytest.raises(InputInvalidError):
        bare.synthesize(styled, idempotency_key=K)
    plain = TtsRequest(text="x", voice_ref="v", model="m", language="mr")
    assert plain.pace is None
    assert bare.synthesize(plain, idempotency_key=K).duration_ms > 0
    with pytest.raises(ValidationError):
        TtsRequest(text="x", voice_ref="v", model="m", language="mr", pace="TURBO")
