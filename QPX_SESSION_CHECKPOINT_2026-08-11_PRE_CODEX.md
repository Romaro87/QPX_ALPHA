# QPX SESSION CHECKPOINT — PRE-CODEX

**Date:** 2026-08-11
**Timezone:** America/Chicago
**Purpose:** Maximum-granularity restore point before configuring Codex.

For the full chronological recovery of today's discussion, read:

`QPX_CONVERSATION_JOURNAL_2026-08-11.md`

Then read:

1. `QPX_CONTEXT_CONTINUITY_RULE.md`
2. `QPX_RECOVERY_DECISION_LEDGER.md`
3. `QPX_RECOVERY_PROMPT.md`

## Current verified research state

Strict Candidate V1:

- start: $1,300
- ending equity: $14,510.45
- net profit: $13,210.45
- CAGR: 172.25%
- maximum drawdown: 41.97%
- closed trades: 1,954
- win rate: 49.39%
- profit factor: 1.270
- risk rejections: 5,861
- capacity deferred: 2,550

Non-strict preserved control:

- ending equity: $16,485.76
- CAGR: 192.71%
- maximum drawdown: 30.47%

Current qualification blocker:

**QDTE corporate-action cash availability / payment timing**

Verified Alpaca fields:

- ex_date
- record_date
- payable_date
- process_date
- rate

## Current workflow transition

Current normal ChatGPT GitHub connector is usable for repo inspection but
direct write attempts returned HTTP 403.

The next workflow experiment is Codex with `Romaro87/QPX_ALPHA`.

Goal:

reduce or eliminate the phone acting as a manual code-transfer middleman.

## Permanent context requirement

Every recovery/checkpoint must use the maximum available granularity and
preserve as much of the actual conversation as possible.

During active QPX work:

**checkpoint target = approximately every 5 minutes**
**10 minutes = upper target maximum**
**major event = checkpoint immediately**

## Next exact action

Push this checkpoint.

Then configure Codex.

Do not resume strategy development before the context push and Codex workflow
setup are complete.

After Codex workflow setup, resume:

**authentic QDTE dividend cash timing → strict-causal Candidate V1 rerun**
