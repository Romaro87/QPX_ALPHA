# QPX canonical operating rules

Status: operative. This is the only mandatory governance read for actual QPX work.

## Scope and authority

- **QPX-01 — Applicability.** “Actual QPX work” means running commands or inspecting, creating, changing, testing, operating, committing, pushing, deploying, or deleting repository, data, or runtime assets. Before the first actual work in a continuous session, an agent MUST read this file completely once; it MUST reread it only if this file changes. Ordinary discussion, explanation, and planning MUST NOT require a compliance-file read unless they mutate or operate QPX.
- **QPX-02 — Authority.** Conflicts MUST follow: Constitution, ADRs, Project Charter, Roadmap, Architecture, Module Registry, Service Registry, implementation. Lower authority MUST NOT redefine higher authority; major architectural changes MUST have an ADR.
- **QPX-03 — Task authority.** The current user task governs within QPX authority. Work MUST stay within its authorization and ordered acceptance criteria. Durable governance or architecture amendments MUST be recorded at the proper authority level.
- **QPX-04 — Non-waiver.** Prior behavior, code, tests, commits, runtime state, or assistant statements MUST NOT waive a rule. Apparent conflicts MUST be resolved from authoritative sources, not by silently choosing a stricter, looser, newer, or convenient rule.
- **QPX-05 — Platform mission.** QPX MUST remain modular, explainable, testable, maintainable, reliable, consistent, reproducible, transparent, professionally engineered, and strategy-agnostic; it MUST support governed research, backtesting, paper trading, approved live execution, portfolio/dividend management, analytics, and AI without hardcoding one investment style.
- **QPX-06 — Evidence terms.** Claims and recovery records MUST distinguish `VERIFIED_REPO`, `VERIFIED_ARTIFACT`, `USER_CONFIRMED`, `USER_APPROVED`, `USER_REQUIREMENT`, `RECOVERED_CONTEXT`, `ASSISTANT_PROPOSED`, `DISCUSSED`, `FUTURE_DECISION`, `UNKNOWN / UNRECOVERED`, `PROVIDER BLOCKED`, and `INCOMPLETE` as applicable.
- **QPX-07 — Proportionality.** Work MUST be the shortest sufficient path. Agents MUST NOT add unrequired gates, audits, design loops, hardening, or hypothetical blockers; nonblocking hardening MUST be recorded for later and work MUST continue.

## Pre-work

- **QPX-08 — Repository check.** Before mutating, testing, operating, committing, or pushing, verify repository, authorized branch, HEAD, upstream, and tracked worktree; preserve unrelated tracked and untracked work.
- **QPX-09 — Work contract.** Before action, identify scope, acceptance criteria, prohibited actions, required order, directly affected semantic surfaces, and required evidence. MUST stop immediately if a mandatory prerequisite cannot be met.
- **QPX-54 — First work update.** For actual QPX work, the first user-facing update MUST confirm this file was read and state risk class, authorized scope, prohibitions, sequence, and completion evidence concisely.
- **QPX-10 — Risk classes.** Classify work before code/runtime mutation: LOW = reporting, pure helpers, focused tests, cosmetic/nonsemantic work; MEDIUM = persistence, providers, schedulers, lifecycle, unattended recovery, or resource arbitration; HIGH = strategy, accounting, broker/order authority, causal data, ML, promotion, qualification, or capital authority.
- **QPX-11 — LOW gate.** LOW-risk work MAY proceed directly with proportionate verification.
- **QPX-12 — MEDIUM gate.** Before MEDIUM-risk edits, state existing mechanism, changed state, main failure paths, restart/recovery, invariants, and focused proofs in a compact gate. UNKNOWN required behavior MUST stop implementation.
- **QPX-13 — HIGH gate.** Before HIGH-risk edits, inspect authoritative rules/code/history and obtain a reviewed design resolving state ownership, causal boundaries, failure/restart behavior, invariants, and verification.
- **QPX-14 — New unknowns.** An uncovered semantic/state/dependency question exposed during implementation MUST stop dependent work; agents MUST NOT improvise or test their way into policy.
- **QPX-15 — Semantic surface.** Direct impact is determined by behavior, not imports. Inspect only affected sibling paths, validators/qualifiers, persistence/evidence consumers, recovery, runtime/reporting entry points, tests, and fixtures; MUST NOT conduct unrelated audits.
- **QPX-16 — Parameter uncertainty.** Missing thresholds, caps, modes, timing, allocation, or strategy parameters MUST be retrieved or reported unknown, never invented or hardcoded. Tunables MUST remain versioned/configurable; safety, accounting, causal, and provenance invariants remain code invariants.

## Implementation

- **QPX-17 — Architecture first.** Architecture MUST govern implementation. New functionality SHOULD use builders when practical; builders MUST be repeatable and consistent.
- **QPX-18 — Modular design.** Subsystems MUST have clear responsibilities; modules SHOULD be cohesive and loosely coupled; orphan modules MUST NOT be created.
- **QPX-19 — Configurability.** Strategies, risk models, allocation, and execution rules SHOULD remain configurable. Risk preference MUST belong to strategy, not platform infrastructure.
- **QPX-20 — Narrow change.** Make the smallest change satisfying the governed contract. Reuse existing authority, configuration, recovery, exclusion, lifecycle, uncertainty, and failure mechanisms; MUST NOT create parallel policy or unrelated redesign.
- **QPX-21 — Semantic preservation.** Correct behavior and all out-of-scope semantics MUST remain unchanged. Corrective work MUST NOT silently strengthen, weaken, or “improve” governed behavior.
- **QPX-22 — Truth and durable evidence.** Identity, provenance, data, state, history, and results MUST NOT be fabricated, silently overwritten, discarded, relabeled, grandfathered, or reacquired. Successfully acquired evidence is durable state; RAM is only a buffer.
- **QPX-23 — State distinctions.** Acquisition, qualification, eligibility, training, promotion, and capital authority MUST remain distinct; priority MUST NOT be interpreted as exclusivity. Training and financial/order authority require explicit authorization.
- **QPX-24 — Financial/runtime safety.** Financial, causal-data, accounting, broker, runtime, deployment, and destructive work MUST preserve governed state, evidence, chronology, restart behavior, and authorization boundaries; it MUST NOT fabricate fills/actions or use future/unavailable information.
- **QPX-25 — Traceability.** Trading decisions SHOULD be explainable, calculations reproducible, and automated actions traceable.
- **QPX-26 — Documentation.** Documentation is a required deliverable and architecture documentation MUST remain synchronized with implementation.
- **QPX-27 — Coexistence.** Clean-V2 has priority, but historical work MUST run whenever capacity permits. Capacity arbitration governs download and finalization; market-open status alone MUST NOT block historical finalization.
- **QPX-28 — Baseline discipline.** Broken builds MUST NOT become baseline. Agents MUST NOT reopen settled decisions, mistake legacy behavior for authority, move acceptance goalposts, or block a passed milestone for noncritical speculation.

## Verification

- **QPX-29 — Focused tests.** Routine changes MUST run focused changed-behavior tests plus only directly affected dependency/contract tests. Test scope MUST be proportional.
- **QPX-30 — Affected fixtures.** Changed interfaces, evidence contracts, state schemas, or governed behavior MUST update every directly affected test and fixture in the same change; completion requires those focused modules to pass.
- **QPX-31 — Broad tests.** Broad suites MUST run only for genuinely broad semantic impact, explicit qualification/requalification, specified milestone gates, or explicit user instruction. Shared-file contact, additive change, ceremony, or prior passage is insufficient.
- **QPX-32 — Runtime proof.** Tests, mocks, startup, activity, logs, or retries MUST NOT substitute for specifically required runtime transitions/evidence. External blockers MUST be reported exactly; implementation readiness and runtime acceptance MUST remain distinct.
- **QPX-33 — Quality lifecycle.** Significant features SHOULD include tests and the platform SHOULD remain deployable. Where applicable, follow Architecture → Builder → Testing → Doctor Validation → Commit → Push; a milestone MUST NOT be complete until its required validations succeed.
- **QPX-34 — Evidence-to-claim.** Positive claims require direct evidence: inspected diff for code; exact command/count/result for tests; post-commit process evidence for loaded runtime; required transition/artifact for behavior; identity/checksum/count for preservation; SHA/tree for commit; remote ref for push; absence check for skipped CI; all criteria for completion.
- **QPX-35 — Preservation proof.** When preservation is required, capture and compare the relevant before/after identity, checksum, governed count, or exact artifact.

## Deployment, Git, and continuity

- **QPX-36 — Ordered transactions.** Follow the user’s sequence literally. Each milestone’s prerequisites and evidence MUST exist before advancing; later success MUST NOT cure an earlier ordering violation.
- **QPX-37 — Operational authorization.** Do not commit, push, restart, signal, deploy, qualify, trade, delete, or leave unattended recovery unless authorized. Authorized unattended work MUST be system-owned where required and MUST distinguish current proof from future acceptance.
- **QPX-38 — Git target.** Accepted work belongs on `main`; temporary branches MAY isolate unfinished/unaccepted work. Verify the authorized target and do not deliberately leave accepted `main` stale.
- **QPX-39 — Staging.** MUST NOT use `git add .` or `git add -A`. Stage explicit intended paths, preserve unrelated changes, inspect staged content, and satisfy applicable CI/test scope before commit/push.
- **QPX-40 — Commits.** Major milestones SHOULD be independent commits; architectural transitions MUST be documented. Commit only validated intended content.
- **QPX-41 — Push continuity.** Every meaningful push MUST include a fresh `QPX_RECOVERY_PROMPT.md`; substantive pushes MUST also update the decision ledger and applicable journal in the same push. Source MUST NOT be pushed first and continuity repaired later.
- **QPX-42 — Ref verification.** After push, verify local HEAD, tracking ref, and intended remote ref agree; for isolated work also verify accepted `main` remains expected.
- **QPX-43 — Pre-commit audit.** Immediately before each commit and push, audit every prerequisite criterion. Missing continuity, validation, preservation, or runtime evidence MUST block the dependent Git action.
- **QPX-44 — Context warning.** Warn conservatively about five exchanges before likely context exhaustion and before another substantial block when near the limit; do not wait for the last message, and create/update a durable restore point first.
- **QPX-45 — Checkpoint cadence.** During substantial active work, checkpoint about every five minutes and target no more than ten; checkpoint sooner after important decisions, edits, tests/results, failures, research, Git actions, corrections, tool transitions, or context risk. This does not require asynchronous activity while idle.
- **QPX-46 — Checkpoint content.** Recovery/checkpoints MUST preserve the most granular reasonably available conversation, decisions, corrections, repository/ref/status, changes, commands/results, configurations, identities/fingerprints, artifacts, tests, metrics, failures, blockers, authority, unknowns, and next action. Prefer terminal-created append-only dated journals and Git-backed files over browser downloads/refreshes; do not replace prior entries or convert assistant statements into user decisions.
- **QPX-47 — Recovery truth.** Missing history MUST be retrieved/verified or labeled unknown, never reinterpreted or invented. If direct Git writing is unavailable, immediately provide the shortest safe command for the user to create/push the checkpoint.

## Reporting and amendment

- **QPX-48 — Honest status.** MUST NOT claim `PASS`, `COMPLETE`, `PRESERVED`, `VALID`, `PUSHED`, or `SUCCESS` without direct evidence. Keep source, tests, runtime, provider, data, qualification, training, Git, and whole-task status separate.
- **QPX-49 — Incomplete work.** Any unmet mandatory criterion makes the whole task incomplete; report `RULE COMPLIANCE: VIOLATED` and `TASK STATUS: INCOMPLETE` when an applicable rule was skipped or contradicted. Partial success MUST NOT conceal failure.
- **QPX-50 — Completion audit.** Before completion, verify rules/order/prohibitions, affected surfaces/fixtures, focused tests, required runtime proof, state preservation, same-push continuity, direct evidence, proportionality, intended refs, training authority, and the whole task. Every YES MUST have evidence.
- **QPX-51 — Implementation report.** Implementation completion reports MUST state risk class, pre-code gate, rule compliance, task status, affected surfaces, acceptance results, focused tests, runtime evidence, data/state impact, training authority, files, commits, push, main status, unmet requirements, and next action.
- **QPX-52 — Progress.** A milestone meeting its stated acceptance criteria MUST move forward; noncritical hardening MUST NOT become a new blocker.
- **QPX-53 — Amendments.** Every governance change MUST modify this canonical file and `docs/governance/QPX_RULE_TRACEABILITY.md` in the same commit. Narrative history, incident, accountability, journal, or recovery records MUST NOT become mandatory per-task reading automatically.
