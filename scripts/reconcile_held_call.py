"""Reconcile one held call with the provider's own usage figure (PROVIDERS.md section 5).

Dry run unless ``--apply``. Appends a VERIFIED ledger row; nothing is updated or deleted. The
database connection string is read from the environment variable named by ``--dsn-env``.
"""

import sys

from amw_adapters.real.holds import reconcile_main

if __name__ == "__main__":
    sys.exit(reconcile_main())
