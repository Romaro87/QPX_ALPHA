# QPX Conversation Journal — 2026-09-14

## Primary ten-year ALPACA SIP Candidate V1 causal paper replay

- **USER_REQUIREMENT:** Resume the preserved untracked runner/config after the
  Constitution-alignment commit on `main`, preserve every unrelated worktree
  artifact, bind the existing completed ten-year reservoir, run focused checks,
  execute the replay, and commit accepted advancement to `main`.
- **VERIFIED_REPO:** Starting `main`, local HEAD, upstream, and `origin/main`
  were all `25dc1d5e74e354f4c2d431cd36b8dc7c7f57b099`, ahead/behind 0/0.
  Preserved runner/config hashes exactly matched the handoff values
  `34f73b7951516e6e9172a711fd1402d0ccc7191f68b3d51c09620ae7b6ef017d`
  and `dbc3c2d9815b54e9bcae3921f4919085a7bb8704c7eaf8dfaf1391784b72c8c4`
  before modification.
- **CORRECTION:** The stopped runner incorrectly loaded the legacy default
  `intraday_six_policy.json`, whose 1.5 ATR gap limit contradicted the current
  Candidate policy's governed 2.0 value. It also coupled primary execution to
  the provisional eight-field reconstitution object. The runner now explicitly
  loads `qpx_bot/candidate_v1_policy.json` and validates the exact current
  `qpx_bot/symbols.json` manifest. No Candidate strategy/economic source was
  modified.
- **IMPLEMENTATION:** The runner validates the checksummed acquisition state and
  existing input snapshot fingerprint; records exact source root, full
  partition-inventory identity/counts, and runner hash; uses the actual
  `accepted_patch_sha256` calendar-overlay evidence key; finds prior-session VIX
  without repeated whole-history scans; and serializes portfolio/trade dates for
  deterministic JSON checkpoint recovery.
- **SOURCE OPEN:** Exact path was
  `/home/ron/QPX_ALPHA/research_data/qpx_ml_historical_v1`. Evidence was
  Alpaca/SIP/raw/15Min, 7,370/7,370 partitions, 383,082,447 rows, snapshot
  `bcace64bb55c68de66c256c5b9ed443e6384f80904cff7debaefeb862792d595`,
  inventory `1fa355435551705b6b1aadb70af40aca65039fdc46b0ada0b98f4eb2917ad3cc`,
  and calendar repair `81e3db3203ecdab2ff9ed347d4419ac1013952b32d881960f7122f9ba7e5f822`.
  The driver produced 65,085 boundaries from 2016-09-06 09:30 ET through
  2026-09-03 15:45 ET. No acquisition/provider request occurred.
- **TESTS:** `python3 -m unittest tests.test_historical_paper_replay_runner`
  passed 3/3. `python3 -m unittest tests.test_historical_paper_replay
  tests.test_causal_replay tests.test_candidate_v1_causal
  tests.test_candidate_v1_config` passed 36/36. `python3 -m py_compile` passed
  for runner/test files, and `git diff --check` passed.
- **RUNTIME:** Command was `python3 -m
  qpx_bot.historical_paper_replay_runner --config
  qpx_bot/replay_configs/candidate_v1_ten_year_sip_primary_v1.json --dataset
  research_data/qpx_ml_historical_v1`. Run ID
  `6523acae1db3a437d417de912000cd5bd045ddf58ae8f92d4775d9b6fabd4798`
  exited zero after processing 65,085 completed 15-minute boundaries and
  64,881 Candidate evaluations. Configuration fingerprint is
  `73abd19622c37437194345992d2cdf8817585647fd4b7cd6dca6e27fb0137927`.
- **RESULT:** Starting equity $1,300.00; ending equity
  $1,338.0291861036626; net P&L $38.029186103662596; maximum drawdown
  0.17647901594240054; 253 signals; 238 fills and closed trades; 111 wins; 127
  losses; dividend income $97.97974278984324; 15 gap rejections; zero risk
  rejections/capacity deferrals; no terminal positions. Final-report SHA-256 is
  `43ed58b0d9f8b1c7f513a42cde00f5e2053cd8ce62f4dd7e701eb0286eddaf3e`.
- **INTEGRITY:** Checksummed run manifest, checkpoint, final report, and exit
  status all matched their sidecars. Manifest status and exit status are
  `COMPLETE`; causal-integrity status is `PASS`.
- **QUALIFICATION / AUTHORITY:** The replay remains labeled
  `ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE` with 22,498 known
  unresolved/unbounded corporate actions. Training, promotion, live, broker,
  and capital authority are all `NONE`.
- **PRESERVATION:** Base bars, repair overlays, corporate-action evidence,
  completed Baseline/Wildcard artifacts, all unrelated `runtime/` content, and
  the malformed untracked `ystemctl...` file were not modified or staged.
- **NEXT EXACT ACTION:** Review this completed frozen paper experiment and
  select the next technical milestone; do not infer a strategy optimization or
  any new authority from this result.

## Volume-confirmation 25% runner activation — 2026-09-14

- **USER_REQUIREMENT:** “set the live paper runner to this exact configuration”; continuation: “continue”.
- **IMPLEMENTATION:** Added isolated Candidate V1 snapshot and paper profile, profile-aware contract/initialization, governed volume-confirmation capacity selection, and disabled-profit no-op handling. Existing PR50 state remains preserved.
- **TEST:** Focused configuration, accelerator, Candidate, Fixed25, and IEX runner tests passed 104/104. Profile smoke showed `$1,443.34` total, `$1,438.00` QDTE, `$5.34` swing cash, and disabled policy identity.
- **OPERATIONAL:** Service unit now points to `QPX_PAPER_PROFILE=/home/ron/QPX_ALPHA/qpx_bot/paper_profiles/volume_confirmation_25_v1.json` and fresh runtime `runtime/qpx_volume_confirmation_25_iex_forward_research_paper_clean_v3`; restart is pending commit/push.
