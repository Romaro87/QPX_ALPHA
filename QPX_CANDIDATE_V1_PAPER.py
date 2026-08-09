from __future__ import annotations

import csv
import inspect
import json
import math
import sys
import urllib.request

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import qpx_bot.intraday_six_paper as paper
import qpx_bot.actual_two_year_15m_six as research

from qpx_bot.market_calendar import previous_market_session
from qpx_bot.symbol_config import load_symbol_config
from qpx_bot.portfolio import Portfolio as BasePortfolio
from qpx_bot.strategy import EntryEvaluation
from qpx_bot.scenario_config import load_scenario
from qpx_bot.forward_scenario import (
    forward_bot_config,
    forward_policy,
    forward_symbols,
    validate_forward_scenario,
)


PROJECT_ROOT = Path(__file__).resolve().parent

CANDIDATE_POLICY = (
    PROJECT_ROOT
    / "qpx_bot"
    / "candidate_v1_policy.json"
)


DEFAULT_FORWARD_SCENARIO = (
    PROJECT_ROOT
    / "qpx_bot"
    / "scenarios"
    / "candidate_v1.json"
)

ACTIVE_SCENARIO = load_scenario(
    DEFAULT_FORWARD_SCENARIO
)


CANDIDATE_RUNTIME = (
    PROJECT_ROOT
    / "qpx_bot"
    / "candidate_v1_runtime"
)

CANDIDATE_LEGACY_RUNTIME = (
    PROJECT_ROOT
    / "qpx_bot"
    / "candidate_v1_legacy_runtime"
)

CANDIDATE_REPORTS = (
    PROJECT_ROOT
    / "reports"
    / "qpx_candidate_v1_forward"
)

LOCAL_VIX_CACHE = (
    PROJECT_ROOT
    / "research_data"
    / "qpx_actual_two_year_15m_six"
    / "shared"
    / "CBOE_VIX_DAILY.csv"
)

VIX_URL = research.CBOE_VIX_HISTORY_URL

VIX_EXCLUDE_LOW = float(
    ACTIVE_SCENARIO.entry[
        "vix_exclusion_low"
    ]
)

VIX_EXCLUDE_HIGH = float(
    ACTIVE_SCENARIO.entry[
        "vix_exclusion_high"
    ]
)

MAXIMUM_POSITION_NOTIONAL = float(
    ACTIVE_SCENARIO.risk[
        "maximum_position_notional"
    ]
)

_vix_cache = None


def _find_relaxed_evaluator():
    """
    Locate the research evaluator by its explicit docstring
    rather than depending on a private function name.
    """
    matches = []

    for name, value in vars(research).items():
        if not callable(value):
            continue

        doc = inspect.getdoc(value) or ""

        if (
            "Research-only entry evaluation" in doc
            and
            "established bullish momentum state" in doc
        ):
            matches.append((name, value))

    if len(matches) != 1:
        names = [name for name, _ in matches]
        raise RuntimeError(
            "Could not uniquely locate relaxed entry "
            f"evaluator. Matches: {names}"
        )

    return matches[0]


RELAXED_EVALUATOR_NAME, RELAXED_EVALUATOR = (
    _find_relaxed_evaluator()
)


# ---------------------------------------------------------
# CANDIDATE CONFIGURATION
# ---------------------------------------------------------

_ORIGINAL_BOT_CONFIG = paper.BotConfig


def _candidate_config():
    config = forward_bot_config(
        ACTIVE_SCENARIO,
        _ORIGINAL_BOT_CONFIG(),
    )

    return config


paper.BotConfig = _candidate_config


_ORIGINAL_PAPER_LOAD_POLICY = (
    paper.load_policy
)


def _scenario_symbol_config():
    return forward_symbols(
        ACTIVE_SCENARIO
    )


def _scenario_policy(
    filename=CANDIDATE_POLICY,
):
    base = _ORIGINAL_PAPER_LOAD_POLICY(
        filename
    )

    return forward_policy(
        base,
        ACTIVE_SCENARIO,
    )


paper.load_symbol_config = (
    _scenario_symbol_config
)

paper.load_policy = (
    _scenario_policy
)


# ---------------------------------------------------------
# OFFICIAL PREVIOUS-SESSION VIX
# ---------------------------------------------------------

def _parse_date(value):
    value = value.strip()

    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(
                value,
                fmt,
            ).date()
        except ValueError:
            pass

    raise ValueError(
        f"Unsupported VIX date: {value!r}"
    )


def _parse_vix_csv(raw):
    rows = csv.DictReader(raw.splitlines())

    result = {}

    for row in rows:
        date_text = (
            row.get("DATE")
            or row.get("Date")
            or row.get("date")
        )

        close_text = (
            row.get("CLOSE")
            or row.get("Close")
            or row.get("close")
        )

        if not date_text or not close_text:
            continue

        try:
            day = _parse_date(date_text)
            close = float(close_text)
        except (TypeError, ValueError):
            continue

        if close >= 0:
            result[day] = close

    return result


def _load_official_vix():
    global _vix_cache

    if _vix_cache is not None:
        return _vix_cache

    result = {}

    request = urllib.request.Request(
        VIX_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "QPX-XLE-Candidate-V1"
            ),
            "Accept": "text/csv,*/*",
            "Connection": "close",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            raw = response.read().decode(
                "utf-8-sig"
            )

        result = _parse_vix_csv(raw)

    except Exception as exc:
        print(
            "WARNING: live CBOE VIX download failed:"
        )
        print(f"  {exc}")
        print("Trying local validated VIX cache...")

        if LOCAL_VIX_CACHE.exists():
            result = _parse_vix_csv(
                LOCAL_VIX_CACHE.read_text(
                    encoding="utf-8-sig"
                )
            )

    if not result:
        raise RuntimeError(
            "No official VIX daily-close data "
            "is available."
        )

    _vix_cache = result
    return result


def _previous_session_vix(signal_date):
    values = _load_official_vix()

    required_date = previous_market_session(
        signal_date
    )

    if required_date not in values:
        prior_dates = [
            day
            for day in values
            if day < signal_date
        ]

        latest_available = (
            max(prior_dates)
            if prior_dates
            else None
        )

        raise RuntimeError(
            "VIX_FRESHNESS_FAIL_CLOSED: "
            "required previous completed CBOE "
            f"session {required_date} for signal "
            f"date {signal_date}, but that exact "
            "VIX close is unavailable. "
            "Latest available prior VIX date: "
            f"{latest_available}. "
            "Candidate V1 will not enter a trade."
        )

    return (
        required_date,
        values[required_date],
    )



# ---------------------------------------------------------
# RELAXED ENTRY + VIX REGIME FILTER
# ---------------------------------------------------------

def _candidate_evaluate_entry(
    *,
    candles,
    indicators,
    index,
    vix,
    config,
):
    signal_date = candles[index].date

    vix_date, previous_vix = (
        _previous_session_vix(signal_date)
    )

    evaluation = RELAXED_EVALUATOR(
        candles=candles,
        indicators=indicators,
        index=index,
        vix=previous_vix,
        config=config,
    )

    excluded = (
        VIX_EXCLUDE_LOW
        < previous_vix
        < VIX_EXCLUDE_HIGH
    )

    if not excluded:
        return evaluation

    checks = dict(evaluation.checks)

    checks[
        "candidate_vix_20_25_exclusion"
    ] = False

    failed = tuple(
        dict.fromkeys(
            (
                *evaluation.failed_checks,
                "candidate_vix_20_25_exclusion",
            )
        )
    )

    return EntryEvaluation(
        index=evaluation.index,
        should_enter=False,
        checks=checks,
        triggers=evaluation.triggers,
        failed_checks=failed,
    )


paper.evaluate_entry = _candidate_evaluate_entry


# ---------------------------------------------------------
# FIXED 3% RISK / NO KELLY / 90% NOTIONAL GUARD
# ---------------------------------------------------------

_ORIGINAL_POSITION_SIZE = (
    paper.calculate_position_size
)


def _candidate_position_size(
    *,
    account_equity,
    available_cash,
    entry_price,
    atr,
    active_risk,
    config,
    trade_results_r=(),
):
    # Empty history deliberately keeps the engine
    # on the configured fixed 3% risk instead of
    # switching to Kelly after 20 trades.
    sizing = _ORIGINAL_POSITION_SIZE(
        account_equity=account_equity,
        available_cash=available_cash,
        entry_price=entry_price,
        atr=atr,
        active_risk=active_risk,
        config=config,
        trade_results_r=(
            trade_results_r
            if ACTIVE_SCENARIO.risk[
                "kelly_enabled"
            ]
            else ()
        ),
    )

    if not sizing.is_tradeable:
        return sizing

    raw_share_cap = math.floor(
        (
            account_equity
            * MAXIMUM_POSITION_NOTIONAL
        )
        / sizing.entry_fill
    )

    # Preserve the research one-share floor.
    share_cap = max(
        1,
        raw_share_cap,
    )

    capped_shares = min(
        sizing.shares,
        share_cap,
    )

    if capped_shares >= sizing.shares:
        return sizing

    return replace(
        sizing,
        shares=capped_shares,
        planned_risk=(
            capped_shares
            * sizing.risk_per_share
        ),
    )


paper.calculate_position_size = (
    _candidate_position_size
)


# ---------------------------------------------------------
# NET-REALIZED TAX RESERVE
# ---------------------------------------------------------

class CandidatePortfolio(BasePortfolio):

    def close_position(
        self,
        *,
        symbol,
        exit_price,
        exit_date,
        reason,
        config,
    ):
        trade = super().close_position(
            symbol=symbol,
            exit_price=exit_price,
            exit_date=exit_date,
            reason=reason,
            config=config,
        )

        target = (
            max(0.0, self.realized_pnl)
            * config.annual_tax_reserve_rate
        )

        current = self.tax_reserve_cash

        if target > current + 1e-8:
            raise RuntimeError(
                "Net-realized tax target exceeded "
                "gross reserve."
            )

        released = max(
            0.0,
            current - target,
        )

        self.tax_reserve_cash = target
        self.cash += released

        return trade


paper.Portfolio = CandidatePortfolio


def _install_scenario(
    filename,
):
    global ACTIVE_SCENARIO
    global VIX_EXCLUDE_LOW
    global VIX_EXCLUDE_HIGH
    global MAXIMUM_POSITION_NOTIONAL

    scenario = load_scenario(
        filename
    )

    validate_forward_scenario(
        scenario
    )

    ACTIVE_SCENARIO = scenario

    VIX_EXCLUDE_LOW = float(
        scenario.entry[
            "vix_exclusion_low"
        ]
    )

    VIX_EXCLUDE_HIGH = float(
        scenario.entry[
            "vix_exclusion_high"
        ]
    )

    MAXIMUM_POSITION_NOTIONAL = float(
        scenario.risk[
            "maximum_position_notional"
        ]
    )

    return scenario


# ---------------------------------------------------------
# SAFE SEPARATE PAPER DIRECTORIES
# ---------------------------------------------------------

def _add_default(args, flag, value):
    if flag in args:
        return args

    return [
        *args,
        flag,
        str(value),
    ]


def self_test():
    scenario = ACTIVE_SCENARIO
    symbols = forward_symbols(
        scenario
    )
    policy = _scenario_policy(
        CANDIDATE_POLICY
    )
    config = _candidate_config()

    assert policy.candidates == (
        symbols.candidate_symbols
    )

    assert (
        policy.tradable_symbols
        == symbols.tradable_symbols
    )

    assert (
        policy.income_symbol
        == symbols.income_symbol
    )

    assert (
        policy.volatility_symbol
        == symbols.volatility_symbol
    )

    assert (
        policy.maximum_concurrent_positions
        == scenario.risk[
            "maximum_positions"
        ]
    )

    assert abs(
        policy.maximum_gap_atr_multiple
        - float(
            scenario.entry[
                "maximum_gap_atr_multiple"
            ]
        )
    ) < 1e-12

    assert abs(
        config.risk_per_trade
        - float(
            scenario.risk[
                "risk_per_trade"
            ]
        )
    ) < 1e-12

    assert abs(
        config.maximum_active_portfolio_risk
        - float(
            scenario.risk[
                "maximum_active_portfolio_risk"
            ]
        )
    ) < 1e-12

    print("=" * 72)
    print(
        "QPX FORWARD SCENARIO SELF TEST PASSED"
    )
    print("=" * 72)
    print(
        f"Scenario             : "
        f"{scenario.name}"
    )
    print(
        f"Revision             : "
        f"{scenario.revision}"
    )
    print(
        f"Fingerprint          : "
        f"{scenario.fingerprint}"
    )
    print(
        "Candidate symbols    : "
        + ", ".join(
            symbols.candidate_symbols
        )
    )
    print(
        "Tradable symbols     : "
        + ", ".join(
            symbols.tradable_symbols
        )
    )
    print(
        f"Income symbol        : "
        f"{symbols.income_symbol}"
    )
    print(
        f"Volatility symbol    : "
        f"{symbols.volatility_symbol}"
    )
    print(
        f"Monthly contribution : "
        f"${config.monthly_contribution:,.2f}"
    )
    print(
        f"Rebalance cadence    : "
        f"{config.allocation_rebalance_frequency.upper()}"
    )
    print(
        f"Risk per trade       : "
        f"{config.risk_per_trade:.2%}"
    )
    print(
        f"Active risk ceiling  : "
        f"{config.maximum_active_portfolio_risk:.2%}"
    )
    print(
        f"Maximum positions    : "
        f"{policy.maximum_concurrent_positions}"
    )
    print(
        f"Notional guard       : "
        f"{MAXIMUM_POSITION_NOTIONAL:.2%}"
    )
    print(
        f"Gap ceiling          : "
        f"{policy.maximum_gap_atr_multiple:.2f} ATR"
    )
    print(
        f"Stop / target        : "
        f"{config.stop_atr_multiple:.2f} / "
        f"{config.target_atr_multiple:.2f} ATR"
    )
    print(
        f"Trailing activation  : "
        f"{config.trailing_activation_atr:.2f} ATR"
    )
    print(
        f"Kelly                : "
        + (
            "ENABLED"
            if scenario.risk[
                "kelly_enabled"
            ]
            else "DISABLED"
        )
    )
    print(
        f"VIX exclusion        : "
        f"{VIX_EXCLUDE_LOW:g} < VIX < "
        f"{VIX_EXCLUDE_HIGH:g}"
    )
    print(
        "Existing paper state: UNTOUCHED"
    )
    print(
        "Live broker         : DISABLED"
    )
    print("=" * 72)


def main():
    args = list(sys.argv[1:])

    scenario_path = (
        DEFAULT_FORWARD_SCENARIO
    )

    if "--scenario" in args:
        index = args.index(
            "--scenario"
        )

        if index + 1 >= len(args):
            raise ValueError(
                "--scenario requires a filename."
            )

        scenario_path = Path(
            args[index + 1]
        )

        del args[
            index:index + 2
        ]

    scenario = _install_scenario(
        scenario_path
    )

    if "--self-test" in args:
        self_test()
        return 0

    args = _add_default(
        args,
        "--policy",
        CANDIDATE_POLICY,
    )

    args = _add_default(
        args,
        "--runtime-dir",
        CANDIDATE_RUNTIME,
    )

    args = _add_default(
        args,
        "--legacy-runtime-dir",
        CANDIDATE_LEGACY_RUNTIME,
    )

    args = _add_default(
        args,
        "--report-dir",
        CANDIDATE_REPORTS,
    )

    print("=" * 78)
    print(
        "QPX CANDIDATE V1 — "
        "FORWARD PAPER VALIDATION"
    )
    print("=" * 78)
    print(
        "Symbols loaded from policy | "
        "87.5% swing | 12.5% income"
    )
    print(
        "3% risk | 10% active risk | "
        "Kelly OFF"
    )
    print(
        "VIX: previous session close; "
        "exclude 20-25"
    )
    print(
        "90% notional guard | "
        "2.0 ATR gap limit"
    )
    print("LIVE BROKER: DISABLED")
    print("=" * 78)

    print(
        f"Scenario              : "
        f"{scenario.name}"
    )
    print(
        f"Scenario revision     : "
        f"{scenario.revision}"
    )
    print(
        f"Scenario fingerprint  : "
        f"{scenario.fingerprint}"
    )

    return paper.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
