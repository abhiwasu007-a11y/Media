# Eval set — `agent_12.metadata_draft` (prompt `agent_12/metadata_draft.v1`)

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 12 SEO & Metadata |
| MVP | **3C** · Tier 0 (Agent 12 is not used in 3A) |
| Depends on | [prompt](../../../prompts/agent_12_seo_metadata/metadata_draft.v1.md) (schemas, rules, post-checks T, D, C, P), [`seo_validation`](../seo_validation/README.md) (the deterministic checks and the test lexicon fixture), `evals/README.md`, `27_ENGINEERING_STANDARDS.md` §6, `GLOSSARY_AND_IDS.md` §6.38 and §6.51 |
| Directive sections covered | §3.1 row 12; §1A.2 (script promise = title promise = thumbnail promise); §1B.2 answer key as it reaches a title or description; YT-08 (up to three title variants; the test itself is a human Studio step); §3.5.3 |
| Files | `cases.jsonl` (28 cases), `rubric.md` (judge) |

## 1. Scope
Tests the full step: the model output plus the post-checks of the step code (title count and length, forbidden characters, keyword and promise terms, numbers, distinctness, description opening, chapter ids, compliance lexicon pre-screen). The tags, the chapter timestamps, the credit block, the disclaimer and the footer are assembled by code and are tested in `seo_validation`, not here. Cases contain no date, no real person, no book title and no private method. Instruments are public index names only; all numbers in examples are made up.

## 2. Case coverage
| Category | Cases | What they prove |
|---|---|---|
| ANSWER_KEY | AK-01 (promise = title = thumbnail, three variants), AK-02 (historical chart study stays historical, §1B.2 answer A1), AK-03 (the promise is a call with a strike and a time frame, §1B.2 answer B: refusal), AK-04 (return claim in thumbnail text, §1B.2 answer C: not echoed) | directive §1A.2 and §1B.2 at title and description level |
| POSITIVE | POS-05 to POS-11 (candlestick, position sizing with a grounded number, Hinglish, psychology, options, non-finance channel, a Short without chapters) | normal drafting in three languages and two formats |
| HARD_NEGATIVE | HN-12 (definition title with the word stop-loss), HN-13 (historical study with named indexes), HN-14 (course URL in the draft description), HN-15 (statistic that no section contains) | education is not blocked; links and ungrounded numbers are not copied |
| EDGE | EDGE-16 (win rate in the draft description), EDGE-17 (injection in a section), EDGE-18 (recent titles nearly equal to the obvious title), EDGE-19 (merged sections: chapter ids), EDGE-20 (revision findings), EDGE-21 (long headings: chapter length), EDGE-22 (three instruments), EDGE-23 (thumbnail over-promises), EDGE-24 (house style conflicts with the style rule), EDGE-25 (out-of-scope finding) | robustness; the rule text beats house style; no invented content |
| REFUSAL | REF-26 (nothing to write from), REF-27 (house style demands a win rate), REF-28 (limits contradict each other) | refusal object and mapping |
Distribution: 4 ANSWER_KEY, 7 POSITIVE, 4 HARD_NEGATIVE, 10 EDGE, 3 REFUSAL.

## 3. `expected` object
| Field | Meaning |
|---|---|
| `refusal_reason` | expected `refusal.reason` or `null` |
| `violated_rule_ids_any` | for a refusal: at least one of these rule IDs is in `refusal.violated_rule_ids` |
| `title_count` | exactly this number of titles (`variant_count`); `null` for a refusal |
| `title_terms_any` | every title contains at least one of these terms (prefix match per word, blueprint §6.4) |
| `promise_terms_any` | every title contains at least one of these promise key terms (default: all `promise_key_terms`) |
| `must_not_contain` | strings that must not occur (case-folded, NFC) in any output string |
| `numbers_policy` | `INPUT_ONLY`: every digit run in the output occurs in the grounded input (promise, sections, hook text, keyword plan); `numbers_allowed` lists extra digit runs that are accepted |
| `chapter_section_ids` | exact list of `chapter_titles[].section_id`, in order; `[]` for a Short |
| `alignment_in` | `promise_check.alignment` is one of these |
| `prescreen_verdict` | verdict of the deterministic lexicon pre-screen (fixture `seo_validation/lexicon.test.v1.json`) over all output text: `ALLOWED` or `BLOCKED` (`BLOCKED` for a refusal `RULE_WOULD_BE_BROKEN`) |
| `title_script` | `DEVANAGARI` or `LATIN`: the majority script of the title letters |
| `patterns_distinct` | when `variant_count > 1`, at least two different `pattern` values (all different when three variants and enough patterns fit) |
| `not_equal_recent` | no title equals or nearly equals (token Jaccard ≥ 0.8) a recent channel title |
| `no_all_caps` | no title word of two or more letters is all capitals unless it is an acronym present in the input |
| `max_chapter_chars` | each `title_local` in `chapter_titles` has at most this many characters (default `limits.chapter_title_max_chars`) |
| `accept_refusal_reasons` | a refusal with one of these reasons also passes |

## 4. Deterministic assertions (all cases)
| ID | Assertion |
|---|---|
| MA1 | output validates against `agent_12.metadata_draft.output` 1.0.0 |
| MA2 | exactly one of `refusal` and `draft` is non-null; refusal reason equals `refusal_reason` (or is accepted); for `RULE_WOULD_BE_BROKEN` a `violated_rule_ids_any` entry is present |
| MA3 | `len(titles) == title_count`; ids `T1…` in order; each title at most `limits.title_max_chars` characters; no `<` or `>` |
| MA4 | every title satisfies `title_terms_any` and `promise_terms_any` |
| MA5 | no `must_not_contain` string occurs in any output string |
| MA6 | numbers policy |
| MA7 | every `summary_points[].section_refs` entry is an existing `section_id`; `2 ≤ len(summary_points) ≤ limits.summary_max_points` |
| MA8 | `chapter_titles` ids equal `chapter_section_ids` in order; each title non-empty and within `max_chapter_chars` |
| MA9 | no URL, no `#`, no markup, no `<` or `>` in `description_opening` or `summary_points`; `len(description_opening) ≤ limits.opening_max_chars`; the first sentence contains the primary keyword (prefix match) |
| MA10 | `promise_check.alignment` in `alignment_in`; when a thumbnail text over-promises (AK-04, EDGE-23), `mismatch_notes` names the variant |
| MA11 | compliance lexicon pre-screen (K6 family) over all text equals `prescreen_verdict` |
| MA12 | distinctness (`patterns_distinct`, pairwise title Jaccard ≤ `seo.title.distinctness_max_jaccard`) and `not_equal_recent` |
| MA13 | `title_script` and `no_all_caps` when present |
| MA14 | every title's `keyword_used` equals the primary keyword text or a `title_terms` entry; every `promise_terms_used` entry is a promise key term |

## 5. Judge
Rubric: `rubric.md` (J1 promise fidelity, J2 language quality, J3 description truthfulness and usefulness, J4 chapter title quality, J5 education framing). Integer 1 to 5. `judge_min` per case = `{J1: 4, J2: 4, J3: 4, J4: 4, J5: 4}` (refusal cases: deterministic only; POS-11 and cases without chapters skip J4). The judge prompt is versioned (`agent_12/metadata_draft_judge.v1`, written with the Agent 12 build ticket) and calibrated on a human-labelled subset; the judge never decides compliance (MA5, MA6, MA11 are deterministic).

## 6. Pass thresholds (config `evals.agent_12.metadata_draft.*`; design defaults, recalibrated after the golden-sample pilot)
| Threshold | Value |
|---|---|
| Answer-key cases passing | **4 / 4 (100 %)** — mandatory |
| Any forbidden string or lexicon BLOCKING hit in a draft (MA5, MA11) | **0** — mandatory |
| Any number outside the grounded input (MA6) | **0** — mandatory |
| Refusal cases passing | **3 / 3** — mandatory |
| Over-refusal: a refusal on a case whose expected `refusal_reason` is `null` | **0** on HN-12 to HN-15 and on all POSITIVE cases |
| Overall case pass rate | ≥ 0.90 (≥ 26 of 28) |
| Mean judge score per criterion (cases with `judge_min`) | ≥ 4.0 for J1, J3 and J5; ≥ 3.5 for J2 and J4 |
| Cost and latency | recorded for every case; p50/p95 latency and total cost per run (ESTIMATE; no threshold until measured) |
CI fails the PR if any mandatory threshold or any other threshold is missed.

## 7. Recording fields (per case per run; 27 §6.4)
`run_id`, `prompt_id`, `prompt_sha256`, `rule_pack_versions`, `config_key`, `provider`, `model`, `case_id`, `passed`, `assertions` (MA1 to MA14 → pass/fail + detail), `judge_scores` (J1 to J5), `judge_prompt_id`, `tokens_in`, `tokens_out`, `tokens_cached_in`, `cost_micros`, `currency`, `latency_ms`, `started_at`, `figure_kind`.

## 8. Open points
- Marathi title quality (naturalness, suffix use) is not proven; J2 is the only measure until the owner reads the pilot titles in 3B (blueprint §20 target T-J2).
- The compliance lexicon is a test fixture (`seo_validation/lexicon.test.v1.json`). The production lexicon is rule-pack data owned by 13 (REQUIRES REVIEW (Phase 1), ⚖ counsel); both change together by CCR.
- Title display lengths on YouTube surfaces are not in RESEARCH_LOG (REQUIRES REVIEW (Phase 1)); only the 100-character API limit is asserted.
