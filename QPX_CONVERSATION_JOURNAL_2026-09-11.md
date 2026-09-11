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
