from pathlib import Path

from QPX_ANALYZE_V16_EXIT_DIAGNOSTICS import (
    DIAGNOSTIC_LABEL,
    TradeDiagnostic,
    _format_pf,
    _median,
    _profit_factor,
    _summary,
    _vix_regime,
)


assert (
    DIAGNOSTIC_LABEL
    == "V16_EXIT_DIAGNOSTIC_STUDY_V17"
)
assert abs(
    _median([1.0, 3.0, 2.0]) - 2.0
) < 1e-9
assert abs(
    _median([1.0, 3.0]) - 2.0
) < 1e-9
assert abs(
    _profit_factor(
        [2.0, -1.0, 1.0, -1.0]
    )
    - 1.5
) < 1e-9
assert _format_pf(None) == "∞"
assert _vix_regime(19.99) == "LOW_LT_20"
assert (
    _vix_regime(21.0)
    == "MODERATE_20_TO_24"
)
assert (
    _vix_regime(26.0)
    == "ELEVATED_24_TO_28"
)
assert (
    _vix_regime(29.0)
    == "HIGH_ALLOWED_GT_28"
)

from datetime import datetime, timezone

row = TradeDiagnostic(
    symbol="SPY",
    entry_time=datetime(
        2025, 1, 2, tzinfo=timezone.utc
    ),
    exit_time=datetime(
        2025, 1, 3, tzinfo=timezone.utc
    ),
    shares=1,
    entry_price=100.0,
    exit_price=102.0,
    pnl=2.0,
    result_r=0.4,
    exit_reason="TEST",
    signal_time=datetime(
        2025, 1, 2, tzinfo=timezone.utc
    ),
    entry_atr=2.0,
    entry_vix=18.0,
    vix_regime="LOW_LT_20",
    triggers=("MOMENTUM_PERSISTENCE",),
    trigger_combo="MOMENTUM_PERSISTENCE",
    holding_bars=2,
    holding_sessions=2,
    conservative_mfe_r=1.2,
    conservative_mae_r=0.4,
    pre_exit_mfe_r=1.0,
    profitable_before_exit_bar=False,
    reached_1r=True,
    reached_2r=False,
    reached_3r=False,
)
summary = _summary([row])
assert summary["trades"] == 1
assert summary["wins"] == 1
assert abs(summary["net_pnl"] - 2.0) < 1e-9

root = Path(__file__).resolve().parents[1]
source = (
    root
    / "QPX_ANALYZE_V16_EXIT_DIAGNOSTICS.py"
).read_text(encoding="utf-8")

for marker in (
    "Strategy rerun               : NO",
    "Entry/exit rule changes      : NONE",
    "conservative_exit_bar_method",
    "profitable_before_exit_bar",
    "winner_reached_1r",
    "winner_reached_2r",
    "winner_reached_3r",
    "BY EXIT REASON",
    "BY SYMBOL",
    "BY ENTRY VIX REGIME",
    "BY ENTRY TRIGGER (COUNTS OVERLAP)",
    "BY TRIGGER COMBINATION",
):
    assert marker in source, marker

for prohibited in (
    "fetch_aggregate_history(",
    "MASSIVE_API_KEY",
    "POLYGON_API_KEY",
    "getpass",
):
    assert prohibited not in source, prohibited

print(
    "QPX V16 Exit Diagnostics V17 PASS"
)
