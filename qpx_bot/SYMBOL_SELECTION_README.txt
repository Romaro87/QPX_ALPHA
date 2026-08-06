QPX DATA-DRIVEN SWING SYMBOL SELECTION
======================================

Recommended daily paper command:

python QPX_RUN_AUTO_PAPER.py

Selection policy:

- The candidate universe is stored in qpx_bot/swing_universe.json.
- SPY remains one candidate but receives no preference or bonus.
- No swing ticker is the default for manual runners.
- Each eligible ticker receives the same formula.
- The formula ranks adjusted 63-day and 126-day returns, distance
  above the 200-day trend, and median dollar liquidity.
- Annualized volatility and maximum drawdown reduce the score.
- Candidates with inadequate history, liquidity, or stale data are
  rejected.
- Equal scores are resolved alphabetically, not by preferred ticker.
- The winning symbol is held as the monthly selection decision.
- A live paper position or pending order locks the current symbol
  until that simulated account is flat.
- A flat paper account may rotate to the new monthly winner while
  preserving its cash, QDTE income holding, contributions, taxes,
  and audit history.

Manual explicit-symbol commands remain available:

python QPX_RUN_PAPER.py --symbol TICKER
python QPX_FETCH_AND_RUN_REAL_DATA.py --symbol TICKER
python QPX_RUN_WALK_FORWARD.py --symbol TICKER

Edit swing_universe.json to change candidates or transparent scoring
weights. All weights must remain nonnegative and total exactly 1.0.
Symbol-specific bonuses are rejected by validation.

This is a research ranking process, not a recommendation or guarantee.
