import csv
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.config import BotConfig
from qpx_bot.run_real_backtest import run_real_data_backtest


config = replace(
    BotConfig(),
    starting_cash=10_000.0,
    monthly_contribution=500.0,
    ema_fast_period=2,
    ema_slow_period=3,
    rsi_period=3,
    rmi_period=3,
    rmi_momentum=2,
    sma_trend_period=5,
    sma_slope_lookback=2,
    atr_period=3,
    average_volume_period=3,
    breakout_lookback=3,
)

with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)
    input_dir = root / "inputs"
    output_dir = root / "outputs"
    input_dir.mkdir()

    start = date(2022, 1, 3)
    rows = []

    for index in range(260):
        day = start + timedelta(days=index)
        price = 100.0 + (index * 0.08)
        rows.append(
            {
                "day": day,
                "open": price,
                "high": price + (5.0 if index == 25 else 1.0),
                "low": price - 1.0,
                "close": price + 0.25,
                "volume": 3_000_000,
            }
        )

    with (input_dir / "SWING.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            ["time", "open", "high", "low", "close", "Volume"]
        )
        for row in rows:
            timestamp = int(
                datetime(
                    row["day"].year,
                    row["day"].month,
                    row["day"].day,
                    tzinfo=timezone.utc,
                ).timestamp()
            )
            writer.writerow(
                [
                    timestamp,
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                ]
            )

    with (input_dir / "QDTE.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            ["Date", "Open", "High", "Low", "Close", "Volume"]
        )
        for index, row in enumerate(rows):
            price = 40.0 + (index * 0.03)
            writer.writerow(
                [
                    row["day"].isoformat(),
                    price,
                    price + 0.40,
                    price - 0.40,
                    price + 0.10,
                    1_500_000,
                ]
            )

    with (input_dir / "VIX.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(["Date", "VIX"])
        for row in rows:
            writer.writerow([row["day"].isoformat(), 20.0])

    with (input_dir / "QDTE_DIVIDENDS.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(["Date", "Dividend"])
        for index in (20, 60, 120, 200):
            writer.writerow([rows[index]["day"].isoformat(), 0.20])

    result, validation, artifacts = run_real_data_backtest(
        input_directory=input_dir,
        output_directory=output_dir,
        swing_symbol="TEST",
        config=config,
        forced_entry_indices={20},
    )

    assert validation.ready
    assert result.swing_symbol == "TEST"
    assert result.total_dividends > 0
    assert result.ending_equity > 0
    assert len(result.trades) == 1

    for path in artifacts.values():
        assert path.exists()

    manifest = artifacts["manifest"].read_text(encoding="utf-8")
    assert '"sha256"' in manifest
    assert '"qpx_version": "1.7.0"' in manifest

print("QPX Bot Real Historical Data Pipeline PASS")
