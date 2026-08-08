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


PROJECT_ROOT = Path(__file__).resolve().parent

CANDIDATE_POLICY = (
    PROJECT_ROOT
    / "qpx_bot"
    / "candidate_v1_policy.json"
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

VIX_EXCLUDE_LOW = 20.0
VIX_EXCLUDE_HIGH = 25.0
MAXIMUM_POSITION_NOTIONAL = 0.90

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
    config = _ORIGINAL_BOT_CONFIG(
        dividend_allocation_years_1_2=0.125,
        swing_allocation_years_1_2=0.875,
        dividend_allocation_later=0.125,
        swing_allocation_later=0.875,

        minimum_average_daily_volume=(
            research.RELAXED_MINIMUM_AVERAGE_15M_VOLUME
        ),
        breakout_volume_multiplier=(
            research.RELAXED_BREAKOUT_VOLUME_MULTIPLIER
        ),
        breakout_lookback=(
            research.RELAXED_BREAKOUT_LOOKBACK
        ),
        maximum_vix_for_entries=(
            research.RELAXED_MAXIMUM_VIX
        ),
        rsi_overbought=(
            research.RELAXED_RSI_OVERBOUGHT
        ),

        risk_per_trade=0.03,
        maximum_active_portfolio_risk=0.10,
    )

    config.validate()
    return config


paper.BotConfig = _candidate_config


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
        trade_results_r=(),
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
    policy = json.loads(
        CANDIDATE_POLICY.read_text(
            encoding="utf-8"
        )
    )

    config = _candidate_config()

    assert (
        policy["maximum_gap_atr_multiple"]
        == 2.0
    )
    assert (
        policy["live_broker_enabled"]
        is False
    )
    assert load_symbol_config().candidate_symbols
    assert load_symbol_config().tradable_symbols
    assert set(
        load_symbol_config().tradable_symbols
    ).issubset(load_symbol_config().candidate_symbols)
    assert load_symbol_config().income_symbol
    assert load_symbol_config().volatility_symbol

    assert abs(
        config.swing_allocation_years_1_2
        - 0.875
    ) < 1e-12

    assert abs(
        config.dividend_allocation_years_1_2
        - 0.125
    ) < 1e-12

    assert abs(
        config.risk_per_trade
        - 0.03
    ) < 1e-12

    assert abs(
        config.maximum_active_portfolio_risk
        - 0.10
    ) < 1e-12

    print("=" * 72)
    print("QPX CANDIDATE V1 — SELF TEST PASSED")
    print("=" * 72)
    print(
        "Mode                 : "
        "FORWARD PAPER ONLY"
    )
    print(
        "Candidate symbols    : "
        + ", ".join(load_symbol_config().candidate_symbols)
    )
    print(
        "Tradable symbols     : "
        + ", ".join(load_symbol_config().tradable_symbols)
    )
    print(
        "Income symbol        : "
        + load_symbol_config().income_symbol
    )
    print(
        "Volatility symbol    : "
        + load_symbol_config().volatility_symbol
    )
    print(
        "Income / swing target: "
        "12.5% / 87.5%"
    )
    print(
        "Risk                 : "
        "3% per trade / 10% active"
    )
    print(
        "Kelly                : DISABLED"
    )
    print(
        "Notional guard       : 90%"
    )
    print(
        "VIX source           : "
        "previous completed CBOE session"
    )
    print(
        "VIX excluded         : "
        "20 < VIX < 25"
    )
    print(
        "Gap ceiling          : 2.0 ATR"
    )
    print(
        "Relaxed evaluator    : "
        f"{RELAXED_EVALUATOR_NAME}"
    )
    print(
        "Existing paper state : UNTOUCHED"
    )
    print(
        "Live broker          : DISABLED"
    )
    print("=" * 72)


def main():
    args = list(sys.argv[1:])

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

    return paper.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
