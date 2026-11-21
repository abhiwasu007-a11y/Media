"""Fast checks of the audited pipeline behaviour (no network, no paid calls). Run: pytest apps/studio/tests -q"""

import json

import numpy as np
import soundfile as sf

from studio import config, llm, pipeline


def make_job(tmp_path, monkeypatch, **meta):
    monkeypatch.setenv("AMW_STUDIO_DATA", str(tmp_path))
    job = config.jobs_dir() / "j1"
    job.mkdir()
    pipeline.wj(job / "job.json", {"id": "j1", "language": "mr", **meta})
    return job


def test_unknown_stage_is_reported_not_raised(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    assert pipeline.run(job, "no_such_stage") is False
    assert pipeline.status(job)["stages"]["queue"]["state"] == "failed"


def test_rerun_of_one_stage_reruns_everything_after_it(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(pipeline, "FUNCS", {s: (lambda j, m, s=s: calls.append(s) or "ok") for s in pipeline.STAGES})
    for s in pipeline.STAGES:
        pipeline.set_status(job, s, "done")
    pipeline.set_status(job, "06_fact_check", "failed")
    assert pipeline.run(job) is True
    assert calls == pipeline.STAGES[pipeline.STAGES.index("06_fact_check") :]


def test_failure_marks_later_stages_stale(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)

    def boom(j, m):
        raise RuntimeError("x")

    funcs = {s: (lambda j, m: "ok") for s in pipeline.STAGES}
    funcs["06_fact_check"] = boom
    monkeypatch.setattr(pipeline, "FUNCS", funcs)
    for s in pipeline.STAGES:
        pipeline.set_status(job, s, "done")
    assert pipeline.run(job, "05_script") is False
    st = pipeline.status(job)["stages"]
    assert st["manifest"]["state"] == "stale"


def test_audio_source_follows_voice_mode(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    sf.write(job / "narration_48k.wav", np.zeros(4800, np.float32), 48000)
    sf.write(job / "voice.wav", np.zeros(4800, np.float32), 48000)
    pipeline.wj(job / "voice.json", {"mode": "file"})
    assert pipeline.audio_source(job).name == "voice.wav"
    pipeline.wj(job / "voice.json", {"mode": "none"})
    assert pipeline.audio_source(job) is None


def test_recording_length_equals_timeline_total(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    scenes = [
        {"id": f"s{i:02d}", "narration": "एक दोन तीन चार. पाच सहा सात.", "beats": ["x"], "visual": "kinetic_text"}
        for i in range(1, 6)
    ]
    pipeline.wj(job / "script.json", {"scenes": scenes})
    sf.write(job / "voice.wav", np.zeros(48000 * 40, np.float32), 48000)
    pipeline.wj(job / "voice.json", {"mode": "file"})
    pipeline.s09_timeline(job, {"language": "mr"})
    assert abs(pipeline.rj(job / "timings.json")["total"] - 40.0) < 0.2
    assert (job / "captions_mr.srt").exists()


def test_identical_paid_request_is_served_from_the_saved_reply(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    monkeypatch.setenv("AMW_SECRET_ANTHROPIC_API_KEY", "")  # no key: a real call would be refused
    cfg = config.load()
    cache = llm._cache_file(job, "05_script", cfg.model, "sys", "user", 100, "medium")
    cache.write_text(json.dumps({"text": '{"ok": 1}', "stop_reason": "end_turn"}))
    r = llm.call(job, "05_script", "sys", "user", 100, "medium")
    assert llm.parse_json(r.text) == {"ok": 1}
    assert llm.ledger_rows(job) == []


def test_verified_quote_is_not_flagged_as_unverified(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch)
    q = "life, if you know how to use it, is long."
    pipeline.wj(job / "research.json", {"quote": {"text": q, "credit": "x", "verified_exact": True}})
    pipeline.wj(
        job / "script.json", {"scenes": [{"id": "s01", "narration": f'तो म्हणतो "{q}" असे.', "beats": [], "visual": "quote_card"}]}
    )
    monkeypatch.setattr(llm, "call", lambda *a, **k: llm.Reply('{"items": [], "overall": "PASS"}', "end_turn"))
    (job / "brief.md").write_text("pack")
    pipeline.s06_fact_check(job, {})
    det = pipeline.rj(job / "fact_check.json")["deterministic"]
    assert det["unverified_latin_quotes"] == []
