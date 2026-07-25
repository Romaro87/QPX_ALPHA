from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
ADR = ROOT / "docs" / "adr"
ADR.mkdir(parents=True, exist_ok=True)

content = textwrap.dedent("""
# ADR-0004: Standardize Python Package Execution

**Status:** Accepted

**Date:** 2026-07-25

---

# Context

As the project structure evolved, tests were moved into a dedicated
`tests/` package.

Running test files directly caused Python to lose the project root
from its import path, resulting in errors such as:

ModuleNotFoundError: No module named 'core'

This behavior is expected when scripts inside a package are executed
directly.

---

# Decision

QPX_ALPHA adopts Python package execution as the project standard.

Tests shall be executed using:

python -m tests.test_config

python -m tests.test_logger

python -m tests.test_event_bus

rather than executing the files directly.

The unified test runner shall execute all tests using module execution.

---

# Rationale

Package execution preserves the project root in Python's import system.

This allows imports such as:

from core.logger import get_logger

without modifying sys.path or relying on environment variables.

---

# Alternatives Considered

• Adding sys.path hacks to every test.

Rejected because it introduces hidden behavior.

• Setting PYTHONPATH manually.

Rejected because it complicates development.

• Executing tests as modules.

Accepted because it follows standard Python packaging practices.

---

# Consequences

Positive

• Cleaner imports

• Better IDE compatibility

• Simpler packaging

• Easier migration to pytest

• No path manipulation

Negative

• Developers must use module execution for tests.

---

# Engineering Rule

No module shall modify sys.path.

The project structure shall solve import problems rather than runtime hacks.

---

# Notes

This ADR establishes the official execution model for all future
QPX_ALPHA development.
""").strip()

path = ADR / "ADR-0004-standardize-python-package-execution.md"
path.write_text(content + "\n", encoding="utf-8")

print("=" * 60)
print("ADR-0004 Created")
print("=" * 60)
print(path)