# Dynamic Sizing V1 Accelerator Challenger

Status: research Challenger; not qualified or approved for production.

## Immutable references

- Candidate V1: `7213db1e17fedce9e923889b116775cca121f766`
- Qualified fixed-25% reference: `bba0f48273815ede42374015db7c5770bf446962`
- Development base: `2cab84accdfe79faa8097b7fdb976da46d8dbde5`
- Frozen dataset: `8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8`
- Starting state: QDTE $1,438.00, swing cash $5.34, total equity $1,443.34
- Universe: frozen ordered Top 100 plus QDTE and XLE (102 symbols)

## Architecture and policy

Dynamic Sizing is an isolated, reduction-only post-qualification layer. It receives an immutable scalar context after the qualified strategy has generated, ranked, selected, risk-sized, and capped a trade. It receives no portal, history, bar collection, ranking collection, or future-facing object.

The V1 multiplier uses pre-entry active portfolio risk utilization only:

- utilization below 0.25: 1.00
- utilization from 0.25 to below 0.50: 0.85
- utilization from 0.50 to below 0.75: 0.70
- utilization at or above 0.75: 0.50

`floor(base requested shares × multiplier)` is re-constrained by the base share count, 25% decision-equity notional ceiling, available swing cash, remaining active-risk budget, six-position limit, and one-share feasibility. The accelerator cannot revive a rejected trade. Disabled mode returns the qualified base share count unconditionally.

Each enabled decision has a deterministic ID and durable CSV record. Every opened position receives an immutable entry snapshot in isolated experiment state containing the accelerator/configuration versions, decision ID, multiplier, base shares, and final shares. Qualified portfolio and runner files remain unchanged.

## Validation

The complete causal, fixed-25% Challenger, provenance, and accelerator suite passed 63 tests with 0 failures.

Disabled full replay equivalence passed exactly:

- trades: `316c49ab69bf8babdf0a7fd79707e3ee82dc80c1e7a813ca6add19e36cb41edb`
- equity: `8ef53746573033b0b20f7e788eb309520e07d8779afff005f1eb2b89d6b87571`
- signals: `ecb1c62aca1d17282254526e13fe09d7ec0dc7eea1a88e9a11529dd2c15a7aa9`
- allocations: `90ac573027339208ec4af6d91e0d86413a2cef1cf1e4636bf9b264afa84f8d28`
- complete result object and causal-gate object: identical
- dataset fingerprint and 102-symbol universe: identical

## Single enabled replay

No parameters were changed after observing these results.

| Metric | Qualified fixed-25% | Dynamic Sizing V1 | Difference |
|---|---:|---:|---:|
| Ending equity | $27,880.67 | $28,465.83 | +$585.15 |
| Net profit | $26,437.33 | $27,022.49 | +$585.15 |
| Total return | 1,831.68% | 1,872.22% | +40.54 pp |
| CAGR | 241.87% | 244.83% | +2.96 pp |
| EOD maximum drawdown | 18.72% | 21.47% | +2.74 pp |
| Intraday maximum drawdown | 20.43% | 23.21% | +2.78 pp |
| Sharpe | 2.7946 | 2.7901 | -0.0045 |
| Sortino | 6.7313 | 6.8535 | +0.1222 |
| Profit factor | 1.4062 | 1.3946 | -0.0116 |
| Closed trades | 2,874 | 2,943 | +69 |
| Win rate | 49.93% | 49.98% | +0.05 pp |
| QDTE distributions | $726.46 / 124 | $757.25 / 124 | +$30.79 / 0 |
| Risk rejections | 2,593 | 2,334 | -259 |
| Capacity deferrals | 4,221 | 4,356 | +135 |

Enabled sizing diagnostics:

- decisions: 2,988
- reduced: 247
- unchanged: 2,741
- blocked below one share: 45
- multipliers: 1.00 = 2,741; 0.85 = 239; 0.70 = 8; 0.50 = 0
- maximum observed entry notional: 24.999993% of decision-time equity
- maximum observed active portfolio risk: $1,145.72
- causal status: `FULL_CAUSAL_ACCOUNTING_PASS`

The single replay is mixed evidence: ending equity and Sortino increased, while both drawdown measures worsened, Sharpe decreased slightly, and profit factor declined. It is an unbiased first Challenger result, not evidence of robustness or qualification.

Generated replay outputs remain under ignored `reports/qpx_dynamic_sizing_v1/` and are not part of the source commit.
