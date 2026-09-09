from __future__ import annotations

import copy
import json
import unittest
from datetime import date, timedelta, timezone
from unittest.mock import patch

import qpx_bot.historical_market_calendar as historical_calendar


OPEN_DATES = {
    date.fromisoformat(value)
    for value in (
        "2017-06-19",
        "2018-06-19",
        "2019-06-19",
        "2020-06-19",
        "2021-06-18",
        "2021-12-31",
    )
}
CLOSED_DATES = {
    date.fromisoformat(value)
    for value in (
        "2018-12-05",
        "2022-06-20",
        "2023-06-19",
        "2024-06-19",
        "2025-06-19",
        "2025-01-09",
        "2026-06-19",
    )
}

# Explicit dates transcribed from the primary ICE/NYSE annual schedules and the
# two exceptional-closure notices.  This fixture intentionally does not import
# or derive from qpx_bot.market_calendar.
SOURCE_VERIFIED_FULL_CLOSURES = {
    date.fromisoformat(value)
    for value in (
        "2016-11-24", "2016-12-26",
        "2017-01-02", "2017-01-16", "2017-02-20", "2017-04-14",
        "2017-05-29", "2017-07-04", "2017-09-04", "2017-11-23",
        "2017-12-25",
        "2018-01-01", "2018-01-15", "2018-02-19", "2018-03-30",
        "2018-05-28", "2018-07-04", "2018-09-03", "2018-11-22",
        "2018-12-05", "2018-12-25",
        "2019-01-01", "2019-01-21", "2019-02-18", "2019-04-19",
        "2019-05-27", "2019-07-04", "2019-09-02", "2019-11-28",
        "2019-12-25",
        "2020-01-01", "2020-01-20", "2020-02-17", "2020-04-10",
        "2020-05-25", "2020-07-03", "2020-09-07", "2020-11-26",
        "2020-12-25",
        "2021-01-01", "2021-01-18", "2021-02-15", "2021-04-02",
        "2021-05-31", "2021-07-05", "2021-09-06", "2021-11-25",
        "2021-12-24",
        "2022-01-17", "2022-02-21", "2022-04-15", "2022-05-30",
        "2022-06-20", "2022-07-04", "2022-09-05", "2022-11-24",
        "2022-12-26",
        "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07",
        "2023-05-29", "2023-06-19", "2023-07-04", "2023-09-04",
        "2023-11-23", "2023-12-25",
        "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29",
        "2024-05-27", "2024-06-19", "2024-07-04", "2024-09-02",
        "2024-11-28", "2024-12-25",
        "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17",
        "2025-04-18", "2025-05-26", "2025-06-19", "2025-07-04",
        "2025-09-01", "2025-11-27", "2025-12-25",
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
        "2026-05-25", "2026-06-19", "2026-07-03",
    )
}


class FrozenHistoricalMarketCalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calendar = historical_calendar.load_frozen_historical_calendar()

    def test_exact_session_population_and_source_verified_dates(self) -> None:
        sessions = self.calendar.sessions
        self.assertEqual(len(sessions), 2_513)
        self.assertEqual(sessions[0].trading_date, date(2016, 9, 6))
        self.assertEqual(sessions[-1].trading_date, date(2026, 9, 3))

        expected_dates: list[date] = []
        current = date(2016, 9, 6)
        while current <= date(2026, 9, 3):
            if current.weekday() < 5 and current not in SOURCE_VERIFIED_FULL_CLOSURES:
                expected_dates.append(current)
            current += timedelta(days=1)
        self.assertEqual(
            tuple(session.trading_date for session in sessions),
            tuple(expected_dates),
        )

    def test_audited_false_closures_are_open_and_false_opens_are_closed(self) -> None:
        for trading_date in OPEN_DATES:
            with self.subTest(open=trading_date):
                self.assertTrue(self.calendar.is_session(trading_date))
        for trading_date in CLOSED_DATES:
            with self.subTest(closed=trading_date):
                self.assertFalse(self.calendar.is_session(trading_date))

    def test_all_21_early_closes_end_at_1300_new_york(self) -> None:
        early = {
            session.trading_date: session
            for session in self.calendar.sessions
            if session.early_close
        }
        self.assertEqual(frozenset(early), historical_calendar.EXPECTED_EARLY_CLOSES)
        self.assertEqual(len(early), 21)
        for trading_date, session in early.items():
            with self.subTest(trading_date=trading_date):
                self.assertEqual(session.regular_close.hour, 13)
                self.assertEqual(session.regular_close.minute, 0)

    def test_normal_sessions_close_at_1600_new_york(self) -> None:
        for session in self.calendar.sessions:
            if not session.early_close:
                self.assertEqual(session.regular_close.hour, 16)
                self.assertEqual(session.regular_close.minute, 0)

    def test_local_and_utc_boundaries_agree_across_dst(self) -> None:
        expectations = {
            date(2024, 3, 8): (14, 30, 21),
            date(2024, 3, 11): (13, 30, 20),
            date(2024, 11, 1): (13, 30, 20),
            date(2024, 11, 4): (14, 30, 21),
        }
        for trading_date, (open_hour, open_minute, close_hour) in expectations.items():
            with self.subTest(trading_date=trading_date):
                session = self.calendar.session_on(trading_date)
                self.assertIsNotNone(session)
                assert session is not None
                self.assertEqual(session.regular_open.astimezone(timezone.utc), session.regular_open_utc)
                self.assertEqual(session.regular_close.astimezone(timezone.utc), session.regular_close_utc)
                self.assertEqual(
                    (session.regular_open_utc.hour, session.regular_open_utc.minute),
                    (open_hour, open_minute),
                )
                self.assertEqual(session.regular_close_utc.hour, close_hour)

    def test_duplicate_missing_and_out_of_order_sessions_fail_closed(self) -> None:
        cases = {}
        duplicate = self._envelope()
        duplicate["content"]["sessions"][1] = copy.deepcopy(
            duplicate["content"]["sessions"][0]
        )
        cases["duplicate"] = duplicate

        missing = self._envelope()
        missing["content"]["sessions"].pop(100)
        cases["missing"] = missing

        out_of_order = self._envelope()
        sessions = out_of_order["content"]["sessions"]
        sessions[100], sessions[101] = sessions[101], sessions[100]
        cases["out_of_order"] = out_of_order

        for name, envelope in cases.items():
            with self.subTest(case=name):
                encoded, fingerprint = self._resign(envelope)
                with patch.object(
                    historical_calendar,
                    "FROZEN_CALENDAR_CONTENT_FINGERPRINT",
                    fingerprint,
                ):
                    with self.assertRaises(
                        historical_calendar.HistoricalMarketCalendarError
                    ):
                        historical_calendar._load_manifest_bytes(encoded)

    def test_one_minute_boundary_mutation_changes_fingerprint(self) -> None:
        envelope = self._envelope()
        original = envelope["content_fingerprint"]
        envelope["content"]["sessions"][0]["regular_close_utc"] = (
            "2016-09-06T20:01:00Z"
        )
        changed = historical_calendar._content_fingerprint(envelope["content"])
        self.assertNotEqual(changed, original)

    def test_corrupt_fingerprint_fails_closed(self) -> None:
        envelope = self._envelope()
        envelope["content_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(
            historical_calendar.HistoricalMarketCalendarError,
            "fingerprint does not match",
        ):
            historical_calendar._load_manifest_bytes(
                historical_calendar._canonical_bytes(envelope)
            )

    def test_canonical_reload_is_deterministic(self) -> None:
        first = historical_calendar.load_frozen_historical_calendar()
        second = historical_calendar.load_frozen_historical_calendar()
        self.assertEqual(first, second)
        self.assertEqual(
            first.content_fingerprint,
            historical_calendar.FROZEN_CALENDAR_CONTENT_FINGERPRINT,
        )
        raw = historical_calendar.FROZEN_HISTORICAL_CALENDAR_PATH.read_bytes()
        self.assertFalse(raw.endswith(b"\n"))
        self.assertEqual(raw, historical_calendar._canonical_bytes(json.loads(raw)))

    def test_loader_performs_no_network_access(self) -> None:
        with patch("socket.create_connection", side_effect=AssertionError("network")):
            with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
                loaded = historical_calendar.load_frozen_historical_calendar()
        self.assertEqual(len(loaded.sessions), 2_513)

    @staticmethod
    def _envelope() -> dict[str, object]:
        return json.loads(
            historical_calendar.FROZEN_HISTORICAL_CALENDAR_PATH.read_text(
                encoding="utf-8"
            )
        )

    @staticmethod
    def _resign(envelope: dict[str, object]) -> tuple[bytes, str]:
        content = envelope["content"]
        assert isinstance(content, dict)
        fingerprint = historical_calendar._content_fingerprint(content)
        envelope["content_fingerprint"] = fingerprint
        return historical_calendar._canonical_bytes(envelope), fingerprint


if __name__ == "__main__":
    unittest.main()
