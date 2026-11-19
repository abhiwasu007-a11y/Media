# Real owner-evidence path (WS-08 / ticket 3A-13; R14, D5)

Status: **built for review, not yet relied on. REQUIRES REVIEW (owner): the residual risks in section 5 before the first real run.**
Contract sources (not edited here): 08 `sys_operator` paragraph (CCR-100, CCR-113), 03 §11.6 rules 6 and 7 (CCR-059, CCR-101, CCR-116, CCR-125), 04 §3.6a / §5.16. Owner decision 2026-11-19: TEST confirmation fixtures are for the dry run only; real runs need this path.

## 1. Flow

| Step | Process and login | Code | What it can do |
|---|---|---|---|
| 1. Owner types a decision in the chat (`approve R7K2` / `R7K2 मंजूर`) | the owner, on his phone | — | — |
| 2. Record | operator (the assistant), `amw_operator` | `amw_core.owner_evidence_operator.OperatorDesk.record` | finds the message (`locate`), inserts `PENDING_VERIFICATION` evidence with the verbatim quote, posts the echo |
| 3. Echo | operator | `owner_evidence_echo.json` (en, mr) | "Recorded: «quote». Reply `confirm R7K2`" / "नोंद केली: «quote» … `R7K2 पक्के`" |
| 4. Verify | verifier, `amw_verifier` | `amw_core.owner_evidence_real.VerifierWorker.verify` | fetches the event itself from the session record, runs 03 rule 7, calls `amw_evidence_mark_verified` (the database stamps the MAC) or `amw_evidence_refuse` |
| 5. Confirm | verifier | `VerifierWorker.confirm_from_chat` | searches the record's own session for the owner's reply. The first later owner message that names the code decides: a confirmation means `CONFIRMED`; anything else (a dispute, a correction) means the row stays `VERIFIED` (`DISPUTED`) and the operator asks again |
| 6. Apply | operator, `amw_operator` | `PgEvidenceDatabase.human_record_apply` | the database writes the one human row, only for `CONFIRMED` with a valid MAC |

The operator never passes a verification result, the anchor time or the confirmation event. The verifier finds all three itself.

`EvidenceMode.REAL` refuses a session source that is not marked `production_grade`. The in-memory fake is reachable only through `dry_run_verifier_service`, and rows verified with it are TEST fixtures. This mark guards against wiring mistakes only: it is not a security boundary.

## 2. The session record: what is read, and how a message is accepted

Source: `amw_adapters.session_record.ClaudeSessionJsonlSource`. It reads `<transcript_root>/<session_id>.jsonl`, the Claude Code session transcript (one JSON record per line), read-only and per call. It does not follow symlinks and does not open sub-agent files.

The schema below was observed on the session runtime on 2026-11-19 by reading field names and marker values only. No message text was read or kept.

| Record | Distinguishing structure | Result |
|---|---|---|
| owner chat message | `type:"user"`, `message.role:"user"`, `origin` exactly `{"kind":"human"}`, `turnOrigin:"human"`, `isSidechain:false`, string (or text-block) content, only known keys | **accepted** |
| tool result | `toolUseResult`, `sourceToolAssistantUUID`, `tool_result` content block | refused |
| sub-agent hand-back / peer message | `origin.kind:"peer"` (`handback`, `handbackReportText`, …), `isMeta:true` | refused |
| task notification | `origin.kind:"task-notification"` | refused |
| system reminder, other injected text | `isMeta:true`, no `origin` | refused |
| compact summary | `isCompactSummary`, `isVisibleInTranscriptOnly` | refused |
| sub-agent transcript record | `isSidechain:true`, `agentId` | refused |
| queue operation, attachment, mode, cost and other records | `type` is not `user` | refused |
| the assistant's own message | `type:"assistant"` | refused |
| pasted or attached content | `pastedContents`, `imagePasteIds`, or a non-text block | marked as embedding content: the verifier refuses it as `embedded_part_unmarked` (CCR-125), and the owner restates |
| any record with an unknown key, an extra `origin` field, a duplicate UUID, another `sessionId`, or a bad timestamp | — | refused (fail closed) |

The check reads structure, never text. A text test can only add a refusal: a message that contains a harness wrapper tag (`<system-reminder>`, `<task-notification>`, `<agent-message …>`, …) is refused. A refused record reaches the verifier as an event that fails role / `is_synthetic` / `inbound_origin` (`refused:<reason>`) and carries no text, so the evidence row becomes `REFUSED` instead of staying pending.

Event fields: `event_uuid` is the record `uuid`. `timestamp` is the record `timestamp` (UTC, millisecond precision). `OwnerChatEvent.content_sha256` is the SHA-256 of the UTF-8 text.

**What the transcript does not show (configured, not observed):**
- **Account.** No record names an account. `sender_account` is the configured `owner_account_id` of the session. Anyone who types into the owner's session counts as the owner.
- **Top level.** No record says whether a cloud session is a child session (one created by another session, whose first prompt is that session's text). A session counts as top level only if its ID is in `top_level_session_ids`, which the owner sets; any other session is refused by test A5.
- **Which part was pasted.** Only the paste markers above are visible.
- **Schema stability.** The allow-list matches the observed CLI version. After a CLI upgrade, a new field refuses every message until `allowed_keys` is reviewed (fail closed).

## 3. Database part (`amw_core.owner_evidence_pg.PgEvidenceDatabase`)

- Every call reads `session_user` of the tenant transaction's connection and refuses unless it is the role the caller names. The operator process holds only the `amw_operator` DSN.
- State changes and the MAC happen only in the `amw_verifier_fn` definer functions (migration 0009), which check `session_user = 'amw_verifier'` themselves. The Python code computes no MAC and holds no key.
- The MAC key is loaded once by the migrator (`amw_core.tenancy.evidence_keys`) from the environment's secret mechanism, and no role can read it.
- Secret NAMES (values never printed or committed). REQUIRES REVIEW (owner): confirm these proposed names:
  - `AMW_SECRETS__OPERATOR_DATABASE_URL`, held by the operator process;
  - `AMW_SECRETS__VERIFIER_DATABASE_URL`, held by the verifier process only;
  - the MAC key, read by the migrator at setup only.
- An own review code for CONTENT / SCORE evidence without an approval (CCR-116) is issued at insert and registered by the 0055 trigger.

## 4. What this stops

1. **Text that is not the owner's chat message becomes an approval.** This covers tool results, sub-agent hand-backs, peer messages, task notifications, system reminders, compact summaries, documents and the assistant's own messages, even when the text is exactly `approve R7K2` or `confirm R7K2`. They are refused by structure.
2. **The operator marks its own record verified or confirmed.** Its login can only insert pending or refused rows; the database refuses verification columns, and the functions refuse any other login.
3. **The operator names a confirmation.** The verifier finds the reply itself; a forged confirmation from any non-owner record is never seen.
4. **Replay** (one message backs one row; a confirmation can never be a record), wrong code, negation or condition (`needs_clarification`), a message older than the request, another org's owner account, or another tenant's row.
5. **A database edit after verification by a superuser.** It is detected (the MAC no longer verifies), not prevented (08 honest limit).

## 5. What a malicious or confused assistant with shell access can still do (residual risks)

The assistant runs as the same operating-system user as the Claude Code process that writes the transcript. The file is mode 0600 for that user, so **file permissions do not protect it from the assistant.**

| # | Attack | Stopped? | Notes |
|---|---|---|---|
| R1 | Append a forged record with `origin:{"kind":"human"}` and a new UUID to the transcript (`approve R7K2`, later `confirm R7K2`) | **No**, by this source | A well-formed forged line cannot be told apart by structure. A duplicate UUID is caught; a new one is not. |
| R2 | Edit an owner message already in the file (e.g. `reject` to `approve`) before the verifier reads it | **No** | Same cause as R1. |
| R3 | Read the verifier DSN or the MAC key when they are in the same environment, then call the definer functions directly | **No**, if the secrets are present there | CCR-113 needs the verifier to run where the assistant cannot read. One shared container does not meet that. |
| R4 | Run a modified copy of the verifier code, or change the allow-list in a branch | Partly | Code changes go through a PR the owner merges. A local run with the verifier login is R3. |
| R5 | Use a superuser or migrator credential | **No** | 08 honest limit. The MAC and the audit chain detect the change afterwards. |

**Mitigations that exist now:**
- **Owner-visible echo with the review code.** Every record produces a chat message the owner sees on his phone: the verbatim quote, the code and the exact reply. A record he did not make, or a quote he did not write, is visible to him, and nothing is applied before a `confirm` reply.
  - If he disputes before any confirmation appears, the row stays `VERIFIED` (`DISPUTED`).
  - If a forged confirmation is already in the file (R1), his dispute does not undo it automatically. The operator must stop and the owner reverses it.
  - REQUIRES REVIEW: whether a line added to the local transcript also shows in the owner's app. This was not tested in this lane. If it does not show, the owner sees an echo for a message he never sent.
- MAC re-verification and the audit hash chain (database tampering only).
- Separate logins and roles (stops a confused operator, not a hostile one with R3 access).

**Mitigations not built (REQUIRES REVIEW, owner decision needed):**
- **Platform event store as the source.** The verifier would read the owner's messages from the session platform's own event record (the session API reports role, `isSynthetic` and `inbound_origin` per event), from a process outside the assistant's container, with a credential the assistant does not hold. This is the only option found that closes R1 and R2. It needs a verifier host outside the session and an API credential for it. Not built: no such credential or host exists in this environment.
- **Pinning or a hash chain.** A verifier streaming the transcript out of band (separate user or host) would pin each record's SHA-256 when first seen. Later edits of seen lines (R2) are then detected; a line forged before the next read (R1) still is not.
- **Running the verifier as a separate OS user or on another host, with its DSN only there.** This closes R3, not R1 or R2.

**Honest summary.** On one machine where the assistant has a shell, this path stops accidental and injected approvals (tool, sub-agent, notification, document and self-generated text) and any operator-side forgery through the database. It does **not** stop a deliberately malicious assistant from forging transcript lines. Against that, the owner's reading of the echo is the only control in place.

## 6. Dry-run TEST path

- `dry_run_verifier_service(..., MemorySessionEventSource, ...)` is the only constructor that accepts the in-memory source.
- `build_verifier_service(EvidenceMode.REAL, ...)` refuses it.
- The run preflight (`amw_runtime`, PR #70) refuses a `test_fixture` provider-limit confirmation in real-run mode. `ConfirmedEvidenceLookup` reports `CONFIRMED` only for a MAC-valid owner-chat row.
- Open gap: FIN-R10 is cleared by a self-asserted record (CCR-261). There is a strict-xfail test for it.

## 7. Tests

| File | What it covers |
|---|---|
| `tests/adapters/test_session_record_jsonl.py` | every refused record kind (19 variants), paste and image markers, duplicate UUID, session mismatch, bad timestamp, path traversal, symlink, size cap, top-level configuration |
| `tests/adapters/test_session_record_flow.py` | the end-to-end flow on the database model (en and mr grammar); `approve R7K2` from a hand-back, tool result or assistant message refused; forged confirmations ignored; wrong code, negation, condition, mismatch, pasted text, replay, order, dispute, other org; operator refusal audited; real-mode guards; echo replies pass the confirmation whitelist |
| `tests/adapters/test_session_record_preflight.py` | the preflight against real-path evidence (skipped until `amw_runtime` is merged) |
| `tests/core_services_db/test_owner_evidence_real_path_pg.py` | PostgreSQL with real logins: record, verify, confirm, apply; the operator login cannot verify; the DB refuses forged columns; replay; other tenant; a superuser tamper detected; own code round trip |

All transcripts in tests are synthetic: they copy the real structure and contain no real conversation.
