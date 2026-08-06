QPX PERSISTENT PAPER TRADING
============================

Daily command:

python QPX_RUN_AUTO_PAPER.py

The runner:

- Refreshes real SPY, QDTE, QDTE dividend, and VIX data
- Processes only unseen daily bars
- Persists cash, holdings, positions, stops, pending entries, taxes,
  dividends, contribution history, and completed order keys
- Executes entry signals at the next daily open with simulated slippage
- Applies ATR stops, targets, and trailing stops
- Prevents duplicate daily processing and duplicate entry fills
- Verifies state with a SHA-256 checksum
- Maintains an append-only hash-chain JSONL audit journal
- Uses a process lock to prevent concurrent runs
- Reconciles account equity after every processed bar
- Writes status files to reports/qpx_paper/

Hard stop:

python QPX_RUN_PAPER.py --kill

Resume:

python QPX_RUN_PAPER.py --resume

Status without advancing:

python QPX_RUN_PAPER.py --status

Use existing downloaded files without network refresh:

python QPX_RUN_PAPER.py --symbol SPY --no-refresh

Runtime state is stored under qpx_bot/paper_runtime/ and is excluded
from Git. Preserve that folder when moving the paper account.

This module has no brokerage connection and cannot place live orders.
It is a simulated operational rehearsal, not financial advice.
