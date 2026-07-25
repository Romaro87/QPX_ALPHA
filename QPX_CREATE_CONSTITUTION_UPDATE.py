from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
DOCS = ROOT / "docs"
DOCS.mkdir(parents=True, exist_ok=True)

constitution = textwrap.dedent("""
# QPX_ALPHA CONSTITUTION

Version: 1.0

Ratified: Sprint 1 – Foundation

---

# Purpose

This Constitution is the highest governing document of the QPX_ALPHA project.

Every architectural decision, feature request, refactor, and release shall be evaluated against this document.

If any implementation conflicts with this Constitution, the Constitution takes precedence.

---

# Article I – Mission

QPX_ALPHA exists to become a professional quantitative trading platform built through disciplined engineering and continuous improvement.

The objective is not simply to automate trading.

The objective is to create a maintainable, extensible, intelligent software platform.

---

# Article II – Core Values

The project shall always value:

• Simplicity

• Reliability

• Transparency

• Testability

• Documentation

• Performance

• Maintainability

Short-term convenience shall never outweigh long-term quality.

---

# Article III – Architecture

Architecture is the foundation of the platform.

Every new module must strengthen the architecture rather than bypass it.

Temporary solutions must eventually become permanent engineering solutions or be removed.

---

# Article IV – Engineering Standards

Every new module should:

- Have one responsibility.
- Use descriptive names.
- Include meaningful documentation.
- Handle errors gracefully.
- Produce useful logging where appropriate.
- Be testable in isolation.

Duplicated logic should be eliminated whenever practical.

---

# Article V – Documentation

Documentation is part of the software.

A feature is not considered complete until its documentation has been updated.

The following documents are considered mandatory:

PROJECT_CHARTER.md

ARCHITECTURE.md

ROADMAP.md

CHANGELOG.md

MODULE_INDEX.md

SESSION_LOG.md

DECISIONS.md

ENGINEERING_HANDBOOK.md

CONSTITUTION.md

---

# Article VI – Git

GitHub is the canonical source of truth.

Every meaningful change shall:

Design

Implement

Test

Commit

Push

No work is considered complete until committed.

---

# Article VII – Sprint Definition of Done

A sprint is complete only when:

✓ Code works.

✓ Tests pass.

✓ Documentation updated.

✓ Session log updated.

✓ Changelog updated.

✓ Commit completed.

✓ Changes pushed.

---

# Article VIII – Architectural Decisions

Major architectural decisions shall be recorded in DECISIONS.md.

Future contributors should understand not only what changed, but why.

---

# Article IX – AI Collaboration

Artificial intelligence is an engineering collaborator.

AI assists with:

Architecture

Design

Implementation

Review

Documentation

Testing

AI does not replace engineering judgment.

Final approval always belongs to the repository owner.

---

# Article X – The Golden Rule

No code enters QPX_ALPHA unless it makes the platform:

Simpler

Stronger

More Maintainable

More Valuable

If uncertain,

choose the solution that improves the long-term health of the platform.

---

# Oath

Every contribution should leave QPX_ALPHA in a better state than it was found.

---

"Engineer with purpose.

Trade with intelligence.

Build for tomorrow."
""").strip()

path = DOCS / "CONSTITUTION.md"

path.write_text(constitution + "\n", encoding="utf-8")

print("=" * 60)
print("QPX_ALPHA Constitution Ratified")
print("=" * 60)
print(path)