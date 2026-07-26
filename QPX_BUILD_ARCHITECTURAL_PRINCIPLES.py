#!/usr/bin/env python3
"""
============================================================
QPX_BUILD_ARCHITECTURAL_PRINCIPLES.py

QPX_ALPHA Version 2.0
Release 2.0
Milestone 1

Creates:

docs/ARCHITECTURAL_PRINCIPLES.md
============================================================
"""

from pathlib import Path

DOCS = Path("docs")
DOCS.mkdir(exist_ok=True)

principles = r"""# QPX_ALPHA Architectural Principles
## Version 2.0

---

# Purpose

This document defines the engineering principles that guide
every architectural and implementation decision within
QPX_ALPHA.

These principles are subordinate only to the Constitution.

---

# Principle 1
## Platform Before Features

QPX_ALPHA shall be developed as a coherent investment
platform rather than a collection of independent scripts.

Every new capability should strengthen the platform.

---

# Principle 2
## Architecture Before Implementation

Architecture defines implementation.

Implementation must never redefine architecture.

Significant architectural changes require an ADR.

---

# Principle 3
## Builder-First Development

Whenever practical, new functionality shall be introduced
through builder scripts.

Builders ensure:

• Repeatability

• Consistency

• Documentation

• Maintainability

---

# Principle 4
## Configuration Over Hardcoding

Investment strategies, portfolio allocations, broker
connections, and platform behavior shall be configurable.

Business rules should not be embedded directly in source
code.

---

# Principle 5
## Modular Design

Every subsystem has one clearly defined responsibility.

Subsystems communicate through well-defined interfaces.

Modules should remain loosely coupled.

---

# Principle 6
## Event-Driven Architecture

Components should communicate through events whenever
appropriate.

This minimizes coupling and improves extensibility.

---

# Principle 7
## Explainability

Every recommendation, trade, rebalance, and report should
be explainable.

Users should always understand why the platform acted.

---

# Principle 8
## Deterministic Behavior

Identical inputs should produce identical outputs whenever
possible.

Backtests should be reproducible.

Results should be auditable.

---

# Principle 9
## Testability

Every subsystem should be testable independently.

Automated tests are required for significant features.

The platform should remain deployable after every milestone.

---

# Principle 10
## Documentation-Driven Development

Documentation is part of the implementation.

Documentation should evolve together with code.

---

# Principle 11
## Interface Independence

The platform should not depend upon a single:

• Broker

• Market Data Provider

• Strategy

• Database

• AI Provider

Every major dependency should be replaceable.

---

# Principle 12
## Human-Centered Automation

Automation exists to reduce repetitive work and improve
consistency.

Users remain responsible for approving strategy changes and
live trading decisions.

---

# Principle 13
## Progressive Validation

New investment strategies should progress through:

Research

↓

Backtesting

↓

Paper Trading

↓

Limited Live Trading

↓

Production

Each stage should produce measurable evidence before moving
to the next.

---

# Principle 14
## Continuous Improvement

QPX_ALPHA is designed to evolve.

The architecture should support future capabilities without
requiring major redesign.

Examples include:

• Multiple brokers

• Multiple portfolios

• Cryptocurrency

• Options

• Futures

• Mobile applications

• Cloud deployment

• AI strategy assistants

---

# Principle 15
## Professional Engineering

QPX_ALPHA shall prioritize:

Maintainability

Reliability

Transparency

Scalability

Security

Extensibility

Long-term sustainability

over short-term convenience.

---

End of Architectural Principles
"""

output = DOCS / "ARCHITECTURAL_PRINCIPLES.md"

with output.open("w", encoding="utf-8") as f:
    f.write(principles)

print("=" * 60)
print("ARCHITECTURAL PRINCIPLES INSTALLED")
print("=" * 60)
print(output.resolve())