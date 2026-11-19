# Runtime readiness (lane S4)

Package: `packages/amw_runtime`. No paid calls, no network, no keys in tests. Binding rules: D1, D8 (no paid calls and no real keys until the owner sets the limits and supplies keys through the secret mechanism), IN-02 (30-day price-data lag), FIN-R9, FIN-R10, CCR-106/107/133.

## Public interfaces
- `amw_runtime.config.load_runtime_config(env) -> RuntimeConfig` (caps in integer micros; exponent from config data, RV-07; env may only lower the owner caps; hard stop on breach).
- `amw_runtime.preflight.run_preflight(config, confirmations, *, env, evidence, calendar, render_start) -> PreflightReport`, raising `PreflightRefused` with every unmet item.
- `amw_runtime.calendar.MarketCalendar` (`render_allowed(dt)`, `check_render(dt)`, `in_regular_session(dt)`, `covers(year)`).
- `amw_runtime.chartdata.assert_bars_older_than_lag(last_bar_date, as_of)` and `ChartDataPolicy`.
- `amw_runtime.disclaimer.get_disclaimer(version) -> Disclaimer(text, version, status)`.

## Owner decisions recorded as data (`runtime_config.json`, not code)
- Caps: USD 5 per video, USD 50 pilot, HARD STOP on breach (stored in minor units, converted to micros with the ISO 4217 exponent, RV-07).
- Topic: "RSI divergence explained on historical charts" (provisional per D8 rule 7 until confirmed in writing; the evidence id is **REQUIRES REVIEW**).
- No music in the first sample; no upload.
- Providers: Anthropic (LLM) and ElevenLabs (TTS) required; stock footage not used.

## What the owner must do for the real run (exact list)
1. Set the spending limit at **Anthropic** and at **ElevenLabs** (provider consoles) and confirm each in the owner chat: provider, amount, currency. The operator records it as an owner-evidence row, verified by the verifier (`CONFIRMED`, channel `OWNER_CHAT_OPERATOR`). A test fixture is accepted in dry runs only.
2. Add the two secrets (SECRETS.md) through the environment's secret form.
3. Confirm the caps and the topic in writing (budget and topic decisions above).
4. Confirm whether the owner is **not** SEBI-registered (FIN-R10). The disclaimer states it; until confirmed the report lists it as an open owner item.
5. Have the disclaimer lawyer-approved (status stays `DRAFT – not lawyer-approved` until then; 13 section 5.6).
6. Provide the **official NSE 2027 trading-holiday list** when published (NSE-03): replace `calendar/nse_holidays_2027.json` (status VERIFIED, source, date). Until then every 2027 date is refused. The 2026 list is verified (NSE-02, checked 2026-11-19).
7. Provide the chart `data_pack` location (variable `AMW_CHART_DATA_PACK_LOCATION`): a pointer to the private store; the data never enters this repository. Every bar must be at least 30 days old on the publish date.
8. Run only in the development environment (`AMW_ENVIRONMENT=development`, no VPS marker) and outside market hours. The guard blocks 09:00 to 16:00 IST on trading days (regular session 09:15 to 15:30, NSE-01, plus pre-open and closing session as a margin).

## Open items
See the REQUIRES REVIEW list in the pull request: NSE-03 (2027 holidays), Muhurat timings, evidence kind for provider limits and FIN-R10 owner status (not yet in `evidence_record_kind`), stock provider, topic approval evidence, lawyer approval of the disclaimer.

## Report label
Agent 16 prints `DRAFT, not lawyer-approved` (checks/rules.py); the owner-specified status string here is `DRAFT – not lawyer-approved` (en dash). The integrator should take the label from `Disclaimer.status` so both agree.
