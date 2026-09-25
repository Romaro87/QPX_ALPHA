# 2026-09-24 — live-paper causal execution correction

USER_REQUIREMENT: implement, focused-test, commit/push and deploy tonight; no
historical replay changes and no waiting for tomorrow. Account and authority
must remain intact. Market-open acceptance is separately pending the schedule.

VERIFIED_ARTIFACT: main starts at 8755c986d3246be4e8899f65dfc9477771a6c6d5;
tracked tree clean, unrelated untracked journal/runtime/shell-name preserved.
Audit: Sep17 INTC eligible 13:48Z observed 13:48:12.155Z, Sep24 TSLL eligible
16:33Z observed 16:33:04.029Z. Both nevertheless expired with PROCESS_NOT_OBSERVED.
Sep17 TSLL shared INTC's minute and was starved by the pending-loop early return.
The session daemon ran continuously: polling completed minute bars inside their
own minute was the defect, not a 15-minute systemd start schedule.

HIGH RISK pre-code design, reviewed against ADR-0010 and the existing authentic
OPEN/CLOSE contract: read first qualifying IEX trade in the current eligible
minute (bounded read-only requests), never a later completed candle. Observe all
pending symbols, prioritize execution over slow decision/provider work, persist
causal source/timestamps and explicit no-data/deadline/session reasons. Reuse
checksummed state and idempotent hash-chained journal with a durable state outbox.
Account metrics are additive, use completed causal marks and existing accounting;
unknown pre-migration marks are null, never reconstructed as historical truth.
Preserve sizing, strategy fingerprints, cash, holdings, dividends and evidence.
Focused proofs: CLOSE staging, OPEN fill, repeated polling/restart/crash,
unavailable minutes, session/DST/early close, valuation/dividends and no orders.
Deploy only committed source via the existing supervised path; finite afterhours
valuation refresh, then exit with market execution explicitly pending.

Provider contract reference: https://docs.alpaca.markets/us/docs/market-data-faq
(minute open uses first eligible trade; strictest trade condition applies).

Implementation delta: IEX adapter now obtains a bounded GET of sorted IEX trades
inside the eligible minute, filters minute-open conditions, persists observation,
and never fills after its deadline. All pending symbols are serviced; unresolved
account OPEN phase preserves observations without executing out of order. Audit
delivery uses committed state outbox and existing journal idempotence. Shared
decision path gains additive exit P&L/causal marks and yields after staging IEX
pending actions; no strategy changes. Metrics module persists state/report data
with explicit unavailable historic window equity. Unit requests five-second daemon
polling; canonical session calendar supplies early-close boundaries.
VERIFIED_ARTIFACT: first focused run (runner/accounting/supervisor) 63 passed;
new execution/restart/metrics tests initially 10 passed. Production state remains
unmodified, worker inactive, supervisor PID709504 active/restarts0. Next: finish
integration tests, inspect exact diff, continuity+commit/push, committed deployment
and finite valuation-only runtime verification. Market-open proof remains pending.

2026-09-24 evening checkpoint: completed CLOSE integration and no-order tests
added; final focused command across four named modules passed 78 tests. Exact
diff inspected; git diff --check and systemd-analyze --user verify target unit
passed (unrelated spice-vdagent warning only). Admission path contained an obsolete
25% qualification fallback despite persisted90%; reviewed against explicit user
90% requirement and bound cap to the unchanged persisted contract. No parameters
were edited. New deployed path will use committed package export, not dirty tree.
Source fingerprint eb4fca116146e78427ee73a5504ef5488c2206a1138714f94bc6a841cad3a009;
contract still65d6f7c50e8b7efb9e08dfe5bee855e0b90fd52772a36ed78de1a8422ca5b0bc.
Baseline original-field hashes captured, audit1887686bytes SHA256
59d229ec89d5f11ecdac0b6eeeb2cdd5ab80386680a1535f737e18cba18dbca6.
Pre-commit audit: governance/design satisfied; focused affected surfaces updated
and passing; source/staged review and continuity required before push; deployment
and real runtime migration verification still pending, no completion claim.
