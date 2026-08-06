QPX REGULAR-SESSION EXECUTION
=============================

The workflow is now split into two independent phases.

1. After-close analysis
-----------------------

QPX_TERMUX_DAILY.sh runs only after completed daily data is expected.

It may:
- refresh completed daily bars;
- rank the monthly swing universe;
- reconcile the completed regular session;
- update stops and targets from completed regular-session OHLC;
- create a staged entry instruction for the next market session;
- write health reports and verified backups.

It may not fill a staged entry.

2. Regular-session execution
----------------------------

QPX_TERMUX_SESSION.sh checks every 15 minutes across a broad morning
window. Python permits an entry only from 09:35 through 10:30
America/New_York on the next eligible market session.

A paper entry uses the open of the first available one-minute
regular-session bar. includePrePost=false is required.

Safety rules:

- extended-hours execution is hard-disabled;
- the staged signal must be from the immediately preceding market
  session;
- stale instructions are cancelled;
- instructions that miss the opening window are cancelled;
- no after-close backfill is permitted;
- duplicate order IDs cannot execute twice;
- an opening gap above 1.5 signal ATR is rejected;
- position sizing and portfolio-risk rules still apply;
- the existing paper kill switch blocks session execution;
- every result is appended to the hash-chained audit journal;
- this remains simulated paper trading with no brokerage connection.

Future broker integration must use regular-hours orders and
broker-held protective OCO orders. Extended-hours trading remains
disabled unless a separate, explicit policy is designed and tested.

Commands:

python QPX_RUN_REGULAR_SESSION.py --check-only
python QPX_RUN_REGULAR_SESSION.py

Reports:

reports/qpx_session_execution/latest_session_execution.txt
reports/qpx_session_execution/latest_session_execution.json
