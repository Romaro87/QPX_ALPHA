# QPX_ALPHA RECOVERY PROMPT

**Checkpoint date:** 2026-08-11T12:34:41-05:00

Use this file to resume QPX_ALPHA after a lost or frozen ChatGPT conversation.

## RECOVERY RULES

Do not invent QPX history.

Before changing architecture, read:

1. `QPX_RECOVERY_DECISION_LEDGER.md`
2. `QPX_CONTEXT_CONTINUITY_RULE.md`
3. current `git status`
4. current Git HEAD
5. source files relevant to the next milestone

Keep evidence states distinct:
VERIFIED_REPO, VERIFIED_ARTIFACT, USER_CONFIRMED, USER_APPROVED,
USER_REQUIREMENT, RECOVERED_CONTEXT, ASSISTANT_PROPOSED, DISCUSSED,
FUTURE_DECISION, UNKNOWN / UNRECOVERED.

Never convert plausible reconstruction into historical fact.

## WORKSPACE

Repository: `Romaro87/QPX_ALPHA`

Android workspace:
`/storage/emulated/0/QPX_ALPHA`

Environment:
- Pydroid 3
- Termux

The user does not write or assemble code manually.
Provide complete runnable code and exact phone-friendly commands.

Never use `git add .`.
Never silently stage unrelated files.

Normal QPX development must not depend on browser downloads or browser refreshes.
Prefer terminal-created files and Git-backed checkpoints.

## PER-PUSH RULE

Every QPX push must include a freshly updated:

`QPX_RECOVERY_PROMPT.md`

For substantive milestones also update:

`QPX_RECOVERY_DECISION_LEDGER.md`

After every push, verify local HEAD equals the configured upstream tracking ref for the current branch. When `main` is protected and work occurs on a review/research branch, separately verify `main` and `origin/main` remain at the expected protected SHA. Do not imply that a review-branch HEAD should equal `origin/main`.

Continue warning the user roughly five exchanges before usable chat context is likely to run out.

## CURRENT CANDIDATE V1 BASELINE

- starting capital: $1,300
- initially all QDTE
- starting swing cash: $0
- external contributions: $0
- Thursday-only weekly rebalance
- six-position Candidate V1 lineage
- risk lineage: 3% per trade / 10% active risk
- strategy universe remains configuration-driven

## TOP-100 PORTFOLIO CHECKPOINT

Frozen selection fingerprint:

`5e271e4a9e0d4a20b6f4d0cecc08e8bf9efe1d2123a64832d09ba1c1eb9ffd23`

Frozen dataset fingerprint:

`1a0d8d772b02079ee340109811d38678c73053f9a55e2fb3d3b5b96e484c5007`

Local experimental runner:

`QPX_RUN_FROZEN_TOP100_PORTFOLIO.py`

Runner SHA-256:

`0fb5e1937ab94ac5d7f0e10dc902219986a9f1c73bb5a8c5727bf8ce1b1faa1a`

Do not assume that runner is committed unless Git verifies it.

## LATEST TOP-100 RESULT

Range: 2024-03-07 through 2026-08-07

- common 15m bars: 12,049
- sessions: 596
- trades: 1,710
- win rate: 49.06%
- profit factor: 1.313
- swing P&L: $14,924.20
- net portfolio profit: $15,185.76
- ending equity: $16,485.76
- reported CAGR: 192.71%
- maximum drawdown: 30.47%
- risk rejections: 5,008
- capacity deferred: 2,405
- all 100 symbols traded
- 61 profitable overall
- 39 losing overall

Summary fingerprint:

`f185f69744ca1e4663de0bbb0263759c331b06f049440edd2afbbb90f4417672`

Status:

**TOP-100 VIABILITY: PRELIMINARY PASS**

**STRICT CAUSAL REPLAY: NOT YET FORMALLY QUALIFIED**

Do not treat the reported CAGR as a production expectation.

## KEY FINDINGS

The original discovery rank is not a reliable portfolio priority order.

- ranks 1-10 lost money as a group
- ranks 41-50 were the strongest decile
- 8 of 10 rank deciles were profitable
- discovery ranking and portfolio selection are different problems

Winner rotation was substantial:

- profitable both halves: 26
- profitable early only: 28
- profitable late only: 30

Do not hard-code in-sample winners into a production universe.

The $1,300 account was materially capital constrained:

- 4,853 risk rejects because one share could not fit available risk/cash
- 155 rejects because no capital was available
- six-position limit was reached
- 2,405 opportunities were capacity deferred

Do not assume rejected or deferred trades would have been profitable.

## STRICT CAUSAL REPLAY REQUIREMENT

At every simulated historical moment, future information must be technically inaccessible.

Required properties:

- no future-bar access
- no future OHLCV access
- no future-derived indicators
- completed-bar signals execute only at the next legitimate execution point
- no synthetic favorable data
- no forward-filled opportunity
- no timestamp substitution
- support and corporate data obey actual availability time
- missing one symbol's bar must not fabricate data
- one missing symbol should not erase valid opportunities for unrelated symbols

## NEXT EXACT MILESTONE

Stop further in-sample winner mining.

Next:

**FORMAL STRICT-CAUSAL REPLAY AUDIT / GATE**

Target report:

- LOOKAHEAD PROTECTION: PASS
- SIMULATION CLOCK: STRICT
- FUTURE BAR ACCESS: BLOCKED
- SYNTHETIC FUTURE DATA: NONE
- DECISION DATA CUTOFF: VERIFIED
- EXECUTION TIMING: VERIFIED

Resume from this audit unless the user explicitly redirects.

<!-- QPX_PRE_CODEX_RESUME_POINT_20260811 -->
# PRE-CODEX RESUME POINT — 2026-08-11

Before asking the user any QPX-history question, read:

1. `QPX_SESSION_CHECKPOINT_2026-08-11_PRE_CODEX.md`
2. `QPX_CONVERSATION_JOURNAL_2026-08-11.md`
3. `QPX_RECOVERY_DECISION_LEDGER.md`
4. `QPX_CONTEXT_CONTINUITY_RULE.md`

Maximum granularity is mandatory.

Preserve as much actual conversation as available.

During active work checkpoint approximately every five minutes and no later
than the ten-minute target ceiling, or immediately after a major event.

Current workflow action:

**configure Codex GitHub access after this checkpoint is safely pushed**

Current next technical QPX milestone after Codex setup:

**authentic QDTE dividend cash timing → strict-causal Candidate V1 rerun**


<!-- QPX_DURABLE_RECOVERY_PROMPT_20260813 -->
# DURABLE RECOVERY PROMPT — 2026-08-13

## QPX GOVERNING RULES — APPLY IMMEDIATELY ON RESTORE

Load governing rules before project history. **MISSING CONTEXT MEANS RETRIEVE/VERIFY — NEVER REINTERPRET OR INVENT.**

### PARAMETER UNCERTAINTY RULE

If an exact threshold, percentage, cap, delay, cooldown, allocation, weight, multiplier, mode, limit, timing value, or other strategy/operational parameter is not explicitly recovered, do not assume it was forgotten and do not invent or hard-code it. QPX values are generally user-configurable, versioned, fingerprinted, and hot-swappable where safe. Engine code supplies capability and validation; runtime configuration supplies values. Frozen experiment values are not universal defaults. Safety, accounting, and provenance invariants remain code invariants.

## RESTORE NOW

Repository `/mnt/sdcard/QPX_ALPHA`; branch `qpx-shadow-matrix-v1-review-2026-08-12`; local/remote HEAD `1ce96941e8fb1cbe8c9e7c5dabf3327842603814`; main/origin-main `2cab84accdfe79faa8097b7fdb976da46d8dbde5`; ahead/behind `0/0`; worktree clean before this context update.

Read in order: `QPX_CONTEXT_CONTINUITY_RULE.md`, latest appended section in `QPX_RECOVERY_DECISION_LEDGER.md`, this prompt, and latest `QPX_CONVERSATION_JOURNAL_2026-08-13.md` if present. Then inspect `git status`, current HEAD, and artifact fingerprints.

## COMPLETED TRAJECTORY

The repository preserves strict Candidate V1 causal/provenance work; fixed-25 qualification; Dynamic Sizing V1; Pyramiding V1; Capacity Arbitration V1; process-isolated parallel research; Regime Allocation V1 foundation/no-op/policies/results; and Profit Recycling foundation, hot swap, governor, checkpoint continuity, equivalence, and fraction matrix. See the detailed ledger section for commits and evidence.

Profit Recycling fraction matrix: 20/20 jobs, 0 failures, fixed-25/hash-control, fractions 100/75/50/25/0, periods full/2024/2025/2026, dataset `8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8`, manifest `4213719f443f7ed8285511e4268a8a1b181b32d082cde03a12e75538b1129133`. The former false causal flag was a reporting bug fixed by `1ce9694`; corrected flag is true, no economics changed.

## CURRENT STATE / NEXT ACTION

No active run, no unpushed commit, and no approved next Profit Recycling matrix. Do not tune or promote any fraction. Next action requires explicit user direction and predeclaration of exact values.

## ROADMAP / LONG-TERM DIRECTION

Preserve Top100 exactly; keep Dividend Opportunity Engine separate; test accelerator combinations only after evidence; use Champion/Challenger/Shadow governance; eventually harden trusted-core failover, broker reconciliation, unattended safe recovery, LAN workers, Tailscale phone access, energy-aware scheduling, and QPX-native constrained ML. AM4 is a replaceable role host, not QPX identity.

## SECURITY / PRESERVATION

Do not stage ignored reports, caches, raw data, `.env`, credentials, private broker data, or the malformed `qpx_bot/QPX_ALPHA` gitlink. Never use `git add .`. Main remains untouched.


<!-- QPX_AUGUST14_RECOVERY_PROMPT_20260814 -->
# AUGUST 14 RECOVERY PROMPT — APPLY BEFORE RESUMING

## QPX GOVERNING RULES — APPLY IMMEDIATELY ON RESTORE

**MISSING CONTEXT MEANS RETRIEVE/VERIFY — NEVER REINTERPRET OR INVENT.** Do not modify main, protected Candidate V1, frozen Top100/data, provenance, permanent controls, or economic behavior. Do not self-promote research/ML/Wildcard outputs.

### PARAMETER UNCERTAINTY RULE

Unrecovered exact thresholds, percentages, caps, delays, allocations, weights, modes, limits, schedules, resource quotas, and ML values must not be invented or hard-coded. Treat them as versioned, fingerprinted, user-configurable/hot-swappable where safe; engine code validates capability and invariants.

## RESTORE STATE

Repository: `/mnt/sdcard/QPX_ALPHA`
Branch: `qpx-shadow-matrix-v1-review-2026-08-12`
Recovery HEAD before this snapshot: `458f26c420b62b1b9999adf9da3c0c4168c34d12`
Main/origin-main: `2cab84accdfe79faa8097b7fdb976da46d8dbde5`
Boundary: approximately 2026-08-14 13:12 CDT; later context is UNKNOWN / UNRECOVERED.

Read the continuity rule, latest ledger section, this prompt, and `QPX_CONVERSATION_JOURNAL_2026-08-14.md`; then verify Git state before action.

## RECOVERED DECISIONS

- Ubuntu 24.04 LTS dedicated Linux services are the initial trusted QPX Core direction; Tailscale is the preferred fast phone path. Indiana success means one reachable, unattended, persistent, reboot-reconciling Core; family time remains priority.
- Development speed and understandable PASS/FAIL/NEXT workflows matter; learning should not block progress and QPX must not become opaque.
- Local-first ownership, user-supplied credentials, no mandatory subscription/heartbeat, and private-state locality are approved philosophy only; price/licensing remain future decisions.
- One-minute support is eventual: Core + 5900XT worker first, authentic/frozen 1-minute data, 1-minute→15-minute parity against protected 15-minute control, then isolated resolution Shadows.
- Strategy lineage is Boundary → Challenger → Champion; approximately 10 governed Challenger slots; Qualification Layer has no capital authority.
- Research, Qualification, and Operations ML are logically separated. Jetson Orin Nano Super is intended ML hardware direction.
- AI Wildcard #11 is permanent conceptual, paper-only, causal, logged, no credentials/live order/real-money authority/self-promotion, and must pass normal freeze/reproduce → evidence → qualification → governance if exceptional.

## NEXT ACTION

This is preservation-only. Verify the pushed recovery commit, then stop and await explicit direction. Do not begin Indiana deployment, one-minute work, Qualification implementation, ML work, Wildcard implementation, or research until separately requested and exact parameters/acceptance criteria are recovered or declared.


<!-- QPX_POST_AUG14_CONTINUITY_RESTORE_20260825 -->
# POST-AUGUST-14 CONTINUITY RESTORE — 2026-08-25

**Status:** USER_CONFIRMED continuity extension. **MISSING CONTEXT MEANS RETRIEVE/VERIFY — NEVER REINTERPRET OR INVENT.**

The former August 14 recovery boundary is now extended by recovered August 15–17 material. This extension does not turn anything marked **UNKNOWN / UNRECOVERED** into known history; all such items remain **UNKNOWN / UNRECOVERED** until retrieved, verified, or explicitly decided.

On restoration, read in this order:

1. `QPX_CONTEXT_CONTINUITY_RULE.md`
2. the latest section of `QPX_RECOVERY_DECISION_LEDGER.md`
3. `QPX_RECOVERY_PROMPT.md`
4. `QPX_POST_AUG14_CONTINUITY_CHECKPOINT_2026-08-17.md`
5. `QPX_CONVERSATION_JOURNAL_2026-08-17.md`
6. then verify branch, HEAD, upstream, worktree status, and main/origin-main refs before action

Recovery completion is not authorization to begin development. Do not touch main. Do not modify Candidate V1, frozen data/fingerprints, strict-causal provenance, permanent controls, or completed accelerator evidence without separate explicit authorization. Research, Shadow, Challenger, ML, Qualification, and Wildcard actors retain no self-promotion authority.

The next development milestone still requires explicit user direction. Until then, remain preservation-only.
