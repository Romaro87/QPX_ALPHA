# QPX conversation journal — 2026-09-25

## Governance consolidation

USER_REQUIREMENT: Condense mandatory governance to the smallest practical
canonical set without weakening or bypassing substantive rules; preserve full
history, create deterministic traceability, validate counts/mapping/conflicts,
commit and push documentation only, and do not touch runtime/services.

VERIFIED_REPO baseline: `main`/`origin/main`, HEAD
`e1b7404d4a2b277f5e81b4c19028653672f3c32a`; tracked tree clean. Unrelated
untracked Sep21 journal, `runtime/`, and shell-name file preserved. Old mandatory
startup set: 968 lines, 5,921 words, 41,944 bytes across the five current files.

IMPLEMENTATION: Added 54-rule `QPX_CODEX_RULES.md` (75 lines, 1,777 words),
11-line `AGENTS.md` bootstrap, nonoperative compatibility pointers, and
human-audit-only `docs/governance/QPX_RULE_TRACEABILITY.md`. Archived all five
former mandatory documents verbatim under
`docs/governance/archive/pre_consolidation_2026-09-25/`; their bytes match the
pre-change HEAD blobs. Constitution remains unchanged. New mandatory startup set
(bootstrap plus canonical): 86 lines, 1,850 words, 14,430 bytes.

RULE DECISION: read canonical once before first actual QPX work per continuous
session and again only if it changes. Ordinary discussion/explanation/planning
requires no read unless it operates or mutates QPX. No mandatory file recursively
requires the archive. Future governance amendments update canonical and
traceability together; narrative records are never mandatory automatically.

NEXT: complete deterministic mapping/ID/link/count/contradiction validation and
`git diff --check`; stage explicit governance paths, inspect, commit, push main,
verify local/tracking/remote equality, and exit. Application tests are prohibited.

VERIFIED_ARTIFACT: documentation-only validator passed with 54 unique rules,
90/90 mapping rows and zero unmapped rows, zero contradictory duplicate
authorities, no circular reads, valid phases/limits/links/amendment rule,
unchanged Constitution, and byte-identical archives. `git diff --check` passed.
Mandatory startup reductions: lines 91.12%, words 68.76%, bytes 65.60%.
The explicit stage contains 15 governance/continuity/archive paths only; all
unrelated untracked work remains unstaged. No application tests were run.
