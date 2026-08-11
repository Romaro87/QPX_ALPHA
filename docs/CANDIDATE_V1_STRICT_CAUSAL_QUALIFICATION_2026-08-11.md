# Candidate V1 Strict-Causal Qualification — 2026-08-11

Candidate V1 achieved `FULL_CAUSAL_ACCOUNTING_PASS` in the strict-causal Top-100 replay. This qualification confirms the defined historical causal-accounting gates; it does not constitute production approval.

## Validation record

- Focused causal-dividend tests: 15 passed, 0 failed.
- Enriched QDTE dataset fingerprint: `8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8`.
- Authenticated QDTE dividend events: 124.
- Dividend settlement policy: entitlement is captured from shares owned at the ex-date open, and cash becomes available at the first recorded market open on or after the later of the payable or process date.
- Source baseline before this work: commit `ab30b04efaa380086fe09aa37f08db9a78fc80f0`.

## Strict-causal result

| Metric | Result |
| --- | ---: |
| Ending equity | $17,370.70 |
| Net profit | $16,070.70 |
| CAGR | 193.37% |
| Maximum drawdown | 38.66% |
| Sharpe ratio | 2.1671 |
| Sortino ratio | 4.2198 |
| Profit factor | 1.3199 |
| Closed trades | 1,994 |
| QDTE distributions | $552.01 across 124 events |

The preserved non-strict control ended with equity of $16,485.76.

Generated qualification reports under `reports/` and frozen provider/replay data under `research_data/` remain intentionally ignored and are not part of the durable source commit.
