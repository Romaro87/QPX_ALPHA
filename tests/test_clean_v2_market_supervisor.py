from __future__ import annotations

import signal
import threading
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from qpx_bot.clean_v2_market_supervisor import (
    TARGET_UNIT,
    SystemdUserController,
    reconcile,
    schedule_decision,
    session_window,
    status_payload,
    supervisor_sleep_seconds,
)
from qpx_bot.market_calendar import NEW_YORK, market_session
from qpx_bot.pr50_iex_forward_research_paper import _shutdown_signal_scope


ROOT = Path(__file__).resolve().parents[1]


class FakeController:
    def __init__(self, state: str):
        self.current = state
        self.started = 0
        self.stopped = 0

    def state(self) -> str:
        return self.current

    def start(self) -> None:
        self.started += 1
        self.current = "active"

    def stop(self) -> None:
        self.stopped += 1
        self.current = "inactive"


class CleanV2MarketSupervisorTests(unittest.TestCase):
    def test_normal_session_windows_follow_eastern_dst(self):
        winter = session_window(date(2026, 1, 15))
        summer = session_window(date(2026, 8, 31))

        self.assertEqual(winter.configured_start.hour, 9)
        self.assertEqual(winter.configured_start.minute, 25)
        self.assertEqual(winter.configured_stop.hour, 16)
        self.assertEqual(winter.configured_stop.minute, 5)
        self.assertEqual(
            winter.configured_start.astimezone(timezone.utc).hour,
            14,
        )
        self.assertEqual(
            summer.configured_start.astimezone(timezone.utc).hour,
            13,
        )

    def test_holidays_weekends_and_early_closes_use_calendar(self):
        early = market_session(date(2026, 11, 27))
        self.assertTrue(early.early_close)
        self.assertEqual((early.regular_close.hour, early.regular_close.minute), (13, 0))
        self.assertEqual(
            session_window(early.trading_date).configured_stop.time().replace(tzinfo=None),
            datetime(2026, 11, 27, 13, 5).time(),
        )
        self.assertTrue(market_session(date(2026, 12, 24)).early_close)
        self.assertTrue(market_session(date(2025, 7, 3)).early_close)

        holiday = schedule_decision(datetime(2026, 11, 26, 12, tzinfo=NEW_YORK))
        self.assertEqual(holiday.market_session_state, "NON_TRADING_DAY")
        self.assertEqual(holiday.window.session.trading_date, date(2026, 11, 27))
        weekend = schedule_decision(datetime(2026, 11, 28, 12, tzinfo=NEW_YORK))
        self.assertEqual(weekend.market_session_state, "NON_TRADING_DAY")
        self.assertEqual(weekend.window.session.trading_date, date(2026, 11, 30))

    def test_reboot_timing_reconciles_before_inside_and_after_window(self):
        before = schedule_decision(datetime(2026, 8, 31, 9, 20, tzinfo=NEW_YORK))
        self.assertFalse(before.desired_active)
        self.assertEqual(before.next_action_at.hour, 9)
        self.assertEqual(before.next_action_at.minute, 25)

        inside = schedule_decision(datetime(2026, 8, 31, 11, 15, tzinfo=NEW_YORK))
        controller = FakeController("inactive")
        state, action = reconcile(controller, inside)
        self.assertEqual((state, action), ("active", "STARTED_CLEAN_V2"))
        self.assertEqual(controller.started, 1)

        after = schedule_decision(datetime(2026, 8, 31, 16, 5, tzinfo=NEW_YORK))
        state, action = reconcile(controller, after)
        self.assertEqual((state, action), ("inactive", "STOPPED_CLEAN_V2"))
        self.assertEqual(controller.stopped, 1)

    def test_failed_runner_is_not_restart_looped_inside_window(self):
        inside = schedule_decision(datetime(2026, 8, 31, 11, 15, tzinfo=NEW_YORK))
        controller = FakeController("failed")
        state, action = reconcile(controller, inside)
        self.assertEqual(state, "failed")
        self.assertEqual(action, "FAIL_CLOSED_CLEAN_V2_FAILED")
        self.assertEqual(controller.started, 0)

    def test_status_and_sleep_are_compact_and_non_busy(self):
        decision = schedule_decision(datetime(2026, 8, 31, 9, 20, tzinfo=NEW_YORK))
        payload = status_payload(decision, "inactive")
        self.assertEqual(payload["regular_open"], "2026-08-31T09:30:00-04:00")
        self.assertEqual(payload["configured_start"], "2026-08-31T09:25:00-04:00")
        self.assertEqual(payload["configured_stop"], "2026-08-31T16:05:00-04:00")
        self.assertEqual(payload["next_scheduled_action"], "START_CLEAN_V2")
        self.assertEqual(supervisor_sleep_seconds(decision), 300.0)

        far = schedule_decision(datetime(2026, 8, 31, 7, 0, tzinfo=NEW_YORK))
        self.assertEqual(supervisor_sleep_seconds(far), 3600.0)

    def test_target_has_no_boot_owner_and_supervisor_is_enableable(self):
        target = (
            ROOT / "deploy/qpx-pr50-iex-forward-research-paper-clean-v2.service"
        ).read_text(encoding="utf-8")
        supervisor = (
            ROOT
            / "deploy/qpx-pr50-iex-forward-research-paper-clean-v2-supervisor.service"
        ).read_text(encoding="utf-8")
        self.assertNotIn("[Install]", target)
        self.assertIn("TimeoutStopSec=360", target)
        self.assertIn("[Install]", supervisor)
        self.assertIn("WantedBy=default.target", supervisor)
        self.assertEqual(SystemdUserController().unit, TARGET_UNIT)

    def test_systemd_termination_requests_orderly_runner_exit(self):
        requested = threading.Event()
        previous = signal.getsignal(signal.SIGTERM)
        with _shutdown_signal_scope(requested):
            handler = signal.getsignal(signal.SIGTERM)
            handler(signal.SIGTERM, None)
            self.assertTrue(requested.is_set())
        self.assertIs(signal.getsignal(signal.SIGTERM), previous)

    def test_naive_scheduler_time_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            schedule_decision(datetime(2026, 8, 31, 10, 0))


if __name__ == "__main__":
    unittest.main()
