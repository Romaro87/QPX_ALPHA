from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from qpx_bot.wildcard.development_driver import (
    BoundaryBatch, DevelopmentBoundaryDriver, SterileReporter,
)
from qpx_bot.wildcard.reward_policy import load_approved_policy
from qpx_bot.wildcard.world import (
    Action, ActionType, CausalBoundary, CausalGateway, InstrumentEvidence,
    MarketEvent, WildcardWorld, WorldError,
)


UTC = timezone.utc


class Sink:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(dict(record))


class DevelopmentBoundaryDriverTests(unittest.TestCase):
    def setUp(self):
        self.archive = Sink()
        self.reports = Sink()
        self.instrument = InstrumentEvidence("asset")
        self.world = WildcardWorld(
            world_id="driver-toy", gateway=CausalGateway("historical-fixture"),
            instruments={"asset": self.instrument}, archive_sink=self.archive,
            reward_policy=load_approved_policy(),
        )
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.driver = DevelopmentBoundaryDriver(
            world=self.world, checkpoint_directory=self.directory,
            reporter=SterileReporter(self.reports),
        )
        self.when = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)

    def tearDown(self):
        self.temporary.cleanup()

    def event(self, index, *, asset="asset", price="10"):
        return MarketEvent(
            f"event-{index}", CausalBoundary(self.when, self.when, index), "BAR",
            asset, self.when.date(), Decimal(price), Decimal(price), 1000,
        )

    def batch(self, count, *, identity="b0", minutes=15):
        events = tuple(self.event(index) for index in range(count))
        return BoundaryBatch(identity, self.when, self.when, minutes, events)

    def restore(self):
        world = WildcardWorld.restore(
            self.directory, world_id="driver-toy", gateway=CausalGateway("historical-fixture"),
            instruments={"asset": self.instrument}, archive_sink=Sink(),
            reward_policy=load_approved_policy(),
        )
        return DevelopmentBoundaryDriver(
            world=world, checkpoint_directory=self.directory,
            reporter=SterileReporter(Sink()),
        )

    def test_universe_size_never_multiplies_scheduled_time(self):
        for count in (1, 100, 1000):
            with self.subTest(count=count):
                world = WildcardWorld(world_id=f"w-{count}", gateway=CausalGateway("s"),
                    instruments={f"a-{i}": InstrumentEvidence(f"a-{i}") for i in range(count)},
                    archive_sink=Sink())
                events = tuple(MarketEvent(f"e-{i}", CausalBoundary(self.when, self.when, i),
                    "NOTICE", world_boundary_id="b") for i in range(count))
                driver = DevelopmentBoundaryDriver(world=world,
                    checkpoint_directory=self.directory / str(count))
                driver.deliver_boundary(BoundaryBatch("b", self.when, self.when, 15, events))
                self.assertEqual(world.scheduled_market_minutes, 15)

    def test_missing_security_observations_still_advance_calendar_time(self):
        self.driver.deliver_boundary(self.batch(0))
        self.assertEqual(self.world.scheduled_market_minutes, 15)

    def test_ordinary_events_emit_no_reward_and_completion_emits_at_most_one(self):
        event = self.event(0)
        self.world.observe(MarketEvent(event.event_id, event.boundary, event.event_type,
            event.provider_asset_id, event.session_date, event.open_price, event.close_price,
            event.volume, world_boundary_id="b0"))
        self.assertEqual(self.world.rewards, [])
        self.driver.deliver_boundary(self.batch(1))
        self.assertLessEqual(len(self.world.rewards), 1)

    def test_duplicate_and_out_of_order_completion_fail_closed(self):
        batch = self.batch(0)
        self.driver.deliver_boundary(batch)
        with self.assertRaisesRegex(WorldError, "already completed"):
            self.driver.deliver_boundary(batch)
        later_time = self.when.replace(minute=45)
        self.world.observe(MarketEvent("open-later", CausalBoundary(later_time, later_time, 0),
            "NOTICE", world_boundary_id="later"))
        wrong = MarketEvent("wrong-complete", CausalBoundary(later_time, later_time, 9999),
            "BOUNDARY_COMPLETE", payload={"scheduled_market_minutes": 15},
            world_boundary_id="wrong")
        with self.assertRaisesRegex(WorldError, "out of order"):
            self.world.observe(wrong)

    def test_restart_before_completion_finishes_once_without_replaying_event(self):
        event = self.event(0)
        self.world.observe(MarketEvent(event.event_id, event.boundary, event.event_type,
            event.provider_asset_id, event.session_date, event.open_price, event.close_price,
            event.volume, world_boundary_id="b0"))
        self.driver._persist()
        resumed = self.restore()
        resumed.deliver_boundary(self.batch(1))
        self.assertEqual(resumed.world.completed_boundary_count, 1)
        self.assertEqual(resumed.world.scheduled_market_minutes, 15)

    def test_restart_after_completion_rejects_duplicate_time_and_reward(self):
        batch = self.batch(0)
        self.driver.deliver_boundary(batch)
        resumed = self.restore()
        time_before = resumed.world.scheduled_market_minutes
        rewards_before = list(resumed.world.rewards)
        with self.assertRaises(WorldError):
            resumed.deliver_boundary(batch)
        self.assertEqual(resumed.world.scheduled_market_minutes, time_before)
        self.assertEqual(resumed.world.rewards, rewards_before)

    def test_authoritative_half_day_minutes_are_honored(self):
        self.driver.deliver_boundary(self.batch(0, minutes=210))
        self.assertEqual(self.world.scheduled_market_minutes, 210)

    def test_report_cadence_uses_scheduled_minutes_and_is_write_only(self):
        self.driver.deliver_boundary(self.batch(0, minutes=8189))
        self.assertEqual(self.reports.records, [])
        later = self.when.replace(minute=45)
        second = BoundaryBatch("b1", later, later, 1, ())
        self.driver.deliver_boundary(second)
        self.assertEqual(len(self.reports.records), 1)
        report = self.reports.records[0]
        self.assertEqual(report["scheduled_market_minutes"], 8190)
        self.assertEqual(report["development_state"], "DEVELOPMENT_ONLY")
        self.assertEqual(report["authority"], {"promotion": "NONE", "live": "NONE",
                                               "broker": "NONE", "capital": "NONE"})
        self.assertFalse(hasattr(self.world, "reports"))

    def test_integrity_state_reports_immediately_without_completing_boundary(self):
        event = MarketEvent(
            "unsupported-ca", CausalBoundary(self.when, self.when, 0),
            "CORPORATE_ACTION", payload={"economics_supported": False},
        )
        batch = BoundaryBatch("b0", self.when, self.when, 15, (event,))
        self.driver.deliver_boundary(batch)
        self.assertEqual(len(self.reports.records), 1)
        self.assertEqual(
            self.reports.records[0]["status"], "ACCOUNT_RECONCILIATION_BLOCKED"
        )
        self.assertEqual(self.world.completed_boundary_count, 0)
        self.assertEqual(self.world.scheduled_market_minutes, 0)

    def test_existing_next_event_fill_semantics_remain(self):
        self.world.observe(MarketEvent("bar0", CausalBoundary(self.when, self.when, 0),
            "BAR", "asset", self.when.date(), Decimal("10"), Decimal("10"), 1000,
            world_boundary_id="b0"))
        self.world.act(Action(ActionType.BUY, "asset", Decimal("20")))
        completion = MarketEvent("complete0", CausalBoundary(self.when, self.when, 1),
            "BOUNDARY_COMPLETE", payload={"scheduled_market_minutes": 15}, world_boundary_id="b0")
        self.world.observe(completion)
        later = self.when.replace(minute=45)
        self.world.observe(MarketEvent("bar1", CausalBoundary(later, later, 0),
            "BAR", "asset", later.date(), Decimal("11"), Decimal("11"), 500,
            world_boundary_id="b1"))
        self.assertEqual(self.world.fills[0].quantity, Decimal("5.000"))

    def test_forward_handoff_requires_completed_boundary(self):
        self.driver.deliver_boundary(self.batch(0))
        self.driver.handoff_to_forward("forward-fixture")
        self.assertEqual(self.world.gateway.source_identity, "forward-fixture")


if __name__ == "__main__":
    unittest.main()
