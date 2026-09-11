# QPX CODEX COMPLIANCE PROMPT — BINDING

This prompt applies before every QPX_ALPHA task. It governs Codex's own task
process. It is fail-closed: **no repository or runtime action is permitted until
it has been read and applied to the current task.** Read it before interpreting,
planning, inspecting beyond the minimum needed to load governance, editing,
testing, operating runtime state, committing, pushing, or reporting completion.

The first user-facing work update for any action task must state that this prompt
was loaded and concisely identify the risk class, authorized scope, prohibited
actions, required sequence, and completion evidence. Silence, memory of a prior
turn, or a generic promise to “follow the rules” is not compliance.

Also read and obey:

1. `AGENTS.md`
2. `QPX_CONTEXT_CONTINUITY_RULE.md`
3. `QPX_ASSISTANT_CODEX_FAILURE_WARNING.md`
4. The current user task
5. Relevant authoritative repository contracts

These are acceptance criteria, not optional context.

## Authority, precedence, and non-waiver

Apply authority in this order:

1. The current user's explicit instructions and explicit supersessions
2. Repository-wide binding rules in `AGENTS.md`
3. Recorded user-approved QPX governance and semantic contracts
4. Authoritative current code and immutable evidence implementing those contracts
5. Tests and fixtures
6. Local implementation assumptions and convenience behavior

A lower level may prove or implement a higher-level rule; it may never override
one. Apparent conflict must be retrieved and resolved before action. Do not
silently select the stricter, looser, newer-looking, or more convenient rule.

A prior violation, prior commit, passing test, existing runtime behavior, or
previous assistant statement does not amend or waive a governing rule. Only an
explicit authorized decision can do that. Partial compliance is noncompliance.

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
- Convert them into a concrete ordered checklist before acting; do not reorder
  steps for convenience.
- Identify directly affected semantic surfaces and required completion evidence.
- Retrieve the authoritative rule when local behavior conflicts with governance.
- Stop only for a genuinely unresolved required semantic decision or an explicit
  governed stop condition. Do not manufacture uncertainty already resolved.
- If the task cannot satisfy a mandatory criterion, state that immediately and
  do not perform later steps whose authorization depends on that criterion.

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
- Never “improve” governed semantics during a corrective task. Anything outside
  the authorized defect boundary remains unchanged and is, at most, recorded as
  nonblocking later work.

## Test discipline

`QPX_TEST_SCOPE_RULE_V1` is binding. Run focused changed-behavior tests and
directly affected dependencies only. Update every directly affected test and
fixture in the same change. Do not run broad suites for ceremony or preserve
tests encoding obsolete policy. Tests and mocks never substitute for explicitly
required runtime evidence.

## Sequencing and runtime proof

Follow the user's required order literally. Do not commit, push, restart,
deploy, qualify, or report completion earlier than authorized.

Treat every ordered milestone as a transaction with explicit prerequisites.
Before advancing, verify and record that the preceding step's acceptance
evidence exists. A later successful step never cures an earlier sequencing
violation.

When runtime proof is required, obtain the exact evidence. Do not substitute
service startup, activity, retries, logs, mocks, or tests. If external conditions
prevent proof, report the exact blocked state and do not claim completion or
`RULE COMPLIANCE: PASS`.

Leave authorized unattended recovery running only when the task permits it;
distinguish “implementation ready” from “runtime acceptance achieved.”

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

Immediately before each commit and push, re-run the completion audit for every
criterion that is a prerequisite to that Git action. If required continuity or
runtime evidence is absent, do not commit or push. A follow-up continuity commit
cannot retroactively repair a noncompliant earlier push.

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

### Evidence-to-claim rule

Each positive claim must identify its direct evidence:

| Claim | Minimum evidence |
|---|---|
| Code changed as intended | Inspected exact diff |
| Focused tests passed | Exact command, count, and result |
| Runtime loaded new code | Verified service/process start after the commit |
| Runtime behavior works | Specifically required real transition or artifact |
| Data preserved | Before/after identity, checksum, or governed count |
| Commit created | Exact local SHA and tree |
| Push succeeded | Authorized remote ref equals local SHA |
| CI skipped | No run exists for the pushed SHA |
| Task complete | Every criterion and ordered step is verified |

Evidence for one row cannot substitute for another. When direct evidence is
unavailable, report `UNKNOWN / UNRECOVERED`, `PROVIDER BLOCKED`, or `INCOMPLETE`.

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
13. Did I preserve the required order rather than merely perform the same steps?
14. Does every positive claim map to the required direct evidence?
15. Am I reporting the whole task rather than only its successful subset?

If any answer is **NO** or **UNKNOWN**, do not declare completion.

The audit is not ceremonial prose. Every YES must be supported by tool output,
repository evidence, or an explicit user decision in the governed context.
Never mark an item YES merely to make the report appear complete.

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
