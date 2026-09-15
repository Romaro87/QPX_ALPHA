# QPX Conversation Journal — 2026-09-15

## Recovered split-excluded volume-confirmation 90% ten-year replay

- **USER_REQUIREMENT:** Resume the unfinished split-excluded ten-year
  volume-confirmation/90% replay without restarting settled analysis; preserve
  dirty worktree changes, keep starting equity `$1,443.34` and approved
  parameters unchanged, and leave the active paper service untouched.
- **RECOVERED_CONTEXT / VERIFIED_ARTIFACT:** The exact V2 replay had already
  completed before this session resumed. Run ID
  `0297c16374af28361e080df1a9e66d8c484587f6d28c3cad5565834f2af8f741`
  binds configuration fingerprint
  `46790e5a98b777e10f5bba41a05b1221c46f822e2c4489fa29dc95ce9523da70`,
  profile candidate fingerprint
  `347a2831e4f67ab4e7afd895430ef04b0503eb33b32e65a9aac9bf9a08fadf1f`,
  and the volume-confirmation arbitration fingerprint
  `b9a5008ec61f919a4c9da9c4d8afe8fe20c36c1e10fca8690c880ade23b6e89b`.
- **VERIFIED_ARTIFACT:** The completed replay covers 65,085 completed
  15-minute boundaries from `2016-09-06T09:30:00-04:00` through
  `2026-09-03T15:45:00-04:00`. Starting equity was `$1,443.34`; ending equity
  was `$1,185.5936896379146`; net P&L was `-$257.7463103620853`. It records
  487 signals, 459 fills, 458 closed trades, 487 capacity decisions, zero
  capacity deferrals, causal-integrity `PASS`, and zero applicable selected
  asset split events.
- **INTEGRITY:** `run_manifest.json`, `checkpoint.json`,
  `final_report.json`, and `exit_status.json` each validated against their
  checksummed sidecar. Manifest/report/exit status are `COMPLETE`.
- **TEST:** `python3 -m unittest tests.test_historical_paper_replay
  tests.test_historical_paper_replay_runner tests.test_volume_confirmation_profile
  tests.test_candidate_v1_config tests.test_candidate_v1_causal` passed 38/38.
  `git diff --check` passed.
- **RUNTIME PRESERVATION:** Read-only service inspection found the existing
  Clean-V2 supervisor and Clean-V2 IEX forward research paper runner active.
  No systemd, service, runtime, reservoir, or paper-profile state was changed.
- **AUTHORITY:** Historical data remains
  `ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE`; training, promotion, live,
  broker, and capital authority remain `NONE`.
- **NEXT EXACT ACTION:** Review this frozen experimental result only if a new
  governed task is supplied. Do not tune strategy semantics or alter the active
  paper service from this replay evidence.

## Correction — XLE-only replay was not the requested reservoir-universe replay

- **USER_CORRECTION:** Run `0297c16374af28361e080df1a9e66d8c484587f6d28c3cad5565834f2af8f741`
  is the earlier XLE-only result and must not be accepted as the requested
  split-excluded reservoir-universe replay.
- **VERIFIED_ARTIFACT:** The completed reservoir has 33,475 frozen provider
  securities: 14,287 active and 19,188 inactive. Existing resolved
  `stock_split`/`reverse_split` evidence identifies 2,044 provider assets with
  3,182 events. The requested derived universe therefore includes 31,431
  assets (12,637 active; 18,794 inactive). Its deterministic fingerprint over
  sorted `{provider_asset_id, canonical_symbol, provider_status}` records is
  `0087954d86f089584e237f3c37aa91962aa4ec52830d2375c75b247abe1a5212`.
- **NEXT EXACT ACTION:** Implement the separate V3 reservoir-universe replay
  integration, bind that universe and the approved split exclusions into a new
  experiment identity, run its focused tests, then launch and validate the new
  checksummed run. Preserve all prior run directories and leave paper services
  untouched.

## V3 universe recovery and asset-identity correction

- **USER_CORRECTION:** Active/inactive status does not control V3 eligibility:
  all 33,475 reservoir securities are included except the 2,044 approved split
  exclusions. Missing status is `UNKNOWN`. Provider asset ID is security/state
  identity; a symbol is a non-unique label. Same-symbol assets must not merge.
- **VERIFIED_ARTIFACT:** The previously reported fingerprint
  `0087954d86f089584e237f3c37aa91962aa4ec52830d2375c75b247abe1a5212`
  has no recoverable manifest or canonicalization in the repository, Git
  history, or unreachable objects. It is explicitly retained as
  `UNVERIFIED_CANONICALIZATION_UNRECOVERED`, not manufactured.
- **VERIFIED_ARTIFACT:** Builder `qpx_bot/reservoir_replay_universe.py` derives
  the new frozen manifest from provider population fingerprint
  `31d74c00c6a0a6b48b29d876285cd9581310e4b07a911fef2ff435dfbe090b34`
  and resolved `stock_split`/`reverse_split` evidence. It emitted
  `qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_reservoir_split_excluded_v3_universe.json`
  with 31,431 members, 2,044 exclusions, `UNKNOWN` status, and manifest
  fingerprint `3c94d3429559f335be3119832b1f8a8321604853416bb6d6a310c941d4d844a5`.
- **TEST:** `python3 -m unittest tests.test_reservoir_replay_universe` passed
  1/1 against the frozen local reservoir.
- **NEXT EXACT ACTION:** Convert replay-driver, runtime, checkpoint, capacity
  decision, and restart keys from symbols to provider asset IDs while retaining
  symbols as labels; add duplicate-symbol isolation/restart tests, then launch
  the distinct V3 replay. No service, report, or reservoir mutation occurred.

## Correction — prior completion-report classification

- **USER_CORRECTION:** The earlier `RULE COMPLIANCE: VIOLATED` classification
  was not supported by evidence. The task was incomplete because the approved
  asset-ID conversion and launch had not yet occurred; unfinished work alone is
  not a demonstrated rule violation. The correct state was `TASK STATUS:
  INCOMPLETE`, with rule-compliance status not negatively inferred from that
  fact.

## V3 provider-asset-ID implementation and resumable launch

- **USER_REQUIREMENT:** Complete the already-approved provider-asset-ID
  conversion through bars, indicators, positions, pending entries, capacity
  arbitration, checkpoints, and reports; keep symbols as non-unique labels;
  run focused tests and launch the distinct resumable V3 replay without another
  approval loop.
- **VERIFIED_REPO:** `CandidateV1HistoricalPaperRuntime` now keys candidates,
  pending entries, positions, marks, arbitration selections, checkpoint state,
  and report positions by canonical provider asset ID. Checkpoints bind the
  exact asset-ID-to-symbol-label map and universe fingerprint. Capacity
  arbitration preserves exact identifiers instead of uppercasing non-UUID
  provider IDs.
- **VERIFIED_REPO:** `qpx_bot/historical_paper_replay_v3.py` implements a
  batch-transactional SQLite preparation cache because the source reservoir is
  383,082,447 bars while the host has 14 GiB RAM. Completed batches are durable
  and skipped on restart; chronological paper replay resumes from its
  checksummed boundary checkpoint. Source partitions remain read-only.
- **VERIFIED_TEST:** Focused command covering replay configuration/runtime,
  duplicate-symbol asset isolation, volume-confirmation selection, checksummed
  restart identity, universe derivation, Candidate semantics, and directly
  affected arbitration passed 55/55. `git diff --check` passed.
- **VERIFIED_RUNTIME:** Distinct transient user service
  `qpx-v3-reservoir-replay-20260915.service` launched at 2026-09-15 15:20:37
  CDT with restart-on-failure. Run ID is
  `c4159b1c96507b58cc5a2168cfa09020fca7d7322e31821195025b367949f839`.
  Its checksummed manifest is `PREPARING`, binds configuration fingerprint
  `da2a13d93f5a129bd7e550eb998f7576fcba9afa70e0b3a0d7341d96608d2795`
  and universe fingerprint
  `3c94d3429559f335be3119832b1f8a8321604853416bb6d6a310c941d4d844a5`,
  and records 31,431 provider-asset-ID members. At the recorded checkpoint,
  10/670 batches were complete, the SQLite quick check was `ok`, and the cache
  contained 65,086 boundaries, 2,755,753 retained bars, and 7,499 qualifiers.
- **PRESERVATION:** Historical source data, previous replay reports, and paper
  services were not changed. Training, promotion, live, broker, and capital
  authority remain `NONE`.
- **NEXT EXACT ACTION:** Allow the resumable V3 service to finish preparation
  and chronological replay; then validate the checksummed final report and exit
  status. Do not accept XLE-only run `0297c163...f741` as V3 evidence.

## Corrected V3 implementation and invalid-run exclusion

- **USER_REQUIREMENT:** Stop only the defective V3 service, preserve all of
  its evidence, repair the demonstrated historical gaps and matching live
  gaps, run focused tests, push accepted changes, preserve/deploy the live
  simulated account, and launch a distinct corrected resumable replay.
- **STOP / PRESERVATION:** `qpx-v3-reservoir-replay-20260915.service` was
  stopped cleanly with `Result=success`, `NRestarts=0`, and no other service
  stopped. Run `c4159b1c...49f839` remains intact and is acceptance-excluded.
  Its manifest SHA-256 is
  `bdb7784c68abd54d42e4dc94128cbe58bd6c8c758ceda5c270bb4e1d814c329b`;
  last replay-checkpoint SHA-256 is
  `0d72c4a30616d0b02f890ecce4a655e29e0a4423baeed4daeb4467ac3255c4cf`.
- **DEFECT EVIDENCE:** Four lowercase provider UUID positions were stored as
  uppercase keys, for which exact reservoir queries returned zero bars. V3
  preparation used `average_volume[index]`, ex-date immediately released
  dividends, pending fills preceded exits/allocation, and completed bars could
  rebalance at their already-past open. Aggregate rejection counters omitted
  the exact sizing causes.
- **IMPLEMENTED:** Historical exact-identity portfolio mode leaves existing
  symbol normalization intact elsewhere. Provider IDs remain exact through
  pending/fill/position/mark/exit/checkpoint/report. Volume baseline is
  `average_volume[index-1]`. Dividend entitlements and settlements persist
  separately. OPEN now handles settlement, gap exits, allocation, and prior
  pending entries before CLOSE observations stage later signals. Entry outcome
  records retain exact reasons and a fail-closed reconciliation summary.
- **LIVE DIRECT INSPECTION:** The supervised IEX runner is symbol-universe
  based, already used the prior completed bar for volume, and already persisted
  ex-date entitlement plus later payable/process cash release. Its retrospective
  completed-bar weekly rebalance was a matching gap; IEX allocation now runs on
  the authentic one-minute open clock after eligible gap exits and settlement
  and before pending entries. Completed-bar IEX catch-up no longer rebalances.
- **LIVE ACCOUNT BEFORE DEPLOYMENT:** Checksummed state SHA-256
  `a3dd38baba40a46df5c5173a6c72a298832f926c7b2620cb333fcfc1f1ed63b6`
  held 50 QDTE shares, QDTE cost `$1,421.065`, cash `$22.275`, no swing
  positions, and no pending entries. Heartbeat was healthy, simulated-only,
  90% cap, Candidate fingerprint
  `347a2831e4f67ab4e7afd895430ef04b0503eb33b32e65a9aac9bf9a08fadf1f`.
- **FOCUSED VERIFICATION:** 89 directly affected historical replay, universe,
  profile, dividend, fixed-paper, and IEX-paper tests passed. This is not final
  replay acceptance; deployment, push verification, corrected launch, and
  eventual replay completion are recorded separately.

## Corrected deployment and replay launch

- **SOURCE ACCEPTANCE:** Commit
  `9b190fd55ea1fff50a1be58b51f77da65db23702` was pushed to `origin/main`;
  remote `refs/heads/main` verified at the identical SHA.
- **LIVE DEPLOYMENT:** The supervised Clean-V2 target loaded execution-phase
  identity `AUTHENTIC_OPEN_THEN_COMPLETED_CLOSE_V1` through the existing
  checksummed configuration-transition path. Post-transition state SHA-256 is
  `1eac9b53099e219434bb431e8ff46694c5a0f2f38e898b99a2c816eea9d26a38`.
  Account continuity is exact: 50 QDTE shares, QDTE cost `$1,421.065`, cash
  `$22.275`, zero swing positions, zero pending entries, and revision 52.
  The after-hours heartbeat SHA-256 is
  `66a64a0f79704f5075793c6be88b2af4e0606c713b703a41075c41c1f2ef6bd8`;
  it reports the approved Candidate fingerprint, 90% cap, simulated fills,
  no live broker, no failure, and zero service restarts.
- **CORRECTED HISTORICAL LAUNCH:** Distinct service
  `qpx-v3-reservoir-replay-corrected-20260915.service` launched run
  `1fbbd3cb80755e4ed8cbe37e05adee1c50b43ab90ff77ff25668197ecbbf8f83`
  from accepted commit `9b190fd55ea1fff50a1be58b51f77da65db23702` with implementation
  fingerprint
  `4f1261475a0784effd3f3572a60b6bbac5af0449d0823adef625db71e831d1a9`.
  Checksummed manifest SHA-256 is
  `95b656c657833c669b3316e98fc0d1719f2c7c4ee5e690d7ed6bfba2d96ec80d`;
  it binds configuration `da2a13d...d2795`, universe `3c94d342...44a5`,
  31,431 assets, and `$1,443.34` starting cash. Initial preparation checkpoint
  validated at 2/670 batches; SQLite `quick_check` returned `ok`; service was
  active with PID 181490 and zero restarts.
- **ACCEPTANCE STATUS:** Implementation/tests and live after-hours runtime
  acceptance passed. Corrected replay launch passed. Final replay acceptance
  remains pending because preparation/replay are running and no checksummed
  final report or exit status exists yet.
