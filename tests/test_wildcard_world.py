from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from qpx_bot.causal_replay import CausalAccessError
from qpx_bot.wildcard.reward_policy import load_approved_policy
from qpx_bot.wildcard.world import (
    Action, ActionType, CausalBoundary, CausalGateway, InstrumentEvidence,
    MarketEvent, WildcardWorld, WorldError, WorldStatus,
)


UTC = timezone.utc


class Sink:
    def __init__(self) -> None:
        self.records = []

    def append(self, record) -> None:
        self.records.append(dict(record))


class WildcardWorldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sink = Sink()
        self.gateway = CausalGateway("development-fixture-v1")
        self.instrument = InstrumentEvidence("asset-a")
        self.world = WildcardWorld(
            world_id="toy-world", gateway=self.gateway,
            instruments={"asset-a": self.instrument}, archive_sink=self.sink,
            reward_policy=load_approved_policy(),
        )
        self.day = date(2026, 1, 5)
        self.start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)

    def bar(self, number: int, *, price="10", volume=1000, end=False,
            session=None, asset="asset-a") -> MarketEvent:
        when = self.start + timedelta(minutes=15 * number)
        return MarketEvent(
            f"bar-{number}-{asset}", CausalBoundary(when, when, number), "BAR",
            asset, session or self.day, Decimal(price), Decimal(price), volume, end,
            world_boundary_id=f"boundary-{number}",
        )

    def finish(self, number: int, *, minutes=15, world=None) -> None:
        target = world or self.world
        when = self.start + timedelta(minutes=15 * number)
        target.observe(MarketEvent(
            f"complete-{number}", CausalBoundary(when, when, number + 10_000),
            "BOUNDARY_COMPLETE", payload={"scheduled_market_minutes": minutes},
            world_boundary_id=f"boundary-{number}",
        ))

    def test_no_action_and_future_or_archive_access_are_unavailable(self) -> None:
        self.world.observe(self.bar(0))
        self.assertIsNone(self.world.act(Action(ActionType.NO_ACTION)))
        self.assertFalse(hasattr(self.gateway, "archive"))
        with self.assertRaises(CausalAccessError):
            self.world.observe(MarketEvent("past", CausalBoundary(self.start, self.start, 0), "NOTICE"))

    def test_buy_fills_next_event_with_slippage_and_participation_partial(self) -> None:
        self.world.observe(self.bar(0))
        oid = self.world.act(Action(ActionType.BUY, "asset-a", Decimal("20")))
        self.assertEqual(len(self.world.fills), 0)
        self.finish(0)
        self.world.observe(self.bar(1, price="11", volume=500))
        fill = self.world.fills[0]
        self.assertEqual(fill.order_id, oid)
        self.assertEqual(fill.quantity, Decimal("5.000"))
        self.assertEqual(fill.price, Decimal("11.00550000"))
        self.assertEqual(self.world.pending[oid].remaining, Decimal("15.00000000"))

    def test_insufficient_cash_never_goes_negative(self) -> None:
        self.world.observe(self.bar(0, price="100000"))
        self.world.act(Action(ActionType.BUY, "asset-a", Decimal("2")))
        self.finish(0)
        self.world.observe(self.bar(1, price="100000", volume=1000))
        self.assertGreaterEqual(self.world.cash, 0)
        self.assertEqual(self.world.positions["asset-a"], Decimal("0.999"))

    def test_sell_more_than_owned_rejects(self) -> None:
        self.world.observe(self.bar(0))
        with self.assertRaisesRegex(WorldError, "exceeds owned"):
            self.world.act(Action(ActionType.SELL, "asset-a", Decimal("1")))

    def test_cancel_and_replace_acknowledgement_gets_new_fifo(self) -> None:
        self.world.observe(self.bar(0))
        first = self.world.act(Action(ActionType.BUY, "asset-a", Decimal("2")))
        second = self.world.act(Action(ActionType.BUY, "asset-a", Decimal("2")))
        replaced = self.world.act(Action(ActionType.REPLACE, quantity=Decimal("3"), order_id=first))
        self.assertNotIn(first, self.world.pending)
        self.assertLess(self.world.pending[second].sequence, self.world.pending[replaced].sequence)
        self.world.act(Action(ActionType.CANCEL, order_id=second))
        self.assertNotIn(second, self.world.pending)

    def test_invalid_replace_is_atomic_and_keeps_old_order(self) -> None:
        self.world.observe(self.bar(0))
        first = self.world.act(Action(ActionType.BUY, "asset-a", Decimal("2")))
        with self.assertRaises(WorldError):
            self.world.act(Action(ActionType.REPLACE, quantity=Decimal("0.0001"), order_id=first))
        self.assertIn(first, self.world.pending)

    def test_day_order_expires_and_missing_successor_never_fills(self) -> None:
        self.world.observe(self.bar(0))
        oid = self.world.act(Action(ActionType.BUY, "asset-a", Decimal("2")))
        self.finish(0)
        self.world.observe(self.bar(1, asset="asset-b", end=True))
        self.assertEqual(self.world.fills, [])
        self.assertNotIn(oid, self.world.pending)

    def test_fractional_requires_exact_authoritative_evidence_but_whole_works(self) -> None:
        self.world.observe(self.bar(0))
        with self.assertRaisesRegex(WorldError, "not authoritatively proven"):
            self.world.act(Action(ActionType.BUY, "asset-a", Decimal("1.5")))
        self.assertIsNotNone(self.world.act(Action(ActionType.BUY, "asset-a", Decimal("1"))))
        evidence = InstrumentEvidence("asset-f", fractional_eligible=True,
                                      fractional_evidence_fingerprint="f" * 64)
        world = WildcardWorld(world_id="fractional", gateway=CausalGateway("source"),
                              instruments={"asset-f": evidence}, archive_sink=Sink())
        world.observe(self.bar(0, asset="asset-f"))
        self.assertIsNotNone(world.act(Action(ActionType.BUY, "asset-f", Decimal("1.5"),
                                             fractional_eligibility_fingerprint="f" * 64)))

    def test_stale_holding_blocks_reconciliation_and_never_adds_buying_power(self) -> None:
        self.world.observe(self.bar(0))
        self.world.act(Action(ActionType.BUY, "asset-a", Decimal("1")))
        self.finish(0)
        self.world.observe(self.bar(1))
        cash = self.world.buying_power()
        self.world.mark_stale("asset-a")
        self.assertEqual(self.world.buying_power(), cash)
        with self.assertRaises(WorldError):
            self.world.equity()

    def test_unsupported_corporate_action_blocks_without_inventing_economics(self) -> None:
        self.world.observe(self.bar(0))
        self.finish(0)
        when = self.start + timedelta(minutes=1)
        self.world.observe(MarketEvent("ca", CausalBoundary(when, when, 1),
                                       "CORPORATE_ACTION", payload={"economics_supported": False},
                                       world_boundary_id="ca-boundary"))
        self.assertEqual(self.world.status, WorldStatus.ACCOUNT_RECONCILIATION_BLOCKED)

    def test_accounting_bankruptcy_and_economic_dead_end_are_distinct(self) -> None:
        self.world.liabilities = Decimal("100000.01")
        self.world.observe(self.bar(0))
        self.finish(0)
        self.assertEqual(self.world.status, WorldStatus.FAILED_BANKRUPTCY)
        other = WildcardWorld(world_id="other", gateway=CausalGateway("source"),
                              instruments={"asset-a": self.instrument}, archive_sink=Sink())
        other.declare_economic_dead_end(permanent_no_transaction_path_proven=True)
        self.assertEqual(other.status, WorldStatus.ECONOMIC_DEAD_END)

    def test_checkpoint_restart_is_state_equivalent_and_preserves_sequence(self) -> None:
        self.world.observe(self.bar(0))
        self.world.act(Action(ActionType.BUY, "asset-a", Decimal("2")))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.world.checkpoint(directory)
            restored = WildcardWorld.restore(
                directory, world_id="toy-world", gateway=CausalGateway("development-fixture-v1"),
                instruments={"asset-a": self.instrument}, archive_sink=Sink(),
                reward_policy=load_approved_policy(),
            )
            self.assertEqual(restored.state_payload(), self.world.state_payload())
            self.finish(0, world=restored)
            self.finish(0)
            restored.observe(self.bar(1))
            self.world.observe(self.bar(1))
            self.assertEqual(restored.state_payload(), self.world.state_payload())

    def test_corrupt_checkpoint_fails_closed(self) -> None:
        self.world.observe(self.bar(0))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.world.checkpoint(directory)
            (directory / "world_state.json").write_bytes(b"{}")
            with self.assertRaises(RuntimeError):
                WildcardWorld.restore(directory, world_id="toy-world",
                    gateway=CausalGateway("development-fixture-v1"),
                    instruments={"asset-a": self.instrument}, archive_sink=Sink())

    def test_historical_to_forward_handoff_preserves_forward_boundary(self) -> None:
        self.world.observe(self.bar(0))
        self.finish(0)
        self.gateway.handoff("forward-paper-fixture-v1")
        self.world.observe(self.bar(1))
        self.assertEqual(self.gateway.source_identity, "forward-paper-fixture-v1")

    def test_authority_and_decimal_contract_are_in_world_identity(self) -> None:
        payload = self.world.state_payload()
        self.assertEqual(payload["authority"], {"promotion": "NONE", "live": "NONE",
                                                "broker": "NONE", "capital": "NONE"})
        self.assertEqual(len(self.world.world_fingerprint), 64)

    def test_churn_has_cost_and_reward_cannot_erase_bankruptcy(self) -> None:
        self.world.observe(self.bar(0))
        self.world.act(Action(ActionType.BUY, "asset-a", Decimal("10")))
        self.finish(0)
        self.world.observe(self.bar(1))
        self.world.act(Action(ActionType.SELL, "asset-a", Decimal("10")))
        self.finish(1)
        self.world.observe(self.bar(2))
        self.assertLess(self.world.equity(), Decimal("100000"))
        self.world.liabilities = Decimal("200000")
        self.finish(2)
        self.assertEqual(self.world.status, WorldStatus.FAILED_BANKRUPTCY)


if __name__ == "__main__":
    unittest.main()
