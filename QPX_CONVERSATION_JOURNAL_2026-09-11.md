# QPX Conversation Journal — 2026-09-11

## 2026-09-11 11:17 CDT — Corporate-action identity repair

- **USER_REQUIREMENT:** Fix the obsolete historical corporate-action
  mandatory-primary-symbol gate, correct qualification boundedness, apply the
  current Alpaca request contract, strengthen existing rule application, run
  only directly affected tests, preserve all completed bars, resume the existing
  service, push only the review branch, and do not start training.
- **VERIFIED_REPO:** Starting review-branch/upstream HEAD was
  `e0371a70b06328df5edcbd1b423048ca9b57de6b`. Implementation commit is
  `b184d18423fcb842800faeae758a6a46ac591c3f`.
- **VERIFIED_ARTIFACT:** Pre-fix runtime contained 7,370/7,370 bar partitions,
  383,082,447 rows, zero pending partitions/finalizations, manifest integrity
  true, and failed corporate-action stage with
  `ValueError: Corporate action requires authoritative id and symbol.`
- **UNKNOWN / UNRECOVERED:** Exact raw failing provider event.
- **VERIFIED_REPO:** Normalization now requires provider event ID while treating
  `symbol`, `old_symbol`, and `new_symbol` as independent optional canonical
  evidence. The stable-ID resolver remains authoritative and never guesses.
  Qualification requires both security candidates and bounded dates for a
  bounded unresolved exclusion.
- **VERIFIED_REPO:** Corporate-action schema/semantic identity advanced to
  3/`ALPACA_CORPORATE_ACTIONS_HISTORICAL_V3`; requests bind US/complete and
  include capital-gains distributions. Bar acquisition versions are unchanged.
- **VERIFIED_ARTIFACT:** 116 directly affected acquisition/qualification tests
  passed; production modules compiled; diff check passed.
- **VERIFIED_ARTIFACT:** Service resumed with PID 451384, made successful real
  corporate-action requests under governed live coexistence without any bar
  redownload, and later yielded at the protected Clean-V2 decision window.
  Corporate-action status was still `PENDING` at this checkpoint.
- **NEXT EXACT ACTION:** Verify the already-running corporate-action stage's
  atomic completion and identity counts, then continue the governed calendar
  repair/independent qualification sequence. Training remains unauthorized.

## 2026-09-11 — Clock-only decision-window capacity correction

- **USER_CORRECTION:** `CLEAN_V2_DECISION_WINDOW` awareness must not by itself
  block historical requests. Clean-V2 receives actual needed capacity; healthy
  historical work may consume the remainder at the existing low live rate.
- **VERIFIED_REPO:** The unconditional `PROTECTED_DECISION_WINDOW` return was
  removed. Decision-window timing remains telemetry while existing provider,
  host-resource, live-latency/degradation, 429, and safety-latch decisions remain
  authoritative.
- **VERIFIED_ARTIFACT:** `tests.test_ml_historical_acquisition` passed 104/104;
  the changed module compiled and `git diff --check` passed.
- **NEXT EXACT ACTION:** Commit/push only the review branch, restart the existing
  acquisition service through systemd to load the correction, verify bars remain
  7,370/7,370 and 383,082,447 rows, and allow corporate actions to continue.

### Runtime result

- **VERIFIED_REPO:** Capacity correction commit
  `a864b1048ee826c8ee127f457b72aac3012dbcbf` was pushed to the review branch.
- **VERIFIED_ARTIFACT:** The restarted service loaded the correction and reported
  `LIVE_COEXISTENCE`; it did not remain blocked for
  `CLEAN_V2_DECISION_WINDOW`. Bar evidence remained 7,370/7,370 and 383,082,447
  rows.
- **VERIFIED_ARTIFACT:** Alpaca corporate-action requests then received repeated
  HTTP 504 `backend request timeout`, exhausted existing bounded retries, and
  entered the configured systemd auto-restart path. Corporate actions remain
  `PENDING`; no training started.
- **NEXT EXACT ACTION:** Let the existing retry path continue when provider
  service recovers; validate final CA artifacts/identity counts before the
  governed calendar-repair and independent-qualification steps.

## 2026-09-11 — Durable corporate-action pagination recovery

- **USER_REQUIREMENT:** Restore the existing persistence rule: a successfully
  validated corporate-action page is durable state and must survive transient
  provider failure, process exit, and service restart without reacquisition.
- **VERIFIED_REPO:** Commit `8ec5ed3` adds atomic deterministic staged page
  evidence and a checksummed pagination checkpoint bound to the exact request,
  semantic/schema identities, page sequence, tokens, integrity, and provider
  event IDs. Restart validates and reconstructs from persisted evidence before
  requesting only the first unfinished page. Terminal artifacts remain the
  products of complete validated pagination.
- **VERIFIED_ARTIFACT:** `python3 -m unittest
  tests.test_ml_historical_acquisition tests.test_ml_historical_qualification`
  passed 123/123. `qpx_bot/ml_historical_acquisition.py` compiled and
  `git diff --check` passed.
- **VERIFIED_ARTIFACT:** The existing systemd service loaded the new commit.
  The completed reservoir remains 7,370/7,370 partitions and 383,082,447 rows;
  training remains unauthorized.
- **VERIFIED_ARTIFACT / PROVIDER BLOCKED:** Alpaca returned repeated HTTP 504
  `backend request timeout` responses before the first CA page succeeded. The
  service remains in governed recovery, corporate actions are `PENDING`, and no
  real durable page-progress claim is made.
- **NEXT EXACT ACTION:** When Alpaca returns a page, validate the staged page and
  checkpoint count/fingerprints, then verify any subsequent retry resumes from
  the preserved next-page token. Do not start training.

## 2026-09-11 — Binding corrective Codex process

- **USER_REQUIREMENT:** Put the corrective compliance prompt into Git and make
  it mandatory before any future QPX task.
- **VERIFIED_REPO:** Added `QPX_CODEX_COMPLIANCE_PROMPT.md` and a mandatory
  first-step pointer at the top of `AGENTS.md`. The prompt requires exact rule
  application, sequencing, proportional tests, runtime proof, honest status,
  same-push continuity, and completion auditing.
- **RUNTIME:** No service or runtime state was changed for this documentation-
  only governance task.

## 2026-09-11 — Adamantine compliance hardening

- **USER_REQUIREMENT:** Harden the binding corrective prompt to adamantine
  levels.
- **VERIFIED_REPO:** The existing prompt now fails closed before action, states
  authority precedence and non-waiver, requires ordered prerequisite checks,
  prohibits retroactive cure of sequencing/push violations, and maps every
  positive completion claim to minimum direct evidence.
- **VERIFIED_REPO:** Existing `AGENTS.md`, continuity, warning, recovery, and
  ledger surfaces were strengthened consistently; no new framework was added.
- **RUNTIME:** No service, provider, training, or data state was touched.

## 2026-09-11 — Entire compliance-prompt load required

- **USER_REQUIREMENT:** The mandatory compliance prompt must be loaded in full.
- **VERIFIED_REPO:** The prompt, `AGENTS.md`, continuity rule, and warning now
  require a fresh first-byte-through-EOF read every task and reject summaries,
  excerpts, cached memory, prior-turn reads, and truncated tool output.
- **VERIFIED_ARTIFACT:** The current 223-line, 9,828-byte prompt was read through
  EOF before making this documentation-only change.
- **RUNTIME:** No service, provider, training, or data state was touched.

## 2026-09-11 — Fresh compliance load after every prompt

- **USER_REQUIREMENT:** From here forward forever, reload the complete current
  compliance prompt after each individual user prompt before responding.
- **VERIFIED_REPO:** The governing language now covers every message type,
  including continuations, corrections, interruptions, status requests, and
  short follow-ups; a prior prompt's read never carries forward.
- **RUNTIME:** No service, provider, training, or data state was touched.

## 2026-09-11T13:03:59-05:00 — Corporate-action durable-page recovery corrected

- **USER_REQUIREMENT:** Successfully acquired corporate-action provider pages are durable governed evidence. RAM is working state only.
- **VERIFIED_REPO:** Each completed provider page is now committed as one self-contained atomic durable bundle before any later provider request.
- **VERIFIED_REPO:** The durable page chain owns restart position. Progress metadata is reconstructible and cannot strand a completed page.
- **VERIFIED_REPO:** Terminal aggregation retains acquired provider pages.
- **VERIFIED_ARTIFACT:** Focused historical-acquisition and directly affected historical-qualification tests passed; Python compilation and git diff validation passed.
- **VERIFIED_ARTIFACT / RUNTIME:** real CA page 1 survived restart and acquisition resumed forward to real page 2.
- **VERIFIED_ARTIFACT:** Page-1 SHA256: `a5ee1dad88a8ec810080adeb6a9073069d79a0b76a9b7d799f8200f6e7b6acd4`.
- **VERIFIED_ARTIFACT:** Historical reservoir remained 7370 partitions and 383082447 rows.
- **TRAINING AUTHORITY:** Unchanged; training is not authorized.

## 2026-09-11T13:09:31-05:00 — Correction and actual CA restart/resume runtime proof

- **CORRECTION:** The earlier runtime statement attached to the durable-page source correction did not independently prove page-1-to-page-2 restart continuation because 349 validated old-format provider pages had already been migrated into durable bundles before that observation.
- **VERIFIED_ARTIFACT / RUNTIME:** after an explicit process stop/restart, terminal durable pages 1-364 remained byte-identical and QPX recovered to corporate-action COMPLETE without creating another provider page.
- **VERIFIED_ARTIFACT:** The frozen pre-restart durable chain contained 364 pages with chain SHA256 `d3c6b985aa263c6f8d5ce96baf846c041e154336a26182163684bb9ef97920d0`.
- **VERIFIED_ARTIFACT:** Pre-existing durable pages remained byte-identical across the explicit restart.
- **VERIFIED_ARTIFACT:** Historical reservoir remained 7370 partitions and 383082447 rows.
- **TRAINING AUTHORITY:** Unchanged; training remains unauthorized.

## 2026-09-11 — Corporate-action name-change lineage correction

- **USER_REQUIREMENT:** Resolve or bound corporate-action identities using only
  authoritative same-security alias evidence. For Alpaca, only explicit
  `name_change` old/new-symbol evidence creates lineage; merger, spin-off,
  reorganization, and other event aliases do not.
- **VERIFIED_ARTIFACT:** Mechanical classification of the original 69,063
  dated/security-unbounded events found 5,413 without symbol evidence and
  63,650 with symbols but no direct provider-population match. Name-change-only
  traversal produced 10,358 unique anchors, 621 multiple-ID anchors, and 58,084
  records with no anchor.
- **VERIFIED_REPO:** The existing resolver was extended deterministically and
  the evidence identity advanced to schema 2 / semantic
  `ALPACA_PROVIDER_REPORTED_SYMBOL_LINEAGE_V2`. Direct matches, reuse,
  competing components, cycles, non-name-change aliases, bounded ambiguity,
  and unbounded fail-closed behavior have focused coverage.
- **VERIFIED_ARTIFACT:** Real resolution fingerprint
  `3e97e6aeafb3815e0fe6380df2b78c428abe1ff28ef5ced42be114e1bb32591a`;
  manifest fingerprint
  `857a39e00bf690e89933be731e4fa18e0e2b7bd55ddeb6a768ab6d66db4b4e39`.
  Final counts: 299,477 resolved, 63,671 unresolved, 5,587 bounded unresolved,
  and 58,084 unbounded.
- **VERIFIED_ARTIFACT:** Eight focused tests passed; Python compilation and
  diff checks passed. No provider request, CA reacquisition, bar mutation,
  calendar repair, qualification, or training occurred.
- **NEXT EXACT STEP:** Supply authoritative provider identity evidence for the
  remaining 58,084 events or govern their treatment. Do not weaken the existing
  security-and-time qualification boundary.

## 2026-09-11 — Targeted CUSIP/ISIN enrichment in progress

- **USER_REQUIREMENT:** Enrich exactly the 58,084 residual corporate-action
  provider event IDs using Alpaca ID-filter responses, current asset identity
  evidence, and targeted CUSIP lookups; never reacquire the full archive or
  weaken the security-and-time qualification boundary.
- **VERIFIED_REPO:** The in-progress implementation persists each deterministic
  event-ID batch and CUSIP lookup before the next request, resumes from validated
  content-addressed evidence, and extends the existing resolver rather than
  creating another identity authority.
- **VERIFIED_ARTIFACT / RUNTIME:** All 59 event-ID batches were returned and
  durably committed under target fingerprint
  `50711b8675b358907bd5b4728d36eceace22809f594e6af11b31ad757031a8ce`.
  They contain all 58,084 requested IDs exactly once. Of those events, 41,458
  contain CUSIP evidence, 16,626 contain no CUSIP/ISIN evidence, and none of the
  actual targeted responses contains ISIN evidence. Both active/inactive asset
  snapshots are durable but supplied no CUSIP match for the targeted tokens.
- **VERIFIED_ARTIFACT / RUNTIME:** At this checkpoint, 3,834 of 14,286 unique
  targeted CUSIP lookup results are durable. The single governed worker remains
  active under the existing off-market capacity/rate mechanism. No bars or
  original corporate-action pages were modified, and training remains
  unauthorized.
- **TASK STATUS:** IN PROGRESS. The 16,626 events without any returned identity
  token guarantee a nonzero residual; remaining CUSIP lookups continue because
  they can still establish truthful resolved, bounded-ambiguous, or verified
  outside-population scope for other events.

## 2026-09-12 — Identity enrichment completed; experimental training authorized

- **VERIFIED_ARTIFACT:** Completed enrichment fingerprint
  `110c9231e677b2fbf2e618fd33944f7ccdac10fd20475f86a93bf7b737694c24`
  validates against acquisition state, 58,084 targets, 59 event batches, and
  14,286 CUSIP lookups. No enrichment reacquisition occurred.
- **VERIFIED_ARTIFACT:** Rebuilt resolution fingerprint
  `bf36d339de8ceab65a4175d31c742a204b8af2b9efc7819757895e6f9af52f1b`:
  300,628 resolved; 32,623 outside population; 7,399 bounded ambiguous; 22,498
  unresolved/unbounded. Residuals are 16,626 no CUSIP/ISIN, 5,625
  lookup-not-found, and 247 mixed matched/unresolved evidence.
- **VERIFIED_ARTIFACT:** Thirteen focused enrichment/resolver/qualification
  tests passed. Python compilation and diff checks passed. Bars remain
  7,370/7,370 and 383,082,447 rows.
- **USER_APPROVED:** Experimental training is authorized on the explicitly
  limited current snapshot while strict qualification remains
  `NOT_TRAINING_ELIGIBLE`. No promotion, live, broker, or capital authority is
  granted.
- **VERIFIED_REPO / BLOCKER:** No executable trainer or complete governed
  training configuration exists. ADR-0011 leaves model, algorithm,
  optimizer/capsule behavior, bankroll, permissions, and resource limits
  unresolved; launching now would require prohibited invention.
- **NEXT EXACT ACTION:** Govern those training parameters, then implement the
  explicit unqualified-experimental launch boundary and start the detached run.
