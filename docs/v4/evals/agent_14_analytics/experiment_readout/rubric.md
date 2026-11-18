# Judge rubric — experiment gates

No LLM judge applies. Proposal gating, readout sufficiency and Studio-result validation contain no model call (blueprint §6), so this dataset has no subjective criteria. Every case is decided by the deterministic assertions X1–X6 in README §4; `judge_min` is `null` for every case. If a model is later used to phrase a hypothesis or a readout, that step needs its own prompt file, dataset and rubric by CCR (27 §4).
