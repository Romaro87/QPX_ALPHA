# QPX conversation journal — 2026-09-17

## 12:10 CDT — frozen Top-100 evidence repair and causal split implementation

- **USER REQUIREMENT:** Implement and launch a distinct corrected ten-year
  historical replay using every member of
  `qpx_bot/research_universes/alpaca_top100_qdte1300_thursday_v1.json`, including
  split-affected symbols. Keep the selection unchanged and explicitly label it
  retrospective, selection-biased, and in-sample.
- **USER APPROVED:** Narrowly retrieve the missing split-ratio/convention and
  provider-identity evidence only. Do not reacquire price bars. Permit exact
  fractional shares created by corporate actions only; purchases remain
  integer-share transactions and no cash-in-lieu may be fabricated.
- **RISK / PRE-CODE GATE:** HIGH. The reviewed design reuses the governed
  provider population, corporate-action archive and identity resolution,
  historical OPEN/CLOSE event sequence, provider-ID portfolio state, and
  checksummed recovery. State ownership, causal boundary, restart behavior,
  invariants, and focused verification were resolved before implementation.
- **VERIFIED REPO BEFORE WORK:** Repository `/home/ron/QPX_ALPHA`, branch
  `main`, local `HEAD` and `origin/main` both
  `05f6fc7397ff6be4743194140a2fbb91e1567e14`. The tracked tree was clean before
  this implementation. Pre-existing untracked `runtime/` content and the
  malformed `ystemctl --user show qpx-clean-v2-dummy-intervention-20260903.timer
  \\` path remain unrelated and unstaged.
- **PRESERVATION:** No existing replay or live-paper service was stopped,
  restarted, signaled, edited, or reused. Existing reports, checkpoints,
  preparation databases, acquisition state, price bars, and live account state
  were not rewritten.

### Evidence repair

- **VERIFIED ARTIFACT:** Frozen selection fingerprint
  `5e271e4a9e0d4a20b6f4d0cecc08e8bf9efe1d2123a64832d09ba1c1eb9ffd23`
  remains unchanged. The derived manifest preserves all 100 labels in their
  stored order, maps them to 100 distinct provider asset IDs, and keeps QDTE as
  a separate income identity.
- **VERIFIED ARTIFACT:** Derived asset-ID universe fingerprint
  `1840a7a2cc2048c844a104b8434e8cec72c4244bc2a7ed914c9d500be93d185a`;
  manifest fingerprint
  `1bee0e7b1bfe2f654b5ef4c91ba798dc04d994c4bb704e8ecd8aaa70c122cd05`;
  manifest file SHA-256
  `5dbefdc0753f869ea86293ea7bdb45a927f3a48e9a90cff6174db80f2aae1249`;
  source corporate-action fingerprint
  `c08e371f89ca654eee110ad8cae8e42f10943fc3b0cc1c40842cd9d1714a8b9d`;
  source identity-resolution fingerprint
  `bf36d339de8ceab65a4175d31c742a204b8af2b9efc7819757895e6f9af52f1b`.
- **VERIFIED ARTIFACT:** The bundle records 36 explicit provider events: 31
  reverse splits and five forward splits across the selected provider
  identities, dated 2017-05-01 through 2026-08-31. Provider `old_rate` and
  `new_rate` establish `new shares / old shares = new_rate / old_rate`.
  `price_bar_requests` is exactly zero.
- **VERIFIED IDENTITY:** BBBY resolves through governed name-change lineage to
  provider asset ID `96a49f53-6ed9-4900-b92a-44814b21cf92`; exact source/reservoir
  overlap is 6,112 common bars with zero mismatches. The five ambiguous labels
  bind to targeted provider IDs and available exact overlap evidence is stored
  in the checksummed manifest.

### Implementation

- **FILES:** Added `qpx_bot/top100_split_evidence.py`, the checksummed derived
  Top-100 manifest, the distinct replay configuration, and
  `tests/test_top100_causal_splits.py`. Updated
  `qpx_bot/historical_paper_replay_v3.py`,
  `qpx_bot/historical_paper_replay_runner.py`, and `qpx_bot/portfolio.py`.
- **CAUSAL ORDER:** At an effective 09:30 OPEN, split state transforms before
  affected exits, settlements, rebalance, pending admission/gap checks, sizing,
  fills, marks, or risk calculations. A later split cannot alter an earlier
  stored indicator decision; accumulated OHLCV is rescaled only when the event
  becomes effective.
- **ACCOUNTING:** Corporate actions scale position shares and inversely scale
  per-share entry, ATR, stop, target, highest/trailing reference, pending-entry
  price/ATR inputs, and last marks. Cost basis, value, dollar risk, cash, tax
  reserve, and realized P&L reconcile. Applied event IDs, fingerprints, and
  pre/post evidence survive checksummed restart and cannot apply twice.
- **CONFIGURATION:** Replay fingerprint
  `3a454d3e49453393885c462204527f3d2d58d1286c3ee7bcda70289ec656c6a6`;
  Candidate fingerprint
  `347a2831e4f67ab4e7afd895430ef04b0503eb33b32e65a9aac9bf9a08fadf1f`.
  Preserved `$1,443.34`, 90% cap, volume confirmation, momentum 52, VIX
  exclusion `20 < VIX < 25`, maximum VIX 32, six positions, and disabled other
  accelerators. Authority remains historical paper only.

### Focused verification

- **COMMAND:** `python3 -m unittest -v tests.test_top100_causal_splits
  tests.test_historical_paper_replay_runner tests.test_reservoir_replay_universe
  tests.test_portfolio_engine`
- **RESULT:** 31/31 passed in 2.758 seconds, including exact membership,
  provider-ID and duplicate-symbol isolation, split direction, forward/reverse
  position and pending transformations, value/cost/risk preservation, causal
  indicators, no pre-effective change, chronological/deduplicated events,
  OPEN ordering, restart/fingerprint mismatch, outcome reconciliation, exact
  sizing classifications, and existing tax-reserve behavior.
- **ADDITIONAL RESULT:** Changed Python compiled successfully and
  `git diff --check` passed. No broad suite ran.
- **NEXT EXACT ACTION:** Stage and inspect only intended files; commit/push to
  `main`; verify local/remote equality; then start one distinct isolated
  systemd replay and verify its manifest and first checksum-valid advancing
  checkpoint. Final ten-year historical result remains pending.
