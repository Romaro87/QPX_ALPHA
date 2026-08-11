# QPX_ALPHA CHAT CONTEXT CONTINUITY RULE

**STATUS: USER_CONFIRMED / PERMANENT OPERATING RULE — 2026-08-11**

This rule applies to every ChatGPT conversation used to develop, operate, research, debug, document, or plan QPX_ALPHA.

## Early warning

The assistant must warn the user **about five messages/exchanges before the conversation is likely to reach its usable context-length limit**, to the extent that remaining context can reasonably be estimated.

The assistant must warn **before starting another substantial block of work** when the conversation appears close enough to the limit that the next several exchanges could exhaust usable context.

The assistant must not intentionally wait until the last message or until usable context is already exhausted.

Because exact remaining context may not be directly observable, "about five messages" is an early-warning target, not an exact counter. When uncertain, warn conservatively early.

## Restore point

When the warning is triggered, priority shifts to creating or updating a durable QPX restore point before continuing major new work.

The restore point should preserve, as applicable:

- repository and branch
- latest verified Git commit/checkpoint
- current code/research state
- latest test results
- active errors/blockers
- files created/changed
- important commands and outputs
- decisions approved since the previous restore point
- unresolved questions
- current strategy/research configuration
- data/provider state
- hardware/environment state when relevant
- next exact implementation step

All recovered material must continue to be classified honestly as:

- VERIFIED_REPO
- VERIFIED_ARTIFACT
- USER_CONFIRMED
- USER_APPROVED
- USER_REQUIREMENT
- RECOVERED_CONTEXT
- ASSISTANT_PROPOSED
- DISCUSSED
- FUTURE_DECISION
- UNKNOWN / UNRECOVERED

## Purpose

The purpose of this rule is to prevent another QPX context-loss event from forcing repeated reconstruction of settled decisions, capabilities, features, architecture, research state, or debugging history.

**DO NOT REINTERPRET. DO NOT INVENT MISSING HISTORY.**
