QPX 15-MINUTE EIGHT-TICKER SIX-POSITION PAPER ENGINE
=====================================================

Active swing universe
---------------------

DIA
IWM
QQQ
SPY
XLE
XLF
XLK
XLV

Operating schedule
------------------

The one-shot runner is scheduled every 15 minutes on weekdays. The
runner itself enforces the New York regular-session calendar and only
processes completed 15-minute bars from 09:45 through 16:00 ET.

Extended-hours bars are excluded.

Entry and position policy
-------------------------

All eight ETFs are evaluated on every completed 15-minute bar.

Monthly rankings, winner selection, symbol bonuses, preferred symbols,
and fallback symbols are not used.

Up to six different ETF positions may be open or pending at one time.
The existing 1% base risk per trade and 6% aggregate active-risk cap
remain active. A sixth position is not guaranteed: cash, quarter-Kelly
sizing, opening-gap controls, or the global risk limit may reject it.

Signals are generated from a completed 15-minute bar and executed using
the next completed 15-minute bar's opening price. The 1.5 ATR opening
gap rejection remains active.

Account migration
-----------------

On its first in-session run, the engine copies the current persistent
paper-account snapshot into a new multi-position runtime. It preserves
QDTE shares, swing cash, tax reserves, contributions, realized P&L, and
an existing open swing position.

The original single-position paper state is not changed or deleted.
An old pending daily instruction is cancelled during migration because
it is incompatible with the new 15-minute execution clock.

Files
-----

One-shot runner:
    python QPX_RUN_15M_PAPER.py

Compatibility runner:
    python QPX_RUN_AUTO_PAPER.py

Fallback daemon:
    python QPX_START_15M_DAEMON.py

Runtime:
    qpx_bot/intraday_six_runtime/

Latest status:
    reports/qpx_intraday_six/latest_15m_paper_status.json

Latest entry diagnostics:
    reports/qpx_intraday_six/latest_15m_entry_diagnostics.json

Safety
------

This remains simulated paper trading. Live brokerage is disabled.
Historical or paper results do not guarantee future performance.
