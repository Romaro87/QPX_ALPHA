from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.actual_two_year_portfolio import (
    EntryDiagnostic,
    REQUIRED_UNIVERSE,
    _elapsed_years as replay_elapsed_years,
    _write_entry_diagnostics,
)
from qpx_bot.capital_migration import (
    _elapsed_years as migration_elapsed_years,
)
from qpx_bot.hybrid import (
    _elapsed_years as hybrid_elapsed_years,
)
from qpx_bot.paper_engine import (
    _elapsed_years as paper_elapsed_years,
)
from qpx_bot.time_rules import (
    anniversary_date,
    elapsed_complete_years,
)


start = date(2024, 8, 6)

for helper in (
    elapsed_complete_years,
    replay_elapsed_years,
    migration_elapsed_years,
    hybrid_elapsed_years,
    paper_elapsed_years,
):
    assert helper(start, date(2026, 8, 3)) == 1
    assert helper(start, date(2026, 8, 5)) == 1
    assert helper(start, date(2026, 8, 6)) == 2
    assert helper(start, date(2026, 8, 7)) == 2

assert anniversary_date(
    date(2024, 2, 29),
    1,
) == date(2025, 2, 28)
assert elapsed_complete_years(
    date(2024, 2, 29),
    date(2025, 2, 27),
) == 0
assert elapsed_complete_years(
    date(2024, 2, 29),
    date(2025, 2, 28),
) == 1

assert REQUIRED_UNIVERSE == (
    "DIA",
    "IWM",
    "QQQ",
    "SPY",
    "XLE",
    "XLF",
    "XLK",
    "XLV",
)

diagnostic = EntryDiagnostic(
    date=date(2026, 8, 6),
    symbol="XLK",
    monthly_winner="XLK",
    active_symbol="XLK",
    portfolio_locked=False,
    execution_eligible=True,
    should_enter=False,
    triggers=(),
    failed_checks=(
        "breakout_volume",
        "momentum_trigger",
    ),
    checks={
        "data_ready": True,
        "price_above_sma": True,
        "sma_slope_positive": True,
        "average_volume": True,
        "breakout_volume": False,
        "price_breakout": True,
        "vix_filter": True,
        "rsi_not_overbought": True,
        "momentum_trigger": False,
    },
)

with TemporaryDirectory() as temporary_directory:
    path = (
        Path(temporary_directory)
        / "entry_filter_diagnostics.csv"
    )
    _write_entry_diagnostics(
        path,
        (diagnostic,),
    )
    content = path.read_text(
        encoding="utf-8"
    )
    assert "BreakoutVolume" not in content
    assert "breakout_volume" in content
    assert "momentum_trigger" in content
    assert "XLK" in content

root = Path(__file__).resolve().parents[1]
replay_source = (
    root
    / "qpx_bot"
    / "actual_two_year_portfolio.py"
).read_text(encoding="utf-8")
hybrid_source = (
    root / "qpx_bot" / "hybrid.py"
).read_text(encoding="utf-8")
paper_source = (
    root / "qpx_bot" / "paper_engine.py"
).read_text(encoding="utf-8")

assert (
    "for diagnostic_symbol in REQUIRED_UNIVERSE"
    in replay_source
)
assert "entry_filter_diagnostics.csv" in replay_source
assert "failed_check_counts" in replay_source
assert "active_failed_check_counts" in replay_source
assert '"strategy_parameters_changed": False' in replay_source
assert "forced_entry_indices=None" in replay_source
assert "ALLOCATION_PHASE_REBALANCE" in replay_source
assert "ALLOCATION_PHASE_REBALANCE" in paper_source
assert "phase_changed" in hybrid_source
assert "months // 12" not in replay_source
assert "months // 12" not in hybrid_source
assert "months // 12" not in paper_source

print(
    "QPX Exact Anniversary and Entry Diagnostics PASS"
)
