#!/usr/bin/env python3
"""
============================================================
QPX_BUILD_ADR0006_PLATFORM_TRANSITION.py

QPX_ALPHA Version 2.0
Release 2.0
Milestone 2

Creates:

docs/adr/ADR-0006-PLATFORM-TRANSITION.md
============================================================
"""

from pathlib import Path

ADR_DIR = Path("docs") / "adr"
ADR_DIR.mkdir(parents=True, exist_ok=True)

adr = r"""# ADR-0006
# Platform Transition

Status: Accepted

Date: 2026-07-25

---

# Context

QPX_ALPHA began as a Python framework for experimenting with
investment automation.

As development progressed, additional capabilities were
introduced including:

• Module Registry

• Service Registry

• Health Monitoring

• Event Bus

• Builder Scripts

• Testing Framework

• Governance Documents

The project evolved beyond a framework into a structured
software platform.

---

# Problem

Framework-oriented development encouraged independent
features but did not fully define:

• Long-term platform goals

• Product governance

• Architectural evolution

• Strategy lifecycle

• Future extensibility

Without a formal transition, future development risked
becoming inconsistent.

---

# Decision

QPX_ALPHA shall become a modular quantitative investment
platform.

The platform will support multiple investment workflows
rather than a single hard-coded trading bot.

Examples include:

• Dividend Investing

• Swing Trading

• Position Trading

• Portfolio Management

• Strategy Research

• Backtesting

• Paper Trading

• Live Trading

The platform itself remains independent of any specific
investment strategy.

---

# Consequences

Future development will emphasize:

• Modular architecture

• Configurable strategies

• Replaceable services

• Professional governance

• Documentation-first development

• Builder-first implementation

• Test-driven validation

---

# Architectural Impacts

The platform introduces distinct subsystems including:

• GUI

• Strategy Engine

• Portfolio Engine

• Market Data Engine

• Risk Engine

• Execution Engine

• Analytics Engine

• AI Services

Each subsystem shall evolve independently while remaining
compatible through defined interfaces.

---

# Benefits

The transition provides:

• Better maintainability

• Clear governance

• Long-term scalability

• Strategy independence

• Easier testing

• Professional architecture

• Future extensibility

---

# Alternatives Considered

Continue as a collection of scripts.

Rejected because it limits maintainability,
documentation, and long-term growth.

Continue as a lightweight framework.

Rejected because the project's objectives now extend
well beyond framework responsibilities.

---

# Implementation Plan

Release 2.0

Governance modernization.

Platform architecture.

Architecture Decision Records.

Release 2.x

GUI.

Strategy Framework.

Portfolio Engine.

Backtesting.

Paper Trading.

Release 3.x

Broker Integration.

Production Automation.

Advanced Analytics.

---

# Compliance

Future architectural decisions should remain consistent
with:

• Constitution

• Project Charter

• Platform Vision

• Architectural Principles

---

End of ADR-0006
"""

output = ADR_DIR / "ADR-0006-PLATFORM-TRANSITION.md"

with output.open("w", encoding="utf-8") as f:
    f.write(adr)

print("=" * 60)
print("ADR-0006 PLATFORM TRANSITION INSTALLED")
print("=" * 60)
print(output.resolve())