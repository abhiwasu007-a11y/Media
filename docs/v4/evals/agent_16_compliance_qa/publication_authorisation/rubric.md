# Rubric — deterministic only

No LLM judge. Every case passes only if `verdict`, the exact `failed_guards` set, `authorised_action` and `human_wins_total` equal `expected`. A guard result `PASS` for a guard listed in `failed_guards` is a failure of the case.
