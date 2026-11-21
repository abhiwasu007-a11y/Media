"""Budget-guarded Anthropic calls.

The key is read only from the environment variable named in ``SECRET_ENV`` and is never logged.
Before every call: free token count, then the worst case (input + max_tokens at the output price)
must fit in BOTH the per-video cap and the pilot cap, else the call is refused (hard stop, D9).
After every call: the cost from ``usage`` is appended to the job ledger before anything else runs.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

from . import config

SECRET_ENV = "AMW_SECRET_ANTHROPIC_API_KEY"  # noqa: S105 - a variable NAME, not a secret


class BudgetRefused(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    stop_reason: str | None


def ledger_rows(job: Path) -> list[dict]:
    f = job / "ledger.json"
    return json.loads(f.read_text())["rows"] if f.exists() else []


def job_spent(job: Path) -> float:
    return sum(r["cost_usd"] for r in ledger_rows(job))


def pilot_spent() -> float:
    return sum(job_spent(j) for j in config.jobs_dir().iterdir() if j.is_dir())


def append_row(job: Path, row: dict) -> None:
    rows = ledger_rows(job)
    rows.append(row)
    (job / "ledger.json").write_text(json.dumps({"currency": "USD", "rows": rows}, indent=1))


def call(job: Path, stage: str, system: str, user: str, max_tokens: int, effort: str = "medium") -> Reply:
    key = os.environ.get(SECRET_ENV)
    if not key:
        raise BudgetRefused(f"secret {SECRET_ENV} is not set")
    cfg = config.load()
    client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com", max_retries=2)
    msgs = [{"role": "user", "content": user}]
    counted = client.messages.count_tokens(model=cfg.model, system=system, messages=msgs).input_tokens
    worst = counted * cfg.price_in + max_tokens * cfg.price_out
    if job_spent(job) + worst > cfg.per_video_cap_usd:
        raise BudgetRefused(f"per-video cap: spent {job_spent(job):.4f} + worst case {worst:.4f} > {cfg.per_video_cap_usd}")
    if pilot_spent() + worst > cfg.pilot_cap_usd:
        raise BudgetRefused(f"pilot cap: spent {pilot_spent():.4f} + worst case {worst:.4f} > {cfg.pilot_cap_usd}")
    t0 = time.time()
    with client.messages.stream(
        model=cfg.model,
        max_tokens=max_tokens,
        system=system,
        messages=msgs,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
    ) as stream:
        msg = stream.get_final_message()
    text = "".join(b.text for b in msg.content if b.type == "text")
    (job / f"raw_{stage}.txt").write_text(text)
    u = msg.usage
    append_row(
        job,
        {
            "stage": stage,
            "provider": "anthropic",
            "model": cfg.model,
            "request_id": msg.id,
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cost_usd": round(u.input_tokens * cfg.price_in + u.output_tokens * cfg.price_out, 6),
            "basis": "ESTIMATE (list price x usage)",
            "seconds": round(time.time() - t0, 1),
            "stop_reason": msg.stop_reason,
        },
    )
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"model refusal at stage {stage}")
    return Reply(text, msg.stop_reason)


def parse_json(text: str) -> dict:
    s = text.strip()
    a, b = s.find("{"), s.rfind("}")
    return json.loads(s[a : b + 1])
