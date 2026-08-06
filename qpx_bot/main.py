"""QPX Bot command-line entry point."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import load_csv
from qpx_bot.indicators import calculate_indicators
from qpx_bot.portfolio import Portfolio, contribution_allocation
from qpx_bot.risk import calculate_position_size


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_FILE = PACKAGE_DIR / "sample_data" / "sample.csv"


def run(data_file: str | Path | None = None) -> int:
    """Validate indicators, risk sizing, and portfolio accounting."""
    config = BotConfig()
    config.validate()

    selected_file = (
        Path(data_file).expanduser()
        if data_file is not None
        else DEFAULT_DATA_FILE
    )

    candles = load_csv(selected_file)
    indicators = calculate_indicators(candles, config)
    latest_index = indicators.latest_complete_index()

    print("=" * 68)
    print("QPX BOT v1.2 — PORTFOLIO + RISK ENGINE")
    print("=" * 68)
    print(f"Data file      : {selected_file}")
    print(f"Candles loaded : {len(candles)}")

    if latest_index is None:
        print("Status          : INSUFFICIENT DATA")
        return 1

    candle = candles[latest_index]
    atr = indicators.atr[latest_index]

    if atr is None:
        print("Status          : ATR NOT READY")
        return 1

    portfolio = Portfolio(config.starting_cash)
    sizing = calculate_position_size(
        account_equity=portfolio.equity({}),
        available_cash=portfolio.cash,
        entry_price=candle.close,
        atr=atr,
        active_risk=portfolio.active_risk(),
        config=config,
    )
    income_weight, swing_weight = contribution_allocation(
        0,
        config,
    )

    print(f"Latest date     : {candle.date}")
    print(f"Close           : ${candle.close:,.2f}")
    print(f"ATR             : {atr:,.4f}")
    print(f"Risk fraction   : {sizing.risk_fraction:.2%}")
    print(f"Planned shares  : {sizing.shares}")
    print(f"Planned risk    : ${sizing.planned_risk:,.2f}")
    print(f"Stop price      : ${sizing.stop_price:,.2f}")
    print(f"Target price    : ${sizing.target_price:,.2f}")
    print(
        "Contribution mix: "
        f"{income_weight:.0%} income / "
        f"{swing_weight:.0%} swing"
    )

    if sizing.is_tradeable:
        portfolio.open_position(
            symbol="DEMO",
            sizing=sizing,
            entry_date=date.today(),
            entry_atr=atr,
        )
        print(
            f"Active risk     : "
            f"${portfolio.active_risk():,.2f}"
        )
        print(f"Cash remaining  : ${portfolio.cash:,.2f}")
    else:
        print(
            f"Trade status    : {sizing.blocked_reason}"
        )

    print("Tax reserve     : $0.00")
    print("Status          : PASS")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
