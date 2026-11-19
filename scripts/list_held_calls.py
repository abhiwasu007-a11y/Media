"""List the unreconciled held calls of one job (docs/v4/runtime/PROVIDERS.md section 5).

Read-only. The database connection string is read from the environment variable named by
``--dsn-env`` (default ``AMW_DATABASE_URL``), never from the command line. No key, no network.
"""

import sys

from amw_adapters.real.holds import list_main

if __name__ == "__main__":
    sys.exit(list_main())
