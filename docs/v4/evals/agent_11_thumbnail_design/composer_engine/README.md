# Eval set — `agent_11.composer_engine` (deterministic; no LLM)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 11 Thumbnail Design |
| Depends on | agents/agent_11_thumbnail_design.md (§6 decision engine, §8.5 manifest, §10 functions F-06, F-07, F-11, F-12, F-13, F-15, F-16, F-22, F-23, §20 checks), 27_ENGINEERING_STANDARDS.md §6, §8 |
| Directive sections covered | §1A.2 (script promise = title promise = thumbnail promise: text provenance), §1A.1 (picture hierarchy and licence), §1B.2 and FIN-R1/R2/R3/R5/R6/R8/R13 (finance text and imagery), IN-02 / IN-03 (chart still age and label), §1A.8 (size, legibility), YT-08 (distinct variants) |
| Files | `cases.jsonl` (66 cases), `rubric.md` (statement: no judge) |

## 1. Scope
The pure functions of the thumbnail engine run on fixture inputs without any model, clock, font library or network. Each case names the `function` under test, an `input` fixture and the exact `expected` result. It is the dataset that the table-driven unit tests U-21…U-44, U-59…U-89, U-95…U-101 and U-173…U-178 read (blueprint §21). Format: every case carries `case_id` (prefix `CE-` + group), `category`, `function`, `description`, `input`, `expected`, `judge_min` (always `null`: deterministic) and `notes`. The `function` field and the `CE-` prefix extend the case format of `evals/README.md` §2 for deterministic engine datasets (a contract need listed in the blueprint return). The LLM step has its own dataset (`../thumbnail_concepts/`). Cases carry no dates: chart age is the precomputed field `data_age_vs_lag`, so the dataset stays valid when the configured lag changes.

## 2. Case coverage
| Group | Cases | Function | What they prove |
|---|---|---|---|
| CE-TOB-01…13 | 13 | `TextOptionBuilder.build` | source order, key-term spans ranked, de-duplication, the cap, Devanagari whole-word match (CE-TOB-13: an inflected form is not a key-term occurrence), exclusion reasons `EMPTY`, `TOO_LONG`, `BANNED_WORD`, `MUST_NOT_PROMISE`, `INJECTION`, `FIN_TEXT` (digit, lexicon), digit kept off finance |
| CE-SOB-01…12 | 12 | `SubjectOptionBuilder.build` | owner image eligibility (licence, source type, expiry, channel, resolution, status), client asset with `third_party_permission` `UNKNOWN` or `PERMITTED`, person policy (default off, release, finance never), chart still (disabled, lag, `UNKNOWN`, `NOT_APPLICABLE`, label, direction), non-neutral glyph not offered on finance (`FINANCE_DIRECTION`), option ID order |
| CE-GD-01…18 | 18 | `ConceptGuards.check` | G1…G8 hit and no-hit cases; first failing guard only; revision rule of G7 (kept concept changed, named concept repeated) |
| CE-FP-01…07 | 7 | `FallbackPlanner.plan` | control, text then picture change, layout change, `NO_DISTINCT_OPTION`, finance neutrality, count 1, picture tie by lowest option ID |
| CE-FIT-01…05 | 5 | `Composer.fit_text` | font size search, two lines, no fit, lines over the template limit, exact fit |
| CE-CON-01…04 | 4 | `contrast_ratio` | black/white 21.00, identical 1.00, 4.54 and 4.48 around the 4.5 minimum |
| CE-HASH-01…03 | 3 | `Distinctness.check` | pairwise Hamming distance, fail under the minimum, exact minimum |
| CE-REV-01…03 | 3 | `RevisionPlanner.build_previous` | re-map previous choices to current IDs by content, control named, vanished choice (null, not kept) |
| CE-MAN-01 | 1 | `ManifestBuilder.build` | `set_sha256` over the canonical JSON |
Categories: see the `category` field of each line (POSITIVE, HARD_NEGATIVE, EDGE).

## 3. Fixtures and conventions
- **Text builder (`TextOptionBuilder.build`).** `config` holds `max_words`, `max_chars`, `max_options` (test values). `lexicon` and `injection_markers` are fixture lists (the real lexicon is rule-pack content, 13 §5.4). Exclusion reason precedence: `EMPTY`, `TOO_LONG`, `BANNED_WORD`, `MUST_NOT_PROMISE`, `INJECTION`, `FIN_TEXT`. Matching is case-folded, NFC. Source order `BRIEF_TEXT`, `KEY_TERM` (promise order), `TITLE_SPAN` (distinct key terms desc, words asc, start asc); equal text keeps the earlier source. The cap is applied after exclusions.
- **Picture builder.** Option order `OWNER_IMAGE` (by `sha`), `CODE_GLYPH` (by `key`), `NONE`. Asset exclusion precedence: `STATUS`, `KIND`, `SOURCE_TYPE`, `LICENCE` (licence state, covers monetized YouTube, third-party permission), `EXPIRED`, `CHANNEL`, `RESOLUTION`, `PERSON`, then for charts `CHART_DISABLED`, `CHART_LAG` (anything but `OLDER_THAN_LAG`), `CHART_LABEL`, `CHART_DIRECTION`. Glyphs: `g1_level_steps` (neutral: level steps, no slope or arrow), `g2_arrow` (not neutral). On a finance channel a non-neutral glyph is not offered and is listed in `excluded` as `{glyph, reason: FINANCE_DIRECTION}` (blueprint §6.3); guard G4 stays as a backstop, and the guard and planner fixtures (`FX-FIN`) still contain the non-neutral offers `o04` and `tpl_up_arrow_band` to test it. Asset fixtures may carry `third_party_permission` (`PERMITTED`, `NOT_PERMITTED`, `UNKNOWN`); absent means the tenant holds the licence; a `CLIENT_SUPPLIED` asset with `UNKNOWN` or `NOT_PERMITTED` is excluded as `LICENCE`. A chart with `data_age_vs_lag` other than `OLDER_THAN_LAG` (including `NOT_APPLICABLE`) is excluded as `CHART_LAG`.
- **Guard and planner fixtures.** `FX-EDU` (education channel) and `FX-FIN` (finance channel) share these offers. Text: `t01` "Read the trend" (`BRIEF_TEXT`, k1), `t02` "price structure" (`KEY_TERM`, k2), `t03` "trend from price structure" (`TITLE_SPAN`, k1 and k2), `t04` "Start here" (no key term; fixture only). Pictures: `o01` `CODE_GLYPH` "level steps outline", `o02` `CODE_GLYPH` "two overlapping frames", `o03` `NONE` "text only", `o04` `CODE_GLYPH` "rising arrow" (not neutral), `o05` `OWNER_IMAGE` "owner portrait" (`has_face` true). Templates: `tpl_split_left_text` (default, 2 lines, `CODE_GLYPH`/`NONE`/`OWNER_IMAGE`, neutral), `tpl_centered_statement` (2 lines, `CODE_GLYPH`/`NONE`, neutral), `tpl_subject_right` (1 line, `CODE_GLYPH`/`NONE`/`OWNER_IMAGE`, neutral), `tpl_up_arrow_band` (1 line, `CODE_GLYPH`, not neutral). Subject idea "outline of level steps"; the promise key terms are "trend" and "price structure". `overrides` in a planner case restrict the offers (`only_text`, `only_pictures`, `only_templates`). Guard cases may carry `previous_concepts` (`concept_id`, `template_key`, `subject_option_id`, `text_ids`, `keep`) and `revision_feedback` for the revision rule of G7.
- **Revision planner (`RevisionPlanner.build_previous`).** Input: the previous manifest's variants (`picture {kind, key}`, `texts[] {text_id, text}`, `template_key`, angle, hypothesis, emphasis, accent), the current options (`texts`, `pictures` with `option_id`, `kind`, `key`, `templates`) and the feedback. Output: `previous_concepts[]` with choices re-mapped by content (text byte-equal, picture by key, template by key); `keep` is false for a named variant, for every variant when `v1` is named, and for a variant whose choice no longer exists (that choice is `null`, text IDs may be empty).
- **Manifest (`ManifestBuilder.build`).** `set_sha256` = SHA-256 (hex) of `json.dumps(manifest_without_hash, sort_keys=True, separators=(',', ':'), ensure_ascii=False)` encoded as UTF-8.
- **Planner rule.** Concept `c1` is the control; `c2` tries a text change, `c3` a picture change; if the preferred factor is impossible the change moves to `LAYOUT_STYLE` (another compatible, neutral-on-finance template, accent `SECONDARY`); if that is impossible too, `NO_SAFE_CONCEPT` / `NO_DISTINCT_OPTION`. Candidates are tried in offer order and must pass G2 and G3. Picture choice for the control: highest token overlap between the label and (subject idea + hint intent), ties by the lowest option ID.
- **Fit.** Fixture metrics: every character advances 0.5 em; line height 1.2 em; the font size steps down from `max_font_px` by `font_step_px` to `min_font_px`.
- **Contrast.** Relative-luminance contrast ratio, rounded to 2 decimals (the metric source is a RESEARCH_LOG item, blueprint NFR-6).
- **Hash.** 64-bit hashes as 16 hex digits; Hamming distance.

## 4. Assertions (all cases; deterministic)
| ID | Assertion |
|---|---|
| T1 | the function returns exactly the `expected` value (option lists, exclusion lists, hits, concepts, sizes, ratios, distances, verdicts); integer arithmetic where stated |
| T2 | no model call, no network, no clock, no random number is used; running the case twice gives identical output (determinism) |
| T3 | for text and picture builders: every output text is a character-exact brief text, key term or title span, and every excluded item has exactly one reason |

## 5. Thresholds
All cases pass (**100 %**; a failing case is a defect, not noise). No cost or latency is recorded (no paid call).

## 6. Open points
- The finance lexicon, the injection markers and the neutral-word list used here are fixtures; the production lists are rule-pack or package data owned by 13 and the build ticket.
- Template geometry, font coverage and the real renderer are outside this dataset; the composer canary (U-169) and a Marathi render fixture cover them once a rasteriser is chosen (blueprint §9).
