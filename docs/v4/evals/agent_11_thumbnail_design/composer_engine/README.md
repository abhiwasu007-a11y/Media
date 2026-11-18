# Eval set — `agent_11.composer_engine` (deterministic; no LLM)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 11 Thumbnail Design |
| Depends on | agents/agent_11_thumbnail_design.md (§6 decision engine, §10 functions F-06, F-07, F-11, F-12, F-13, F-15, F-16, §20 checks), 27_ENGINEERING_STANDARDS.md §6, §8 |
| Directive sections covered | §1A.2 (script promise = title promise = thumbnail promise: text provenance), §1A.1 (picture hierarchy and licence), §1B.2 and FIN-R1/R2/R3/R6/R13 (finance text and imagery), IN-02 / IN-03 (chart still age and label), §1A.8 (size, legibility), YT-08 (distinct variants) |
| Files | `cases.jsonl` (54 cases), `rubric.md` (statement: no judge) |

## 1. Scope
The pure functions of the thumbnail engine run on fixture inputs without any model, clock, font library or network. Each case names the `function` under test, an `input` fixture and the exact `expected` result. It is the dataset that the table-driven unit tests U-21…U-44, U-59…U-89 and U-95…U-101 read (blueprint §21). The LLM step has its own dataset (`../thumbnail_concepts/`). Cases carry no dates: chart age is the precomputed field `data_age_vs_lag`, so the dataset stays valid when the configured lag changes.

## 2. Case coverage
| Group | Cases | Function | What they prove |
|---|---|---|---|
| CE-TOB-01…12 | 12 | `TextOptionBuilder.build` | source order, key-term spans ranked, de-duplication, the cap, Devanagari whole-word match, exclusion reasons `EMPTY`, `TOO_LONG`, `BANNED_WORD`, `MUST_NOT_PROMISE`, `INJECTION`, `FIN_TEXT` (digit, lexicon), digit kept off finance |
| CE-SOB-01…09 | 9 | `SubjectOptionBuilder.build` | owner image eligibility (licence, source type, expiry, channel, resolution, status), person policy (default off, release, finance never), chart still (disabled, lag, `UNKNOWN`, label, direction), option ID order |
| CE-GD-01…15 | 15 | `ConceptGuards.check` | G1…G8 hit and no-hit cases; first failing guard only |
| CE-FP-01…06 | 6 | `FallbackPlanner.plan` | control, text then picture change, layout change, `NO_DISTINCT_OPTION`, finance neutrality, count 1 |
| CE-FIT-01…05 | 5 | `Composer.fit_text` | font size search, two lines, no fit, lines over the template limit, exact fit |
| CE-CON-01…04 | 4 | `contrast_ratio` | black/white 21.00, identical 1.00, 4.54 and 4.48 around the 4.5 minimum |
| CE-HASH-01…03 | 3 | `Distinctness.check` | pairwise Hamming distance, fail under the minimum, exact minimum |
Categories: POSITIVE 11, HARD_NEGATIVE 16, EDGE 27.

## 3. Fixtures and conventions
- **Text builder (`TextOptionBuilder.build`).** `config` holds `max_words`, `max_chars`, `max_options` (test values). `lexicon` and `injection_markers` are fixture lists (the real lexicon is rule-pack content, 13 §5.4). Exclusion reason precedence: `EMPTY`, `TOO_LONG`, `BANNED_WORD`, `MUST_NOT_PROMISE`, `INJECTION`, `FIN_TEXT`. Matching is case-folded, NFC. Source order `BRIEF_TEXT`, `KEY_TERM` (promise order), `TITLE_SPAN` (distinct key terms desc, words asc, start asc); equal text keeps the earlier source. The cap is applied after exclusions.
- **Picture builder.** Option order `OWNER_IMAGE` (by `sha`), `CODE_GLYPH` (by `key`), `NONE`. Asset exclusion precedence: `STATUS`, `KIND`, `SOURCE_TYPE`, `LICENCE`, `EXPIRED`, `CHANNEL`, `RESOLUTION`, `PERSON`, then for charts `CHART_DISABLED`, `CHART_LAG` (anything but `OLDER_THAN_LAG`), `CHART_LABEL`, `CHART_DIRECTION`. Glyphs: `g1_staircase` neutral, `g2_arrow` not neutral. A non-neutral glyph is offered on finance channels (the model and guard G4 refuse it).
- **Guard and planner fixtures.** `FX-EDU` (education channel) and `FX-FIN` (finance channel) share these offers. Text: `t01` "Read the trend" (`BRIEF_TEXT`, k1), `t02` "price structure" (`KEY_TERM`, k2), `t03` "trend from price structure" (`TITLE_SPAN`, k1 and k2), `t04` "Start here" (no key term; fixture only). Pictures: `o01` `CODE_GLYPH` "staircase schematic", `o02` `CODE_GLYPH` "two overlapping frames", `o03` `NONE` "text only", `o04` `CODE_GLYPH` "rising arrow" (not neutral), `o05` `OWNER_IMAGE` "owner portrait" (`has_face` true). Templates: `tpl_split_left_text` (default, 2 lines, `CODE_GLYPH`/`NONE`/`OWNER_IMAGE`, neutral), `tpl_centered_statement` (2 lines, `CODE_GLYPH`/`NONE`, neutral), `tpl_subject_right` (1 line, `CODE_GLYPH`/`NONE`/`OWNER_IMAGE`, neutral), `tpl_up_arrow_band` (1 line, `CODE_GLYPH`, not neutral). Subject idea "staircase of rising steps"; the promise key terms are "trend" and "price structure". `overrides` in a planner case restrict the offers (`only_text`, `only_pictures`, `only_templates`).
- **Planner rule.** Concept `c1` is the control; `c2` tries a text change, `c3` a picture change; if the preferred factor is impossible the change moves to `LAYOUT_STYLE` (another compatible, neutral-on-finance template, accent `SECONDARY`); if that is impossible too, `NO_SAFE_CONCEPT` / `NO_DISTINCT_OPTION`. Candidates are tried in offer order and must pass G2 and G3.
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
