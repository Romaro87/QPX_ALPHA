from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
ADR_DIR = ROOT / "docs" / "adr"

ADR_DIR.mkdir(parents=True, exist_ok=True)

template = textwrap.dedent("""
# ADR-0000: Template

**Status:** Proposed

**Date:** YYYY-MM-DD

---

## Context

Describe the problem that requires a decision.

---

## Decision

Describe the chosen solution.

---

## Alternatives Considered

- Option A
- Option B

---

## Consequences

Positive:

-

Negative:

-

---

## Notes

Additional implementation notes.

""").strip()

adr1 = textwrap.dedent("""
# ADR-0001: Adopt Project Constitution

**Status:** Accepted

**Date:** 2026-07-25

---

## Context

QPX_ALPHA had grown significantly without a formal engineering governance model.
To ensure consistent development over time, the project required a documented
set of principles and standards.

---

## Decision

Adopt a Project Charter, Constitution, Engineering Handbook, and supporting
documentation as the governing framework for the project.

---

## Alternatives Considered

- Continue with informal development.
- Document standards only in the README.

---

## Consequences

Positive:

- Clear engineering direction.
- Consistent decision-making.
- Easier onboarding for future contributors.

Negative:

- Requires documentation updates as the project evolves.

---

## Notes

The Constitution is the highest-level governing document for QPX_ALPHA.
""").strip()

adr2 = textwrap.dedent("""
# ADR-0002: GitHub as Source of Truth

**Status:** Accepted

**Date:** 2026-07-25

---

## Context

Development occurs across Android (Pydroid 3 and Termux), making version control
essential.

---

## Decision

GitHub is the canonical source of truth.

Every completed milestone shall be committed and pushed.

---

## Alternatives Considered

- Local-only development.
- Periodic manual backups.

---

## Consequences

Positive:

- Complete project history.
- Reliable rollback.
- Stable release management.

Negative:

- Requires disciplined commit practices.

---

## Notes

Release tags should be used for significant milestones.
""").strip()

files = {
    "README.md": """
# Architecture Decision Records

Every significant architectural decision is recorded here.

Naming Convention:

ADR-0001

ADR-0002

ADR-0003

...

Never modify an accepted ADR.

If a decision changes, create a new ADR that supersedes the previous one.
""",
    "ADR-0000-template.md": template,
    "ADR-0001-project-constitution.md": adr1,
    "ADR-0002-github-source-of-truth.md": adr2,
}

for name, content in files.items():
    path = ADR_DIR / name
    if not path.exists():
        path.write_text(content + "\n", encoding="utf-8")
        print("Created:", name)
    else:
        print("Skipped:", name)

print("\nADR framework established.")