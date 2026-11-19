"""Real-run readiness for the 3A skeleton (lane S4): config, preflight, market calendar, chart-data
policy and the FIN-R10 disclaimer. Nothing here calls a provider, a network or a database.

Rules: secrets are read by NAME only and never logged or returned; every check fails closed; the
owner-set values (caps, lag, topics) are data files, never code constants (docs/v4/runtime/).
"""
