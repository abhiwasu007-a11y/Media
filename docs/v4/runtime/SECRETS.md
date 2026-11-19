# Runtime secrets (names only)

Values never appear in git, logs, docs, chat, issues or PR text (08 section 3.1). The runtime reads **names** from the process environment and checks presence; it never prints a value, a length or a prefix. A secret is injected only into the process that needs it (the adapter process), never into a shared or global variable.

| Secret name | Provider (research log) | Role | Needed in |
|---|---|---|---|
| `AMW_SECRET_ANTHROPIC_API_KEY` | Anthropic (PR-01) | LLM | real run |
| `AMW_SECRET_ELEVENLABS_API_KEY` | ElevenLabs (PR-04) | TTS (Marathi supported, PR-04) | real run |
| none | stock footage | not used in 3A: only if the owner buys a licence (ADR-009, 3A_SLICE_SPEC section 3); no provider chosen. **REQUIRES REVIEW (owner): provider and licence if stock is wanted; then add `AMW_SECRET_<PROVIDER>_API_KEY` to `data/runtime_config.json`.** | not required |

Name rule: `AMW_SECRET_<PROVIDER>_API_KEY` (checked by `amw_runtime.config`). The list lives in `packages/amw_runtime/src/amw_runtime/data/runtime_config.json` (`providers`).

## How the owner adds a secret
1. Open the Claude Code environment settings used for these sessions and use the environment's secret / credential form (the "credentials" or "network secrets" form).
2. Create the entry for the provider host with the exact name from the table, and paste the key **into that form only**.
3. Never paste a key into the chat, a file, an issue or a PR. If a key was ever pasted anywhere else, revoke it at the provider and create a new one.
4. Dry runs do not need any key (the secret check is skipped and the report says so).

Also required before a real run: the spending limit set at each provider and confirmed by the owner in the owner chat (see README).
