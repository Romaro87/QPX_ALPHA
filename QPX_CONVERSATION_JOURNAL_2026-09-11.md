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
