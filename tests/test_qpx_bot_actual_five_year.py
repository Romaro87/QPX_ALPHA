import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.actual_five_year import (
    normalize_symbol,
    resolve_symbol,
    subtract_years,
)


assert normalize_symbol("xlk") == "XLK"
assert normalize_symbol("^vix") == "^VIX"
assert subtract_years(
    date(2024, 2, 29),
    5,
) == date(2019, 2, 28)

try:
    normalize_symbol("not a ticker")
except ValueError:
    pass
else:
    raise AssertionError(
        "Invalid ticker text was accepted."
    )

with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)
    selection = root / "selection"
    selection.mkdir(parents=True)
    (
        selection / "selection_decision.json"
    ).write_text(
        json.dumps(
            {
                "selected_symbol": "XLK",
                "symbol_bonus_policy": "none",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    resolution = resolve_symbol(
        explicit_symbol=None,
        selection_runtime=selection,
        paper_runtime=root / "paper",
    )
    assert resolution.symbol == "XLK"
    assert (
        resolution.source
        == "CURRENT_SELECTION_DECISION"
    )

    explicit = resolve_symbol(
        explicit_symbol="IWM",
        selection_runtime=selection,
        paper_runtime=root / "paper",
    )
    assert explicit.symbol == "IWM"
    assert explicit.source == "EXPLICIT_CLI"

source = (
    Path(__file__).resolve().parents[1]
    / "qpx_bot"
    / "actual_five_year.py"
).read_text(encoding="utf-8")

assert "run_backtest(" in source
assert "forced_entry_indices=None" in source
assert 'range_name="6y"' in source
assert "download_real_dataset(" in source
assert "MINIMUM_FIVE_YEAR_BARS = 1_200" in source
assert "No pre-inception QDTE data was fabricated." in source
assert "forced_entry_indices={" not in source

print("QPX Bot Actual Five-Year Backtest Runner PASS")
