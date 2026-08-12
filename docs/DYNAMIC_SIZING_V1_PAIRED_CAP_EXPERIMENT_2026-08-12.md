# Dynamic Sizing V1 Paired Hard-Cap Experiment

Status: controlled research result; not qualified or approved for production.

The unchanged V1 tier algorithm was tested at hard caps 25%, 40%, 60%, and 90%, each against its matching fixed-cap control. Only the hard cap and deterministic configuration identity varied. The original `dynamic_sizing_v1.json` remained byte-identical.

## Full-period results

| Arm | Ending equity | Return | CAGR | EOD DD | Intraday DD | Sharpe | Sortino | PF | Trades | Win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fixed 25 | $27,880.67 | 1,831.68% | 241.87% | 18.72% | 20.43% | 2.7946 | 6.7313 | 1.4062 | 2,874 | 49.93% |
| Dynamic 25 | $28,465.83 | 1,872.22% | 244.83% | 21.47% | 23.21% | 2.7901 | 6.8535 | 1.3946 | 2,943 | 49.98% |
| Fixed 40 | $22,984.07 | 1,492.42% | 215.53% | 30.08% | 31.15% | 2.4328 | 5.4396 | 1.4021 | 2,462 | 49.43% |
| Dynamic 40 | $25,335.43 | 1,655.33% | 228.55% | 34.04% | 34.46% | 2.5079 | 5.6537 | 1.3839 | 2,482 | 49.19% |
| Fixed 60 | $14,243.26 | 886.83% | 158.68% | 40.51% | 41.45% | 1.9775 | 3.8914 | 1.2722 | 2,283 | 49.63% |
| Dynamic 60 | $19,848.31 | 1,275.17% | 196.89% | 36.05% | 36.47% | 2.2759 | 4.3995 | 1.2844 | 2,296 | 49.52% |
| Fixed 90 | $13,355.55 | 825.32% | 151.86% | 42.97% | 44.53% | 1.8926 | 3.5774 | 1.2170 | 1,994 | 49.85% |
| Dynamic 90 | $17,599.19 | 1,119.34% | 182.43% | 41.94% | 43.00% | 2.1278 | 4.0693 | 1.2649 | 2,141 | 50.44% |

## Interpretation

Across the five reported windows (full, 2024, 2025, 2026, and expanding through 2025), Dynamic beat its fixed control on return/EOD drawdown/intraday drawdown respectively: 25% = 2/0/1, 40% = 3/2/2, 60% = 3/3/3, and 90% = 5/4/4. The expanding window overlaps the calendar partitions.

The same rule becomes more interventionist with concentration headroom: full-period decisions reduced were 8.27% at 25%, 12.03% at 40%, 20.11% at 60%, and 23.74% at 90%. Dynamic 60 and 90 improved both return and drawdown against their full-period controls, but absolute risk remained materially worse than Dynamic 25. Dynamic 25 retained the highest ending equity and lowest drawdown among the four Dynamic arms.

Full-period worst losses were RIVN -$685 (Dynamic 25), AMC -$759 (Dynamic 40), VSAT -$1,328 (Dynamic 60), and AMC -$728 (Dynamic 90). These were also overnight-gap losses except Dynamic 40, whose worst gap was GME -$644. Dynamic sizing did not monotonically suppress worst single-trade or gap loss as cap headroom increased.

Every run used starting QDTE $1,438.00, swing cash $5.34, total equity $1,443.34, the frozen 102-symbol universe, dataset fingerprint `8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8`, and `FULL_CAUSAL_ACCOUNTING_PASS`.

The complete compact matrix, configuration fingerprints, causal gates, period metrics, decision distributions, rejection diagnostics, and loss/exposure records are in `docs/research_results/DYNAMIC_SIZING_V1_PAIRED_CAP_MATRIX_2026-08-12.json`. Raw ledgers remain ignored under `reports/qpx_dynamic_sizing_v1_paired_caps/`.
