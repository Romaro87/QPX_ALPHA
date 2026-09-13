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

## Baseline completion accepted and Wildcard V1 world built

- **USER_CONFIRMED:** The missing `broker_authority` key was never part of the
  Baseline V1 manifest schema and does not invalidate its completed evidence.
  Do not rerun or modify the baseline.
- **VERIFIED_ARTIFACT:** Baseline run
  `e0ad4ca03fcbbca8fe7253ca756d66b4eaae127ef3624745ffeb6888c9311d0c`
  completed 7,370 partitions and emitted valid checksummed final model, report,
  checkpoint, and `COMPLETE` exit status. Report fingerprint:
  `f7d9184a4e3f6d1fa44e5558a4b40b23c5e50bc29729b3d41fc1e8bd77bdf357`.
- **USER_APPROVED:** Wildcard V1 subordinate physics now resolve Decimal scale,
  rounding, fractional evidence, FIFO, replace acknowledgement, and fee-source
  boundaries exactly as supplied in the user's September 12 instruction.
- **VERIFIED_REPO:** Added the sterile Wildcard causal-world foundation and
  focused deterministic scripted/pathology fixtures. It is an accounting and
  execution world only, not a learner.
- **VERIFIED_ARTIFACT:** `python3 -m unittest -v
  tests.test_wildcard_world tests.test_wildcard_reward_policy` passed 47/47;
  relevant Python compiled and `git diff --check` passed.
- **NEXT EXACT ACTION:** Commit/push this foundation, then add the external
  DEVELOPMENT_ONLY scripted driver and sterile report layer before any learner.

## Completed-boundary cadence and DEVELOPMENT_ONLY driver/report layer

- **USER_APPROVED:** Reward and scheduled market-time reconciliation occur once
  per completed world boundary. Ordinary per-security events never advance the
  global clock or emit dense reward.
- **VERIFIED_REPO:** Added explicit deterministic boundary completion, external
  archive grouping/streaming, restart-safe open/completed boundary state, and a
  one-way sterile reporter using the 8,190 scheduled-minute cadence.
- **VERIFIED_ARTIFACT:** One, 100, and 1,000-event fixture boundaries each
  advance exactly 15 minutes. Missing-event and 210-minute half-day fixtures
  honor authoritative scheduled-minute input. Restart before completion permits
  one completion; restart after completion rejects duplication.
- **VERIFIED_ARTIFACT:** `python3 -m unittest -v tests.test_wildcard_world
  tests.test_wildcard_development_driver tests.test_wildcard_reward_policy`
  passed 58/58. Python compilation and `git diff --check` passed.
- **PRESERVATION:** Completed Baseline V1 artifacts, historical reservoir,
  strict qualification, and zero-authority boundaries remain unchanged.
- **NEXT EXACT ACTION:** Commit/push the completed driver/report milestone, then
  move to the separately governed Wildcard learner/model-family decision.

## Wildcard V1 model-family review and DEVELOPMENT_ONLY capsule proof

- **USER_REQUIREMENT:** Conduct ADR-0011's separate high-risk learner review;
  freeze model family, online learning, causal capsules, optimizer handling,
  preference conditioning, and apprenticeship authority without using the real
  historical reservoir.
- **VERIFIED_REPO:** ADR-0013 selects a small GRU softmax policy using
  deterministic seeded sampling and one-boundary online reward-modulated plain
  SGD. The small feed-forward family is runner-up. The model input is a fixed,
  fingerprinted neutral causal state vector plus a separately fingerprinted
  reward/preference vector.
- **VERIFIED_REPO:** Episode-local recurrent/pending/RNG state is destroyed at
  restart. Only immutable checksummed episode-terminal additive capsules can
  survive; they carry complete evidence and strictly later eligibility
  boundaries, unique parent lineage, full contract identities, parameter delta,
  and explicit optimizer destruction.
- **VERIFIED_ARTIFACT:** `python3 -m unittest -v
  tests.test_wildcard_learner` passed 14/14. Python compilation and
  `git diff --check` passed. Toy tests prove ordering, eligibility,
  deterministic composition/restart, preference plumbing, archive absence, and
  zero authority.
- **PRESERVATION:** No real apprenticeship or training ran. The Baseline,
  historical reservoir, strict qualification, Wildcard world, and main branch
  were not modified.
- **NEXT EXACT ACTION:** Commit/push the reviewed DEVELOPMENT_ONLY container.
  Later, only after independent `TRAINING_ELIGIBLE` and separate authorization,
  configure and begin real `HISTORICAL_APPRENTICESHIP`.
