# Real provider adapters (lane D): owner steps

Code: `packages/amw_adapters` (`llm/anthropic.py`, `tts/elevenlabs.py`, `real/`; wiring `amw_runtime/providers.py`), catalogue `amw_adapters/data/providers.json`, smoke script `scripts/provider_smoke.py`. Facts: RESEARCH_LOG PR-04, PR-08 to PR-12. Owner decision 2026-11-19: LLM = Anthropic (ADR-007), TTS = ElevenLabs Eleven v3 / v4 class, never Multilingual v2.

No key, no paid call and no network are used by the tests. Nothing in this lane has called a provider.

## 1. What is built

| Part | Behaviour |
|---|---|
| `AnthropicLlmAdapter` | `POST /v1/messages`, `anthropic-version: 2026-10-21` (PR-08); text in, text out, no tools; the caller parses and validates JSON; no `temperature` sent (CCR-250); refusal -> `PERMANENT.PROVIDER_REFUSAL` with `details.usage` / `details.billed` (CCR-252); cost from the catalogue price table, rounded up, ESTIMATE; `count_tokens` costs 0 |
| Models (LLM) | `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` (PR-10 prices, Haiku in two prompt-length bands). Any other id -> `PERMANENT.CONFIG_INVALID` before a request |
| `ElevenLabsTtsAdapter` | `POST /v1/text-to-speech/{voice_id}?output_format=wav_48000` (PR-11); `model_id` and `language_code` always sent; 16-bit PCM WAV checked; cost = code points of the sent text x price per 1K characters (PR-12), rounded up |
| Models (TTS) | enabled: `eleven_v4` (10,000 chars), `eleven_v3` (5,000 chars). Disabled until their limits are documented: `eleven_v4_turbo`, `eleven_v3_conversational`. Refused (`CONFIG_INVALID`): `eleven_multilingual_v2`, `eleven_flash_v2_5`, `eleven_flash_v2`, `eleven_turbo_v2_5`, `eleven_turbo_v2`, any unknown id |
| Style controls | pace `NATIVE` only for a model whose catalogue entry has `speed_control` (then `TtsRequest.pace` is sent as `voice_settings.speed` from the catalogue `pace_speed` map, empty until the owner's 3B listening test; today `NONE`: PR-11 says v4 has no speed slider); `markup_delimiters` `[` `]` (audio tags, PR-12); emotion `NONE` until the owner fills `emotion_audio_tags` (one audio tag per emotion, after the 3B listening test). A control that is not declared is refused, never ignored |
| Retries | inside one call only when nothing can have been processed: connect failure, 429 with `retry-after` (Anthropic), 429 (ElevenLabs). 5xx, 529, read timeouts are raised as their 07 code with `retry_after_ms`; the 07 task policy decides (no provider idempotency key exists, PR-09 / PR-12) |
| Idempotency | per adapter instance: same key + same request = stored result, no second paid call; same key + other request = `PERMANENT.IDEMPOTENCY_CONFLICT` |
| Registry | `amw_runtime.providers.build_providers(runtime_config, preflight=..., env=..., guard_for=...)`: `DRY_RUN` -> fakes; `REAL_RUN` -> real adapters only with the real `PreflightReport` of a passed REAL_RUN `run_preflight` (type-checked) that carries a `ProviderAuthorisation` for each provider (minted only after its evidence-backed `PROVIDER_LIMIT` item passed) and both secrets present by name. A real adapter needs a `CallGuard` bound to its token, so it cannot be built or called any other way (CCR-274) |
| Call guard | before each paid request: worst-case cost in integer micros against the per-video hard cap of the preflight (owner ceiling USD 5) and `BudgetGuard.check_call`; refused before the request. After each response: ESTIMATE ledger row + `after_call`. `BudgetCallGuard` (L1b services, job from `call_scope`), `CapOnlyCallGuard` (smoke script, no database) |
| Logs | request id, token / character counts, cost, SHA-256 of the request body. Never the key, a header value, a prompt or a response text |

## 2. Owner steps before the first real call

1. **Accounts.** An Anthropic API account (billed separately from a Claude subscription, PR-03) and an ElevenLabs plan with API access. REQUIRES REVIEW (Phase 1): ElevenLabs states that 44.1 kHz PCM/WAV needs the Pro tier or above; the tier for 48 kHz WAV is not stated (PR-11). Check it before buying.
2. **Spending limits at each provider: the owner sets them.** Anthropic: Claude Console, Settings, Spend limits (`platform.claude.com/settings/spend-limits`, PR-09). ElevenLabs: an API key can carry its own credit quota (the "Credit quota" restriction of an API key, PR-11 source "Authentication"). The amounts are the owner's; this document gives none.
3. **Confirm each limit in the owner chat**: provider, amount, currency. The operator records each as an owner-evidence row; the preflight accepts it only when the verifier has it `CONFIRMED` from `OWNER_CHAT_OPERATOR` (docs/v4/runtime/README.md). Pre-flight needs the owner's chat confirmation; a test fixture is refused in real-run mode.
4. **Add the two keys** in the Claude Code environment's secret form (the "credentials" / "network secrets" form of the environment used for these sessions), with these exact names, and paste the value **only into that form**:

   | Secret name | Provider | Header the adapter sends |
   |---|---|---|
   | `AMW_SECRET_ANTHROPIC_API_KEY` | Anthropic (host `api.anthropic.com`) | `x-api-key` |
   | `AMW_SECRET_ELEVENLABS_API_KEY` | ElevenLabs (host `api.elevenlabs.io`) | `xi-api-key` |

   Never in chat, a file, an issue or a PR. A key that was pasted anywhere else must be revoked at the provider.
5. **Set the smoke-test cap** `AMW_EVALS__LIVE_SMOKE_MAX_COST_MICROS` (config `live_smoke.max_cost_micros`, Q-O15) to an amount the owner chooses (integer micros of USD; it must not be above the per-video cap). Unset or 0 = the smoke test refuses.
6. **Choose for the smoke test**: an Anthropic model id from the catalogue, `eleven_v4` or `eleven_v3`, and a voice id from the owner's ElevenLabs voice list (a neutral voice or the owner's consented clone, ADR-008 §2.4).

## 3. Smoke test (one tiny call per provider)

Order: the free token count (PR-08), the worst-case check against the cap, one completion (at most 64 output tokens), one TTS call of 7 Marathi characters. Refusals happen before any paid call.

```
AMW_RUNTIME_MODE=REAL_RUN AMW_ENVIRONMENT=development \
AMW_EVALS__LIVE_SMOKE_MAX_COST_MICROS=<owner amount> \
uv run python scripts/provider_smoke.py --confirmations <owner-confirmations.json> \
  --org-id <org id> --llm-model claude-haiku-5-5 --tts-model eleven_v4 --voice-id <voice id>
```

Exit codes: 0 both OK; 2 refused by config (mode, cap, model, catalogue); 3 preflight refused (each unmet item printed); 4 a provider call failed (07 code and HTTP status printed). Output never contains a key.

**REQUIRES REVIEW (integrator):** the command-line entry passes no owner-evidence lookup yet, so the preflight refuses every real-run limit record until the integrator wires the `amw_core` owner-evidence repository into `scripts/provider_smoke.py` (`run_smoke(..., evidence=...)`). This is deliberate fail-closed behaviour (D8), not a bug. Do not run the script before that wiring and the owner's go-ahead.

## 4. Open items

- REQUIRES REVIEW (Phase 1): how ElevenLabs counts a Devanagari "character" (code point or grapheme); compare the ESTIMATE rows with the usage export in the pilot (PR-12).
- REQUIRES REVIEW (Phase 1): character limits of `eleven_v4_turbo` and `eleven_v3_conversational` (not in the official table, PR-11); they stay disabled.
- REQUIRES REVIEW (owner, 3B): `emotion_audio_tags` and `voice_settings` (stability, similarity) after the listening test (ADR-008 §2.2, §4).
- Design defaults marked ESTIMATE in the catalogue: timeouts, in-call retry count 2 (the official Anthropic SDK default, PR-09), in-call wait cap 30 s, voice-list page limit.
- Fable 5.2 is not in the catalogue (cache prices not extracted); `TOP` tier uses Opus 5.5 until it is added with a research row.
- REQUIRES REVIEW (owner, 3B): `pace_speed` (one `voice_settings.speed` per pace) and the per-model `pronunciation_dictionary` flags (PR-11 states no per-model restriction).
- REQUIRES REVIEW: a REAL_RUN preflight cannot pass on the shipped runtime data yet (`render.max_duration_minutes` is unset) and still demands FIN-R10 for every job; D13 / CCR-273 narrows FIN-R10 to finance channels in a separate change.
- CCR-274 (guard and record in the adapter), CCR-250 (temperature), CCR-251 (provider spend limit code), CCR-252 (refusal cost row in callers), CCR-253 (TTS config keys), CCR-254 (`tokens_in` meaning).
