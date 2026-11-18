# Rubric — `agent_16/compliance_gate_frames.v1` evaluation judge

Integer 1–5. The judge sees the case input, the frame descriptions, the model output and the expected object. It never decides a finding or a verdict (assertions A3 and A7 are deterministic).

| Criterion | 5 | 3 | 1 |
|---|---|---|---|
| **J1 Rationale and evidence** | names what is visible and where (region, shots), cites every frame that shows it, and for a clean result says what was checked | correct finding with a generic reason ("looks fine") or frames cited only partly | wrong reasoning, frames that do not show the item, or a reason that would mislead a reviewer |

Anchors for hard negatives: a `NONE_FOUND` rationale scores 5 only when it says why the look-alike is not a mark or a presenter (listed overlay, part of the footage, no speaking role, flat icon).
