#!/usr/bin/env python3
"""
============================================================
QPX_BUILD_HYBRID_STRATEGY_SPEC.py

QPX_ALPHA
Sprint 5
Milestone 3

Creates:

specifications/strategies/
    hybrid_dividend_swing_v1/
        specification.md
============================================================
"""

from pathlib import Path

ROOT = (
    Path("specifications")
    / "strategies"
    / "hybrid_dividend_swing_v1"
)

ROOT.mkdir(parents=True, exist_ok=True)

spec = """# Hybrid Dividend + Swing Strategy

Version: 1.0

Status:
Draft

------------------------------------------------------------

## Objective

Generate long-term capital appreciation while building
an expanding dividend income stream.

The strategy combines:

• High-yield dividend investing

• Momentum swing trading

• Dynamic capital allocation

• Risk-managed position sizing

------------------------------------------------------------

## Long-Term Goal

Target:

$1,000,000 Portfolio Value

using disciplined investing,
systematic trading,
and continuous compounding.

------------------------------------------------------------

## Investment Universe

Primary Holdings

QDTE

Liquid U.S. Equities

Minimum Average Daily Volume

2,000,000 shares

------------------------------------------------------------

## Portfolio Allocation

Years 1–2

65%

Dividend Portfolio

35%

Swing Trading

After Year 2

40%

Dividend Portfolio

60%

Swing Trading

------------------------------------------------------------

## Capital Sources

Initial Capital

User Configurable

Monthly Contributions

User Configurable

Dividend Payments

Automatically reinvested according
to allocation rules.

------------------------------------------------------------

## Dividend Policy

Maintain target allocation
to the dividend portfolio.

Use remaining dividend cash
to increase swing trading liquidity
according to allocation rules.

------------------------------------------------------------

## Swing Trading Overview

Primary Trend

200 SMA Positive

Entry Confirmation

9 EMA

21 EMA

RSI / RMI

Volume Confirmation

Exit

ATR Stop

ATR Profit Target

Trailing Stop

------------------------------------------------------------

## Risk Management

Quarter Kelly sizing

Maximum portfolio risk

Maximum active risk

Maximum position size

Cash reserve management

------------------------------------------------------------

## Market Filters

Suspend new swing entries
during elevated volatility.

------------------------------------------------------------

## Tax Management

Maintain configurable tax reserve.

Tax rules remain configurable
for different jurisdictions.

------------------------------------------------------------

## Required Platform Engines

Portfolio Engine

Risk Engine

Strategy Engine

Execution Engine

Analytics Engine

Backtesting Engine

Paper Trading Engine

------------------------------------------------------------

## Performance Metrics

CAGR

Sharpe Ratio

Maximum Drawdown

Win Rate

Profit Factor

Income Growth

Dividend Growth

Tax Efficiency

------------------------------------------------------------

## Status

Draft

End of Specification
"""

(ROOT / "specification.md").write_text(spec, encoding="utf-8")

print("=" * 60)
print("HYBRID STRATEGY SPECIFICATION CREATED")
print("=" * 60)
print(ROOT.resolve())