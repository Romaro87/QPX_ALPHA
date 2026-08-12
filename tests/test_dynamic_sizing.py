from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path

from qpx_bot.accelerators.base import AcceleratorEntrySnapshot, DynamicSizingContext
from qpx_bot.accelerators.dynamic_sizing import (
    DynamicSizingV1,
    load_dynamic_sizing_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "qpx_bot/accelerators/configs/dynamic_sizing_v1.json"


def context(*, utilization: float = 0.0, **changes) -> DynamicSizingContext:
    maximum_risk = 100.0
    values = {
        "decision_timestamp": datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc),
        "symbol": "AMD",
        "risk_budget_requested_shares": 20,
        "base_requested_shares": 20,
        "entry_price": 10.0,
        "decision_time_total_equity": 1000.0,
        "available_swing_cash": 1000.0,
        "decision_time_active_portfolio_risk": utilization * maximum_risk,
        "maximum_active_portfolio_risk": maximum_risk,
        "risk_per_share": 1.0,
        "existing_open_position_count": 1,
        "maximum_open_positions": 6,
        "existing_portfolio_exposure": 0.20,
    }
    values.update(changes)
    return DynamicSizingContext(**values)


class DynamicSizingV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.enabled = DynamicSizingV1(load_dynamic_sizing_config(CONFIG, enabled=True))

    def test_disabled_is_unconditional_no_op(self) -> None:
        accelerator = DynamicSizingV1(load_dynamic_sizing_config(CONFIG, enabled=False))
        decision = accelerator.decide(context(
            base_requested_shares=7,
            available_swing_cash=1.0,
            existing_open_position_count=6,
        ))
        self.assertEqual(decision.final_requested_shares, 7)
        self.assertEqual(decision.sizing_multiplier, 1.0)
        self.assertEqual(decision.reason_codes, ("ACCELERATOR_DISABLED_NO_OP",))

    def test_pre_entry_risk_utilization_boundaries(self) -> None:
        cases = (
            (0.249999, 1.00),
            (0.25, 0.85),
            (0.499999, 0.85),
            (0.50, 0.70),
            (0.749999, 0.70),
            (0.75, 0.50),
        )
        for utilization, expected in cases:
            with self.subTest(utilization=utilization):
                decision = self.enabled.decide(context(utilization=utilization))
                self.assertEqual(decision.risk_utilization, utilization)
                self.assertEqual(decision.sizing_multiplier, expected)

    def test_never_increases_base_or_exceeds_notional_ceiling(self) -> None:
        decision = self.enabled.decide(context(
            base_requested_shares=100,
            risk_budget_requested_shares=130,
            entry_price=10.0,
        ))
        self.assertLessEqual(decision.final_requested_shares, 100)
        self.assertLessEqual(decision.final_requested_notional, 250.0)

    def test_never_exceeds_available_cash_or_remaining_active_risk(self) -> None:
        decision = self.enabled.decide(context(
            base_requested_shares=20,
            available_swing_cash=55.0,
            decision_time_active_portfolio_risk=96.0,
        ))
        self.assertLessEqual(decision.final_requested_notional, 55.0)
        self.assertLessEqual(
            decision.final_requested_shares,
            math.floor((100.0 - 96.0) / 1.0),
        )

    def test_sub_one_share_fails_closed(self) -> None:
        decision = self.enabled.decide(context(
            base_requested_shares=1,
            utilization=0.75,
        ))
        self.assertEqual(decision.final_requested_shares, 0)
        self.assertIn("BLOCKED_BELOW_ONE_SHARE", decision.reason_codes)

    def test_identical_inputs_are_deterministic(self) -> None:
        first = self.enabled.decide(context(utilization=0.5))
        second = self.enabled.decide(context(utilization=0.5))
        self.assertEqual(first, second)
        self.assertEqual(first.decision_id, second.decision_id)

    def test_context_accepts_only_declared_immutable_scalars(self) -> None:
        names = {item.name for item in fields(DynamicSizingContext)}
        self.assertFalse({"portal", "history", "bars", "rankings"} & names)
        with self.assertRaises(TypeError):
            DynamicSizingContext(**{
                **{item.name: getattr(context(), item.name) for item in fields(DynamicSizingContext)},
                "portal": object(),
            })
        with self.assertRaises(ValueError):
            context(decision_time_active_portfolio_risk=float("nan"))

    def test_invalid_configuration_fails_at_load(self) -> None:
        original = json.loads(CONFIG.read_text(encoding="utf-8"))
        invalid = (
            {**original, "accelerator_version": ""},
            {**original, "maximum_position_notional_fraction": 0.250001},
            {**original, "risk_tiers": [
                {"upper_bound": 0.50, "multiplier": 1.0},
                {"upper_bound": 0.25, "multiplier": 0.85},
                {"upper_bound": None, "multiplier": 0.50},
            ]},
            {**original, "risk_tiers": [
                {"upper_bound": 0.25, "multiplier": 1.01},
                {"upper_bound": None, "multiplier": 0.50},
            ]},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "config.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises((ValueError, KeyError, TypeError)):
                        load_dynamic_sizing_config(path)

    def test_configuration_change_changes_only_future_decisions(self) -> None:
        first = self.enabled.decide(context(utilization=0.5))
        changed_config = replace(
            self.enabled.config,
            configuration_version="future-revision",
        )
        second = DynamicSizingV1(changed_config).decide(context(utilization=0.5))
        self.assertEqual(first.final_requested_shares, second.final_requested_shares)
        self.assertNotEqual(first.configuration_version, second.configuration_version)
        self.assertNotEqual(first.decision_id, second.decision_id)
        self.assertEqual(first.configuration_version, "dynamic-sizing-risk-utilization-v1")


    def test_entry_snapshot_is_immutable_and_retains_entry_version(self) -> None:
        decision = self.enabled.decide(context(utilization=0.5))
        snapshot = AcceleratorEntrySnapshot(
            accelerator_name=decision.accelerator_name,
            accelerator_version=decision.accelerator_version,
            configuration_version=decision.configuration_version,
            sizing_decision_id=decision.decision_id,
            sizing_multiplier=decision.sizing_multiplier,
            base_requested_shares=decision.base_requested_shares,
            final_shares=decision.final_requested_shares,
        )
        future = replace(
            self.enabled.config, configuration_version="future-revision"
        )
        DynamicSizingV1(future).decide(context(utilization=0.5))
        self.assertEqual(
            snapshot.configuration_version, "dynamic-sizing-risk-utilization-v1"
        )
        self.assertEqual(snapshot.sizing_decision_id, decision.decision_id)
        with self.assertRaises((AttributeError, TypeError)):
            snapshot.configuration_version = "mutated"


if __name__ == "__main__":
    unittest.main(verbosity=2)
