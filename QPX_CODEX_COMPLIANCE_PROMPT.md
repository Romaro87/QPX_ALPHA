# QPX CODEX COMPLIANCE PROMPT — BINDING

This prompt applies before every QPX_ALPHA task. It governs Codex's own task
process. Read it before interpreting, planning, inspecting, editing, testing,
operating runtime state, committing, pushing, or reporting completion.

Also read and obey:

1. `AGENTS.md`
2. `QPX_CONTEXT_CONTINUITY_RULE.md`
3. `QPX_ASSISTANT_CODEX_FAILURE_WARNING.md`
4. The current user task
5. Relevant authoritative repository contracts

These are acceptance criteria, not optional context.

## Core rule

Follow the already-governed QPX road exactly. Do not reinterpret, weaken,
strengthen, replace, or supplement governed rules because another approach
appears safer, cleaner, or more robust.

A local precondition, legacy assumption, stale test, convenience check, or
implementation detail never outranks a governed QPX contract.

## Pre-action check

Before editing code or changing runtime state:

- Verify repository, authorized branch, HEAD, upstream, and tracked worktree.
- Preserve unrelated tracked and untracked work.
- Classify risk correctly and complete `QPX_PRE_CODE_GATE_V1`.
- Identify exact acceptance criteria, required sequence, and prohibited actions.
- Identify directly affected semantic surfaces and required completion evidence.
- Retrieve the authoritative rule when local behavior conflicts with governance.
- Stop only for a genuinely unresolved required semantic decision or an explicit
  governed stop condition. Do not manufacture uncertainty already resolved.

## Directly affected surfaces

“Directly affected” is determined by semantic impact, not imports or filenames.
For the defect class being changed, inspect only relevant sibling paths,
downstream validators and qualifiers, persistence/evidence consumers,
restart/recovery paths, runtime and reporting entry points, tests, and fixtures.
Do not conduct an unrelated architecture audit.

## Implementation discipline

- Make the smallest change satisfying the governed contract.
- Reuse existing QPX mechanisms; do not create parallel authority,
  configuration, recovery, exclusion, lifecycle, or governance mechanisms.
- Preserve correct behavior and avoid unrelated redesign.
- Record nonblocking hardening for later and keep moving.
- Never fabricate identity, provenance, data, state, or historical facts.
- Never silently overwrite, discard, relabel, grandfather, or reacquire governed
  evidence. Successfully acquired evidence is durable state; RAM is a buffer.
- Never confuse acquisition, qualification, eligibility, training, promotion,
  or capital authority. Never confuse priority with exclusivity.

## Test discipline

`QPX_TEST_SCOPE_RULE_V1` is binding. Run focused changed-behavior tests and
directly affected dependencies only. Update every directly affected test and
fixture in the same change. Do not run broad suites for ceremony or preserve
tests encoding obsolete policy. Tests and mocks never substitute for explicitly
required runtime evidence.

## Sequencing and runtime proof

Follow the user's required order literally. Do not commit, push, restart,
deploy, qualify, or report completion earlier than authorized.

When runtime proof is required, obtain the exact evidence. Do not substitute
service startup, activity, retries, logs, mocks, or tests. If external conditions
prevent proof, report the exact blocked state and do not claim completion or
`RULE COMPLIANCE: PASS`.

## Git and continuity

- Stay on the authorized branch; never touch or push `main` unless authorized.
- Never use `git add .` or `git add -A`; stage explicit intended paths only.
- Inspect staged content before committing.
- Every meaningful push must include a freshly updated
  `QPX_RECOVERY_PROMPT.md` in that same push.
- Substantive pushes must also update the decision ledger and applicable journal
  in that same push. Never push source first and repair continuity later.
- Verify the authorized remote branch after push and verify `main` is unchanged.
- Respect CI and test-scope instructions before pushing.

## Evidence and reporting

Never claim `PASS`, `COMPLETE`, `PRESERVED`, `VALID`, `PUSHED`, or `SUCCESS`
without direct evidence. Keep source, tests, runtime, provider, data,
qualification, training authority, and Git status separate.

Use honest classifications including `VERIFIED_REPO`, `VERIFIED_ARTIFACT`,
`USER_REQUIREMENT`, `UNKNOWN / UNRECOVERED`, `PROVIDER BLOCKED`, and
`INCOMPLETE`. If one mandatory criterion is unmet:

```text
RULE COMPLIANCE: VIOLATED
TASK STATUS: INCOMPLETE
```

Do not conceal that result with partial successes.

## Mandatory completion audit

Before calling any task complete, verify every answer is **YES**:

1. Did I follow every applicable standing rule?
2. Did I follow the requested sequence and avoid every prohibited action?
3. Did I inspect all directly affected semantic surfaces?
4. Did I update directly affected tests and fixtures?
5. Did the proportionate focused tests pass?
6. Did I obtain every specifically required runtime proof?
7. Did I preserve all governed data and state?
8. Did every meaningful push include required continuity in that same push?
9. Does every completion claim have direct evidence?
10. Did I avoid unrelated redesign, hardening, and new bureaucracy?
11. Is the authorized remote branch verified and `main` untouched?
12. Is training unauthorized unless explicitly approved?

If any answer is **NO** or **UNKNOWN**, do not declare completion.

## Mandatory completion fields

```text
RISK CLASS:
PRE-CODE GATE:
RULE COMPLIANCE:
TASK STATUS:
DIRECTLY AFFECTED SURFACES CHECKED:
ACCEPTANCE CRITERIA:
FOCUSED TESTS:
RUNTIME EVIDENCE:
DATA/STATE IMPACT:
TRAINING AUTHORITY:
FILES CHANGED:
COMMITS:
PUSH:
MAIN:
UNMET REQUIREMENTS:
NEXT EXACT ACTION:
```

## Final operating principle

Build the governed architecture. Prevent known destructive mistakes. Fix
observed blockers. Use proportional verification. Preserve durable evidence.
Do not invent barriers. Do not move goalposts. Do not overclaim. Keep QPX moving.
