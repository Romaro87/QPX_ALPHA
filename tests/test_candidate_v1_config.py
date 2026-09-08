from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
import qpx_bot.fixed25_forward_paper as fixed25
import qpx_bot.pr50_iex_forward_research_paper as clean_v2
from qpx_bot.candidate_v1_config import (
    CandidateV1ConfigError,
    candidate_v1_config_from_snapshot,
    load_candidate_v1_config,
)
from qpx_bot.config import BotConfig


class _Store:
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self.events: list[tuple[str, dict]] = []

    def save(self, state) -> None:
        self.saved.append(json.loads(json.dumps(state)))

    def event(self, event_type, details) -> bool:
        self.events.append((event_type, dict(details)))
        return True


class CandidateV1ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.default = load_candidate_v1_config()
        self.payload = self.default.as_dict()

    def _write(self, payload, *, raw: str | None = None) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "candidate.json"
        path.write_text(
            raw if raw is not None else json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        return path

    def test_default_v1_exact_current_governed_values(self):
        config = self.default.bot_config
        self.assertEqual(config.breakout_lookback, 10)
        self.assertEqual(config.minimum_average_daily_volume, 75_000)
        self.assertEqual(config.breakout_volume_multiplier, 1.05)
        self.assertEqual(config.maximum_vix_for_entries, 32.0)
        self.assertEqual(config.rsi_overbought, 75.0)
        self.assertEqual(config.allocation_rebalance_frequency, "weekly")
        self.assertEqual(config.monthly_contribution, 0.0)
        self.assertEqual(self.default.maximum_position_notional_fraction, 0.25)
        self.assertEqual(self.default.maximum_gap_atr_multiple, 2.0)
        self.assertEqual(self.default.forward_starting_capital, 1470.0)
        self.assertFalse(self.default.kelly_enabled)

    def test_default_bot_config_matches_pre_repair_effective_semantics(self):
        pre_repair = replace(
            BotConfig(),
            starting_cash=1300.0,
            starting_swing_cash=0.0,
            monthly_contribution=0.0,
            dividend_allocation_years_1_2=0.125,
            swing_allocation_years_1_2=0.875,
            dividend_allocation_later=0.125,
            swing_allocation_later=0.875,
            allocation_rebalance_frequency="weekly",
            maximum_swing_positions=6,
            minimum_average_daily_volume=75_000,
            breakout_volume_multiplier=1.05,
            breakout_lookback=10,
            maximum_vix_for_entries=32.0,
            rsi_overbought=75.0,
            risk_per_trade=0.03,
            maximum_active_portfolio_risk=0.10,
            stop_atr_multiple=2.5,
            target_atr_multiple=5.0,
            trailing_activation_atr=3.0,
            slippage_rate=0.00075,
            annual_tax_reserve_rate=0.37,
            allocation_rebalance_tolerance=0.0025,
            minimum_rebalance_trade=1.0,
        )
        self.assertEqual(self.default.bot_config, pre_repair)
        self.assertEqual(self.default.forward_starting_capital, 1470.0)
        self.assertEqual(self.default.maximum_gap_atr_multiple, 2.0)
        self.assertEqual(self.default.maximum_position_notional_fraction, 0.25)

    def test_every_bot_config_field_is_explicit_not_defaulted(self):
        loaded = self.default.bot_config
        self.assertEqual(
            {item.name for item in fields(BotConfig)},
            set(loaded.__dataclass_fields__),
        )
        payload = self.default.as_dict()
        del payload["indicators"]["ema_fast_period"]
        with self.assertRaisesRegex(CandidateV1ConfigError, "missing"):
            load_candidate_v1_config(self._write(payload))

    def test_breakout_change_requires_no_source_edit_and_changes_fingerprint(self):
        changed = self.default.as_dict()
        changed["entry"]["breakout_lookback"] = 11
        loaded = load_candidate_v1_config(self._write(changed))
        self.assertEqual(loaded.bot_config.breakout_lookback, 11)
        self.assertNotEqual(loaded.fingerprint, self.default.fingerprint)

    def test_fingerprint_ignores_harmless_json_format_and_key_order(self):
        reversed_payload = dict(reversed(list(self.default.as_dict().items())))
        reversed_payload["exit"]["target_atr_multiple"] = 5.0
        path = self._write(
            reversed_payload,
            raw=json.dumps(reversed_payload, separators=(",", ":")),
        )
        self.assertEqual(
            load_candidate_v1_config(path).fingerprint,
            self.default.fingerprint,
        )
        self.assertEqual(load_candidate_v1_config().fingerprint, self.default.fingerprint)

    def test_duplicate_unknown_missing_and_invalid_values_fail_closed(self):
        duplicate = self.default.canonical_json.replace(
            '"schema_version":1', '"schema_version":1,"schema_version":1', 1
        )
        with self.assertRaisesRegex(CandidateV1ConfigError, "Duplicate"):
            load_candidate_v1_config(self._write({}, raw=duplicate))

        unknown = self.default.as_dict()
        unknown["python_default_override"] = True
        with self.assertRaisesRegex(CandidateV1ConfigError, "unknown"):
            load_candidate_v1_config(self._write(unknown))

        malformed = self.default.as_dict()
        malformed["entry"]["breakout_lookback"] = True
        with self.assertRaisesRegex(CandidateV1ConfigError, "JSON integer"):
            load_candidate_v1_config(self._write(malformed))

        invalid = self.default.as_dict()
        invalid["risk"]["maximum_position_notional_fraction"] = 1.1
        with self.assertRaisesRegex(CandidateV1ConfigError, "governed range"):
            load_candidate_v1_config(self._write(invalid))

    def test_snapshot_and_bot_config_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.default.fingerprint = "x" * 64
        with self.assertRaises(FrozenInstanceError):
            self.default.bot_config.breakout_lookback = 99
        detached = self.default.as_dict()
        detached["entry"]["breakout_lookback"] = 99
        self.assertEqual(self.default.bot_config.breakout_lookback, 10)

    def test_historical_fixed25_and_clean_share_one_loader(self):
        self.assertEqual(strict.candidate_config(), self.default.bot_config)
        self.assertEqual(
            fixed25.load_candidate_v1_config().fingerprint,
            clean_v2.sip.load_candidate_v1_config().fingerprint,
        )

    def test_reload_is_boundary_atomic_and_records_transition(self):
        state = {
            "candidate_v1_config_snapshot": self.default.as_dict(),
            "candidate_v1_config_fingerprint": self.default.fingerprint,
            "candidate_v1_config_effective_boundary": None,
        }
        store = _Store()
        ny = ZoneInfo("America/New_York")
        first = datetime(2026, 9, 9, 10, 0, tzinfo=ny)
        changed = self.default.as_dict()
        changed["entry"]["breakout_lookback"] = 11
        path = self._write(changed)

        original = fixed25.bind_candidate_v1_config_at_boundary(
            state, store, first
        )
        self.assertEqual(original.fingerprint, self.default.fingerprint)
        still_original = fixed25.bind_candidate_v1_config_at_boundary(
            state, store, first, config_path=path
        )
        self.assertEqual(still_original.fingerprint, self.default.fingerprint)

        replacement = fixed25.bind_candidate_v1_config_at_boundary(
            state, store, first + timedelta(minutes=15), config_path=path
        )
        self.assertEqual(replacement.bot_config.breakout_lookback, 11)
        self.assertEqual(len(store.events), 1)
        details = store.events[0][1]
        self.assertEqual(details["old_fingerprint"], self.default.fingerprint)
        self.assertEqual(details["new_fingerprint"], replacement.fingerprint)
        self.assertEqual(
            details["effective_boundary"],
            (first + timedelta(minutes=15)).isoformat(),
        )

    def test_invalid_next_boundary_reload_fails_without_rebinding(self):
        state = {
            "candidate_v1_config_snapshot": self.default.as_dict(),
            "candidate_v1_config_fingerprint": self.default.fingerprint,
            "candidate_v1_config_effective_boundary": None,
        }
        store = _Store()
        invalid = self.default.as_dict()
        del invalid["entry"]["breakout_lookback"]
        with self.assertRaises(CandidateV1ConfigError):
            fixed25.bind_candidate_v1_config_at_boundary(
                state,
                store,
                datetime(2026, 9, 9, 10, 0, tzinfo=ZoneInfo("America/New_York")),
                config_path=self._write(invalid),
            )
        self.assertEqual(state["candidate_v1_config_fingerprint"], self.default.fingerprint)
        self.assertEqual(store.saved, [])

    def test_entry_snapshot_remains_stable_after_repository_change(self):
        old_payload = self.default.as_dict()
        changed = self.default.as_dict()
        changed["exit"]["stop_atr_multiple"] = 3.0
        replacement = load_candidate_v1_config(self._write(changed))
        restored = candidate_v1_config_from_snapshot(
            old_payload, self.default.fingerprint
        )
        self.assertNotEqual(replacement.fingerprint, restored.fingerprint)
        self.assertEqual(restored.bot_config.stop_atr_multiple, 2.5)
        position = fixed25.Position(
            symbol="TEST", shares=1, entry_date=datetime(2026, 9, 9).date(),
            entry_price=100.0, entry_atr=2.0, stop_price=95.0,
            target_price=110.0, highest_price=100.0,
            entry_stop_atr_multiple=restored.bot_config.stop_atr_multiple,
            entry_target_atr_multiple=restored.bot_config.target_atr_multiple,
            entry_trailing_activation_atr=(
                restored.bot_config.trailing_activation_atr
            ),
            exit_slippage_rate=restored.bot_config.slippage_rate,
            entry_semantic_snapshot={
                "candidate_v1_config_fingerprint": restored.fingerprint,
                "candidate_v1_config_snapshot": restored.as_dict(),
            },
        )
        round_trip = fixed25._position(fixed25._position_dict(position))
        self.assertEqual(round_trip.entry_stop_atr_multiple, 2.5)
        self.assertEqual(
            round_trip.entry_semantic_snapshot[
                "candidate_v1_config_fingerprint"
            ],
            self.default.fingerprint,
        )

    def test_contract_declares_json_authority_without_tunable_copy(self):
        contract = clean_v2.load_contract()
        self.assertEqual(
            contract["candidate_v1_configuration_reload_boundary"],
            "COMPLETED_15M_DECISION_BOUNDARY",
        )
        self.assertNotIn("maximum_position_notional_fraction", contract)
        self.assertFalse(contract["live_broker_enabled"])
        self.assertTrue(contract["simulated_fills_only"])

    def test_protected_components_are_not_dependencies(self):
        source = Path(fixed25.__file__).read_text(encoding="utf-8")
        loader = Path(__import__(
            "qpx_bot.candidate_v1_config", fromlist=["x"]
        ).__file__).read_text(encoding="utf-8")
        self.assertNotIn("ml_historical_acquisition", source + loader)
        self.assertNotIn("broker_orders_enabled", loader)


if __name__ == "__main__":
    unittest.main()
