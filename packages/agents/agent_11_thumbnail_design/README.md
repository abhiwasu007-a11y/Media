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
| Fallback when Raqm is absent | none: `render` raises `ComposeFailedError` (a basic layout would draw unshaped conjuncts) |
| Output | PNG, 8-bit RGB, no metadata, `compress_level=6`, `optimize=False`; byte-identical for equal inputs (test `test_byte_identical_across_runs_and_instances`, canary `CANARY_SHA256`) |

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

## Fonts, templates, glyphs (licence rows)

- Package data (`src/agent_11_thumbnail_design/data/`): `templates.json` (4 templates, geometry in permille of the canvas),
  `glyphs.json` (4 code glyphs and the neutral allow-list with the written criterion), `palette.json` (default colour roles).
  `template_set_sha256()` hashes templates and glyphs; the manifest provenance records it.
- Each template, the glyph set (`TEMPLATE`) and the font (`FONT`) are tenant `assets` rows registered once by the shared registry
  (CCR-031). The stage reads them (`ThumbnailRepository.registered_assets`) and writes `licence_ledger` rows without interval
  (`usage_kind` `TEMPLATE`, `FONT`, `IMAGE`); a missing registration is `PERMANENT.MISSING_DEPENDENCY`.
- The default Devanagari font is a tenant `FONT` asset (an OFL font, owner question Q-O6). **No font file is committed here.**

## Tenant isolation (blueprint 19.1)

Every row is read or written through the tenant transaction (`TenancyContext.transaction`) and the repository port; every payload
URI is compared with the task's org before use (`CROSS_TENANT_REF`); blobs go through `BlobStorage` (tenant check, write-once);
the composer's font and cmap caches are keyed `amw:<org>:a11:<hash>`; logs, audit details, check messages and cost rows carry IDs,
hashes and counts only (test `test_s05_...`). Tests: `test_s01_cross_tenant_payload_ref_is_rejected`, `test_s05_...`,
`test_u170_...` (the cached prompt prefix holds no tenant data; the tenant rule pack follows the data).

## Tests

`tests/agents/agent_11_thumbnail_design/`: the 66 `composer_engine` cases (`test_ce_*`), the 31 `thumbnail_concepts` cases with
assertions A1..A15 against the deterministic baseline and replayed through `amw_evals.run_eval` (`test_eval_concepts.py`),
23 checks with pass/fail fixtures (`test_checks.py`), composer determinism and shaping (`test_composer.py`), whole-task, failure
injection, revision, replay, tenancy and security tests (`test_stage.py`).

## Open items

1. `amw_core.config` registry does not exist: `Agent11Settings.load` reads the flat dotted keys itself (core need).
2. No `amw_core` repository for scripts, brand kits, assets, licences: `ports.ThumbnailRepository` is package-local (core need).
3. Memory digest (`a11.set_digest`, `memory_items`) is not written: no memory port in `amw_core` yet.
4. Checkpoints CK1..CK3 are written; a resume that reads them (FI-08 kill mid-composition) is not implemented. Repeated LLM calls are
   already prevented by the `llm.call` idempotency key, and blobs are write-once; the resume path and its test are open.
5. The judged part of `thumbnail_concepts` (J1..J4, judge prompt, online model) is not run: no paid call. CI runs A1..A15 on the
   deterministic baseline only; the baseline is not the model and its pass says nothing about model quality.
6. The finance marker lists, injection phrases and neutral words are injected (`Lexicons`); production lists are 13 / rule-pack
   content. The lists used in tests are fixtures.
7. Real-font Devanagari evidence needs a font on the machine (skipped when absent); the OFL default font asset is not chosen.
8. Chart stills (3B), AI stills (3C), upload and Studio test are out of scope. `a11.q.chart_still` is emitted `SKIPPED` unless a
   chart is used.
9. Official thumbnail spec (dimensions, formats) and the preview-size threshold are `REQUIRES REVIEW`; `a11.q.preview_legibility`
   is `WARN` until its threshold is configured.
10. Composition and checks run per task in one process; measured time and memory (P-01, P-03 over 100 runs) are not recorded.
