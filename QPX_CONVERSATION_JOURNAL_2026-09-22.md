# QPX Conversation Journal — 2026-09-22

## Bounded V3 replay evidence

- Reapplied the complete repository compliance prompt and governing chain before action.
- Classified the change HIGH RISK because it changes checksummed replay evidence persistence and restart behavior; strategy and accounting semantics remain out of scope.
- Confirmed the seven-run replay queue is inactive and complete, all seven requested jobs are recorded complete, and the completed run directories will not be migrated or modified.
- Reviewed design: deterministic append-only evidence batches at the existing checkpoint cadence; write and reread batch; checkpoint its ordered checksum reference and rolling totals; only then release persisted events from RAM. Pending entry outcomes and next-boundary state remain resident. Restart validates the full referenced batch prefix and replays only the suffix after the durable checkpoint. Final reports reconstruct the existing evidence fields from verified batches; progress reports contain rolling totals only.
- Planned focused verification: batch checksum/hash-chain failures, crash window/orphan reuse, exact restart boundary selection, no gaps/duplicates, final-report semantic equivalence, bounded retained evidence, and comparable runtime measurements.

### Implementation and focused evidence

- Added a V3-only bounded evidence archive. Each deterministic batch is written with a checksum and reread, its path/sequence/byte length/checksum/hash-chain predecessor and rolling totals are placed in the next checkpoint, and only after the checkpoint succeeds are the persisted runtime lists cleared. Pending outcomes remain resident. Restart validates the complete referenced batch chain. A deterministic matching orphan is reusable; a differing or incomplete orphan fails closed.
- Final-report evidence is reconstructed from verified batches. The periodic `progress_report.json` contains rolling totals and current progress only.
- The new evidence module participates in the V3 implementation fingerprint, so existing completed runs/checkpoints cannot be relabelled or reused.
- Focused tests: `python3 -m unittest tests.test_v3_bounded_evidence tests.test_v3_checkpoint_interval tests.test_v3_active_checkpoint_migration tests.test_historical_paper_replay_runner tests.test_historical_replay_accelerators tests.test_top100_stop_exposure_replays` — 38 passed.
- Controlled real-cache replay, 8,192 identical boundaries and 256 checkpoints on tmpfs (logical serialization I/O): legacy steady private 120,598,528 B, sampled private peak 120,598,528 B, max RSS 169,615,360 B, checkpoint 35,102,097 B, logical writes 4,506,574,015 B, 174.52 boundaries/s; bounded steady private 29,384,704 B, sampled private peak 29,384,704 B, max RSS 124,235,776 B, checkpoint 872,914 B, logical writes 141,984,723 B, 649.95 boundaries/s. Resident bounded evidence lists were all zero after the checkpoint; 256 batch references remained.
- Controlled real-cache replay on ext4, 2,048 identical boundaries and 64 checkpoints: legacy block writes 244,260,864 B and 517.06 boundaries/s; bounded block writes 15,613,952 B and 744.61 boundaries/s. This is a 93.6% checkpoint-workload block-write reduction, not a claim about total system disk I/O.
- Completion audit: 44 directly affected tests passed after expanding restart equivalence to compare every persisted capacity, terminal outcome, profit-recycling, dynamic-sizing, pyramiding, and regime-allocation record against uninterrupted execution. `git diff --check` and Python compilation passed. Worktree V3 implementation fingerprint is `5f190be4edf74aeaf17bbfa2b836997c7b93ba996c5d495b964a78c851e5f88f`, distinct from the seven preserved completed runs (`56d4a2aa...9fed5`). The seven manifests remain `COMPLETE`; no run was launched or migrated. Replay queue remains inactive with PID 0/restart count 0. Live-paper supervisor remains PID 709504/restart count 0 and its current worker PID 774150/restart count 0. `qpx.slice` was 553,791,488 B, zero swap, 2 GiB maximum at final check.
- Removed only the generated benchmark directories after recording measurements: `/tmp/qpx-v3-evidence-benchmark-20260922` (67 MB) and `/home/ron/QPX_ALPHA/runtime/v3-evidence-measurement.hDXnwZ` (16 MB). They contained no source cache or run evidence and are not recoverable; the completed run directories were read-only inputs.

### Push/deployment follow-up — 2026-09-22

- User authorized preserving `e306be256d1492f67fe6c7974e9ec415f5e641ba` and
  creating a separate follow-up commit rather than rewriting it.
- Follow-up scope is limited to required recovery prompt/decision-ledger
  continuity, the previously implemented V3 queue/controller/configuration,
  queue and aggregate `qpx.slice` systemd controls, six existing service-unit
  `Slice=qpx.slice` bindings, focused queue tests, and this journal update.
- Unrelated service edits, runtime state, prior journal material, and queue
  runtime artifacts remain excluded. The queue must stay inactive and live paper
  must not be restarted or modified.
