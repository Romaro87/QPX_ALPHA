#!/usr/bin/env python3
"""
============================================================
QPX_BUILD_ADR0007_BUILDER_ENGINE.py

QPX_ALPHA Version 2.0
Release 2.0
Milestone 2

Creates:

docs/adr/ADR-0007-BUILDER-ENGINE.md
============================================================
"""

from pathlib import Path

ADR_DIR = Path("docs") / "adr"
ADR_DIR.mkdir(parents=True, exist_ok=True)

adr = r"""# ADR-0007
# Builder Engine and Engineering Workflow

Status: Accepted

Date: 2026-07-25

---

# Context

QPX_ALPHA has adopted Builder-First Development to ensure
that architectural changes are repeatable, documented,
reviewable, and consistently implemented.

Builder scripts have become the primary mechanism for
creating platform components and governance documents.

This ADR formally establishes the Builder Engine as part
of the platform architecture.

---

# Problem

Without a standardized engineering workflow,
development can become inconsistent.

Different contributors may:

• Skip documentation

• Bypass architectural review

• Implement incompatible solutions

• Introduce unnecessary technical debt

A formal process is required.

---

# Decision

QPX_ALPHA adopts the following engineering workflow.

Idea

↓

Governance Review

↓

Architecture Decision Record (ADR)

↓

Functional Specification

↓

Builder Script

↓

Generated Implementation

↓

Automated Testing

↓

Doctor Validation

↓

Git Commit

↓

Git Push

↓

Release

Every significant platform feature shall follow this
workflow.

---

# Builder Engine Responsibilities

The Builder Engine exists to create and maintain
consistent project assets.

Builders may generate:

• Documentation

• Configuration

• Templates

• Source Code

• Tests

• Project Structure

• Specifications

Builders should be deterministic and safe to rerun.

---

# Builder Standards

Each builder should:

• Have a single responsibility

• Produce predictable output

• Be idempotent whenever practical

• Display completion status

• Be version controlled

• Include descriptive headers

---

# Repository Organization

Builder scripts should eventually be organized into
functional groups.

Example:

builders/

    governance/

    architecture/

    platform/

    strategy/

    gui/

    ai/

    utilities/

The project root should remain focused on the platform.

---

# Engineering Principles

Builder scripts shall never replace governance.

Builders implement architecture.

Architecture governs builders.

---

# Documentation Requirements

Every builder should identify:

Purpose

Inputs

Outputs

Files Created

Files Updated

Validation Steps

Expected Results

---

# Validation Requirements

Every milestone should conclude with:

Doctor Validation

Automated Tests

Git Status

Commit

Push

A milestone is not complete until validation succeeds.

---

# Future Evolution

The Builder Engine may eventually support:

• Interactive builders

• GUI builders

• Configuration-driven builders

• Plugin builders

• AI-assisted builders

while remaining compatible with this workflow.

---

# Consequences

Benefits include:

• Consistency

• Repeatability

• Documentation

• Easier onboarding

• Better maintainability

• Traceable implementation

---

# Compliance

This workflow applies to:

Platform Services

Trading Engines

Portfolio Management

GUI

Artificial Intelligence

Backtesting

Paper Trading

Broker Integrations

Risk Management

Analytics

---

End of ADR-0007
"""

output = ADR_DIR / "ADR-0007-BUILDER-ENGINE.md"

with output.open("w", encoding="utf-8") as f:
    f.write(adr)

print("=" * 60)
print("ADR-0007 BUILDER ENGINE INSTALLED")
print("=" * 60)
print(output.resolve())