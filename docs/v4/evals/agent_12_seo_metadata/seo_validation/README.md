# Eval set — `agent_12.metadata` deterministic core (`seo_validation`, **no LLM step**)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 12 SEO & Metadata |
| MVP | **3C** · Tier 0 (Agent 12 is not used in 3A) |
| Step type | **Deterministic** (pure functions of the Agent 12 package). There is **no model, no prompt file and no judge**; hence no `rubric.md` (27 §6.2 allows a judge only for subjective quality, and nothing here is subjective). |
| Depends on | blueprint [`agents/agent_12_seo_metadata.md`](../../../agents/agent_12_seo_metadata.md) (§6.3 checks, §6.5 pre-screen, §6.7 to §6.9, §10.3 to §10.5), `evals/README.md`, `27_ENGINEERING_STANDARDS.md` §6, `GLOSSARY_AND_IDS.md` §6.27 and §6.38 |
| Directive sections covered | §3.1 row 12 (SEO validation); §1B.2 answer key as far as it can be checked by code (AK-59 to AK-61, controls POS-54, HN-55 to HN-58); §3.5.3 (≥ 20 cases, hard negatives, edge cases, every applicable answer key) |
| Files | `cases.jsonl` (76 cases), `lexicon.test.v1.json` (test fixture), this README |
| Run mode | **offline, free, every commit** (no network, no adapter); also re-run in the eval gate so a regression in a function is visible next to the model sets |

## 1. Scope
These cases test the pure functions behind the checks that the blueprint runs on every bundle: title checks, tag budget and assembly, description-opening and description-size checks, chapter resolution and validation, the compliance pre-screen and description assembly. The two model steps are tested in [`keyword_plan`](../keyword_plan/README.md) and [`metadata_draft`](../metadata_draft/README.md); both of those call these functions as their post-checks.

No case contains a calendar date, a clock time, a real person, a book title, a course name or a private method. Instruments are public index names only. Every number in a text is made up. Limits asserted as "official" were read on the official YouTube pages (blueprint §12.2); they are configuration in production, and the cases pass the value in `args` so that a change of a limit changes data, not code.

## 2. Case format
One JSON object per line (format of `evals/README.md` §2, adapted to a function-level set):
| Field | Meaning |
|---|---|
| `case_id`, `category`, `description`, `notes` | as in `evals/README.md`; categories used: `ANSWER_KEY`, `POSITIVE`, `HARD_NEGATIVE`, `EDGE` (no `REFUSAL`: there is no model) |
| `input.function` | the function under test: `validate_titles`, `count_tag_budget`, `assemble_tags`, `validate_opening`, `validate_description_text`, `resolve_chapters`, `validate_chapters`, `prescreen`, `assemble_description` |
| `input.args` | keyword arguments of the function (names as in blueprint §10.3 to §10.5). Two generators keep long strings out of the file: `titles_spec` = list of `{prefix, unit, count}` meaning `prefix + unit × count`, and `text_spec` = one `{prefix, unit, count}`; the harness expands them before the call. `lexicon` names the fixture file in this folder |
| `expected.returns` | a map of expected result fields; a case passes when **every** listed key equals the returned value (extra returned keys are ignored; list order is compared where the list is ordered by design: tags, chapters, flags sorted by `entry_id`, then `field`) |
| `judge_min` | absent = `null` (deterministic-only) |

## 3. Case coverage
| Function | Cases | IDs | What they prove |
|---|---|---|---|
| `validate_titles` | 17 | AK-01 to AK-04, POS-05, POS-06, HN-07 to HN-10, EDGE-11 to EDGE-17 | 100 versus 101 characters, `<` and `>`, three variants at most (YT-08), primary keyword in `T1` fails but in `T2` only warns, promise term, grounded numbers (Devanagari digit equals ASCII digit), distinctness, recent titles, style warnings, display-length warning, zero titles |
| `count_tag_budget` | 5 | AK-18, AK-19, POS-20, EDGE-21, EDGE-22 | official examples `Foo-Baz` = 7 and `Foo Baz` = 9; commas count; Devanagari counted as code points; empty list |
| `assemble_tags` | 5 | POS-23, EDGE-24 to EDGE-27 | order, duplicates by case and spacing, budget cut with a later shorter tag still fitting, count cap, `<` `>` never used |
| `validate_opening` | 6 | POS-28, HN-29, HN-30, EDGE-31 to EDGE-33 | URL and bare domain, hashtag and markup, keyword in the first sentence (Devanagari sentence end), length limit |
| `validate_description_text` | 3 | AK-34, AK-35, EDGE-36 | 5 000 bytes pass, 5 001 fail, limit in **bytes** (1 666 versus 1 667 Devanagari letters), `>` fails |
| `resolve_chapters` | 10 | AK-37 to EDGE-46 | official rules (first at 00:00, at least three, ascending, at least 10 s), merge of short or ineligible sections, first-section absorb, omit when fewer than three (not an error), lead-in warning, flooring to seconds, unsorted input, last section short, long video (format pending review) |
| `validate_chapters` | 7 | POS-47, HN-48 to HN-52, EDGE-53 | first not at 00:00, two chapters, not ascending, under 10 s, start more than 1 000 ms from the section start, last chapter at the end |
| `prescreen` | 18 | POS-54, HN-55 to HN-58, AK-59 to AK-61, POS-62, POS-63, EDGE-64 to EDGE-71 | educational text allowed; stop-loss, "target audience", "study tips" and a historical index mention not over-blocked; answer-key calls, return claims and broker referral blocked; evasion by zero-width characters and capitals; Devanagari substrings; live session and paid group; "our method" with and without a release; flags carry the field |
| `assemble_description` | 5 | POS-72 to EDGE-76 | fixed block order with credits, disclaimer and footer; skipped blocks; summary points dropped from the end first, protected blocks never dropped; `FAIL` without text when still too long; no disclaimer block when no template (the separate blocking check `meta.disclaimer.present` catches it) |
Distribution: 12 `ANSWER_KEY`, 11 `POSITIVE`, 15 `HARD_NEGATIVE`, 38 `EDGE` (76).

**Answer-key cases.** Nine encode official limits (AK-01 to AK-04 titles and variants, AK-18 and AK-19 tags, AK-34 and AK-35 description bytes, AK-37 chapters; facts in blueprint §12.2, to be logged as `YT-16`/`YT-17`); three encode directive §1B.2 at pre-screen level (AK-59 answer B: a call with strike and time frame; AK-60 answer C: a performance claim; AK-61 answer D intent: a broker referral). Answer A (a historical chart study) is the control POS-54 and HN-58. Answer-key cases require 100 %.

## 4. Fixture `lexicon.test.v1.json`
A **test fixture only**: it is neither rule-pack content nor legal text. The production lexicon is rule-pack data owned by `13_COMPLIANCE_YOUTUBE_POLICY.md` (**REQUIRES REVIEW (Phase 1): counsel ⚖; content per language**) and changes together with this fixture by contract change request. Entries `L01` to `L10` cover FIN-R1, R2, R3, R4, R5, R6, R8, R12 and R13 with the kinds `phrase`, `regex`, `composite_instrument_future` and a context entry. Matching rules: NFC, case-fold, zero-width characters removed, whitespace collapsed; Latin phrases on word boundaries; phrases with Devanagari as substrings. **Documented limit** (EDGE-64): a future wording without a named instrument is not flagged by the composite entry; the model prompts and Agent 16 cover it.

## 5. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| SV1 | the function returns without raising for every case (these functions never raise on content; they return verdicts) |
| SV2 | every key of `expected.returns` equals the returned value (rules of §2) |
| SV3 | determinism: running the same case twice, and with the arguments' dictionaries in a different key order, returns identical results |
| SV4 | purity: no network call, no file write, no clock read (the socket guard and a frozen clock are active) |
| SV5 | verdict values are only `PASS`, `FAIL`, `WARN`, `SKIPPED` (GLOSSARY §6.27) and pre-screen verdicts only `ALLOWED`, `BLOCKED`, `NEEDS_HUMAN_REVIEW` (§6.29) |
| SV6 | every `check_id` returned is one named in blueprint §6.3 |

## 6. Pass thresholds (config `evals.agent_12.seo_validation.*`)
| Threshold | Value |
|---|---|
| Answer-key cases passing | **12 / 12 (100 %)** — mandatory |
| Overall case pass rate | **76 / 76 (100 %)** — a deterministic function has no tolerance |
| Cost | none (no paid call) |
| Run time | recorded; no threshold |
CI fails the commit if any case fails.

## 7. Recording fields (per case per run; 27 §6.4, adapted)
`run_id`, `function`, `case_id`, `passed`, `assertions` (SV1 to SV6 → pass/fail + detail), `code_version`, `lexicon_fixture_sha256`, `latency_ms`, `started_at`. No model, token or cost fields (there is no model call).

## 8. Open points
- The long-video timestamp format (`h:mm:ss`) is a provisional choice; EDGE-46 asserts only ordering and the warning `TIMESTAMP_FORMAT_PENDING_REVIEW` (official help page gives only `00:00` as the example).
- Title display length (70, a proposal) and the Jaccard limit (0.8, a proposal) are configuration defaults; the cases pass them in `args` so they can change without editing a case.
- Tag count cap (15) is a proposal; the official limit is the character budget only.
- Term matching is prefix-per-word (blueprint §6.4); its false-match rate on real Marathi titles is measured in the 3C pilot.
- The lexicon content is a fixture (§4).
