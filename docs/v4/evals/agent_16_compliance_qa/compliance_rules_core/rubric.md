# Rubric — deterministic only

No LLM judge. A case passes only if the function's result equals `expected` exactly (all fields). A result that is more permissive than `expected` is a failure of the case and, for a BLOCKED / NEEDS_HUMAN_REVIEW expectation, a false ALLOWED (mandatory zero).
