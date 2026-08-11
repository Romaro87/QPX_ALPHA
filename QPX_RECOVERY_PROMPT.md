# QPX_ALPHA RECOVERY PROMPT

**Checkpoint date:** 2026-08-11T10:54:18-05:00

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

Verify local HEAD equals remote `main` after every push.

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
