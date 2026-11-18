# Rubric — `agent_10.deterministic_core`

| Field | Value |
|---|---|
| Status | Draft — documentation. Software: **Planned** |
| Owner | Agent 10 |
| Judge | **none**: this dataset has no LLM step and no judge. Every case is decided by the exact-equality assertions T1–T6 of README §4. |

The owner's look-and-feel scores of the golden-sample pilot (18 §9.2 human rows for audio, editing and visual quality) and the owner's listening and viewing of the evidence pack are recorded in the pilot evidence package, not here; they calibrate the config values that the cases set explicitly (README §6).
The LLM-judged checks that 18 attaches to the render stage (`qc.watermark.visual`, `qc.visual.no_synthetic_presenter`) run in Agent 16 on Agent 10's frame evidence (blueprint §5); their datasets belong to Agent 16.
