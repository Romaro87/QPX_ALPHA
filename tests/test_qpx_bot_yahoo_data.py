from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.dividends import load_dividend_csv
from qpx_bot.real_data import load_market_csv, load_vix_csv
from qpx_bot.yahoo_data import download_real_dataset


def make_result(
    *,
    symbol: str,
    base_price: float,
    volume: int,
    with_dividends: bool,
):
    start = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    timestamps = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []

    for index in range(260):
        moment = start + timedelta(days=index)
        price = base_price + (index * 0.03)
        timestamps.append(int(moment.timestamp()))
        opens.append(price)
        highs.append(price + 1.0)
        lows.append(price - 1.0)
        closes.append(price + 0.25)
        volumes.append(volume)

    events = {}

    if with_dividends:
        dividend_events = {}
        for index, amount in (
            (20, 0.20),
            (70, 0.22),
            (140, 0.19),
            (220, 0.24),
        ):
            timestamp = timestamps[index]
            dividend_events[str(timestamp)] = {
                "amount": amount,
                "date": timestamp,
            }
        events["dividends"] = dividend_events

    return {
        "meta": {"symbol": symbol},
        "timestamp": timestamps,
        "indicators": {
            "quote": [
                {
                    "open": opens,
                    "high": highs,
                    "low": lows,
                    "close": closes,
                    "volume": volumes,
                }
            ]
        },
        "events": events,
    }


responses = {
    "SPY": make_result(
        symbol="SPY",
        base_price=450.0,
        volume=70_000_000,
        with_dividends=False,
    ),
    "QDTE": make_result(
        symbol="QDTE",
        base_price=40.0,
        volume=1_500_000,
        with_dividends=True,
    ),
    "^VIX": make_result(
        symbol="^VIX",
        base_price=18.0,
        volume=0,
        with_dividends=False,
    ),
}


def fake_fetcher(symbol: str):
    return responses[symbol]


with TemporaryDirectory() as temporary_directory:
    input_directory = Path(temporary_directory) / "inputs"

    summary = download_real_dataset(
        swing_symbol="SPY",
        input_directory=input_directory,
        fetcher=fake_fetcher,
    )

    assert summary.swing_symbol == "SPY"
    assert summary.income_symbol == "QDTE"
    assert summary.swing_rows == 260
    assert summary.income_rows == 260
    assert summary.vix_rows == 260
    assert summary.dividend_events == 4
    assert summary.common_first_date <= summary.common_last_date

    swing = load_market_csv(input_directory / "SWING.csv")
    income = load_market_csv(input_directory / "QDTE.csv")
    vix = load_vix_csv(input_directory / "VIX.csv")
    dividends = load_dividend_csv(
        input_directory / "QDTE_DIVIDENDS.csv"
    )

    assert len(swing) == 260
    assert len(income) == 260
    assert len(vix) == 260
    assert len(dividends) == 4
    assert dividends[0].amount_per_share == 0.20

    manifest = json.loads(
        (
            input_directory / "DOWNLOAD_MANIFEST.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["symbols"]["swing"] == "SPY"
    assert manifest["rows"]["dividend_events"] == 4
    assert len(manifest["files"]["swing"]["sha256"]) == 64

print("QPX Bot Market Data Acquisition PASS")
