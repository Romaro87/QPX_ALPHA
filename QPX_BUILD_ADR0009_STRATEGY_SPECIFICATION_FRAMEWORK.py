#!/usr/bin/env python3
"""
============================================================
QPX_BUILD_ADR0009_STRATEGY_SPECIFICATION_FRAMEWORK.py

QPX_ALPHA Version 2.0
Release 2.0
Milestone 2

Creates:

docs/adr/ADR-0009-STRATEGY-SPECIFICATION-FRAMEWORK.md
============================================================
"""

from pathlib import Path

ADR_DIR = Path("docs") / "adr"
ADR_DIR.mkdir(parents=True, exist_ok=True)

adr = r"""# ADR-0009
# Strategy Specification Framework

Status: Accepted

Date: 2026-07-25

---

# Context

QPX_ALPHA is designed to support many investment
strategies throughout its lifetime.

Embedding trading rules directly into source code
makes strategies difficult to understand, review,
version, and compare.

A structured specification framework is required.

---

# Problem

Without formal specifications:

• Trading logic becomes tightly coupled to code.

• Strategy reviews become difficult.

• Testing is inconsistent.

• Documentation falls behind implementation.

• Strategy evolution is difficult to manage.

---

# Decision

Every investment strategy shall be defined by a
Strategy Specification before implementation.

The specification becomes the authoritative description
of strategy behavior.

Implementations must remain consistent with the
approved specification.

---

# Required Specification Sections

Every strategy should define:

• Name

• Version

• Objective

• Investment Universe

• Time Horizon

• Strategy Profile

• Market Regime Assumptions

• Entry Rules

• Exit Rules

• Position Sizing

• Capital Allocation

• Risk Management

• Stop Loss Rules

• Profit Target Rules

• Reinvestment Policy

• Cash Management

• Tax Considerations

• Performance Metrics

• Backtesting Requirements

• Paper Trading Requirements

• Live Trading Requirements

---

# Strategy Lifecycle

Idea

↓

Specification

↓

Architecture Review

↓

Implementation

↓

Unit Testing

↓

Backtesting

↓

Paper Trading

↓

Limited Live Trading

↓

Production

Every stage should produce measurable evidence before
progressing to the next.

---

# Strategy Independence

The platform shall not assume a single investment style.

Supported examples include:

• Dividend Investing

• Swing Trading

• Position Trading

• Momentum

• Value Investing

• Growth Investing

• Income Investing

• Multi-Strategy Portfolios

---

# Version Control

Strategy Specifications shall be version controlled.

Changes to strategy behavior should be documented,
reviewed, and traceable.

---

# GUI Integration

Future GUI versions should allow users to:

Browse Specifications

View Revisions

Compare Versions

Clone Strategies

Export Specifications

Import Specifications

without modifying platform source code.

---

# Future Evolution

Future specifications may include:

Machine-readable formats

Validation schemas

Simulation parameters

Optimization metadata

AI-generated suggestions

while preserving human review and approval.

---

# Benefits

The framework provides:

Transparency

Consistency

Reviewability

Reproducibility

Maintainability

Strategy Portability

Long-term Governance

---

# Compliance

Every implemented strategy should remain consistent with:

Constitution

Project Charter

Platform Vision

Architectural Principles

ADR-0008 Strategy Profile Framework

---

End of ADR-0009
"""

output = ADR_DIR / "ADR-0009-STRATEGY-SPECIFICATION-FRAMEWORK.md"

with output.open("w", encoding="utf-8") as f:
    f.write(adr)

print("=" * 60)
print("ADR-0009 STRATEGY SPECIFICATION FRAMEWORK INSTALLED")
print("=" * 60)
print(output.resolve())