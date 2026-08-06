QPX INITIAL CAPITAL AND ALLOCATION REBALANCE
============================================

Initial external capital
------------------------

QDTE seed          : $1,300
Swing liquidity    : $1,500
Total initial cash : $2,800

The initial account is immediately rebalanced toward the active target
after the two explicit seed amounts are deposited.

Target allocations
------------------

Years 1–2
    65% QDTE / 35% swing

Year 3 onward
    40% QDTE / 60% swing

Monthly processing
------------------

On the first processed market session of each new month:

1. The complete $2,000 external contribution enters swing cash.
2. The portfolio is marked using the current QDTE and swing prices.
3. QDTE is bought or sold to move toward the active target.
4. Open swing positions are never liquidated by the allocator.
5. When QDTE is underweight but swing cash is committed to an open
   trade, the QDTE purchase is partial and the remaining drift is
   reported.
6. Positive realized gains from QDTE rebalance sales reserve 37% in
   tax cash.
7. Slippage is applied to every QDTE rebalance trade.
8. The rebalance is recorded in the paper audit journal.

The tolerance is 0.25 percentage points. Trades below $1 are deferred.

Existing paper account
----------------------

The installer creates a verified backup before migration. It then:

- adds the missing $1,500 initial swing contribution exactly once;
- changes initial contributed capital from $1,300 to $2,800;
- rebalances QDTE toward the currently active target;
- preserves any open swing position;
- writes a hash-chained CAPITAL_ALLOCATION_MIGRATION event.

Manual idempotent migration command:

python QPX_MIGRATE_CAPITAL_ALLOCATION.py

Simulation only. No brokerage connection or live orders.
