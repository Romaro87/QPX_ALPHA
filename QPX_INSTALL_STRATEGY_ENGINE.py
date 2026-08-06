#!/usr/bin/env python3
"""Install, test, commit, and push the QPX Bot strategy engine."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    candidates = [
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ]

    for start in candidates:
        for candidate in (start, *start.parents):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Save this installer inside "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_root()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / "qpx_bot_strategy_engine" / STAMP

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nBacktesting bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.3.0"\n',
    "qpx_bot/strategy.py": '"""Entry decisions and ATR-based exit management for QPX Bot."""\n\nfrom __future__ import annotations\n\nfrom dataclasses import dataclass\nfrom typing import Sequence\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.indicators import IndicatorSet\nfrom qpx_bot.portfolio import Position\n\n\n@dataclass(frozen=True, slots=True)\nclass EntryEvaluation:\n    """Complete explanation of one potential long entry."""\n\n    index: int\n    should_enter: bool\n    checks: dict[str, bool]\n    triggers: tuple[str, ...]\n    failed_checks: tuple[str, ...]\n\n    @property\n    def decision(self) -> str:\n        return "ENTER" if self.should_enter else "HOLD"\n\n\n@dataclass(frozen=True, slots=True)\nclass ExitEvaluation:\n    """Exit decision plus the stop state for the next daily bar."""\n\n    should_exit: bool\n    reason: str | None\n    exit_price: float | None\n    next_stop_price: float\n    highest_price: float\n    trailing_active: bool\n\n    @property\n    def decision(self) -> str:\n        return "EXIT" if self.should_exit else "HOLD"\n\n\ndef _value(\n    series: Sequence[float | None],\n    index: int,\n) -> float | None:\n    if index < 0 or index >= len(series):\n        return None\n    return series[index]\n\n\ndef _resolve_vix(\n    vix: float | Sequence[float],\n    index: int,\n) -> float:\n    if isinstance(vix, (int, float)):\n        value = float(vix)\n    else:\n        if index < 0 or index >= len(vix):\n            raise IndexError("VIX series does not cover the requested index.")\n        value = float(vix[index])\n\n    if value < 0:\n        raise ValueError("VIX cannot be negative.")\n\n    return value\n\n\ndef evaluate_entry(\n    *,\n    candles: Sequence[Candle],\n    indicators: IndicatorSet,\n    index: int,\n    vix: float | Sequence[float],\n    config: BotConfig,\n) -> EntryEvaluation:\n    """\n    Evaluate the configured long-entry rules at one closing bar.\n\n    Every filter must pass. At least one momentum trigger must cross\n    bullishly on the current bar. The order is intended for execution\n    at the next bar\'s open by the later backtesting engine.\n    """\n    config.validate()\n\n    if index < 0 or index >= len(candles):\n        raise IndexError("Entry index is outside the candle series.")\n\n    previous_index = index - 1\n    slope_index = index - config.sma_slope_lookback\n    breakout_start = index - config.breakout_lookback\n\n    if (\n        previous_index < 0\n        or slope_index < 0\n        or breakout_start < 0\n    ):\n        return EntryEvaluation(\n            index=index,\n            should_enter=False,\n            checks={"data_ready": False},\n            triggers=(),\n            failed_checks=("data_ready",),\n        )\n\n    current_fast = _value(indicators.ema_fast, index)\n    previous_fast = _value(indicators.ema_fast, previous_index)\n    current_slow = _value(indicators.ema_slow, index)\n    previous_slow = _value(indicators.ema_slow, previous_index)\n    current_rsi = _value(indicators.rsi, index)\n    previous_rsi = _value(indicators.rsi, previous_index)\n    current_rmi = _value(indicators.rmi, index)\n    previous_rmi = _value(indicators.rmi, previous_index)\n    current_sma = _value(indicators.sma_trend, index)\n    slope_sma = _value(indicators.sma_trend, slope_index)\n    baseline_volume = _value(\n        indicators.average_volume,\n        previous_index,\n    )\n    current_atr = _value(indicators.atr, index)\n\n    required_values = (\n        current_fast,\n        previous_fast,\n        current_slow,\n        previous_slow,\n        current_rsi,\n        previous_rsi,\n        current_rmi,\n        previous_rmi,\n        current_sma,\n        slope_sma,\n        baseline_volume,\n        current_atr,\n    )\n\n    if any(value is None for value in required_values):\n        return EntryEvaluation(\n            index=index,\n            should_enter=False,\n            checks={"data_ready": False},\n            triggers=(),\n            failed_checks=("data_ready",),\n        )\n\n    candle = candles[index]\n    prior_high = max(\n        prior_candle.high\n        for prior_candle in candles[breakout_start:index]\n    )\n    current_vix = _resolve_vix(vix, index)\n\n    ema_cross = (\n        previous_fast <= previous_slow\n        and current_fast > current_slow\n    )\n    rsi_cross = (\n        previous_rsi <= config.rsi_strength_level\n        and current_rsi > config.rsi_strength_level\n    )\n    rmi_cross = (\n        previous_rmi <= config.rsi_strength_level\n        and current_rmi > config.rsi_strength_level\n    )\n\n    triggers = tuple(\n        name\n        for name, triggered in (\n            ("EMA_CROSS", ema_cross),\n            ("RSI_CROSS", rsi_cross),\n            ("RMI_CROSS", rmi_cross),\n        )\n        if triggered\n    )\n\n    checks = {\n        "data_ready": True,\n        "price_above_sma": candle.close > current_sma,\n        "sma_slope_positive": current_sma > slope_sma,\n        "average_volume": (\n            baseline_volume\n            >= config.minimum_average_daily_volume\n        ),\n        "breakout_volume": (\n            candle.volume\n            >= (\n                baseline_volume\n                * config.breakout_volume_multiplier\n            )\n        ),\n        "price_breakout": candle.close > prior_high,\n        "vix_filter": (\n            current_vix <= config.maximum_vix_for_entries\n        ),\n        "rsi_not_overbought": (\n            current_rsi <= config.rsi_overbought\n        ),\n        "momentum_trigger": bool(triggers),\n    }\n\n    failed = tuple(\n        name\n        for name, passed in checks.items()\n        if not passed\n    )\n\n    return EntryEvaluation(\n        index=index,\n        should_enter=not failed,\n        checks=checks,\n        triggers=triggers,\n        failed_checks=failed,\n    )\n\n\ndef scan_entry_signals(\n    *,\n    candles: Sequence[Candle],\n    indicators: IndicatorSet,\n    vix: float | Sequence[float],\n    config: BotConfig,\n) -> list[EntryEvaluation]:\n    """Return every qualifying long-entry signal."""\n    start_index = max(\n        config.sma_trend_period - 1,\n        config.breakout_lookback,\n        config.sma_slope_lookback,\n        1,\n    )\n    signals: list[EntryEvaluation] = []\n\n    for index in range(start_index, len(candles)):\n        evaluation = evaluate_entry(\n            candles=candles,\n            indicators=indicators,\n            index=index,\n            vix=vix,\n            config=config,\n        )\n        if evaluation.should_enter:\n            signals.append(evaluation)\n\n    return signals\n\n\ndef evaluate_exit(\n    *,\n    position: Position,\n    candle: Candle,\n    current_atr: float,\n    config: BotConfig,\n) -> ExitEvaluation:\n    """\n    Evaluate stop, target, and trailing-stop behavior.\n\n    Existing stop and target levels are checked before calculating a\n    new trailing stop. This prevents using the current bar\'s high to\n    create a stop that is then assumed to have executed earlier inside\n    the same bar. When both stop and target are touched, the stop wins.\n    """\n    config.validate()\n\n    if current_atr <= 0:\n        raise ValueError("Current ATR must be positive.")\n\n    stop = position.stop_price\n    target = position.target_price\n\n    if candle.open <= stop:\n        return ExitEvaluation(\n            should_exit=True,\n            reason="STOP_GAP",\n            exit_price=candle.open,\n            next_stop_price=stop,\n            highest_price=max(position.highest_price, candle.high),\n            trailing_active=False,\n        )\n\n    if candle.low <= stop:\n        return ExitEvaluation(\n            should_exit=True,\n            reason="ATR_STOP",\n            exit_price=stop,\n            next_stop_price=stop,\n            highest_price=max(position.highest_price, candle.high),\n            trailing_active=False,\n        )\n\n    if candle.open >= target:\n        return ExitEvaluation(\n            should_exit=True,\n            reason="TARGET_GAP",\n            exit_price=candle.open,\n            next_stop_price=stop,\n            highest_price=max(position.highest_price, candle.high),\n            trailing_active=False,\n        )\n\n    if candle.high >= target:\n        return ExitEvaluation(\n            should_exit=True,\n            reason="ATR_TARGET",\n            exit_price=target,\n            next_stop_price=stop,\n            highest_price=max(position.highest_price, candle.high),\n            trailing_active=False,\n        )\n\n    highest_price = max(position.highest_price, candle.high)\n    activation_price = (\n        position.entry_price\n        + (\n            position.entry_atr\n            * config.trailing_activation_atr\n        )\n    )\n    trailing_active = highest_price >= activation_price\n    next_stop = stop\n\n    if trailing_active:\n        candidate = (\n            highest_price\n            - (\n                current_atr\n                * config.stop_atr_multiple\n            )\n        )\n        next_stop = max(stop, candidate)\n\n    return ExitEvaluation(\n        should_exit=False,\n        reason=None,\n        exit_price=None,\n        next_stop_price=next_stop,\n        highest_price=highest_price,\n        trailing_active=trailing_active,\n    )\n',
    "qpx_bot/main.py": '"""QPX Bot command-line entry point."""\n\nfrom __future__ import annotations\n\nfrom pathlib import Path\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import load_csv\nfrom qpx_bot.indicators import calculate_indicators\nfrom qpx_bot.portfolio import Portfolio\nfrom qpx_bot.risk import calculate_position_size\nfrom qpx_bot.strategy import evaluate_entry, scan_entry_signals\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nDEFAULT_DATA_FILE = PACKAGE_DIR / "sample_data" / "sample.csv"\nDEMO_VIX = 20.0\n\n\ndef _display_value(value: float | None, decimals: int = 2) -> str:\n    if value is None:\n        return "not ready"\n    return f"{value:,.{decimals}f}"\n\n\ndef run(data_file: str | Path | None = None) -> int:\n    """Load data and run the strategy-decision milestone."""\n    config = BotConfig()\n    config.validate()\n\n    selected_file = (\n        Path(data_file).expanduser()\n        if data_file is not None\n        else DEFAULT_DATA_FILE\n    )\n\n    print("=" * 70)\n    print("QPX BOT v1.3 — STRATEGY DECISION ENGINE")\n    print("=" * 70)\n    print(f"Data file       : {selected_file}")\n    print(f"Starting cash   : ${config.starting_cash:,.2f}")\n    print(f"Demo VIX        : {DEMO_VIX:.2f}")\n    print()\n\n    candles = load_csv(selected_file)\n    indicators = calculate_indicators(candles, config)\n    latest_index = indicators.latest_complete_index()\n\n    if latest_index is None:\n        print("Status           : INSUFFICIENT DATA")\n        return 1\n\n    candle = candles[latest_index]\n    atr = indicators.atr[latest_index]\n\n    if atr is None:\n        print("Status           : ATR NOT READY")\n        return 1\n\n    current = evaluate_entry(\n        candles=candles,\n        indicators=indicators,\n        index=latest_index,\n        vix=DEMO_VIX,\n        config=config,\n    )\n    signals = scan_entry_signals(\n        candles=candles,\n        indicators=indicators,\n        vix=DEMO_VIX,\n        config=config,\n    )\n\n    portfolio = Portfolio(config.starting_cash)\n    sizing = calculate_position_size(\n        account_equity=config.starting_cash,\n        available_cash=portfolio.cash,\n        entry_price=candle.close,\n        atr=atr,\n        active_risk=portfolio.active_risk(),\n        config=config,\n    )\n\n    print(f"Candles loaded  : {len(candles)}")\n    print(f"Latest date     : {candle.date}")\n    print(f"Close           : ${candle.close:,.2f}")\n    print(f"ATR             : {_display_value(atr, 4)}")\n    print(f"Signals found   : {len(signals)}")\n    print(f"Latest decision : {current.decision}")\n\n    if current.triggers:\n        print(f"Latest triggers : {\', \'.join(current.triggers)}")\n    else:\n        print("Latest triggers : none")\n\n    if current.failed_checks:\n        print(\n            "Blocked by      : "\n            + ", ".join(current.failed_checks)\n        )\n    else:\n        print("Blocked by      : none")\n\n    print(f"Planned shares  : {sizing.shares}")\n    print(f"Planned risk    : ${sizing.planned_risk:,.2f}")\n    print()\n    print("Status           : PASS")\n    print("=" * 70)\n\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(run())\n',
    "tests/test_qpx_bot_strategy.py": 'from datetime import date, timedelta\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.indicators import IndicatorSet\nfrom qpx_bot.portfolio import Position\nfrom qpx_bot.strategy import evaluate_entry, evaluate_exit\n\n\nconfig = BotConfig()\ncount = 220\nstart = date(2024, 1, 2)\n\ncandles = []\nfor index in range(count):\n    close = 100.0 + (index * 0.10)\n    candles.append(\n        Candle(\n            date=start + timedelta(days=index),\n            open=close - 0.20,\n            high=close + 0.50,\n            low=close - 0.50,\n            close=close,\n            volume=2_500_000,\n        )\n    )\n\nsignal_index = count - 1\ncandles[signal_index] = Candle(\n    date=candles[signal_index].date,\n    open=126.00,\n    high=131.00,\n    low=125.50,\n    close=130.00,\n    volume=3_200_000,\n)\n\nempty = [None] * count\nema_fast = empty.copy()\nema_slow = empty.copy()\nrsi = empty.copy()\nrmi = empty.copy()\natr = empty.copy()\nsma = empty.copy()\naverage_volume = empty.copy()\n\nprevious = signal_index - 1\nslope_index = signal_index - config.sma_slope_lookback\n\nema_fast[previous] = 100.0\nema_slow[previous] = 101.0\nema_fast[signal_index] = 103.0\nema_slow[signal_index] = 102.0\n\nrsi[previous] = 49.0\nrsi[signal_index] = 55.0\nrmi[previous] = 48.0\nrmi[signal_index] = 56.0\n\natr[signal_index] = 2.0\nsma[slope_index] = 109.0\nsma[signal_index] = 110.0\naverage_volume[previous] = 2_500_000.0\n\nindicators = IndicatorSet(\n    ema_fast=ema_fast,\n    ema_slow=ema_slow,\n    rsi=rsi,\n    rmi=rmi,\n    atr=atr,\n    sma_trend=sma,\n    average_volume=average_volume,\n)\n\nentry = evaluate_entry(\n    candles=candles,\n    indicators=indicators,\n    index=signal_index,\n    vix=20.0,\n    config=config,\n)\n\nassert entry.should_enter\nassert entry.decision == "ENTER"\nassert "EMA_CROSS" in entry.triggers\nassert "RSI_CROSS" in entry.triggers\nassert "RMI_CROSS" in entry.triggers\nassert not entry.failed_checks\n\nblocked_vix = evaluate_entry(\n    candles=candles,\n    indicators=indicators,\n    index=signal_index,\n    vix=30.0,\n    config=config,\n)\nassert not blocked_vix.should_enter\nassert blocked_vix.failed_checks == ("vix_filter",)\n\nposition = Position(\n    symbol="TEST",\n    shares=10,\n    entry_date=date(2024, 1, 1),\n    entry_price=100.0,\n    entry_atr=2.0,\n    stop_price=95.0,\n    target_price=110.0,\n    highest_price=100.0,\n)\n\nboth_touched = Candle(\n    date=date(2024, 1, 2),\n    open=100.0,\n    high=111.0,\n    low=94.0,\n    close=105.0,\n    volume=3_000_000,\n)\nstop_exit = evaluate_exit(\n    position=position,\n    candle=both_touched,\n    current_atr=2.0,\n    config=config,\n)\nassert stop_exit.should_exit\nassert stop_exit.reason == "ATR_STOP"\nassert stop_exit.exit_price == 95.0\n\ntarget_bar = Candle(\n    date=date(2024, 1, 3),\n    open=100.0,\n    high=111.0,\n    low=96.0,\n    close=109.0,\n    volume=3_000_000,\n)\ntarget_exit = evaluate_exit(\n    position=position,\n    candle=target_bar,\n    current_atr=2.0,\n    config=config,\n)\nassert target_exit.should_exit\nassert target_exit.reason == "ATR_TARGET"\nassert target_exit.exit_price == 110.0\n\ntrail_bar = Candle(\n    date=date(2024, 1, 4),\n    open=103.0,\n    high=108.0,\n    low=101.0,\n    close=107.0,\n    volume=3_000_000,\n)\ntrail = evaluate_exit(\n    position=position,\n    candle=trail_bar,\n    current_atr=2.0,\n    config=config,\n)\nassert not trail.should_exit\nassert trail.trailing_active\nassert trail.highest_price == 108.0\nassert trail.next_stop_price == 103.0\n\nprint("QPX Bot Strategy Decision Engine PASS")\n',
}

originals: dict[str, bytes | None] = {}


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("$ " + " ".join(command))
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
    )


def ensure_target_files_are_safe() -> None:
    changed: list[str] = []

    for relative in FILES:
        worktree = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=ROOT,
        )

        if worktree.returncode != 0 or staged.returncode != 0:
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These bot files have uncommitted edits and were not "
            "overwritten:\n" + "\n".join(changed)
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
        print("Strategy engine is already installed and committed.")
        return

    run([
        "git",
        "commit",
        "-m",
        "Implement QPX Bot strategy decision engine",
    ])

    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError("Cannot push from a detached Git state.")

    run(["git", "push", "origin", branch])


def main() -> int:
    print("=" * 68)
    print("QPX BOT — STRATEGY DECISION ENGINE INSTALLER")
    print("=" * 68)
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
    print("=" * 68)
    print("QPX BOT STRATEGY DECISION ENGINE: COMPLETE")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
