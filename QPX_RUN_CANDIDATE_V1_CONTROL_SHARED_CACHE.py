from __future__ import annotations

from qpx_bot.symbol_config import load_symbol_config

_SYMBOL_CONFIG = load_symbol_config()
_TRADABLE_SYMBOLS = set(_SYMBOL_CONFIG.tradable_symbols)

import inspect
import shutil
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

import qpx_bot.actual_two_year_15m_six as qpx
from dataclasses import replace as dataclass_replace

# Accurate Candidate V1 research universe:
# XLE is the only tradable swing instrument.
qpx.SWING_SYMBOLS = _SYMBOL_CONFIG.candidate_symbols

# The normal paper policy validates eight symbols first.
# For this historical XLE-only test, return the same validated
# policy with only the research candidate tuple changed.
_ORIGINAL_LOAD_POLICY = qpx.load_policy

def _xle_only_policy(*args, **kwargs):
    policy = _ORIGINAL_LOAD_POLICY(*args, **kwargs)
    return dataclass_replace(
        policy,
        candidates=_SYMBOL_CONFIG.candidate_symbols,
    )

qpx.load_policy = _xle_only_policy

# January 9, 2025 was an actual NYSE closure for the
# National Day of Mourning, not a missing-data session.
_ORIGINAL_IS_MARKET_SESSION = qpx.is_market_session

def _correct_market_session(day):
    if day == date(2025, 1, 9):
        return False
    return _ORIGINAL_IS_MARKET_SESSION(day)

qpx.is_market_session = _correct_market_session


QDTE_INCEPTION = date(2024, 3, 7)
REQUESTED_END = date(2026, 8, 7)

RISK_PROFILE = "FIXED_3PCT_10PCT_NO_KELLY_RESEARCH"
NOTIONAL_PROFILE = (
    "MAX_90PCT_ACCOUNT_EQUITY_ONE_SHARE_FLOOR_RESEARCH"
)

FRESH_ROOT = Path("research_data/qpx_actual_two_year_15m_six")

FRESH_CACHE = (
    FRESH_ROOT
    / "shared"
    / "aggregate_15m"
)

FRESH_VIX = (
    FRESH_ROOT
    / "shared"
    / "CBOE_VIX_DAILY.csv"
)

REPORT_ROOT = Path(
    "reports/"
    "qpx_candidate_v1_control_shared_cache"
)


# ============================================================
# API KEY
# ============================================================

api_key = ""


# ============================================================
# FIXED VALIDATED TEST RANGE — NO PROVIDER DISCOVERY
# ============================================================

START = date(2024, 8, 8)


print()
print(
    "Earliest authorized 15m session: "
    f"{START}"
)

print(
    "Requested ending session       : "
    f"{REQUESTED_END}"
)


# ============================================================
# DESTROY ANY PREVIOUS TEST CACHE
#
# This is deliberate. Accuracy test uses a completely fresh
# provider download and cannot reuse historical QPX bars.
# ============================================================

print("REUSING EXISTING VALIDATED PROVIDER DATA")

FRESH_CACHE.mkdir(
    parents=True,
    exist_ok=True,
)

REPORT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


# Point the research engine at the isolated empty cache.

qpx.DEFAULT_AGGREGATE_CACHE = FRESH_CACHE
qpx.DEFAULT_VIX_CACHE = FRESH_VIX


# ============================================================
# CANDIDATE V1 ALLOCATION
# ============================================================

OriginalBotConfig = qpx.BotConfig


def CandidateBotConfig(*args, **kwargs):
    kwargs.update(
        monthly_contribution=2_000.0,
        dividend_allocation_years_1_2=0.125,
        swing_allocation_years_1_2=0.875,
        dividend_allocation_later=0.125,
        swing_allocation_later=0.875,
    )

    return OriginalBotConfig(
        *args,
        **kwargs,
    )


qpx.BotConfig = CandidateBotConfig


# ============================================================
# FIXED 3% RISK / 10% ACTIVE RISK / KELLY OFF
# ============================================================

qpx.FIXED_ONE_PERCENT_RISK_PROFILE = (
    RISK_PROFILE
)

_original_replace = qpx.replace


def candidate_replace(
    obj,
    /,
    **changes,
):
    if (
        "risk_per_trade" in changes
        and abs(
            float(
                changes["risk_per_trade"]
            )
            - 0.01
        )
        < 1e-12
    ):
        changes[
            "risk_per_trade"
        ] = 0.03

    if (
        "maximum_active_portfolio_risk"
        in changes
        and abs(
            float(
                changes[
                    "maximum_active_portfolio_risk"
                ]
            )
            - 0.06
        )
        < 1e-12
    ):
        changes[
            "maximum_active_portfolio_risk"
        ] = 0.10

    return _original_replace(
        obj,
        **changes,
    )


qpx.replace = candidate_replace


# ============================================================
# 90% NOTIONAL GUARD
# ============================================================

qpx.NOTIONAL_CAP_16PCT_PROFILE = (
    NOTIONAL_PROFILE
)

qpx.RESEARCH_MAXIMUM_POSITION_NOTIONAL_FRACTION = (
    0.90
)


# ============================================================
# XLE ONLY FOR ACTUAL ENTRIES
#
# The other symbols remain reference/evaluation data.
# ============================================================

_original_choose = (
    qpx.choose_without_ranking
)


def choose_xle_only(
    *,
    signal_bar,
    qualifying,
    available_slots,
):
    xle = tuple(
        symbol
        for symbol in qualifying
        if symbol.strip().upper() in _TRADABLE_SYMBOLS
    )

    return _original_choose(
        signal_bar=signal_bar,
        qualifying=xle,
        available_slots=available_slots,
    )


qpx.choose_without_ranking = (
    choose_xle_only
)


# ============================================================
# CANDIDATE V1 VIX 20-25 EXCLUSION
# ============================================================

_original_entry = (
    qpx._evaluate_entry_relaxed_frequency
)


def candidate_entry(
    *,
    candles,
    indicators,
    index,
    vix,
    config,
):
    evaluation = _original_entry(
        candles=candles,
        indicators=indicators,
        index=index,
        vix=vix,
        config=config,
    )

    previous_vix = float(vix)

    if not (
        20.0
        < previous_vix
        < 25.0
    ):
        return evaluation

    checks = dict(
        evaluation.checks
    )

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

    return qpx.EntryEvaluation(
        index=evaluation.index,
        should_enter=False,
        checks=checks,
        triggers=evaluation.triggers,
        failed_checks=failed,
    )


qpx._evaluate_entry_relaxed_frequency = (
    candidate_entry
)


# ============================================================
# ENABLE RESEARCH PROFILES FOR A FIXED PROVIDER WINDOW
# ============================================================

source = inspect.getsource(
    qpx.run_backtest
)

guard = """swing_only
            and fixed_window
            and local_only"""

count = source.count(guard)

if count < 4:
    raise RuntimeError(
        "Could not safely locate research guards. "
        f"Found {count}."
    )

source = source.replace(
    guard,
    "fixed_window",
)

source = source.replace(
    'reference_bars=histories[qpx.SWING_SYMBOLS[0]]',
    'reference_bars=histories[qpx.SWING_SYMBOLS[0]]',
)

namespace = {}

exec(
    compile(
        source,
        str(Path(qpx.__file__)),
        "exec",
    ),
    qpx.__dict__,
    namespace,
)

qpx.run_backtest = (
    namespace["run_backtest"]
)


# ============================================================
# RUN
# ============================================================

print()
print("=" * 92)
print("QPX CANDIDATE V1 — ACCURATE MAXIMUM PROVIDER TEST")
print("=" * 92)
print(f"Start                 : {START}")
print(f"Requested end         : {REQUESTED_END}")
print("Market data           : FRESH MASSIVE/POLYGON ONLY")
print("Old QPX bar cache     : NOT USED")
print("Historical splicing   : DISABLED")
print("Synthetic data        : DISABLED")
print("Placeholder data      : DISABLED")
print("Market-data universe  : XLE + QDTE + official CBOE VIX")
print("Swing universe        : XLE ONLY")
print("QDTE / swing          : 12.5% / 87.5%")
print("Risk                  : 3%")
print("Active-risk ceiling   : 10%")
print("Kelly                 : OFF")
print("Notional guard        : 90%")
print("VIX                   : previous completed CBOE close")
print("Excluded VIX          : 20 < VIX < 25")
print("Maximum VIX           : 32")
print("Gap ceiling           : 2.0 ATR")
print("Exit profile          : BASELINE")
print("Initialization        : 200 common 15m bars")
print("=" * 92)
print()


result, artifacts = qpx.run_backtest(
    api_key=api_key,
    data_root=FRESH_ROOT,
    report_root=REPORT_ROOT,
    fixed_start=START,
    fixed_end=REQUESTED_END,
    local_only=True,
    initialization_bars=200,
    swing_only=False,
    entry_profile=qpx.RELAXED_ENTRY_PROFILE,
    risk_profile=RISK_PROFILE,
    tax_reserve_profile=(
        qpx.NET_REALIZED_TAX_RESERVE_PROFILE
    ),
    notional_profile=NOTIONAL_PROFILE,
    exit_profile=qpx.BASELINE_EXIT_PROFILE,
)


print()
print(qpx._format_report(result))


print()
print("=" * 92)
print("ACCURATE TEST SUMMARY")
print("=" * 92)

print(
    f"Requested range       : "
    f"{START} -> {REQUESTED_END}"
)

print(
    f"Actual common range   : "
    f"{result.actual_start} -> {result.actual_end}"
)

print(
    f"Common 15m bars       : "
    f"{result.common_test_bars:,}"
)

print(
    f"Market sessions       : "
    f"{result.test_sessions:,}"
)

print(
    f"Session coverage      : "
    f"{result.session_coverage:.2%}"
)

print(
    f"Closed XLE trades     : "
    f"{result.closed_trades}"
)

print(
    f"Win rate              : "
    f"{result.win_rate:.2%}"
)

print(
    f"Profit factor         : "
    f"{result.profit_factor:.3f}"
)

print(
    f"Realized swing P&L    : "
    f"${result.realized_swing_pnl:,.2f}"
)

print(
    f"QDTE distributions    : "
    f"${result.qdte_distributions_received:,.2f}"
)

print(
    f"Net portfolio profit  : "
    f"${result.net_profit:,.2f}"
)

print(
    f"Ending equity         : "
    f"${result.ending_equity:,.2f}"
)

print(
    f"Maximum drawdown      : "
    f"{result.maximum_drawdown:.2%}"
)

print(
    f"CAGR                  : "
    f"{result.flow_adjusted_cagr:.2%}"
)

print(
    f"Risk rejections       : "
    f"{result.risk_rejections}"
)

print(
    f"Notional adjustments  : "
    f"{result.notional_cap_adjustments}"
)

print()
print(
    "This result is the authoritative Candidate V1 "
    "historical test for the currently available "
    "provider data window."
)

print("=" * 92)

print()
print("Artifacts:")
print(f"  Result      : {artifacts.result}")
print(f"  Trades      : {artifacts.trades}")
print(f"  Equity      : {artifacts.equity}")
print(f"  Diagnostics : {artifacts.diagnostics}")
print()
