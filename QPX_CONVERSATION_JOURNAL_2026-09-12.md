# QPX Conversation Journal — 2026-09-12

## Experimental Causal Baseline V1 implementation

- **USER_APPROVED:** Implement and start the first executable experimental ML
  baseline using the current explicitly limited historical snapshot. The
  supplied design resolves model, features, target, splits, SGD, checkpoint,
  output, resource, and authority semantics for this baseline only.
- **VERIFIED_REPO:** Added the standard-library streaming causal logistic
  trainer and focused toy verification. It reads but never mutates historical
  acquisition evidence or strict qualification state.
- **VERIFIED_ARTIFACT:** Exact snapshot fingerprint
  `bcace64bb55c68de66c256c5b9ed443e6384f80904cff7debaefeb862792d595`;
  inventory fingerprint
  `1fa355435551705b6b1aadb70af40aca65039fdc46b0ada0b98f4eb2917ad3cc`;
  configuration fingerprint
  `cb1a68a29280a9c4faafa5e04a37667b6436f4134db6486a68d54c694d8beaf4`.
- **LIMITATIONS:** 22,498 corporate actions remain unresolved/unbounded,
  calendar repair is not run, and the strict dataset state remains
  `ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE`.
- **AUTHORITY:** Experimental training only. Promotion, live, broker, and
  capital authority remain `NONE`.
- **NEXT EXACT ACTION:** Complete focused tests and diff checks, commit/push the
  review branch, then launch and verify one detached `nice -n 10` trainer
  process without waiting for completion.
