# Fixed 25% Challenger strict-causal qualification

Status: `PASS` for formal strict-causal research qualification. This is not production approval.

The immutable reference is Candidate V1 commit `7213db1e17fedce9e923889b116775cca121f766`. The frozen dataset fingerprint is `8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8`.

The separate Challenger changes only maximum position notional to exactly 25% and the account-sized starting state to QDTE $1,438.00 plus swing cash $5.34, for total starting equity of $1,443.34. Candidate V1 strategy logic is unchanged.

## Verification

- Focused causal and Challenger isolation suite: 28 passed, 0 failed.
- Two complete strict-causal replays produced identical summary metrics, dataset fingerprint, causal gates, and SHA-256 hashes for trades, equity, signals, and allocations.
- All strict causal gates passed, including dividend entitlement, later-of-payable/process-date cash release, data cutoff, execution phase, future/current-bar blocking, indicator-prefix and strategy equivalence, missing-symbol behavior, strict recorded-union clock, look-ahead protection, and no synthetic future data.
- The predefined 2024, 2025, 2026-through-frozen-end, and expanding-through-2025 results exactly reproduced the preserved chronological robustness evidence.

## Full-period result

- Ending equity: $27,880.67
- Net profit: $26,437.33
- Total return: 1,831.68%
- CAGR: 241.87%
- EOD maximum drawdown: 18.72%
- Intraday maximum drawdown: 20.43%
- Sharpe: 2.7946
- Sortino: 6.7313
- Profit factor: 1.4062
- Closed trades: 2,874
- Win rate: 49.93%
- QDTE distributions: $726.46 across 124 events
- Risk rejections: 2,593
- Capacity deferrals: 4,221

Generated qualification artifacts remain under `reports/qpx_challenger_25pct_qualification_v1/` and are intentionally ignored pending review.
