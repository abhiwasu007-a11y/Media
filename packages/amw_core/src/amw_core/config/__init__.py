"""Typed configuration (27 section 7.3 rule 1; 08 section 3; 18 section 13 key registry).

* Models, providers, limits, thresholds and windows are configuration, never literals in code.
* Only this package reads the process environment; no other package calls ``os.environ``.
* Secrets reach a process only through the environment's secret mechanism (an environment value or
  a mounted secret file, 08 section 3.1 rule 1). They never have defaults and they are never read
  from a non-secret config file. ``require_secrets`` is the startup check of 08 section 3.1 rule 7.
* Numeric defaults below are the design defaults (ESTIMATE) of 07 sections 3.3, 4.2, 6 and 9; values
  the documents leave to the owner (budgets, eval caps, FX, thresholds marked REQUIRES REVIEW) have
  no default and stay ``None`` until set.
"""

from amw_core.config.registry import SHARED_NAMESPACES, ConfigKeyRegistry
from amw_core.config.settings import (
    DEFAULT_NON_FINANCE_CATEGORIES,
    DOCUMENTED_RULE_PACK_CATEGORIES,
    AmwSettings,
    BreakerSettings,
    CapsSettings,
    DatabaseSettings,
    DlqSettings,
    EvalSettings,
    FinanceSettings,
    LimitsSettings,
    LlmSettings,
    LlmTaskSettings,
    LlmTierSettings,
    ReaperSettings,
    RetryPolicySettings,
    RulePackSettings,
    StorageSettings,
    WaitSettings,
    WindowSettings,
    load_settings,
    require_secrets,
)

__all__ = [
    "DEFAULT_NON_FINANCE_CATEGORIES",
    "DOCUMENTED_RULE_PACK_CATEGORIES",
    "SHARED_NAMESPACES",
    "AmwSettings",
    "BreakerSettings",
    "CapsSettings",
    "ConfigKeyRegistry",
    "DatabaseSettings",
    "DlqSettings",
    "EvalSettings",
    "FinanceSettings",
    "LimitsSettings",
    "LlmSettings",
    "LlmTaskSettings",
    "LlmTierSettings",
    "ReaperSettings",
    "RetryPolicySettings",
    "RulePackSettings",
    "StorageSettings",
    "WaitSettings",
    "WindowSettings",
    "load_settings",
    "require_secrets",
]
