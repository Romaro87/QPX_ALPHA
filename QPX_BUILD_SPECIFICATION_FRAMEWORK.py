#!/usr/bin/env python3
"""
============================================================
QPX_BUILD_SPECIFICATION_FRAMEWORK.py

QPX_ALPHA Version 2.0
Sprint 5
Milestone 3

Creates the platform Specification Framework.
============================================================
"""

from pathlib import Path

ROOT = Path("specifications")

folders = {
    "platform": "Platform-wide specifications.",
    "strategies": "Trading strategy specifications.",
    "portfolio": "Portfolio engine specifications.",
    "risk": "Risk engine specifications.",
    "execution": "Trade execution specifications.",
    "broker": "Broker integration specifications.",
    "market_data": "Market data specifications.",
    "analytics": "Analytics engine specifications.",
    "gui": "Graphical user interface specifications.",
    "ai": "Artificial intelligence specifications.",
}

ROOT.mkdir(exist_ok=True)

root_readme = """# QPX_ALPHA Specifications

This directory contains the functional specifications for
every major subsystem of QPX_ALPHA.

Hierarchy

Governance
    ↓
Architecture
    ↓
Specifications
    ↓
Builders
    ↓
Implementation
    ↓
Testing

Every production subsystem should have an approved
specification before implementation.
"""

(ROOT / "README.md").write_text(root_readme, encoding="utf-8")

for name, description in folders.items():
    folder = ROOT / name
    folder.mkdir(exist_ok=True)

    readme = f"""# {name.replace('_',' ').title()}

{description}

Future specifications placed in this directory should define:

• Purpose

• Scope

• Functional Requirements

• Non-Functional Requirements

• Interfaces

• Validation Requirements

• Future Enhancements
"""

    (folder / "README.md").write_text(readme, encoding="utf-8")

print("=" * 60)
print("SPECIFICATION FRAMEWORK INSTALLED")
print("=" * 60)

print()

for folder in folders:
    print(ROOT / folder)