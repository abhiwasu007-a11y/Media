"""Live provider smoke test: ONE tiny call per provider (Anthropic LLM, ElevenLabs TTS).

Runs only when ALL hold (D1, D8, 27 section 8.4, Q-O15), else it refuses before any paid call:
1. ``AMW_RUNTIME_MODE=REAL_RUN`` and ``amw_runtime.run_preflight`` passes (provider spending
   limits confirmed by the owner with CONFIRMED owner-chat evidence, secrets present by NAME,
   development environment, outside the market-hours guard, ...);
2. the owner-set cap ``AMW_EVALS__LIVE_SMOKE_MAX_COST_MICROS`` (config
   ``live_smoke.max_cost_micros``) is set, is not above the per-video cap, and the worst-case
   cost of both calls fits in it (the free token count runs first to size the prompt, PR-08).

Output: one status line per provider (ids, token / character counts, cost in micros). Never a key,
never a header value. Exit codes: 0 ok, 2 refused (config), 3 preflight refused, 4 a call failed.
Usage: see docs/v4/runtime/PROVIDERS.md. Do not run it without the owner's go-ahead.
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path

import httpx

from amw_adapters.llm import LlmMessage, LlmRequest
from amw_adapters.llm.anthropic import cost_micros
from amw_adapters.real.catalogue import load_catalogue
from amw_adapters.real.guard import CapBook, CapOnlyCallGuard
from amw_adapters.tts import TtsRequest
from amw_core.config import load_settings
from amw_core.enums import RetryPolicy
from amw_core.errors import AmwError
from amw_core.ids import ORG, IdempotencyScope, make_idempotency_key
from amw_runtime.config import RunMode, load_runtime_config
from amw_runtime.confirmations import ConfirmationRecord, EvidenceStatusLookup
from amw_runtime.errors import PreflightRefused
from amw_runtime.preflight import run_preflight
from amw_runtime.providers import build_providers

LLM_MAX_OUTPUT_TOKENS = 64
LLM_PROMPT = "Reply with the single word: ok"
TTS_TEXT = "नमस्कार"
"""Seven code points of Marathi text (cost ESTIMATE rule PR-12)."""


def run_smoke(
    env: Mapping[str, str],
    *,
    confirmations: Sequence[ConfirmationRecord],
    evidence: EvidenceStatusLookup | None,
    org_id: str,
    llm_model: str,
    tts_model: str,
    voice_id: str,
    transports: Mapping[str, httpx.BaseTransport] | None = None,
    render_start: datetime | None = None,
    out: Callable[[str], None] = print,
) -> int:
    try:
        config = load_runtime_config(env)
        settings = load_settings(environ=env)
    except AmwError as exc:
        out(f"refused: {exc.code}: {exc.message}")
        return 2
    if config.mode is not RunMode.REAL_RUN:
        out("refused: AMW_RUNTIME_MODE must be REAL_RUN for a live smoke test")
        return 2
    cap = settings.evals.live_smoke_max_cost_micros
    if cap is None or cap == 0:
        out("refused: owner cap AMW_EVALS__LIVE_SMOKE_MAX_COST_MICROS is not set (Q-O15)")
        return 2
    if cap > config.per_video_cap_micros:
        out("refused: the live smoke cap is above the per-video cap")
        return 2
    try:
        report = run_preflight(
            config,
            confirmations,
            env=env,
            evidence=evidence,
            render_start=render_start,
            org_id=org_id,
        )
    except PreflightRefused as exc:
        out("preflight refused:")
        for item in exc.items:
            out(f"  {item.code}: {item.message}")
        return 3
    catalogue = load_catalogue()
    if {catalogue.anthropic.currency, catalogue.elevenlabs.currency} != {config.currency}:
        out("refused: catalogue currency differs from the budget currency")
        return 2
    try:
        llm_price = catalogue.anthropic.model(llm_model)
        tts_price = catalogue.elevenlabs.model(tts_model)
        book = CapBook()  # one counter for both providers: the cap covers the run together
        providers = build_providers(
            config,
            preflight=report,
            env=env,
            guard_for=lambda auth: CapOnlyCallGuard(auth, book=book),
            catalogue=catalogue,
            transports=transports,
            backoff=settings.retry_policy(RetryPolicy.TEMPORARY),
        )
    except AmwError as exc:
        out(f"refused: {exc.code}: {exc.message} {exc.details}")
        return 2
    org = ORG.new()
    stamp = datetime.now().isoformat()
    request = LlmRequest(
        model=llm_model,
        system="",
        messages=(LlmMessage(role="user", content=LLM_PROMPT),),
        max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
        timeout_ms=60_000,
    )
    try:
        counted = providers.llm.count_tokens(
            request,
            idempotency_key=make_idempotency_key(
                org, IdempotencyScope.LLM_CALL, ["smoke", stamp, "count"]
            ),
        )
    except AmwError as exc:
        out(f"anthropic: FAILED token count {exc.code} upstream_status={exc.upstream_status}")
        return 4
    worst_llm = cost_micros(
        llm_price,
        {"input_tokens": counted.tokens_in, "output_tokens": LLM_MAX_OUTPUT_TOKENS},
        catalogue.anthropic.cache_ttl,
    )
    worst_tts = -(-len(TTS_TEXT) * tts_price.price_micros_per_1k_chars // 1000)
    out(f"worst case: llm {worst_llm} + tts {worst_tts} micros; cap {cap} micros")
    if worst_llm + worst_tts > cap:
        out("refused: worst-case cost is above the owner cap; no paid call made")
        return 2
    status = 0
    spent = 0
    try:
        reply = providers.llm.complete(
            request,
            idempotency_key=make_idempotency_key(
                org, IdempotencyScope.LLM_CALL, ["smoke", stamp, "complete"]
            ),
        )
        u = reply.usage
        spent += u.amount_micros
        out(
            f"anthropic: OK model={u.model} stop_reason={reply.stop_reason} "
            f"tokens_in={u.tokens_in} tokens_out={u.tokens_out} cost_micros={u.amount_micros} "
            f"request_id={u.external_request_id}"
        )
    except AmwError as exc:
        out(f"anthropic: FAILED {exc.code} upstream_status={exc.upstream_status}")
        status = 4
    try:
        audio = providers.tts.synthesize(
            TtsRequest(text=TTS_TEXT, voice_ref=voice_id, model=tts_model, language="mr"),
            idempotency_key=make_idempotency_key(
                org, IdempotencyScope.TTS_SYNTHESIZE, ["smoke", stamp, voice_id]
            ),
        )
        u = audio.usage
        spent += u.amount_micros
        out(
            f"elevenlabs: OK model={u.model} characters={u.units} duration_ms={audio.duration_ms} "
            f"sample_rate_hz={audio.sample_rate_hz} cost_micros={u.amount_micros} "
            f"request_id={u.external_request_id}"
        )
    except AmwError as exc:
        out(f"elevenlabs: FAILED {exc.code} upstream_status={exc.upstream_status}")
        status = 4
    out(
        f"total estimate: {spent} micros (ESTIMATE; the provider usage page is the VERIFIED figure)"
    )
    return status


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--confirmations",
        type=Path,
        required=True,
        help="JSON list of owner confirmation records (amw_runtime)",
    )
    parser.add_argument("--org-id", required=True, help="the run's org (evidence is bound to it)")
    parser.add_argument("--llm-model", required=True)
    parser.add_argument("--tts-model", required=True)
    parser.add_argument("--voice-id", required=True)
    args = parser.parse_args(argv)  # fmt: skip
    records = [
        ConfirmationRecord.model_validate(r)
        for r in json.loads(args.confirmations.read_text(encoding="utf-8"))
    ]
    # The owner-evidence lookup is wired by the integrator (amw_core owner-evidence repository);
    # without it the preflight refuses every real-run limit record (fail closed).
    return run_smoke(
        os.environ,
        confirmations=records,
        evidence=None,
        org_id=args.org_id,
        llm_model=args.llm_model,
        tts_model=args.tts_model,
        voice_id=args.voice_id,
    )


if __name__ == "__main__":
    sys.exit(main())
