#!/usr/bin/env python3
"""
============================================================
QPX_BUILD_PROJECT_CHARTER_V2.py

QPX_ALPHA Version 2.0
Release 2.0
Platform Transition

Creates:

docs/PROJECT_CHARTER.md
============================================================
"""

from pathlib import Path

DOCS = Path("docs")
DOCS.mkdir(exist_ok=True)

charter = r"""# QPX_ALPHA Project Charter
## Version 2.0

---

# Executive Summary

QPX_ALPHA is a modular quantitative investment platform
designed to research, simulate, evaluate, and automate
rule-based investment strategies through a governed,
testable, and explainable architecture.

The platform emphasizes transparency, reproducibility,
modularity, and long-term maintainability.

---

# Mission

Develop a professional investment operating system that
allows investors to confidently design, validate,
backtest, paper trade, and automate investment
strategies while maintaining complete visibility into
every decision made by the platform.

---

# Vision

QPX_ALPHA will evolve into a complete investment
platform capable of supporting:

• Portfolio Management

• Dividend Investing

• Swing Trading

• Strategy Development

• Strategy Research

• Backtesting

• Paper Trading

• Live Trading

• Portfolio Analytics

• Artificial Intelligence Assistance

---

# Product Definition

QPX_ALPHA is not a single trading bot.

It is a modular investment platform capable of hosting
multiple investment strategies through a common,
well-governed architecture.

---

# Primary Stakeholders

## Platform Owner

Responsible for:

• Product direction

• Investment philosophy

• Platform approval

• Production deployment

---

## Platform Architect

Responsible for:

• Architecture

• Governance

• Builder methodology

• Technical design

• Documentation

• Long-term maintainability

---

## Platform Operator

Responsible for:

• Configuring strategies

• Running simulations

• Monitoring performance

• Reviewing analytics

• Approving live execution

---

# Objectives

The project will provide:

• Professional architecture

• Configurable strategies

• Reliable backtesting

• Paper trading

• Risk management

• Portfolio management

• Trade execution

• Analytics

• Explainable automation

---

# Product Scope

Included

• Modular platform

• GUI

• Strategy engine

• Portfolio engine

• Risk engine

• Market data

• Analytics

• Builder engine

• AI assistance

Excluded

• Guaranteed investment returns

• Prediction without supporting data

• Hidden trading logic

• Unexplained automated decisions

---

# Success Criteria

The platform shall:

• Build successfully

• Pass automated tests

• Validate through Doctor

• Maintain documentation

• Support modular expansion

• Remain architecture driven

---

# Development Methodology

Every feature follows:

Architecture

↓

ADR

↓

Builder Script

↓

Implementation

↓

Testing

↓

Doctor Validation

↓

Git Commit

↓

Git Push

---

# Definition of Done

A milestone is complete only when:

✓ Documentation updated

✓ Tests passing

✓ Doctor passes

✓ Code reviewed

✓ Git committed

✓ Git pushed

---

# Long-Term Vision

Version 2.x establishes the platform.

Version 3.x introduces broker integration,
advanced analytics, and production-ready
automation.

Future versions may introduce additional
capabilities while remaining faithful to
the architectural principles established by
the Constitution and ADRs.

---

End of Project Charter
"""

output = DOCS / "PROJECT_CHARTER.md"

with output.open("w", encoding="utf-8") as f:
    f.write(charter)

print("=" * 60)
print("PROJECT CHARTER VERSION 2 INSTALLED")
print("=" * 60)
print(output.resolve())