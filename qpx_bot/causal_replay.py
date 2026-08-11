"""Strict causal historical-replay primitives for QPX_ALPHA.

The replay clock is independent of per-symbol bar availability.
At OPEN, only the current bar's open price may be exposed.
At CLOSE, the completed current bar may be exposed.
Future full-bar access is blocked by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping, Sequence


class CausalAccessError(RuntimeError):
    """Raised when replay code attempts to access unavailable future data."""


class ReplayPhase(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


@dataclass(frozen=True, slots=True)
class ReplayBar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError("Replay bars must use timezone-aware timestamps.")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("Replay OHLC prices must be positive.")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("Replay high is inconsistent with OHLC values.")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Replay low is inconsistent with OHLC values.")
        if self.volume < 0:
            raise ValueError("Replay volume cannot be negative.")


@dataclass(frozen=True, slots=True)
class OpenSnapshot:
    symbol: str
    time: datetime
    open: float


class MarketClock:
    """Explicit market timeline that does not depend on symbol intersections."""

    def __init__(self, times: Sequence[datetime]) -> None:
        ordered = tuple(times)
        if not ordered:
            raise ValueError("Market clock requires at least one timestamp.")
        if any(value.tzinfo is None for value in ordered):
            raise ValueError("Market clock timestamps must be timezone-aware.")
        if tuple(sorted(set(ordered))) != ordered:
            raise ValueError(
                "Market clock timestamps must be unique and strictly increasing."
            )
        self._times = ordered
        self._index = 0
        self._phase = ReplayPhase.OPEN

    @property
    def time(self) -> datetime:
        return self._times[self._index]

    @property
    def phase(self) -> ReplayPhase:
        return self._phase

    @property
    def index(self) -> int:
        return self._index

    @property
    def is_last(self) -> bool:
        return self._index == len(self._times) - 1

    @property
    def times(self) -> tuple[datetime, ...]:
        return self._times

    def advance_to_close(self) -> None:
        if self._phase is not ReplayPhase.OPEN:
            raise RuntimeError("Clock is already at CLOSE.")
        self._phase = ReplayPhase.CLOSE

    def advance_to_next_open(self) -> bool:
        if self._phase is not ReplayPhase.CLOSE:
            raise RuntimeError("Clock must close the current bar before advancing.")
        if self.is_last:
            return False
        self._index += 1
        self._phase = ReplayPhase.OPEN
        return True


class CausalDataPortal:
    """Read-only causal view over complete historical source data."""

    def __init__(
        self,
        *,
        clock: MarketClock,
        histories: Mapping[str, Sequence[ReplayBar]],
    ) -> None:
        self._clock = clock
        self._maps: dict[str, dict[datetime, ReplayBar]] = {}

        for raw_symbol, bars in histories.items():
            symbol = raw_symbol.strip().upper()
            if not symbol:
                raise ValueError("Symbol cannot be empty.")
            mapping: dict[datetime, ReplayBar] = {}
            previous: datetime | None = None

            for bar in bars:
                if previous is not None and bar.start <= previous:
                    raise ValueError(
                        f"{symbol} history must be strictly increasing."
                    )
                if bar.start in mapping:
                    raise ValueError(f"Duplicate {symbol} bar: {bar.start}.")
                mapping[bar.start] = bar
                previous = bar.start

            self._maps[symbol] = mapping

    @property
    def market_time(self) -> datetime:
        return self._clock.time

    @property
    def phase(self) -> ReplayPhase:
        return self._clock.phase

    def current_open(self, symbol: str) -> OpenSnapshot | None:
        key = symbol.strip().upper()
        bar = self._maps.get(key, {}).get(self.market_time)
        if bar is None:
            return None
        return OpenSnapshot(symbol=key, time=self.market_time, open=bar.open)

    def completed_bar(self, symbol: str) -> ReplayBar | None:
        if self.phase is not ReplayPhase.CLOSE:
            raise CausalAccessError(
                "Current bar is not complete; OHLCV is unavailable at OPEN."
            )
        return self._maps.get(symbol.strip().upper(), {}).get(self.market_time)

    def completed_history(self, symbol: str) -> tuple[ReplayBar, ...]:
        key = symbol.strip().upper()
        mapping = self._maps.get(key, {})
        if self.phase is ReplayPhase.OPEN:
            cutoff = lambda ts: ts < self.market_time
        else:
            cutoff = lambda ts: ts <= self.market_time
        return tuple(
            bar for ts, bar in mapping.items()
            if cutoff(ts)
        )

    def bar_at(self, symbol: str, timestamp: datetime) -> ReplayBar | None:
        if timestamp > self.market_time:
            raise CausalAccessError(
                f"Future bar access blocked: {timestamp.isoformat()} > "
                f"{self.market_time.isoformat()}."
            )
        if timestamp == self.market_time and self.phase is ReplayPhase.OPEN:
            raise CausalAccessError(
                "Current bar OHLCV is unavailable before CLOSE."
            )
        return self._maps.get(symbol.strip().upper(), {}).get(timestamp)

    def assert_no_future_access(self, timestamp: datetime) -> None:
        if timestamp > self.market_time:
            raise CausalAccessError("Future timestamp is not causally available.")
