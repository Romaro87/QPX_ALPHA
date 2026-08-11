"""Dependency-free qualification tests for QPX strict causal replay."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from qpx_bot.causal_replay import (
    CausalAccessError,
    CausalDataPortal,
    MarketClock,
    ReplayBar,
    ReplayPhase,
)
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import calculate_indicators


def _bar(moment: datetime, price: float) -> ReplayBar:
    return ReplayBar(
        start=moment,
        open=price,
        high=price + 1.0,
        low=price - 1.0,
        close=price + 0.25,
        volume=100_000,
    )


class StrictCausalReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        base = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
        self.times = tuple(base + timedelta(minutes=15 * i) for i in range(4))

    def test_future_bar_is_blocked(self) -> None:
        clock = MarketClock(self.times)
        portal = CausalDataPortal(
            clock=clock,
            histories={"AAA": [_bar(t, 100 + i) for i, t in enumerate(self.times)]},
        )
        with self.assertRaises(CausalAccessError):
            portal.bar_at("AAA", self.times[1])

    def test_open_only_exposes_open_not_full_current_bar(self) -> None:
        clock = MarketClock(self.times)
        portal = CausalDataPortal(
            clock=clock,
            histories={"AAA": [_bar(t, 100 + i) for i, t in enumerate(self.times)]},
        )
        snap = portal.current_open("AAA")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.time, self.times[0])
        with self.assertRaises(CausalAccessError):
            portal.completed_bar("AAA")
        self.assertEqual(portal.completed_history("AAA"), ())
        clock.advance_to_close()
        self.assertIsNotNone(portal.completed_bar("AAA"))
        self.assertEqual(len(portal.completed_history("AAA")), 1)

    def test_missing_symbol_bar_does_not_stop_market_clock(self) -> None:
        clock = MarketClock(self.times)
        portal = CausalDataPortal(
            clock=clock,
            histories={
                "AAA": [_bar(t, 100 + i) for i, t in enumerate(self.times)],
                "BBB": [_bar(self.times[0], 50), _bar(self.times[2], 52)],
            },
        )
        clock.advance_to_close()
        self.assertTrue(clock.advance_to_next_open())
        self.assertEqual(clock.time, self.times[1])
        self.assertIsNotNone(portal.current_open("AAA"))
        self.assertIsNone(portal.current_open("BBB"))

    def test_clock_requires_open_close_sequence(self) -> None:
        clock = MarketClock(self.times)
        self.assertEqual(clock.phase, ReplayPhase.OPEN)
        with self.assertRaises(RuntimeError):
            clock.advance_to_next_open()
        clock.advance_to_close()
        self.assertEqual(clock.phase, ReplayPhase.CLOSE)
        with self.assertRaises(RuntimeError):
            clock.advance_to_close()

    def test_indicator_prefix_matches_full_history_at_cutoff(self) -> None:
        config = BotConfig()
        candles = []
        for i in range(260):
            price = 100.0 + (i * 0.1) + ((i % 7) * 0.03)
            candles.append(
                Candle(
                    date=(self.times[0] + timedelta(days=i)).date(),
                    open=price,
                    high=price + 1.0,
                    low=price - 1.0,
                    close=price + 0.2,
                    volume=100_000 + i,
                )
            )
        cutoff = 230
        full = calculate_indicators(candles, config)
        prefix = calculate_indicators(candles[:cutoff], config)
        fields = (
            "ema_fast",
            "ema_slow",
            "rsi",
            "rmi",
            "atr",
            "sma_trend",
            "average_volume",
        )
        for name in fields:
            self.assertEqual(
                getattr(full, name)[cutoff - 1],
                getattr(prefix, name)[-1],
                msg=name,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
