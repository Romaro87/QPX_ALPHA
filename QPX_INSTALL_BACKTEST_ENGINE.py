#!/usr/bin/env python3
"""Install, test, commit, and push the QPX Bot backtesting engine."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    starts = [
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ]

    for start in starts:
        for candidate in (start, *start.parents):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Run this file from "
        "/storage/emulated/0/QPX_ALPHA."
    )


ROOT = find_root()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / "qpx_bot_backtest_engine" / STAMP

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nBacktesting bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.4.0"\n',
    "qpx_bot/backtest.py": '"""Historical backtesting engine for QPX Bot."""\n\nfrom __future__ import annotations\n\nfrom dataclasses import dataclass\nfrom datetime import date\nfrom typing import Sequence\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.indicators import calculate_indicators\nfrom qpx_bot.portfolio import ClosedTrade, Portfolio\nfrom qpx_bot.risk import calculate_position_size\nfrom qpx_bot.strategy import evaluate_entry, evaluate_exit\n\n\n@dataclass(frozen=True, slots=True)\nclass EquityPoint:\n    """One end-of-day portfolio valuation."""\n\n    date: date\n    equity: float\n    cash: float\n    market_value: float\n    tax_reserve: float\n\n\n@dataclass(frozen=True, slots=True)\nclass BacktestResult:\n    """Complete immutable result of one historical simulation."""\n\n    symbol: str\n    start_date: date\n    end_date: date\n    starting_cash: float\n    total_contributions: float\n    ending_equity: float\n    ending_cash: float\n    tax_reserve: float\n    signal_count: int\n    rejected_entries: int\n    contribution_count: int\n    trades: tuple[ClosedTrade, ...]\n    equity_curve: tuple[EquityPoint, ...]\n\n    @property\n    def net_profit(self) -> float:\n        return self.ending_equity - self.total_contributions\n\n    @property\n    def return_on_contributed_capital(self) -> float:\n        if self.total_contributions <= 0:\n            return 0.0\n        return self.net_profit / self.total_contributions\n\n    @property\n    def win_rate(self) -> float:\n        if not self.trades:\n            return 0.0\n        winners = sum(1 for trade in self.trades if trade.pnl > 0)\n        return winners / len(self.trades)\n\n    @property\n    def profit_factor(self) -> float:\n        gross_profit = sum(\n            trade.pnl for trade in self.trades if trade.pnl > 0\n        )\n        gross_loss = -sum(\n            trade.pnl for trade in self.trades if trade.pnl < 0\n        )\n\n        if gross_loss == 0:\n            return float("inf") if gross_profit > 0 else 0.0\n\n        return gross_profit / gross_loss\n\n    @property\n    def maximum_drawdown(self) -> float:\n        if not self.equity_curve:\n            return 0.0\n\n        peak = self.equity_curve[0].equity\n        maximum = 0.0\n\n        for point in self.equity_curve:\n            peak = max(peak, point.equity)\n            if peak > 0:\n                drawdown = (peak - point.equity) / peak\n                maximum = max(maximum, drawdown)\n\n        return maximum\n\n\ndef _portfolio_prices(\n    portfolio: Portfolio,\n    symbol: str,\n    price: float,\n) -> dict[str, float]:\n    if symbol in portfolio.positions:\n        return {symbol: price}\n    return {}\n\n\ndef run_backtest(\n    *,\n    candles: Sequence[Candle],\n    symbol: str,\n    config: BotConfig,\n    vix: float | Sequence[float] = 20.0,\n    forced_entry_indices: set[int] | None = None,\n) -> BacktestResult:\n    """\n    Run a long-only, one-symbol historical simulation.\n\n    Strategy signals are evaluated at the close and executed at the\n    next bar\'s open. Existing stops are checked before targets when a\n    daily bar touches both. Monthly contributions are deposited on the\n    first available trading bar of each new calendar month.\n\n    ``forced_entry_indices`` is an explicit signal adapter used by\n    deterministic tests and external strategy integrations. Production\n    runs should leave it as ``None`` so QPX strategy rules are used.\n    """\n    config.validate()\n\n    normalized_symbol = symbol.strip().upper()\n    if not normalized_symbol:\n        raise ValueError("Backtest symbol cannot be empty.")\n\n    if len(candles) < 2:\n        raise ValueError("At least two candles are required.")\n\n    dates = [candle.date for candle in candles]\n    if dates != sorted(dates):\n        raise ValueError("Candles must be sorted by date.")\n\n    if len(dates) != len(set(dates)):\n        raise ValueError("Candles contain duplicate dates.")\n\n    indicators = calculate_indicators(candles, config)\n    portfolio = Portfolio(config.starting_cash)\n\n    pending_signal_index: int | None = None\n    signal_count = 0\n    rejected_entries = 0\n    contribution_count = 0\n    equity_curve: list[EquityPoint] = []\n    previous_month = (\n        candles[0].date.year,\n        candles[0].date.month,\n    )\n\n    for index, candle in enumerate(candles):\n        current_month = (candle.date.year, candle.date.month)\n\n        if current_month != previous_month:\n            if config.monthly_contribution > 0:\n                portfolio.deposit(config.monthly_contribution)\n                contribution_count += 1\n            previous_month = current_month\n\n        if (\n            pending_signal_index is not None\n            and normalized_symbol not in portfolio.positions\n        ):\n            signal_atr = indicators.atr[pending_signal_index]\n\n            if signal_atr is None or signal_atr <= 0:\n                rejected_entries += 1\n            else:\n                equity_at_open = portfolio.equity(\n                    _portfolio_prices(\n                        portfolio,\n                        normalized_symbol,\n                        candle.open,\n                    )\n                )\n                trade_results = [\n                    trade.result_r\n                    for trade in portfolio.closed_trades\n                ]\n                sizing = calculate_position_size(\n                    account_equity=equity_at_open,\n                    available_cash=portfolio.cash,\n                    entry_price=candle.open,\n                    atr=signal_atr,\n                    active_risk=portfolio.active_risk(),\n                    config=config,\n                    trade_results_r=trade_results,\n                )\n\n                if sizing.is_tradeable:\n                    portfolio.open_position(\n                        symbol=normalized_symbol,\n                        sizing=sizing,\n                        entry_date=candle.date,\n                        entry_atr=signal_atr,\n                    )\n                else:\n                    rejected_entries += 1\n\n            pending_signal_index = None\n\n        position = portfolio.positions.get(normalized_symbol)\n        current_atr = indicators.atr[index]\n\n        if position is not None and current_atr is not None:\n            exit_evaluation = evaluate_exit(\n                position=position,\n                candle=candle,\n                current_atr=current_atr,\n                config=config,\n            )\n\n            if exit_evaluation.should_exit:\n                assert exit_evaluation.exit_price is not None\n                portfolio.close_position(\n                    symbol=normalized_symbol,\n                    exit_price=exit_evaluation.exit_price,\n                    exit_date=candle.date,\n                    reason=exit_evaluation.reason or "EXIT",\n                    config=config,\n                )\n            else:\n                position.stop_price = (\n                    exit_evaluation.next_stop_price\n                )\n                position.highest_price = (\n                    exit_evaluation.highest_price\n                )\n\n        if (\n            index < len(candles) - 1\n            and normalized_symbol not in portfolio.positions\n            and pending_signal_index is None\n        ):\n            if forced_entry_indices is None:\n                entry_evaluation = evaluate_entry(\n                    candles=candles,\n                    indicators=indicators,\n                    index=index,\n                    vix=vix,\n                    config=config,\n                )\n                should_enter = entry_evaluation.should_enter\n            else:\n                should_enter = index in forced_entry_indices\n\n            if should_enter:\n                signal_count += 1\n                pending_signal_index = index\n\n        prices = _portfolio_prices(\n            portfolio,\n            normalized_symbol,\n            candle.close,\n        )\n        market_value = portfolio.market_value(prices)\n        equity_curve.append(\n            EquityPoint(\n                date=candle.date,\n                equity=portfolio.equity(prices),\n                cash=portfolio.cash,\n                market_value=market_value,\n                tax_reserve=portfolio.tax_reserve_cash,\n            )\n        )\n\n    final_candle = candles[-1]\n\n    if normalized_symbol in portfolio.positions:\n        portfolio.close_position(\n            symbol=normalized_symbol,\n            exit_price=final_candle.close,\n            exit_date=final_candle.date,\n            reason="END_OF_TEST",\n            config=config,\n        )\n        equity_curve[-1] = EquityPoint(\n            date=final_candle.date,\n            equity=portfolio.equity({}),\n            cash=portfolio.cash,\n            market_value=0.0,\n            tax_reserve=portfolio.tax_reserve_cash,\n        )\n\n    ending_equity = portfolio.equity({})\n\n    return BacktestResult(\n        symbol=normalized_symbol,\n        start_date=candles[0].date,\n        end_date=candles[-1].date,\n        starting_cash=config.starting_cash,\n        total_contributions=portfolio.total_contributions,\n        ending_equity=ending_equity,\n        ending_cash=portfolio.cash,\n        tax_reserve=portfolio.tax_reserve_cash,\n        signal_count=signal_count,\n        rejected_entries=rejected_entries,\n        contribution_count=contribution_count,\n        trades=tuple(portfolio.closed_trades),\n        equity_curve=tuple(equity_curve),\n    )\n',
    "qpx_bot/report.py": '"""Performance reporting and CSV exports for QPX Bot backtests."""\n\nfrom __future__ import annotations\n\nimport csv\nfrom pathlib import Path\n\nfrom qpx_bot.backtest import BacktestResult\n\n\ndef _money(value: float) -> str:\n    return f"${value:,.2f}"\n\n\ndef _percent(value: float) -> str:\n    return f"{value * 100.0:,.2f}%"\n\n\ndef format_backtest_report(result: BacktestResult) -> str:\n    """Return a readable text report for one backtest."""\n    profit_factor = (\n        "∞"\n        if result.profit_factor == float("inf")\n        else f"{result.profit_factor:,.2f}"\n    )\n\n    lines = [\n        "=" * 72,\n        "QPX BOT v1.4 — HISTORICAL BACKTEST",\n        "=" * 72,\n        f"Symbol                    : {result.symbol}",\n        f"Period                    : {result.start_date} to {result.end_date}",\n        f"Starting cash             : {_money(result.starting_cash)}",\n        f"Monthly deposits made     : {result.contribution_count}",\n        f"Total contributed capital : {_money(result.total_contributions)}",\n        f"Ending equity             : {_money(result.ending_equity)}",\n        f"Net profit                : {_money(result.net_profit)}",\n        (\n            "Return on contributed capital: "\n            f"{_percent(result.return_on_contributed_capital)}"\n        ),\n        f"Signals accepted          : {result.signal_count}",\n        f"Entries rejected by risk  : {result.rejected_entries}",\n        f"Closed trades             : {len(result.trades)}",\n        f"Win rate                  : {_percent(result.win_rate)}",\n        f"Profit factor             : {profit_factor}",\n        f"Maximum drawdown          : {_percent(result.maximum_drawdown)}",\n        f"Tax reserve cash          : {_money(result.tax_reserve)}",\n        "=" * 72,\n        "Research simulation only. This is not live trading or advice.",\n    ]\n\n    return "\\n".join(lines)\n\n\ndef write_trade_log(\n    result: BacktestResult,\n    filename: str | Path,\n) -> Path:\n    """Write completed trades to a CSV file."""\n    path = Path(filename)\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open("w", newline="", encoding="utf-8") as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            [\n                "Symbol",\n                "EntryDate",\n                "ExitDate",\n                "Shares",\n                "EntryPrice",\n                "ExitPrice",\n                "PnL",\n                "TaxReserved",\n                "ExitReason",\n                "ResultR",\n            ]\n        )\n\n        for trade in result.trades:\n            writer.writerow(\n                [\n                    trade.symbol,\n                    trade.entry_date.isoformat(),\n                    trade.exit_date.isoformat(),\n                    trade.shares,\n                    f"{trade.entry_price:.6f}",\n                    f"{trade.exit_price:.6f}",\n                    f"{trade.pnl:.6f}",\n                    f"{trade.tax_reserved:.6f}",\n                    trade.reason,\n                    f"{trade.result_r:.6f}",\n                ]\n            )\n\n    return path\n\n\ndef write_equity_curve(\n    result: BacktestResult,\n    filename: str | Path,\n) -> Path:\n    """Write end-of-day equity observations to a CSV file."""\n    path = Path(filename)\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open("w", newline="", encoding="utf-8") as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            [\n                "Date",\n                "Equity",\n                "Cash",\n                "MarketValue",\n                "TaxReserve",\n            ]\n        )\n\n        for point in result.equity_curve:\n            writer.writerow(\n                [\n                    point.date.isoformat(),\n                    f"{point.equity:.6f}",\n                    f"{point.cash:.6f}",\n                    f"{point.market_value:.6f}",\n                    f"{point.tax_reserve:.6f}",\n                ]\n            )\n\n    return path\n',
    "qpx_bot/main.py": '"""QPX Bot command-line entry point."""\n\nfrom __future__ import annotations\n\nfrom pathlib import Path\n\nfrom qpx_bot.backtest import run_backtest\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import load_csv\nfrom qpx_bot.report import format_backtest_report\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nDEFAULT_DATA_FILE = PACKAGE_DIR / "sample_data" / "sample.csv"\nDEMO_SYMBOL = "DEMO"\nDEMO_VIX = 20.0\n\n\ndef run(data_file: str | Path | None = None) -> int:\n    """Run the permanent historical-backtesting milestone."""\n    config = BotConfig()\n    config.validate()\n\n    selected_file = (\n        Path(data_file).expanduser()\n        if data_file is not None\n        else DEFAULT_DATA_FILE\n    )\n    candles = load_csv(selected_file)\n    result = run_backtest(\n        candles=candles,\n        symbol=DEMO_SYMBOL,\n        config=config,\n        vix=DEMO_VIX,\n    )\n\n    print(format_backtest_report(result))\n    print("Status                    : PASS")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(run())\n',
    "tests/test_qpx_bot_backtest.py": 'from datetime import date, timedelta\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.backtest import run_backtest\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.report import (\n    format_backtest_report,\n    write_equity_curve,\n    write_trade_log,\n)\n\n\nconfig = BotConfig(\n    starting_cash=10_000.0,\n    monthly_contribution=500.0,\n)\n\nstart = date(2024, 1, 2)\ncandles = []\n\nfor index in range(80):\n    day = start + timedelta(days=index)\n    base = 100.0 + (index * 0.25)\n\n    if index == 31:\n        open_price = 108.0\n        high = 109.0\n        low = 107.0\n        close = 108.5\n    elif index == 32:\n        open_price = 108.5\n        high = 121.0\n        low = 108.0\n        close = 120.0\n    else:\n        open_price = base\n        high = base + 1.0\n        low = base - 1.0\n        close = base + 0.25\n\n    candles.append(\n        Candle(\n            date=day,\n            open=open_price,\n            high=high,\n            low=low,\n            close=close,\n            volume=3_000_000,\n        )\n    )\n\nresult = run_backtest(\n    candles=candles,\n    symbol="TEST",\n    config=config,\n    vix=20.0,\n    forced_entry_indices={30},\n)\n\nassert result.symbol == "TEST"\nassert result.signal_count == 1\nassert result.contribution_count >= 2\nassert result.total_contributions > config.starting_cash\nassert len(result.trades) == 1\nassert result.trades[0].entry_date == candles[31].date\nassert result.trades[0].exit_date >= result.trades[0].entry_date\nassert len(result.equity_curve) == len(candles)\nassert result.ending_equity > 0\nassert 0.0 <= result.maximum_drawdown <= 1.0\nassert "HISTORICAL BACKTEST" in format_backtest_report(result)\n\nwith TemporaryDirectory() as temporary_directory:\n    directory = Path(temporary_directory)\n    trade_log = write_trade_log(\n        result,\n        directory / "trades.csv",\n    )\n    equity_log = write_equity_curve(\n        result,\n        directory / "equity.csv",\n    )\n\n    assert trade_log.exists()\n    assert equity_log.exists()\n    assert "EntryDate" in trade_log.read_text(encoding="utf-8")\n    assert "MarketValue" in equity_log.read_text(encoding="utf-8")\n\nprint("QPX Bot Backtesting Engine PASS")\n',
}

originals: dict[str, bytes | None] = {}


def run(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    print("$ " + " ".join(command))
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
    )


def ensure_target_files_are_safe() -> None:
    changed: list[str] = []

    for relative in FILES:
        unstaged = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=ROOT,
        )

        if unstaged.returncode != 0 or staged.returncode != 0:
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files contain uncommitted edits and were "
            "not overwritten:\n" + "\n".join(changed)
        )


def install() -> None:
    for relative, content in FILES.items():
        path = ROOT / relative
        originals[relative] = (
            path.read_bytes()
            if path.exists()
            else None
        )

        if path.exists():
            backup_path = BACKUP / relative
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )
        print(f"Installed: {relative}")


def restore() -> None:
    print("Restoring the previous working files...")

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(FILES)

    try:
        installer_relative = str(
            Path(__file__).resolve().relative_to(ROOT)
        )
        paths.append(installer_relative)
    except ValueError:
        pass

    run(["git", "add", "--", *paths])

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print("Backtesting engine is already installed and committed.")
        return

    run(
        [
            "git",
            "commit",
            "-m",
            "Implement QPX Bot historical backtesting engine",
        ]
    )

    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError("Cannot push from a detached Git state.")

    run(["git", "push", "origin", branch])


def main() -> int:
    print("=" * 70)
    print("QPX BOT — HISTORICAL BACKTEST ENGINE INSTALLER")
    print("=" * 70)
    print(f"Project: {ROOT}")

    ensure_target_files_are_safe()
    install()

    try:
        run([sys.executable, "-m", "qpx_bot"])
        run([sys.executable, "tests/run_all_tests.py"])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print("=" * 70)
    print("QPX BOT HISTORICAL BACKTEST ENGINE: COMPLETE")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
