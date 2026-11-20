"""Brand kit document, manifest-only fonts, glyph coverage and the real ``BrandKitReader``.

Fonts are the repo's pinned manifest fonts; the kit is the packaged config document; assets and
storage are the in-memory / local-disk fakes. No network, no key."""

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from agent_08_visual_assets.persistence.records import NewAsset
from agent_08_visual_assets.testing.memory import MemoryAssetRepository
from agent_11_thumbnail_design.pinning import pinned_font_bytes
from amw_core.enums import AssetKind, LicenceSourceType
from amw_core.errors import (
    ConfigInvalidError,
    CrossTenantRefError,
    InputInvalidError,
    MissingDependencyError,
    SchemaInvalidError,
)
from amw_core.ids import ORG, new_uuid7
from amw_core.interfaces.storage import BlobUri
from amw_core.interfaces.tenancy_context import TenantContext
from amw_core.storage.local import LocalDiskStorage
from amw_core.tenancy.storage_paths import blob_uri
from amw_core.testing.memory import MemoryTransaction
from amw_orchestrator.brand_kit import (
    BrandKitDocument,
    FontManifest,
    ManifestBrandKitReader,
    check_kit_fonts,
    packaged_brand_kit,
    packaged_manifest_path,
    seed_brand_kit,
)
from amw_orchestrator.brand_kit.packaged import packaged_brand_kit_bytes
from amw_orchestrator.input_limits import packaged_input_limits

pytestmark = pytest.mark.unit
ORG_A = ORG.from_uuid(new_uuid7())
ORG_B = ORG.from_uuid(new_uuid7())


def _doc(**changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(packaged_brand_kit_bytes("philosophy_mr"))
    doc.update(changes)
    return doc


def _tx(org: str) -> MemoryTransaction:
    return MemoryTransaction(TenantContext(org, "agent_08", None))  # type: ignore[arg-type]


class World:
    def __init__(self, tmp_path: Path, org: str = ORG_A, *, fonts: bool = True) -> None:
        self.org = org
        self.storage = LocalDiskStorage(tmp_path / "store")
        self.assets = MemoryAssetRepository()
        self.tx = _tx(org)
        self.font_ids: dict[str, str] = {}
        if fonts:
            for key in ("mukta_regular", "noto_sans_devanagari_vf"):
                self.add_font(key)
        self.reader = ManifestBrandKitReader(
            self.storage,
            self.assets,
            FontManifest(packaged_manifest_path()),
            packaged_input_limits(),
        )

    def add_font(self, key: str, kind: AssetKind = AssetKind.FONT) -> str:
        data = pinned_font_bytes(key)
        sha = hashlib.sha256(data).hexdigest()
        rec = self.assets.insert(
            self.tx,
            NewAsset(
                kind=kind, source_type=LicenceSourceType.FONT, content_sha256=sha,
                uri=f"amw-blob://{self.org}/assets/fonts/{sha}.ttf", size_bytes=len(data),
                title="font",
            ),
        )  # fmt: skip
        self.font_ids[key] = str(rec.asset_id)
        return str(rec.asset_id)

    def put(self, doc: dict[str, Any] | bytes, name: str = "kit.json") -> tuple[str, str]:
        data = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
        uri = blob_uri(self.org, "assets", name)  # type: ignore[arg-type]
        self.storage.put(self.tx.context, BlobUri(uri), io.BytesIO(data))
        return uri, hashlib.sha256(data).hexdigest()


def test_packaged_philosophy_kit_is_valid_config_data() -> None:
    kit = packaged_brand_kit("philosophy_mr")
    assert (kit.channel_key, kit.language) == ("philosophy_mr", "mr-IN")
    assert kit.fonts.primary == "mukta_regular"
    assert kit.fonts.fallback == "noto_sans_devanagari_vf"
    assert kit.caption_style.font_key == "mukta_bold"


def _luminance(colour: str) -> float:
    def lin(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def test_packaged_palette_text_contrast_is_readable() -> None:
    p = packaged_brand_kit("philosophy_mr").palette
    for fg, bg in ((p.foreground, p.background), (p.foreground, p.shade), (p.accent, p.background)):
        hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 4.5


def test_no_logo_trademark_or_font_path_field_is_accepted() -> None:
    for extra in ("logo", "logo_uri", "trademark", "wordmark", "font_path"):
        with pytest.raises(ValueError, match=extra):
            BrandKitDocument.model_validate(_doc(**{extra: "x"}))


@pytest.mark.parametrize("bad", ["#FFF", "red", "#ABCDEF", "#12345g", ""])
def test_colours_must_be_lowercase_hex(bad: str) -> None:
    doc = _doc()
    doc["palette"]["accent"] = bad
    with pytest.raises(ValueError, match="accent"):
        BrandKitDocument.model_validate(doc)


def test_kit_fonts_pass_and_cover_the_marathi_texts() -> None:
    kit = packaged_brand_kit("philosophy_mr")
    fonts = check_kit_fonts(kit, FontManifest(packaged_manifest_path()))
    assert set(fonts.fonts) == {"mukta_regular", "noto_sans_devanagari_vf", "mukta_bold"}
    assert (
        fonts.uncovered(kit.coverage_texts, ("mukta_regular", "noto_sans_devanagari_vf")) == set()
    )


def test_a_character_no_font_draws_refuses_the_kit() -> None:
    doc = BrandKitDocument.model_validate(_doc(coverage_texts=["चांगले \U0001f600 中"]))
    with pytest.raises(ConfigInvalidError) as err:
        check_kit_fonts(doc, FontManifest(packaged_manifest_path()))
    assert "U+1F600" in err.value.details["code_points"]


def test_only_manifest_fonts_with_a_brand_purpose_are_accepted() -> None:
    manifest = FontManifest(packaged_manifest_path())
    unknown = _doc()
    unknown["fonts"]["primary"] = "dejavu_sans"  # a system font is not in the manifest
    with pytest.raises(MissingDependencyError):
        check_kit_fonts(BrandKitDocument.model_validate(unknown), manifest)
    fixture = _doc()
    fixture["fonts"]["primary"] = "a11_test_box"  # test fixture purpose
    with pytest.raises(ConfigInvalidError):
        check_kit_fonts(BrandKitDocument.model_validate(fixture), manifest)
    swapped = _doc()
    swapped["fonts"]["primary"], swapped["fonts"]["fallback"] = (
        "noto_sans_devanagari_vf",
        "mukta_regular",
    )
    with pytest.raises(ConfigInvalidError):
        check_kit_fonts(BrandKitDocument.model_validate(swapped), manifest)
    caption = _doc()
    caption["caption_style"]["font_key"] = "noto_sans_devanagari_vf"
    with pytest.raises(ConfigInvalidError):
        check_kit_fonts(BrandKitDocument.model_validate(caption), manifest)


def test_a_font_file_that_does_not_match_its_manifest_hash_refuses(tmp_path: Path) -> None:
    src = packaged_manifest_path()
    manifest = json.loads(src.read_text())
    for entry in manifest["fonts"]:
        if entry["key"] == "mukta_regular":
            entry["sha256"] = "0" * 64
        (tmp_path / entry["file"]).write_bytes((src.parent / entry["file"]).read_bytes())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ConfigInvalidError):
        check_kit_fonts(
            packaged_brand_kit("philosophy_mr"), FontManifest(tmp_path / "manifest.json")
        )


def test_unreadable_manifest_refuses(tmp_path: Path) -> None:
    (tmp_path / "m.json").write_text("{")
    with pytest.raises(ConfigInvalidError):
        FontManifest(tmp_path / "m.json")


def test_reader_returns_the_agent_08_kit(tmp_path: Path) -> None:
    w = World(tmp_path)
    uri, sha = w.put(_doc())
    kit = w.reader.brand_kit(w.tx, uri, sha)
    doc = packaged_brand_kit("philosophy_mr")
    assert kit.palette.background == doc.palette.background == "#16130f"
    assert kit.palette.accent == doc.palette.accent
    assert kit.font_asset_ids == (
        w.font_ids["mukta_regular"],
        w.font_ids["noto_sans_devanagari_vf"],
    )


def test_seeded_packaged_kit_is_read_back_and_seeding_is_idempotent(tmp_path: Path) -> None:
    w = World(tmp_path)
    first = seed_brand_kit(w.storage, ORG_A, "philosophy_mr")
    assert seed_brand_kit(w.storage, ORG_A, "philosophy_mr") == first
    assert first.uri.startswith(f"amw-blob://{ORG_A}/assets/brand_kits/philosophy_mr/")
    assert first.sha256 == hashlib.sha256(packaged_brand_kit_bytes("philosophy_mr")).hexdigest()
    assert len(w.reader.brand_kit(w.tx, first.uri, first.sha256).font_asset_ids) == 2


def test_seeding_an_unknown_kit_refuses(tmp_path: Path) -> None:
    for name in ("nope", "../x", ""):
        with pytest.raises(MissingDependencyError):
            seed_brand_kit(LocalDiskStorage(tmp_path), ORG_A, name)


def test_missing_brand_kit_document_refuses(tmp_path: Path) -> None:
    w = World(tmp_path)
    uri = blob_uri(ORG_A, "assets", "missing.json")
    with pytest.raises(Exception) as err:  # noqa: PT011 - typed AmwError of the storage
        w.reader.brand_kit(w.tx, uri, "a" * 64)
    assert type(err.value).__module__.startswith("amw_core")  # a typed error, never a default kit


def test_no_hash_wrong_hash_and_other_tenant_refuse(tmp_path: Path) -> None:
    w = World(tmp_path)
    uri, sha = w.put(_doc())
    with pytest.raises(InputInvalidError):
        w.reader.brand_kit(w.tx, uri, None)
    with pytest.raises(Exception) as err:  # noqa: PT011
        w.reader.brand_kit(w.tx, uri, "b" * 64)
    assert type(err.value).__module__.startswith("amw_core")
    other = World(tmp_path / "b", ORG_B)
    with pytest.raises(CrossTenantRefError):
        other.reader.brand_kit(other.tx, uri, sha)  # org A's document, read as org B


def test_font_asset_not_registered_refuses(tmp_path: Path) -> None:
    w = World(tmp_path, fonts=False)
    w.add_font("mukta_regular")  # the fallback font has no asset
    uri, sha = w.put(_doc())
    with pytest.raises(MissingDependencyError):
        w.reader.brand_kit(w.tx, uri, sha)
    w2 = World(tmp_path / "w2", fonts=False)
    w2.add_font("mukta_regular", AssetKind.TEMPLATE)  # right bytes, wrong kind
    w2.add_font("noto_sans_devanagari_vf")
    uri2, sha2 = w2.put(_doc())
    with pytest.raises(MissingDependencyError):
        w2.reader.brand_kit(w2.tx, uri2, sha2)


def test_font_asset_of_another_tenant_is_not_used(tmp_path: Path) -> None:
    w = World(tmp_path, fonts=False)
    foreign = _tx(ORG_B)
    for key in ("mukta_regular", "noto_sans_devanagari_vf"):
        data = pinned_font_bytes(key)
        w.assets.insert(
            foreign,
            NewAsset(
                kind=AssetKind.FONT, source_type=LicenceSourceType.FONT,
                content_sha256=hashlib.sha256(data).hexdigest(),
                uri=f"amw-blob://{ORG_B}/assets/fonts/x.ttf", size_bytes=len(data), title="font",
            ),
        )  # fmt: skip
    uri, sha = w.put(_doc())
    with pytest.raises(MissingDependencyError):
        w.reader.brand_kit(w.tx, uri, sha)


@pytest.mark.parametrize(
    "body",
    [b"not json", b"[]", json.dumps({"schema": "amw.brand_kit/1"}).encode(), b"{" * 100_000],
)
def test_malformed_document_is_a_schema_error(tmp_path: Path, body: bytes) -> None:
    w = World(tmp_path)
    uri, sha = w.put(body)
    with pytest.raises((SchemaInvalidError, InputInvalidError)):
        w.reader.brand_kit(w.tx, uri, sha)


def test_document_with_a_logo_field_is_refused_by_the_reader(tmp_path: Path) -> None:
    w = World(tmp_path)
    uri, sha = w.put(_doc(logo="amw-blob://x/assets/logo.png"))
    with pytest.raises(SchemaInvalidError) as err:
        w.reader.brand_kit(w.tx, uri, sha)
    assert "logo" in str(err.value.details)


def test_the_reader_satisfies_the_agent_08_port(tmp_path: Path) -> None:
    from agent_08_visual_assets.stage import BrandKitReader

    reader: BrandKitReader = World(tmp_path).reader
    assert callable(reader.brand_kit)
