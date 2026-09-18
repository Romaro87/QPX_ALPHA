# QPX Conversation Journal — 2026-09-18

## Three simultaneous Top-100 stop variants

- **USER REQUIREMENT:** Create three distinct ten-year aggressive accelerated
  Top-100 replays with configured 5%, 7%, and 9% initial stops; cap aggregate
  exposure per provider asset ID at 17% including pyramids; remove the separate
  per-position risk cap; preserve every other experiment surface; launch all
  three simultaneously without touching existing replays or live paper.
- **RISK / DESIGN:** HIGH. Approved design keeps the base Candidate/profile and
  four accelerator authorities unchanged. Versioned replay configuration V3
  owns the experiment stop/exposure/no-per-position-risk overlay. Entries are
  bounded by cash, 17% exposure, and the existing 60% aggregate active-risk
  ceiling. ATR target/trailing semantics remain unchanged.
- **IMPLEMENTATION:** Added three versioned replay configs and minimal runtime
  integration for entry-fill percentage stops, provider-asset exposure sizing,
  pyramid exposure enforcement, captured position semantics, and split-stable
  initial-risk accounting. Added atomic direct account valuation fields and
  fingerprints to every new checkpoint, restart recomputation/validation, and
  identical final-report fields.
- **CONFIGURATION FINGERPRINTS:** 5% stop
  `f1b31b1f5310db967c2257cae96603cf6a67cd730bd6d72853593d29f7378ea9`;
  7% stop `b7a77f13e09b14903c0f5c0e03768749562dde45bb231005894ef7a3ff6683c4`;
  9% stop `780821b03737a7853c072f875e8ef92258923d13913e32713959c44014958d84`.
- **FOCUSED TESTS:** The exact command recorded in the recovery prompt passed
  54/54 after one test-only floating-point precision assertion correction.
  No broad suite ran.
- **PRESERVATION:** Pre-existing untracked `runtime/` and malformed systemctl
  filename remain untouched. Existing historical services and live paper have
  not been signaled, restarted, or modified.
- **NEXT EXACT ACTION:** Inspect and stage explicit paths, commit/push the whole
  continuity transaction to `main`, verify remote equality, then launch and
  validate the three isolated services and their first direct-valuation
  checkpoints. Final ten-year results remain pending.
