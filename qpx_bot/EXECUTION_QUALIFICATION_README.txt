QPX PAPER EXECUTION QUALIFICATION
=================================

Purpose
-------

This milestone is an operational reliability gate between simulated
paper execution and any future broker sandbox work.

It does not measure profitability and it does not enable a broker.

The qualification ledger records:

- regular-session scheduler heartbeats;
- opening-window coverage;
- after-close processing health;
- paper-state checksum validity;
- audit-journal hash-chain validity;
- verified backup and recovery-drill coverage;
- staged instruction outcomes;
- quote-backed regular-session outcomes;
- stale or missed instructions;
- duplicate terminal order IDs;
- any extended-hours execution evidence;
- kill-switch, circuit-breaker, scheduler, and cron status.

Default qualification sample
----------------------------

- at least 20 completed market sessions;
- at least 3 staged instruction outcomes;
- at least 95% opening-window coverage;
- at least 95% healthy after-close coverage;
- at least 90% verified backup + drill coverage;
- at least 95% operational instruction processing;
- zero missed-window cancellations;
- zero stale-instruction cancellations;
- zero extended-hours events;
- zero duplicate terminal order outcomes.

The result can be:

COLLECTING
    The minimum evidence sample has not accumulated.

BLOCKED
    A hard safety or integrity rule failed.

NOT_QUALIFIED
    The minimum sample exists, but reliability criteria failed.

PAPER_QUALIFIED
    The paper execution layer met the configured operational criteria.

PAPER_QUALIFIED still does not authorize live trading. The
qualification configuration requires live_broker_enabled=false.

Commands
--------

Show status:

python QPX_RUN_QUALIFICATION.py --status

Initialize without changing the paper account:

python QPX_RUN_QUALIFICATION.py --initialize

Reports
-------

reports/qpx_qualification/latest_qualification.txt
reports/qpx_qualification/latest_qualification.json
reports/qpx_qualification/session_ledger.csv

The Termux regular-session and after-close wrappers update the ledger
automatically.
