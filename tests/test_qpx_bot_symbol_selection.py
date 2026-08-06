import json
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.symbol_selector import (
    SelectionConfig,
    load_selection_config,
    rank_candidates,
    write_selection_artifacts,
)
from qpx_bot.yahoo_data import MarketRow


def make_rows(
    *,
    slope: float,
    volume: int,
    wave: float,
):
    start = date(2024, 1, 2)
    rows = []

    for index in range(300):
        base = 100.0 + (slope * index)
        wobble = wave * ((index % 10) - 5) / 10.0
        price = base + wobble
        rows.append(
            MarketRow(
                date=start + timedelta(days=index),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.20,
                adjusted_close=price + 0.20,
                volume=volume,
            )
        )

    return rows


config = SelectionConfig(
    schema_version=1,
    decision_frequency="monthly",
    history_range="3y",
    candidates=("IWM", "QQQ", "SPY"),
    minimum_history_bars=252,
    minimum_eligible_candidates=3,
    minimum_median_dollar_volume=50_000_000.0,
    maximum_stale_days=4,
    short_return_lookback=63,
    long_return_lookback=126,
    trend_lookback=200,
    volatility_lookback=63,
    drawdown_lookback=126,
    liquidity_lookback=20,
    weights={
        "short_return": 0.25,
        "long_return": 0.30,
        "trend": 0.15,
        "liquidity": 0.10,
        "volatility_penalty": 0.10,
        "drawdown_penalty": 0.10,
    },
    symbol_bonus_policy="none",
)
config.validate()

histories = {
    "SPY": make_rows(
        slope=0.03,
        volume=5_000_000,
        wave=0.20,
    ),
    "QQQ": make_rows(
        slope=0.11,
        volume=5_000_000,
        wave=0.10,
    ),
    "IWM": make_rows(
        slope=0.01,
        volume=5_000_000,
        wave=0.40,
    ),
}

result = rank_candidates(histories, config)

assert result.selected_symbol == "QQQ"
assert result.symbol_bonus_policy == "none"
assert result.rankings[0].symbol == "QQQ"
assert next(
    candidate.rank
    for candidate in result.rankings
    if candidate.symbol == "SPY"
) != 1

with TemporaryDirectory() as temporary_directory:
    directory = Path(temporary_directory)
    config_path = directory / "universe.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "decision_frequency": "monthly",
                "history_range": "3y",
                "candidates": ["IWM", "QQQ", "SPY"],
                "minimum_history_bars": 252,
                "minimum_eligible_candidates": 3,
                "minimum_median_dollar_volume": 50000000,
                "maximum_stale_days": 4,
                "short_return_lookback": 63,
                "long_return_lookback": 126,
                "trend_lookback": 200,
                "volatility_lookback": 63,
                "drawdown_lookback": 126,
                "liquidity_lookback": 20,
                "weights": dict(config.weights),
                "symbol_bonus_policy": "none",
            }
        ),
        encoding="utf-8",
    )
    loaded = load_selection_config(config_path)
    assert "SPY" in loaded.candidates

    artifacts = write_selection_artifacts(
        result,
        directory / "reports",
    )
    assert artifacts["report"].exists()
    assert artifacts["rankings"].exists()
    assert artifacts["result"].exists()
    assert (
        '"selected_symbol": "QQQ"'
        in artifacts["result"].read_text(
            encoding="utf-8"
        )
    )

root = Path(__file__).resolve().parents[1]
paper_source = (
    root / "qpx_bot" / "paper_runner.py"
).read_text(encoding="utf-8")
fetch_source = (
    root / "QPX_FETCH_AND_RUN_REAL_DATA.py"
).read_text(encoding="utf-8")
walk_source = (
    root / "QPX_RUN_WALK_FORWARD.py"
).read_text(encoding="utf-8")

assert 'default="SPY"' not in paper_source
assert 'default="SPY"' not in fetch_source
assert 'default="SPY"' not in walk_source
assert "SPY" in (
    root / "qpx_bot" / "swing_universe.json"
).read_text(encoding="utf-8")

print("QPX Bot Data-Driven Symbol Selection PASS")
