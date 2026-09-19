# QPX conversation journal — 2026-09-19

## 11:20 CDT — four 25%-exposure Top-100 replay variants

- **USER REQUIREMENT:** Create and launch four additional ten-year frozen
  Top-100 replays alongside the running 5%, 7%, and 9%/17% runs. Use stop/cap
  pairs 9%/25%, 11%/25%, 13%/25%, and 15%/25%; make configuration-only changes;
  preserve every other strategy, accelerator, dataset, universe, causal,
  execution, accounting, and evidence surface; do not touch live paper.
- **RISK / PRE-CODE GATE:** HIGH / SATISFIED. Configuration V3 remains state
  authority for stop and provider-asset aggregate exposure. Each new run owns
  isolated preparation, checkpoint, portfolio, trade, accounting, report, and
  service state. Existing replays and live paper are preservation boundaries.
- **RESOURCE EVIDENCE:** 28 logical CPUs, 7.2 GiB available memory, 345 GiB
  available disk. The three running replay processes were healthy with zero
  restarts and 0.70-0.86 GiB RSS each; four additional low-priority workers fit
  the measured resource envelope.
- **FILES ADDED:**
  `qpx_bot/replay_configs/top100_aggressive_stop09_exposure25_v1.json`,
  `top100_aggressive_stop11_exposure25_v1.json`,
  `top100_aggressive_stop13_exposure25_v1.json`, and
  `top100_aggressive_stop15_exposure25_v1.json`.
- **FINGERPRINTS:** 9% `874d0e7040bd39b5afc23c104eb4278be4aa0f63f565c9ccbe46b1a01c7b8a9b`;
  11% `f996dd17749ab50f688aa7786f7a567a7cb70b5f1f45af547b13729074ef6eec`;
  13% `dc830b3609558b733646e87e11cdde101164dd9c0d02c989380f5e18a4ea73ea`;
  15% `292d70a4cd46bdb7769a7bfe03a0084dcf63d55b0d288260fcdb110f3a2e26d0`.
- **FOCUSED VALIDATION:** The governed loader accepted all four configs. Exact
  recursive comparison proved the bridge differs from 9%/17% only by cap after
  normalizing identity, and the new four differ only by stop after normalizing
  identity. `git diff --check` passed. No suite ran because no production or
  schema behavior changed.
- **PRESERVATION:** Pre-existing untracked `runtime/` and malformed
  `ystemctl ...` path remain unrelated and unstaged. Existing services were not
  stopped, restarted, or signaled. Live paper was not accessed or modified.
- **NEXT EXACT ACTION:** Explicitly stage/audit the four configs and continuity
  files; commit/push to `main`; verify remote equality; launch four isolated
  low-priority services; verify manifests and first advancing checkpoints.
