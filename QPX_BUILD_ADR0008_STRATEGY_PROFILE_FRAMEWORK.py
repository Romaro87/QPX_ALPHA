#!/usr/bin/env python3
"""
============================================================
QPX_BUILD_ADR0008_STRATEGY_PROFILE_FRAMEWORK.py

QPX_ALPHA Version 2.0
Release 2.0
Milestone 2

Creates:

docs/adr/ADR-0008-STRATEGY-PROFILE-FRAMEWORK.md
============================================================
"""

from pathlib import Path

ADR_DIR = Path("docs") / "adr"
ADR_DIR.mkdir(parents=True, exist_ok=True)

adr = r"""# ADR-0008
# Strategy Profile Framework

Status: Accepted

Date: 2026-07-25

---

# Context

QPX_ALPHA is designed as a multi-strategy investment
platform.

Different strategies have different objectives,
risk tolerances, holding periods, capital allocation
rules, and execution characteristics.

Hardcoding these characteristics into the platform
would reduce flexibility and maintainability.

---

# Problem

Without standardized strategy profiles:

• Risk management becomes inconsistent.

• Portfolio behavior varies unpredictably.

• Strategies cannot be compared objectively.

• Users must repeatedly configure common settings.

---

# Decision

QPX_ALPHA shall introduce Strategy Profiles.

A Strategy Profile defines the operational behavior
of a strategy without defining the strategy logic itself.

Trading rules remain part of the Strategy Specification.

---

# Standard Strategy Profiles

Conservative

Balanced

Growth

Aggressive

Income

Experimental

Custom

---

# Profile Responsibilities

A Strategy Profile may define:

• Risk tolerance

• Maximum portfolio exposure

• Maximum position size

• Maximum active risk

• Default stop methodology

• Default profit methodology

• Position scaling

• Cash reserve targets

• Reinvestment policy

• Capital allocation policy

---

# Strategy Independence

Profiles shall never define:

Entry Rules

Exit Rules

Indicators

Market Selection

Signal Generation

These belong to the Strategy Specification.

---

# Portfolio Integration

The Portfolio Engine should be capable of managing
multiple strategies simultaneously.

Each strategy may operate under its own Strategy Profile.

Examples:

Income Portfolio

Growth Portfolio

Swing Trading Portfolio

Dividend Portfolio

Experimental Portfolio

---

# Risk Management

Profiles establish default limits.

Examples include:

Maximum Portfolio Risk

Maximum Trade Risk

Maximum Simultaneous Positions

Maximum Sector Exposure

Cash Reserve Targets

These limits may be refined by individual strategies.

---

# GUI Integration

Future versions of the GUI should allow users to:

View Strategy Profiles

Create Profiles

Modify Profiles

Assign Profiles

Compare Profiles

Import and Export Profiles

without modifying source code.

---

# Future Expansion

Future profiles may support:

Options

Futures

Cryptocurrency

International Markets

Alternative Assets

Multi-Currency Portfolios

---

# Benefits

Strategy Profiles provide:

Consistency

Reusability

Configurability

Simplified Risk Management

Cleaner Architecture

Reduced Code Duplication

---

# Compliance

Strategy Profiles shall operate under:

Constitution

Project Charter

Platform Vision

Architectural Principles

Builder Engine Workflow

Strategy Specifications

---

End of ADR-0008
"""

output = ADR_DIR / "ADR-0008-STRATEGY-PROFILE-FRAMEWORK.md"

with output.open("w", encoding="utf-8") as f:
    f.write(adr)

print("=" * 60)
print("ADR-0008 STRATEGY PROFILE FRAMEWORK INSTALLED")
print("=" * 60)
print(output.resolve())