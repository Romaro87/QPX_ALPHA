"""Readiness checks for real QPX Bot historical data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.dividends import DividendEvent
from qpx_bot.real_data import VixPoint


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    passed: bool
    detail: str
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class RealDataValidation:
    ready: bool
    common_start: date | None
    common_end: date | None
    swing_bars: int
    income_bars: int
    vix_points: int
    dividend_events: int
    checks: tuple[ValidationCheck, ...]

    def format_text(self) -> str:
        lines = [
            "=" * 74,
            "QPX REAL-DATA READINESS REPORT",
            "=" * 74,
            f"Ready          : {'YES' if self.ready else 'NO'}",
            f"Common start   : {self.common_start or 'none'}",
            f"Common end     : {self.common_end or 'none'}",
            f"Swing bars     : {self.swing_bars}",
            f"Income bars    : {self.income_bars}",
            f"VIX points     : {self.vix_points}",
            f"Dividend events: {self.dividend_events}",
            "-" * 74,
        ]

        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(
                f"{status:<5} {check.name:<28} {check.detail}"
            )

        lines.append("=" * 74)
        return "\n".join(lines)

    def write_json(self, filename: str | Path) -> Path:
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["common_start"] = (
            self.common_start.isoformat()
            if self.common_start
            else None
        )
        payload["common_end"] = (
            self.common_end.isoformat()
            if self.common_end
            else None
        )
        path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        return path


def validate_real_data(
    *,
    swing_candles: Sequence[Candle],
    income_candles: Sequence[Candle],
    vix_points: Sequence[VixPoint],
    dividends: Sequence[DividendEvent],
    config: BotConfig,
) -> RealDataValidation:
    config.validate()
    checks: list[ValidationCheck] = []

    common_start: date | None = None
    common_end: date | None = None

    nonempty = (
        bool(swing_candles)
        and bool(income_candles)
        and bool(vix_points)
    )
    checks.append(
        ValidationCheck(
            name="required histories",
            passed=nonempty,
            detail=(
                "swing, income, and VIX histories are present"
                if nonempty
                else "one or more required histories are empty"
            ),
        )
    )

    if nonempty:
        common_start = max(
            swing_candles[0].date,
            income_candles[0].date,
            vix_points[0].date,
        )
        common_end = min(
            swing_candles[-1].date,
            income_candles[-1].date,
            vix_points[-1].date,
        )

    overlap_valid = (
        common_start is not None
        and common_end is not None
        and common_start <= common_end
    )
    checks.append(
        ValidationCheck(
            name="date overlap",
            passed=overlap_valid,
            detail=(
                f"{common_start} through {common_end}"
                if overlap_valid
                else "histories do not share a usable date range"
            ),
        )
    )

    required_bars = max(
        2,
        config.sma_trend_period
        + config.sma_slope_lookback
        + 2,
    )
    overlapping_swing_bars = (
        sum(
            1
            for candle in swing_candles
            if common_start <= candle.date <= common_end
        )
        if overlap_valid
        else 0
    )
    checks.append(
        ValidationCheck(
            name="strategy warm-up",
            passed=overlapping_swing_bars >= required_bars,
            detail=(
                f"{overlapping_swing_bars} overlapping swing bars; "
                f"{required_bars} required"
            ),
        )
    )

    vix_covers_start = (
        bool(vix_points)
        and bool(swing_candles)
        and vix_points[0].date <= swing_candles[0].date
    )
    checks.append(
        ValidationCheck(
            name="VIX start coverage",
            passed=vix_covers_start or overlap_valid,
            detail=(
                "VIX can be aligned after common-date trimming"
                if overlap_valid
                else "VIX starts too late"
            ),
        )
    )

    dividend_dates_valid = (
        not dividends
        or (
            bool(income_candles)
            and all(
                income_candles[0].date
                <= event.date
                <= income_candles[-1].date
                for event in dividends
            )
        )
    )
    checks.append(
        ValidationCheck(
            name="dividend date range",
            passed=dividend_dates_valid,
            detail=(
                "all dividend events fall inside income history"
                if dividend_dates_valid
                else "one or more dividends fall outside income history"
            ),
        )
    )

    positive_prices = all(
        candle.open > 0
        and candle.high > 0
        and candle.low > 0
        and candle.close > 0
        for candle in (*swing_candles, *income_candles)
    )
    checks.append(
        ValidationCheck(
            name="positive prices",
            passed=positive_prices,
            detail=(
                "all OHLC values are positive"
                if positive_prices
                else "non-positive OHLC value detected"
            ),
        )
    )

    no_duplicate_dates = (
        len({candle.date for candle in swing_candles})
        == len(swing_candles)
        and len({candle.date for candle in income_candles})
        == len(income_candles)
        and len({point.date for point in vix_points})
        == len(vix_points)
    )
    checks.append(
        ValidationCheck(
            name="unique daily dates",
            passed=no_duplicate_dates,
            detail=(
                "one bar per date"
                if no_duplicate_dates
                else "duplicate daily dates detected"
            ),
        )
    )

    ready = all(
        check.passed
        for check in checks
        if check.severity == "error"
    )

    return RealDataValidation(
        ready=ready,
        common_start=common_start,
        common_end=common_end,
        swing_bars=len(swing_candles),
        income_bars=len(income_candles),
        vix_points=len(vix_points),
        dividend_events=len(dividends),
        checks=tuple(checks),
    )
