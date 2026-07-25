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
