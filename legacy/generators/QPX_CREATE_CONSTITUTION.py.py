from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
DOCS = ROOT / "docs"

DOCS.mkdir(parents=True, exist_ok=True)

FILES = {

"PROJECT_CHARTER.md": """
# QPX_ALPHA PROJECT CHARTER

Version: 2.0

---

# Vision

QPX_ALPHA exists to become a professional-grade quantitative trading platform
built on engineering excellence, modular architecture, quantitative research,
and artificial intelligence.

The platform shall evolve through disciplined engineering rather than
uncontrolled feature growth.

---

# Mission

Build software that is:

• Reliable

• Modular

• Extensible

• Testable

• Documented

• AI Assisted

• Production Ready

---

# Core Principles

1. Architecture First

Every feature must support the architecture.

Architecture always wins.

---

2. Stability Before Expansion

Working systems are improved carefully.

Never sacrifice stability for unnecessary features.

---

3. One Responsibility

Every module has one purpose.

Large scripts become collections of focused modules.

---

4. Quality Over Quantity

A smaller number of excellent modules is preferred over
hundreds of disconnected scripts.

---

5. Version Everything

Every milestone is:

Designed

Implemented

Tested

Documented

Committed

Released

---

6. Engineering Discipline

Every change should make QPX_ALPHA:

Simpler

Stronger

Cleaner

More Valuable

---

# Golden Rule

No code enters QPX_ALPHA unless it makes the platform
simpler, stronger, or more valuable.

---

# Motto

Engineer with purpose.

Trade with intelligence.

Build for tomorrow.
""",

"ARCHITECTURE.md": """
# Architecture

Application

↓

Core

↓

Trading Engines

↓

Analytics

↓

Persistence

---

Application

Dashboard

CLI

Launcher

AI Assistant

---

Core

Configuration

Logging

Health

Scheduler

Events

---

Trading Engines

Data

Feature

Signal

Portfolio

Risk

Execution

Backtesting

---

Analytics

Performance

Optimization

Statistics

Reports

---

Persistence

Database

Cache

Historical Data

Trade Journal

---

Rule

Business logic never belongs inside the UI.
""",

"ROADMAP.md": """
# Roadmap

Sprint 1

Platform Foundation

Sprint 2

Dashboard

Sprint 3

Strategy Center

Sprint 4

AI Portfolio Manager

Sprint 5

Autopilot

Future

Machine Learning

Cloud Deployment

Live Trading
""",

"ENGINEERING_HANDBOOK.md": """
# Engineering Handbook

Coding Standards

One responsibility per module.

Meaningful names.

Clear documentation.

Logging.

Error handling.

Testing.

Git Workflow

Design

↓

Implement

↓

Test

↓

Commit

↓

Push

↓

Release

Commit Messages

Implement launcher

Improve portfolio engine

Add dashboard

Refactor signal engine

Golden Rule

Leave the project better than you found it.
""",

"CHANGELOG.md": """
# Changelog

Version 2.0

Project Constitution Established

Architecture Standardized

Sprint Development Process Adopted
""",

"SESSION_LOG.md": """
# Session Log

Every session records

Date

Sprint

Completed Work

Current Task

Problems

Next Objective
""",

"DECISIONS.md": """
# Architectural Decisions

Every major architectural decision is documented here.

Decision Number

Date

Decision

Reason

Alternatives

Approved

Implementation Notes
""",

"MODULE_INDEX.md": """
# Module Index

Purpose

Dependencies

Inputs

Outputs

Status

Owner
""",

"README.md": """
# QPX_ALPHA

See docs/PROJECT_CHARTER.md first.

The charter defines the philosophy and engineering standards for the platform.
"""

}

for name, content in FILES.items():
    path = DOCS / name
    if path.exists():
        print(f"Skipping existing file: {name}")
    else:
        path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
        print(f"Created: {name}")

print()
print("=" * 50)
print("QPX_ALPHA Constitution Created")
print("=" * 50)
print(f"Location: {DOCS}")
print("Review the generated files before committing.")