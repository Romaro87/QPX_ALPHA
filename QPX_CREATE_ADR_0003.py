from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
ADR = ROOT / "docs" / "adr"

ADR.mkdir(parents=True, exist_ok=True)

content = textwrap.dedent("""
# ADR-0003: Unified Application Launcher

**Status:** Accepted

**Date:** 2026-07-25

---

# Context

QPX_ALPHA has evolved through many development stages.

As the project grew, multiple entry scripts were introduced for different
purposes, including system startup, automation, testing, monitoring,
backtesting, and maintenance.

Although functional, this approach has several disadvantages:

- difficult navigation
- duplicated startup logic
- inconsistent user experience
- growing maintenance cost

A professional platform should have one clear entry point.

---

# Decision

The project shall adopt a Unified Application Launcher.

The launcher becomes the primary interface between the user and every
major subsystem.

Existing scripts are not removed immediately.

Instead, they are migrated behind the launcher in phases.

This minimizes risk while allowing continuous improvement.

---

# Goals

The launcher shall provide access to:

• Dashboard

• Market Data

• Strategy Center

• Paper Trading

• Backtesting

• Portfolio

• Analytics

• Reports

• AI Assistant

• Settings

• System Health

---

# Non-Goals

This ADR does not redesign trading engines.

This ADR does not replace existing business logic.

This ADR establishes navigation and orchestration only.

---

# Migration Strategy

Phase 1

Create launcher framework.

Phase 2

Connect existing modules.

Phase 3

Retire duplicate entry scripts.

Phase 4

Launcher becomes the official startup interface.

---

# Consequences

Positive

- Single startup point.

- Consistent workflow.

- Easier documentation.

- Cleaner architecture.

- Lower maintenance cost.

Negative

- Requires gradual migration.

- Existing startup scripts remain temporarily.

---

# Success Criteria

The launcher becomes the recommended way to start QPX_ALPHA.

All major capabilities are accessible from one interface.

Future modules integrate through the launcher rather than becoming
independent scripts.

---

# Notes

This ADR marks the beginning of the transition from a script collection
to a cohesive software platform.

Future ADRs will define the launcher architecture and service interfaces.
""").strip()

path = ADR / "ADR-0003-unified-launcher.md"
path.write_text(content + "\n", encoding="utf-8")

print("=" * 60)
print("ADR-0003 Created")
print("=" * 60)
print(path)