# agent_11_thumbnail_design (Agent 11, Thumbnail Design)

Task `agent_11.thumbnail_variants` (stage `s11_thumbs`). Authority: `docs/v4/agents/agent_11_thumbnail_design.md`,
prompt `docs/v4/prompts/agent_11_thumbnail_design/`, evals `docs/v4/evals/agent_11_thumbnail_design/`.
Up to three PNG variants per task, composed by code; one closed-choice LLM step behind `LlmAdapter`; no
image-provider call, no real person, no upload. Software status: built in the development environment only.

## Imaging library (blueprint section 9 note, 27 section 3 record)

| Item | Value |
|---|---|
| Rasteriser and shaper | Pillow 13.0.0 (pinned) with the Raqm layout engine (`ImageFont.Layout.RAQM`) |
| Shaping stack in the wheel | libraqm 0.11.0, HarfBuzz 14.5.0 (bundled in the wheel), FreeType 2.14.3; FriBiDi 1.0.13 is reported by `PIL.features` |
| Licences (from the wheel metadata and `licenses/LICENSE`) | Pillow: MIT-CMU (HPND style); HarfBuzz: "Old MIT"; Raqm: MIT; FreeType: FreeType licence (FTL) or GPLv2; FriBiDi: LGPL-2.1 (a separate library; the wheel does not bundle it) |
| Glyph coverage check | fontTools 4.68.0 (MIT), cmap lookup per character (`a11.q.language_glyphs`) |
| Fallback when Raqm is absent | none. `a11.pre.config` checks `raqm_available()` before any model call and raises the permanent `MISSING_DEPENDENCY`; `render` raises `ComposeFailedError` as a second line (a basic layout would draw unshaped conjuncts) |
| System dependency | Raqm in the wheel loads the system library `libfribidi.so.0` (not bundled in the wheel): install it (Debian: `libfribidi0`) on every worker, otherwise tasks fail closed with `MISSING_DEPENDENCY` |
| Output | PNG, 8-bit RGB, no metadata, `compress_level=6`, `optimize=False`. Same inputs give the same PNG bytes on one host and the same decoded raster (`pixel_sha256`) on every pinned environment (see Determinism) |

### Devanagari shaping evidence

Measured with `ImageFont.getlength` at 100 px, Raqm layout versus the naive BASIC layout:

| Font | String | Raqm | BASIC | Reading |
|---|---|---|---|---|
| generated test font (`tests/.../fontgen.py`, one `akhn` ligature KA+VIRAMA+SSA) | क्ष | 70.0 | 150.0 | the conjunct ligature is applied by Raqm |
| GNU FreeFont FreeSerif (system font, used only when present, never committed) | क्ष | 77.3 | 135.0 | conjunct shaped |
| same | ज्ञ | 69.4 | 154.0 | conjunct shaped |
| same | ट्रेंड | 128.0 | 177.0 | reph / vowel sign / anusvara reordering applied |

The real-font test `test_system_devanagari_font_when_present` is skipped with an explicit message when no
system Devanagari font exists (open item below). The generated test font is built at test time by code
(a few kilobytes, box glyphs, no download, no network); nothing large is committed.

## Determinism (host independence)

Findings from the verifier report and the reviews (the first design, which refused to render on an unlisted host, was withdrawn: it
failed the repo's own `gates` job on a runner with another FriBiDi patch version):

| Symptom | Cause | Evidence |
|---|---|---|
| `test_same_inputs_give_byte_identical_files` flaked | the generated test font carried the wall-clock time in `head.created` / `head.modified`, so two builds a second apart had different font hashes, hence different `composition_sha256` | two builds 1.1 s apart differ; fixed stamps make them equal; `test_test_font_bytes_do_not_depend_on_the_wall_clock` fails without the fix |
| canary PNG hash `c58d42db...` on the verifier's host instead of `3cbf11ec...` | **UNEXPLAINED.** Host zlib is a possible cause of PNG byte differences (the wheel links the system `libz.so.1`), but an emulation of Pillow's encoder with zlib 1.3 reproduces `3cbf11ec` exactly and 24 zlib variants never gave `c58d42db` | run `scripts/probe_render_env.py` on that host and compare |

What was measured to change the raster (full table in `data/environments.json`, `evidence`):

- **FreeType**: the Noto variable font renders differently with FreeType 2.13.3 (Pillow 11.3.0) than with 2.14.1 (Pillow 12.0.0, 12.1.0) and
  2.14.3 (Pillow 13.0.0); 2.14.1 and 2.14.3 are identical. This is the canary key.
- **Not shown to matter**: HarfBuzz 12.1.0, 12.3.0, 14.5.0; libraqm 0.10.3, 0.11.0; libfribidi 1.0.8, 1.0.13, 1.0.16; Pillow 11.3.0 to 13.0.0
  for the box font. CPU architecture and OS: x86_64 and aarch64 Ubuntu matched in CI for FreeType 2.14.3.

What the code does:

- **The renderer never refuses because the environment is unlisted.** The environment (`pillow`, `freetype2`, `harfbuzz`, `raqm`, `fribidi`,
  `machine`, `font_manifest_sha256`, `canary_recorded`) and the font source are written to the manifest `provenance` (proposed as CCR-192).
- **Raster identity**: `RenderResult.pixel_sha256` (mode, size, decoded RGB). The PNG file hash (`file.sha256`) identifies the stored blob and
  is stable on one host. A fixed PNG encoder was rejected: stored (uncompressed) deflate blocks are host independent but make a 1920x1080 file
  about 6.2 MB instead of about 9 KB.
- **Canary** (`canary.py`, tests `test_canary_hash_is_recorded`): box test font and the real Noto font, recorded per FreeType version. A listed
  FreeType must match exactly. An unlisted one is skipped with its hash in the normal `gates` job and fails in the clean-image job
  `a11-render-determinism` (`A11_REQUIRE_RECORDED_ENV=1`). No perceptual tolerance exists: nothing measured needs one.
- **Fonts**: bytes must hash to the recorded hash (registered asset `sha256`, or a manifest entry), else `FontIntegrityError` (stage:
  `PERMANENT.MISSING_DEPENDENCY`, `font_hash_match`), also on the glyph-coverage path. Tenant brand-kit fonts (FR-09) stay allowed; the stage
  still requires a registered asset with a licence row. Fonts load from memory only, so a system font is never used.
- **Lock**: `pillow==13.0.0` exactly in `pyproject.toml` and `uv.lock`; fontTools (test-font generator) is locked. FreeType, HarfBuzz and Raqm
  are inside the Pillow wheel; FriBiDi and zlib are system libraries.
- **Probe**: `scripts/probe_render_env.py` prints the full fingerprint, loaded libraries, canary raster, PNG and font hashes of a host
  (exit code non-zero if it cannot run; no absolute paths printed). Ready to paste on the host to be compared:

  ```
  git clone --depth 1 --branch claude/v4-p4-agent11-determinism https://github.com/abhiwasu007-a11y/Media.git media-probe && cd media-probe && export UV_PYTHON=3.14 && uv sync --frozen --all-packages && uv run --frozen python scripts/probe_render_env.py 2>&1 | grep -v '^warning' | tee probe_out.txt
  ```
- **Known limits**: a missing font asset or licence row is detected only when the rows are written, after the paid model call (pre-existing order);
  hinted tenant fonts are not covered by a canary; `pixel_sha256` is not stored in the manifest.

Still open (`REQUIRES REVIEW`): (1) no runtime image exists in the repo (deployment is not approved); (2) macOS and Windows have no recorded canary (CI run 44447278617 matched on x86_64 Ubuntu 24.04 with FriBiDi 1.0.13, x86_64 Ubuntu 26.04 with FriBiDi 1.0.16 and arm64 Ubuntu 24.04, all strict, FreeType 2.14.3 only; the 2.13.3 and 2.14.1 rows are local x86_64 measurements); (3) the owner picks the default Devanagari font (Q-O6): the pinned OFL candidate is
verified, not chosen; (4) the verifier's `c58d42db` is unexplained until their probe output is compared.

## Fonts, templates, glyphs (licence rows)

- Package data (`src/agent_11_thumbnail_design/data/`): `templates.json` (4 templates, geometry in permille of the canvas),
  `glyphs.json` (4 code glyphs and the neutral allow-list with the written criterion), `palette.json` (default colour roles).
  `template_set_sha256()` hashes templates and glyphs; the manifest provenance records it.
- Each template, the glyph set (`TEMPLATE`) and the font (`FONT`) are tenant `assets` rows registered once by the shared registry
  (CCR-031). The stage reads them (`ThumbnailRepository.registered_assets`) and writes `licence_ledger` rows without interval
  (`usage_kind` `TEMPLATE`, `FONT`, `IMAGE`); a missing registration is `PERMANENT.MISSING_DEPENDENCY`.
- Pinned fonts (`data/fonts/`, manifest with SHA-256, licence and source): Noto Sans Devanagari variable font, Version 2.007, SIL OFL 1.1,
  unmodified, 641,944 bytes, licence text `OFL-NotoSansDevanagari.txt` (research entry RV-08); and the generated box test font
  `a11_test_box.ttf` (5.6 KB, no third-party outlines; `test_committed_test_font_equals_generator_and_is_pinned`). The default Devanagari
  font stays a tenant `FONT` asset chosen by the owner (question Q-O6); its bytes must hash to the recorded `sha256` of the asset.

## Tenant isolation (blueprint 19.1)

Every row is read or written through the tenant transaction (`TenancyContext.transaction`) and the repository port; every payload
URI is compared with the task's org before use (`CROSS_TENANT_REF`); blobs go through `BlobStorage` (tenant check, write-once);
the composer's font and cmap caches are keyed `amw:<org>:a11:<hash>`; logs, audit details, check messages and cost rows carry IDs,
hashes and counts only (test `test_s05_...`). Tests: `test_s01_cross_tenant_payload_ref_is_rejected`, `test_s05_...`,
`test_u170_...` (the cached prompt prefix holds no tenant data; the tenant rule pack follows the data).

## Tests

`tests/agents/agent_11_thumbnail_design/`: the 66 `composer_engine` cases (`test_ce_*`), the 31 `thumbnail_concepts` cases with
assertions A1..A12, A14, A15 (A13 not implemented; A8 circular; A11 and A15 partial, see the module docstring) against the deterministic baseline and replayed through `amw_evals.run_eval` (`test_eval_concepts.py`),
23 checks with pass/fail fixtures (`test_checks.py`), composer determinism and shaping (`test_composer.py`), whole-task, failure
injection, revision, replay, tenancy and security tests (`test_stage.py`).

## Open items

1. `amw_core.config` registry does not exist: `Agent11Settings.load` reads the flat dotted keys itself (core need).
2. No `amw_core` repository for scripts, brand kits, assets, licences: `ports.ThumbnailRepository` is package-local (core need).
3. Memory digest (`a11.set_digest`, `memory_items`) is not written: no memory port in `amw_core` yet.
4. Checkpoints CK1..CK3 are written; a resume that reads them (FI-08 kill mid-composition) is not implemented. Repeated LLM calls are
   already prevented by the `llm.call` idempotency key, and blobs are write-once; the resume path and its test are open.
5. The judged part of `thumbnail_concepts` (J1..J4, judge prompt, online model) is not run: no paid call. CI runs A1..A12, A14, A15 (partial, A13 missing) on the
   deterministic baseline only; the baseline is not the model and its pass says nothing about model quality.
6. The finance marker lists, injection phrases and neutral words are injected (`Lexicons`); production lists are 13 / rule-pack
   content. The lists used in tests are fixtures.
7. Real-font Devanagari evidence now uses the pinned OFL font (`test_production_font_is_pinned_ofl_and_shapes_devanagari`); the owner has not yet chosen the default font asset (Q-O6).
8. Chart stills (3B), AI stills (3C), upload and Studio test are out of scope. `a11.q.chart_still` is emitted `SKIPPED` unless a
   chart is used.
9. Official thumbnail spec (dimensions, formats) and the preview-size threshold are `REQUIRES REVIEW`; `a11.q.preview_legibility`
   is `WARN` until its threshold is configured.
10. Composition and checks run per task in one process; measured time and memory (P-01, P-03 over 100 runs) are not recorded.

## Review fixes (PR #39) and remaining gaps

Fixed: fail-closed `a11.pre.config` (empty finance markers, injection lists, missing platform or finance rule pack, prompt hash
mismatch, Raqm) before any model call; the promise statement is screened like the title; Devanagari edge stripping removes only
punctuation and symbols (whole-word matching, no stemming); whole-set blocking checks run before any blob, asset or ledger row is
written; an `IN_FLIGHT` LLM call is the retryable `LOCK_CONFLICT` and a stale `RECONCILE` key is marked failed and re-run (a
completion has no external effect to look up); `ASSET` context refs are tenant-checked (`CROSS_TENANT_REF` plus the
`security.cross_tenant_ref` audit event) and must resolve (`MISSING_DEPENDENCY`).

Still open (disclosed, not fixed here):
- Text normalisation is a package-local seam (`textutil.py`); `amw_core.text_normalise` is not on `origin/main` yet.
- Persistence order: blobs are put inside the tenant transaction, so a database rollback after a successful put leaves complete,
  content-addressed blobs without rows (never a partial file; a replay reuses them). The manifest is written after the commit.
- A kill between the commit and the manifest write is completed by a replay; there is no resume from checkpoints (open item 4).
- Minors not addressed: owner `IMAGE` is always direction-neutral on finance (owner question), `chart_stills_used` is always empty,
  `max_llm_calls` is the literal 2, `max_wall_ms` is not enforced, the port `NewLedgerRow` lacks `licence_id` and `recorded_by`,
  checkpoints are thinner than blueprint section 16, no `thumb.*` structured log events, one flat finance list instead of one per
  language, the canary pins Latin text only (no Devanagari canary), a refusal is always labelled `PROMISE_IS_A_CALL`.
- The ledger-row check now runs on the planned rows before writing and is verified against the written rows inside the transaction.
