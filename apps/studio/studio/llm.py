"""Budget-guarded Anthropic calls.

The key is read only from the environment variable named in ``SECRET_ENV`` and is never logged.
Before every call: free token count, then the worst case (input + max_tokens at the output price)
must fit in BOTH the per-video cap and the pilot cap, else the call is refused (hard stop, D9).
After every call: the cost from ``usage`` is appended to the job ledger before anything else runs.
"""

import hashlib
import json
import time
import uuid
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


def _write_rows(job: Path, rows: list[dict]) -> None:
    f = job / "ledger.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"currency": "USD", "rows": rows}, indent=1))
    tmp.replace(f)  # atomic: a crash never leaves a half-written ledger


def append_row(job: Path, row: dict) -> None:
    _write_rows(job, [*ledger_rows(job), row])


def replace_row(job: Path, rid: str, row: dict | None) -> None:
    """Swap the reservation ``rid`` for the measured row (or drop it when ``row`` is None)."""
    rows = [r for r in ledger_rows(job) if r.get("rid") != rid]
    _write_rows(job, rows + ([row] if row else []))


def _cache_file(job: Path, stage: str, model: str, system: str, user: str, max_tokens: int, effort: str) -> Path:
    h = hashlib.sha256(json.dumps([model, system, user, max_tokens, effort], ensure_ascii=False).encode()).hexdigest()[:16]
    return job / f"raw_{stage}_{h}.json"


def call(job: Path, stage: str, system: str, user: str, max_tokens: int, effort: str = "medium") -> Reply:
    """One paid call. The worst case is reserved on the ledger BEFORE the request and replaced by the measured cost
    after it, so a crash or a broken stream never under-counts. An identical earlier request (same model, prompt,
    limits) is answered from its saved reply: a re-run after a parse failure does not pay twice."""
    cfg = config.load()
    cache = _cache_file(job, stage, cfg.model, system, user, max_tokens, effort)
    if cache.exists():
        d = json.loads(cache.read_text())
        return Reply(d["text"], d.get("stop_reason"))
    key = config.get(SECRET_ENV)
    if not key:
        raise BudgetRefused(f"secret {SECRET_ENV} is not set")
    client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com", max_retries=2)
    msgs = [{"role": "user", "content": user}]
    counted = client.messages.count_tokens(model=cfg.model, system=system, messages=msgs).input_tokens
    worst = counted * cfg.price_in + max_tokens * cfg.price_out
    if job_spent(job) + worst > cfg.per_video_cap_usd:
        raise BudgetRefused(f"per-video cap: spent {job_spent(job):.4f} + worst case {worst:.4f} > {cfg.per_video_cap_usd}")
    if pilot_spent() + worst > cfg.pilot_cap_usd:
        raise BudgetRefused(f"pilot cap: spent {pilot_spent():.4f} + worst case {worst:.4f} > {cfg.pilot_cap_usd}")
    rid = uuid.uuid4().hex
    append_row(
        job,
        {
            "rid": rid,
            "stage": stage,
            "provider": "anthropic",
            "model": cfg.model,
            "cost_usd": round(worst, 6),
            "basis": "RESERVED worst case: call in flight, or lost (reconcile with the provider console)",
        },
    )
    t0 = time.time()
    try:
        with client.messages.stream(
            model=cfg.model,
            max_tokens=max_tokens,
            system=system,
            messages=msgs,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
        ) as stream:
            msg = stream.get_final_message()
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        status = getattr(exc, "status_code", None)
        if status is not None and 400 <= status < 500 and status != 429:
            replace_row(job, rid, None)  # rejected before any processing: nothing billed
        raise
    u = msg.usage
    replace_row(
        job,
        rid,
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
    text = "".join(b.text for b in msg.content if b.type == "text")
    cache.write_text(json.dumps({"text": text, "stop_reason": msg.stop_reason}, ensure_ascii=False))
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"model refusal at stage {stage}")
    return Reply(text, msg.stop_reason)


SEARCH_USD = 0.01  # web search: $10 per 1,000 searches (claude-api skill, Managed Agents list-cost note)


def research(job: Path, topic_brief: str, max_searches: int = 6, max_tokens: int = 32000) -> Reply:
    """Stage-04 research with the Claude web search server tool. Same reservation rule as ``call``: worst case (tokens +
    every allowed search) reserved before the request, replaced by the measured cost (tokens + searches made)."""
    cfg = config.load()
    system = (
        "You are a careful researcher for a YouTube explainer/story video. Search the web, prefer primary and authoritative "
        "sources (encyclopedias, museums, universities, official sites, classical texts in public translations). Write a "
        "RESEARCH PACK in English markdown: 1) 8-15 key facts, each followed by its source URL in brackets; 2) for stories "
        "or mythology, the traditional version with its textual source and notable variants; 3) one original story or "
        "scene idea that makes the topic vivid (clearly marked as our creative idea); 4) a minute-by-minute outline for the "
        "requested length; 5) facts to avoid or treat with care. Never invent facts, quotes or numbers."
    )
    cache = _cache_file(job, "04_research", cfg.model, system, topic_brief, max_tokens, f"search{max_searches}")
    if cache.exists():
        d = json.loads(cache.read_text())
        return Reply(d["text"], d.get("stop_reason"))
    key = config.get(SECRET_ENV)
    if not key:
        raise BudgetRefused(f"secret {SECRET_ENV} is not set")
    client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com", max_retries=2)
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
    msgs: list = [{"role": "user", "content": topic_brief}]
    counted = client.messages.count_tokens(model=cfg.model, system=system, messages=msgs, tools=tools).input_tokens
    # search results add input tokens on the continuation turns: reserve generously (3x input + output + searches)
    worst = 3 * (counted + 20000) * cfg.price_in + max_tokens * cfg.price_out + max_searches * SEARCH_USD
    if job_spent(job) + worst > cfg.per_video_cap_usd or pilot_spent() + worst > cfg.pilot_cap_usd:
        raise BudgetRefused(f"research worst case {worst:.4f} USD does not fit the caps")
    rid = uuid.uuid4().hex
    append_row(
        job,
        {
            "rid": rid,
            "stage": "04_research",
            "provider": "anthropic",
            "model": cfg.model,
            "cost_usd": round(worst, 6),
            "basis": "RESERVED worst case (web research in flight or lost)",
        },
    )
    tin = tout = searches = 0
    text, stop = "", None
    for _ in range(4):  # pause_turn continuations of the server tool loop
        with client.messages.stream(
            model=cfg.model,
            max_tokens=max_tokens,
            system=system,
            messages=msgs,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
        ) as stream:
            msg = stream.get_final_message()
        tin += msg.usage.input_tokens
        tout += msg.usage.output_tokens
        stu = getattr(msg.usage, "server_tool_use", None)
        searches += int(getattr(stu, "web_search_requests", 0) or 0)
        text = "".join(b.text for b in msg.content if b.type == "text")
        stop = msg.stop_reason
        if stop != "pause_turn":
            break
        msgs = [msgs[0], {"role": "assistant", "content": msg.content}]
    cost = tin * cfg.price_in + tout * cfg.price_out + searches * SEARCH_USD
    replace_row(
        job,
        rid,
        {
            "stage": "04_research",
            "provider": "anthropic",
            "model": cfg.model,
            "input_tokens": tin,
            "output_tokens": tout,
            "web_searches": searches,
            "cost_usd": round(cost, 6),
            "basis": "ESTIMATE (list price x usage + searches)",
            "stop_reason": stop,
        },
    )
    cache.write_text(json.dumps({"text": text, "stop_reason": stop}, ensure_ascii=False))
    if stop == "refusal":
        raise RuntimeError("model refusal at research")
    return Reply(text, stop)


def parse_json(text: str) -> dict:
    s = text.strip()
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("the reply holds no JSON object (empty text, or output cut off)")
    return json.loads(s[a : b + 1])
