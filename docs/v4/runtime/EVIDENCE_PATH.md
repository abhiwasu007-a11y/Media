# Real owner-evidence path (WS-08 / ticket 3A-13; R14, D5)

Status: **built for review, not yet relied on. REQUIRES REVIEW (owner): the residual trust in section 5 before the first real run.**
Contract sources (not edited here): 08 `sys_operator` paragraph (CCR-100, CCR-113), 03 §11.6 rules 6 and 7 (CCR-059, CCR-101, CCR-116, CCR-125), 04 §3.6a / §5.16. Owner decision 2026-11-19: TEST confirmation fixtures are for the dry run only; real runs need this path.

## 1. Flow

| Step | Process and login | Code | What it can do |
|---|---|---|---|
| 1. Owner decides | the owner, on his phone | — | types `approve R7K2` / `R7K2 मंजूर` in the chat |
| 2. Record | operator (the assistant), `amw_operator` | `amw_core.owner_evidence_operator.OperatorDesk.record` | finds the message (`locate`), inserts `PENDING_VERIFICATION` evidence with the verbatim quote, returns the echo text |
| 3. Echo | operator | `owner_evidence_echo.json` (en, mr) | the assistant posts "Recorded: «quote» … reply `confirm R7K2`" / "नोंद केली: «quote» … `R7K2 पक्के`" |
| 4. Verify | verifier, `amw_verifier` | `amw_core.owner_evidence_real.VerifierWorker.verify` | fetches the event itself from the session record, runs 03 rule 7, calls `amw_evidence_mark_verified` (the database stamps the MAC) or `amw_evidence_refuse` |
| 5. Confirm | verifier | `VerifierWorker.confirm_from_chat` | finds the owner's reply itself (step 5 rules below) |
| 6. Apply | operator, `amw_operator` | `PgEvidenceDatabase.human_record_apply` | the database writes the one human row, only for `CONFIRMED` with a valid MAC |

**Step 5 rules.**
1. **Latest decision wins (fail closed).** Before reading replies, the verifier looks at the other evidence rows of the same subject that carry the same code.
   - For a decision row, any other decision row on that code, approval and step whose owner message is as late or later supersedes it. This holds in any state, so a later reject that was itself refused still counts, and a tie supersedes both. The older row is refused (`superseded_by_later_decision`) and never confirmed. Only the latest decision on a code can be confirmed (PROPOSED CCR-264).
   - `amw_evidence_mark_confirmed` (0059) applies the same rule in the database, whatever the worker read.
   - A decision row that was already CONFIRMED before a newer decision was recorded is reported unbound by `ConfirmedEvidenceLookup` (`kind` / `subject` None), so a preflight cannot use it.
   - Residual race (ticket, REQUIRES REVIEW): a newer decision inserted in a transaction that commits after the confirmation is not seen by that confirmation. The consumer check above makes the older row unusable afterwards; applying the human row is a separate operator step, and the approval accepts only one decision per step. For a content or score row, a second open row on the same code makes a `confirm` ambiguous (`AMBIGUOUS`), and nothing is confirmed.
2. **The echo comes first.** The verifier finds the first assistant message of the same session, after the recorded message, that shows the row's code and the start of its quote.
3. **Replies in time order.** It then reads, in time order, the owner messages that name the code. It skips the row's own message, the recorded messages of the sibling rows, and messages stamped after "now".

| Owner message | Before the echo | After the echo |
|---|---|---|
| exactly `confirm R7K2` or `R7K2 पक्के` (ASCII letters and digits or the exact Devanagari word, one plain space, no compatibility folding, so fullwidth letters, NBSP and em space are refused; one optional final `.` / `!` / `।`) | ignored | `CONFIRMED` |
| exactly `approve R7K2` or `R7K2 मंजूर`, for an APPROVED row only (PROPOSED CCR-264; these four forms and nothing else) | ignored | `CONFIRMED` |
| a question or deferral naming the code | skipped; result `NEEDS_CLARIFICATION` if nothing confirms; the row stays `VERIFIED` | same |
| anything else naming the code (`yes R7K2`, `confirm R7K2_`, `approve R7K2 please`, a dispute, a correction, the other decision) | `amw_evidence_refuse`: the row becomes `REFUSED` (`owner_disputed`, earlier checks kept); the owner restates and a new row is recorded | same |

Possible outcomes:
- A confirmation-shaped reply that fails the authenticity check (for example pasted text) is reported as `REFUSED_CHECK`, and the scan goes on.
- With no echo there is no confirmation (`AWAITING_ECHO`).
- The operator never passes a verification result, an anchor time or a confirmation event.

**TEST rows (migration 0059, PROPOSED CCR-265).**
- Every `verifier_result` written through `build_verifier_service` carries `session_source_production` (REAL) or `session_source_test_fixture` (DRY_RUN). The mark is covered by the MAC.
- The database fixes the mark at verification. `amw_evidence_mark_confirmed` and `amw_evidence_refuse` merge the new result into the stored one, and the stored mark always wins, so a TEST row confirmed by a real worker stays TEST.
- A one-row table `evidence_db_profile` (REAL by default; only the table owner can change it) decides which mark a database accepts: a TEST mark only in a TEST database, a production mark only in a REAL one.
- The DRY_RUN path refuses any session source but the in-memory one, and any database whose profile is not TEST. For PostgreSQL it reads the profile row inside the transaction it is given; without one it refuses. A dry run can never write into the real database.
- `ConfirmedEvidenceLookup` reports `source_kind = TEST_FIXTURE` for a row without the production mark.
- These marks still do not stop a holder of the verifier login of a REAL database, who can write a production mark for fabricated events (section 5, item 2).

## 2. The session record: what is read, and how a message is accepted

Source: `amw_adapters.session_record.ClaudeSessionJsonlSource`.
- It reads `<transcript_root>/<session_id>.jsonl`, the Claude Code session transcript (one JSON record per line), read-only, per call, and does not open sub-agent files.
- The root is resolved first. The file is opened with `O_NOFOLLOW` and checked as a regular file on the open descriptor (no check-then-open race).

**File content never raises.**
- A final line without its newline (the CLI is mid-write, for example cut inside a Devanagari character) is ignored until the next read.
- Any other line that is not valid UTF-8 JSON, or repeats a JSON key, is corrupt and is never a message.
- An event whose UUID occurs in a corrupt line is refused as `corrupt_record`.

The schema below was observed on the session runtime on 2026-11-19 from field names and marker values only. No message text was read or kept.

| Record | Distinguishing structure | Result |
|---|---|---|
| owner chat message | `type:"user"`, `message.role:"user"`, `origin` exactly `{"kind":"human"}`, `turnOrigin:"human"`, `isSidechain:false`, string (or text-block) content, only known keys | **accepted** |
| owner message typed while the assistant is busy | `type:"attachment"`, `attachment.type:"queued_command"`, `attachment.commandMode:"prompt"`, `attachment.humanTurn:true`, `attachment.origin` exactly `{"kind":"human"}`, no `isMeta`, `isSidechain:false`, only known record and attachment keys, text in `attachment.prompt` | **accepted** |
| tool result | `toolUseResult`, `sourceToolAssistantUUID`, `tool_result` content block | refused |
| sub-agent hand-back / peer message | `origin.kind:"peer"` (`handback`, `handbackReportText`, …), `isMeta:true`; queued form with `attachment.origin.kind:"peer"` | refused |
| task notification | `origin.kind:"task-notification"`, direct or queued | refused |
| system reminder, other injected text | `isMeta:true`, no `origin` | refused |
| compact summary | `isCompactSummary`, `isVisibleInTranscriptOnly` | refused |
| sub-agent transcript record | `isSidechain:true`, `agentId` | refused |
| queue operation, other attachments, mode, cost and other records | another `type` or `attachment.type` | refused |
| the assistant's own message | `type:"assistant"` | refused (read only to find the echo) |
| pasted or attached content | `pastedContents`, `imagePasteIds`, a non-text block, or the queued keys `fileAttachments` / `imageFileUuids` / `inlinedImage*` / `savedFiles` | marked as embedding content: the verifier refuses it as `embedded_part_unmarked` (CCR-125) and the owner restates |
| an unknown key, an extra `origin` field, a duplicate UUID or JSON key, another `sessionId`, a bad timestamp | — | refused (fail closed) |

The check reads structure, never text. A text test can only add a refusal: a message that contains a harness wrapper tag in any letter case (`<system-reminder>`, `<task-notification>`, `<agent-message …>`, …) is refused. A refused record reaches the verifier as an event that fails role / `is_synthetic` / `inbound_origin` (`refused:<reason>`) and carries no text.

**What the transcript does not show** (configured, not observed):
- **Account.** No record names an account. `sender_account` is the configured `owner_account_id` of the session.
- **Top level.** No record says whether a cloud session is a child session. A session counts as top level only if its ID is in `top_level_session_ids`, set by the owner.
- **Authenticity of any line.** There is no signature, MAC or hash chain in the file. Fields the platform sets on every human record (`parentUuid`, `promptId`, `turnPosition`, …) can be copied, so requiring them would add nothing against a forger.
- **Schema stability.** After a CLI upgrade, a new field refuses every message until the allow-lists are reviewed (fail closed).
- **Messages the assistant schedules for itself** (send-later reminders, scheduled tasks): their record shape was never observed. REQUIRES REVIEW: whether they carry `origin: human` (part of residual trust item 1).
- **Size.** A transcript over 256 MB (`max_file_bytes`) is not read at all, so nothing in it verifies. The live transcript observed was 15 MB.

## 3. Database part (`amw_core.owner_evidence_pg.PgEvidenceDatabase`)

- Every call reads `session_user` of the tenant transaction's connection and refuses unless it is the role the caller names.
- Every read filters `org_id = amw_current_org()` explicitly, on top of RLS.
- `evidence_db_profile` (0059) is a GLOBAL one-row table. It is added to the global allow-list of the tenancy suite (CCR-265 asks for the 04 section 4 entry).
- State changes and the MAC happen only in the `amw_verifier_fn` definer functions (migration 0009), which check `session_user` themselves.
- The Python code computes no MAC and holds no key. The MAC key is loaded once by the migrator from the environment's secret mechanism.
- Secret NAMES (proposed; REQUIRES REVIEW, owner):
  - `AMW_SECRETS__OPERATOR_DATABASE_URL`;
  - `AMW_SECRETS__VERIFIER_DATABASE_URL`;
  - the MAC key, read by the migrator at setup only.
- The database binds nothing about the confirmation event. Whoever holds the verifier login can call `amw_evidence_mark_confirmed` with any event identifier (independent review, 2026-11-19). The placement of the verifier login is the whole database-side control.

## 4. What this stops

1. **Text that is not an owner chat message becomes an approval or a confirmation.** This covers tool results, sub-agent hand-backs, peer messages, task notifications, system reminders, compact summaries, documents and the assistant's own messages, even when the text is exactly `approve R7K2` or `confirm R7K2`.
2. **The operator login verifies, confirms or writes verification columns.** The database refuses it.
3. **The operator names a confirmation.** The verifier finds the reply itself.
4. **Rule failures.** All of these are refused: replay, wrong code, negation or condition, a message older than the request, another org's owner account, another tenant's row, a superseded decision, and a TEST (dry-run) row presented to a real run.
5. **A superuser edit of a verified row.** It is detected, not prevented (08 honest limit).

These hold against a **confused or injected** assistant, meaning one that misreads where a text came from. They do not hold against a **malicious** assistant with a shell; section 5 lists what remains.

## 5. Residual trust (REQUIRES REVIEW, owner)

1. **Forged or edited owner lines.** In one container, the assistant can forge or edit the owner's chat lines in the local transcript file. The file is mode 0600 for the same OS user that runs the assistant. The independent review demonstrated both:
   - a 7-key forged line is accepted as an owner message;
   - a forged `confirm` line yields `CONFIRMED`.

   Nothing in the file can be checked: there is no signature and no hash chain.
2. **Readable credentials.** Any credential stored in this container, including the verifier DSN, is readable by the assistant. With it, the definer functions can be called directly (section 3).
3. **Assistant-posted output.** Every echo or audit list the owner sees here is posted by the assistant itself. `OperatorDesk.record` returns the echo text, and the same assistant decides whether to post it and what it says.
   - The echo is an **owner-visible disclosure, not an independent control**: a forging assistant can post no echo, or a misleading one.
   - The echo condition of step 5 only makes a confirmation depend on an assistant message in the same file, which the same assistant can forge.
4. **What would close this.** Only a separate verifier host closes this, and it cannot be built here. That host would hold its own platform-API credential and the verifier DSN (CCR-113), fetch each event from the platform's server-side event store, and report to the owner through its own channel (email or push from that host).
   - Not verified: whether the server-side store marks human events in a way the container's own ingress credential cannot reproduce (REQUIRES REVIEW, Phase 1).
   - The server-side event fields observed by the independent review are `client_platform`, `server_received_wall_ms` and `trace_context` on owner messages, and `isReplay` / `isSynthetic` / `origin` on hand-backs. No `inbound_origin` field was observed.
5. **Until then: the owner's own check.** The owner compares the approval lists he is shown with his own app history. That history is held by the platform server, not by the container. A record he never made shows up as a difference.
   - Limit: a list the assistant posts can omit rows.
   - Proposed, not built: a periodic verifier-role audit post of all VERIFIED / CONFIRMED rows (code, quote, time), and a run preflight that requires such a post after the last confirmation.

## 6. The shared evidence contract and the run preflight

**The contract** (`amw_core.owner_evidence_status`; integrator decision for PR #77 + #70). One `EvidenceStatus` dataclass and one `EvidenceStatusLookup` Protocol, imported by `amw_runtime`; it defines no copy of its own.

| Field | Meaning |
|---|---|
| `evidence_id`, `org_id` | the row and its tenant |
| `evidence_state` | the row's state |
| `recorded_from` | `OWNER_CHAT_OPERATOR`, or the source kind |
| `kind` | the bound confirmation kind, or `None` |
| `subject_kind`, `subject_id` | the row's own subject |
| `subject` | the bound key `kind\|provider\|amount_minor\|currency\|org`, or `None` |
| `source_kind` | `REAL` or `TEST_FIXTURE` |
| `mac_valid` | from the database function |

`kind` and `subject` are set only when all of these hold:
- the MAC is valid;
- the row carries the production mark;
- it belongs to the binding's org;
- its record kind is allowed;
- its quote states the provider, the amount (in major units) and the currency, or the FIN-R10 statement.

So a consumer that compares `subject` can never accept a TEST, tampered or unbound row. `ConfirmedEvidenceLookup.for_confirmations(...)` builds the bindings from the run's own confirmation records, and one evidence row may back one confirmation only.

**Run preflight** (PR #70 head `e42dbd1`): it checks state, channel, org and `subject`, refuses TEST fixtures, and now looks FIN-R10 evidence up as well.
- Verified on a local merge of both PRs: the runtime suite and this lane's preflight tests pass (136 tests across `tests/runtime` and the two lane files).

**Open gaps**
- No record kind exists for these owner statements yet, so by default no kind is allowed (fail closed; CCR-260).
- The CONTENT rules refuse negation, so "not SEBI-registered" cannot pass them today (CCR-260).

## 7. Tests

| File | What it covers |
|---|---|
| `tests/adapters/test_session_record_jsonl.py` | every refused record kind (31 variants, including queued peer, task-notification, meta, other-mode, extra-key and mixed-case wrapper forms); queued owner messages accepted; paste and attachment markers; a cut multibyte last line; an invalid byte and a duplicate key (no exception; `corrupt_record`); duplicate UUID; session mismatch; bad timestamp; path traversal; symlinked file vs resolved root; size cap; top level |
| `tests/adapters/test_session_record_flow.py` | the flow on the database model; non-owner sources refused; forged confirmations ignored; exactly the four reply forms; latest decision wins (approve, reject, confirm and the reverse; a refused later reject; a tie; the store guard; a confirmed decision made unusable by a newer one); no compatibility folding (fullwidth, NBSP, em space); content rows ambiguous on a shared code; reply before the echo; echo without the quote; question then confirm; dispute refuses the row; time order, not file order; future messages; replay; other org; TEST marks; dry-run factory guards; preflight bindings (provider, amount, currency, kind, one row per confirmation) |
| `tests/adapters/test_session_record_preflight.py` | the preflight of PR #70 against real-path evidence: pass with bound evidence for both limits and FIN-R10; refused for pending rows, another org, reused rows, TEST fixtures and FIN-R10 without evidence (skipped until `amw_runtime` is merged; verified on a local merge with `e42dbd1`) |
| `tests/core_services_db/test_owner_evidence_real_path_pg.py` | PostgreSQL with real logins: the database refuses to confirm a superseded decision (0059 guard); record, verify, confirm, apply; the operator login cannot verify; forged columns refused; replay; other tenant; a superuser tamper detected; a dispute refused through `amw_evidence_refuse`; own code round trip; fabricated events plus the REAL database refused (factory and database); a TEST row confirmed by a REAL service stays TEST and the lookup refuses it; a production mark refused in a TEST database |

All transcripts in tests are synthetic. They copy the real structure and contain no real conversation.
