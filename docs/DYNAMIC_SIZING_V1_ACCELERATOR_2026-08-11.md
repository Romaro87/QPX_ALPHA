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

The complete causal, fixed-25% Challenger, provenance, and accelerator suite passed 69 tests with 0 failures.

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

## Chronological robustness

The unchanged V1 configuration fingerprint was `dab4dda61ffeeb93a85a46caac2d8c46125145a89230e9e6490751723178b328` in every run. All runs used the predefined account-sized periods, fixed 25% reference, frozen dataset, and full causal gates.

| Period | Arm | Ending equity | Return | CAGR | EOD DD | Intraday DD | Sharpe | Sortino | PF | Trades | Win rate | Risk rejects | Capacity | QDTE distributions |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024 | Fixed 25% | $4,758.53 | 229.69% | 327.30% | 18.72% | 20.43% | 3.1664 | 6.3854 | 1.4706 | 929 | 49.41% | 651 | 967 | $79.94 / 40 |
| 2024 | Dynamic V1 | $4,614.42 | 219.70% | 311.60% | 21.47% | 23.21% | 3.0902 | 6.3357 | 1.4500 | 955 | 49.42% | 514 | 1,054 | $79.18 / 40 |
| 2025 | Fixed 25% | $5,696.94 | 294.71% | 299.06% | 13.03% | 14.08% | 4.0555 | 8.4118 | 1.5367 | 1,173 | 51.15% | 1,069 | 2,095 | $118.22 / 52 |
| 2025 | Dynamic V1 | $4,946.82 | 242.73% | 246.13% | 13.29% | 14.02% | 3.6818 | 7.2490 | 1.4800 | 1,196 | 50.84% | 906 | 2,221 | $108.63 / 52 |
| 2026 | Fixed 25% | $2,942.00 | 103.83% | 230.81% | 14.23% | 15.12% | 2.1184 | 6.5252 | 1.3013 | 740 | 48.92% | 565 | 1,134 | $41.04 / 31 |
| 2026 | Dynamic V1 | $2,643.29 | 83.14% | 176.35% | 15.28% | 16.91% | 1.8671 | 5.9428 | 1.2464 | 731 | 47.61% | 503 | 1,191 | $40.02 / 31 |
| Through 2025 | Fixed 25% | $13,999.52 | 869.94% | 250.04% | 18.72% | 20.43% | 3.2327 | 6.5177 | 1.4644 | 2,100 | 50.57% | 1,850 | 3,066 | $364.17 / 92 |
| Through 2025 | Dynamic V1 | $14,777.50 | 923.84% | 260.63% | 21.47% | 23.21% | 3.3094 | 6.8095 | 1.5027 | 2,152 | 50.70% | 1,674 | 3,142 | $364.90 / 92 |

Dynamic decision diagnostics:

| Period | Decisions | Reduced | Unchanged | Below one share | Multipliers | Max notional | Max active risk |
|---|---:|---:|---:|---:|---|---:|---:|
| 2024 | 985 | 144 | 841 | 30 | 1.00: 841; 0.85: 136; 0.70: 8 | 24.999775% | $233.66 |
| 2025 | 1,237 | 177 | 1,060 | 41 | 1.00: 1,060; 0.85: 177 | 24.999938% | $174.11 |
| 2026 | 767 | 155 | 612 | 36 | 1.00: 612; 0.85: 154; 0.70: 1 | 24.998800% | $118.52 |
| Through 2025 | 2,195 | 211 | 1,984 | 43 | 1.00: 1,984; 0.85: 203; 0.70: 8 | 24.999775% | $465.50 |

Dynamic V1 beat the reference on return in one of four reported windows, on EOD drawdown in zero, and on intraday drawdown in one. The expanding window overlaps 2024 and 2025 and is not a fourth independent sample. Its favorable compounded result despite trailing in each independently restarted calendar partition shows strong path and starting-state dependence. These results do not support promotion or parameter revision.

The compact machine-readable record is `docs/research_results/DYNAMIC_SIZING_V1_CHRONOLOGICAL_ROBUSTNESS_2026-08-12.json`. Generated replay outputs remain under ignored `reports/qpx_dynamic_sizing_v1_robustness/` and are not part of the source commit.
