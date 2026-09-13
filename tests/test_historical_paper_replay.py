from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from qpx_bot.candidate_v1_causal import (
    CandidateV1CausalInputs,
    evaluate_candidate_v1_causal,
)
from qpx_bot.candidate_v1_config import load_candidate_v1_config
from qpx_bot.causal_replay import (
    CausalAccessError,
    CausalDataPortal,
    MarketClock,
    ReplayBar,
)
from qpx_bot.historical_paper_replay import (
    CausalEvidenceEvent,
    CausalEvidenceGateway,
    CandidateV1ReplayPort,
    ReplayAdapterBindings,
    ReplayCheckpoint,
    ReplayConfigurationError,
    load_replay_configuration,
    read_replay_checkpoint,
    replay_configuration_from_mapping,
    write_replay_checkpoint,
)


FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64
FINGERPRINT_C = "c" * 64


def static_configuration() -> dict:
    return {
        "schema_version": 1,
        "semantic_version": "QPX_CAUSAL_HISTORICAL_PAPER_REPLAY_CONFIG_V1",
        "experiment_id": "REPLAY.TEST.V1",
        "market_data": {
            "provider": "ALPACA",
            "feed": "SIP",
            "decision_bar_interval": "15m",
            "adjustment_mode": "RAW",
            "adapter_identity": "ALPACA.SIP.REPLAY.V1",
        },
        "execution": {
            "model": "NEXT_ELIGIBLE_15M_OPEN",
            "adapter_identity": "HISTORICAL.PAPER.EXECUTION.V1",
            "semantic_version": "NEXT.OPEN.V1",
        },
        "income": {
            "implementation_identity": "INCOME.ROLE.V1",
            "bootstrap_mode": "CASH_UNTIL_INCOME_IMPLEMENTATION_AVAILABLE",
            "availability_source": "POINT_IN_TIME.QUALIFICATION.V1",
        },
        "volatility": {
            "source": "CBOE.VIX.PREVIOUS.COMPLETED.SESSION",
            "adapter_identity": "CBOE.VIX.REPLAY.V1",
            "evidence_fingerprint": FINGERPRINT_A,
        },
        "universe": {
            "mode": "STATIC_FROZEN",
            "identity": "STATIC.TEST.UNIVERSE.V1",
            "manifest_reference": "fixtures/causal_static_universe.json",
            "manifest_fingerprint": FINGERPRINT_B,
            "retrospective_selection": True,
            "policy": None,
        },
        "starting_account": {
            "configuration_identity": "FRESH.PAPER.ACCOUNT.V1",
            "currency": "USD",
            "starting_cash": 100000.0,
        },
        "contributions": {
            "schedule_identity": "NO.CONTRIBUTIONS.V1",
            "currency": "USD",
            "amount": 0.0,
        },
        "strategy": {
            "identity": "CANDIDATE.V1",
            "configuration_fingerprint": FINGERPRINT_C,
            "entry_semantics_fingerprint": FINGERPRINT_A,
        },
        "runtime": {
            "causal_driver_version": "CAUSAL.DRIVER.V1",
            "accounting_version": "PAPER.ACCOUNTING.V1",
            "execution_version": "HISTORICAL.EXECUTION.V1",
        },
        "dataset": {
            "root_identity": "research_data/qpx_ml_historical_v1",
            "snapshot_fingerprint": FINGERPRINT_B,
            "qualification_status": "ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE",
        },
        "authority": {
            "training": "NONE",
            "promotion": "NONE",
            "live": "NONE",
            "broker": "NONE",
            "capital": "NONE",
        },
    }


def reconstituted_configuration() -> dict:
    value = static_configuration()
    value["universe"] = {
        "mode": "CAUSALLY_RESELECTED",
        "identity": "CAUSAL.RECONSTITUTION.TEST.V1",
        "manifest_reference": None,
        "manifest_fingerprint": None,
        "retrospective_selection": False,
        "policy": {
            "eligibility_source": "TEST.ELIGIBILITY.V1",
            "selection_rule": "TEST.RANKING.V1",
            "membership_count": 25,
            "lookback": "TEST.LOOKBACK.V1",
            "reselection_cadence": "TEST.CADENCE.V1",
            "evidence_cutoff": "TEST.CUTOFF.V1",
            "effective_time_boundary": "TEST.EFFECTIVE.TIME.V1",
            "entry_removal_treatment": "TEST.MEMBERSHIP.TRANSITION.V1",
        },
    }
    return value


class ReplayConfigurationTests(unittest.TestCase):
    def test_missing_unknown_and_malformed_configuration_fail_closed(self):
        missing = static_configuration()
        del missing["execution"]
        with self.assertRaisesRegex(ReplayConfigurationError, "missing"):
            replay_configuration_from_mapping(missing)

        unknown = static_configuration()
        unknown["historical_default"] = True
        with self.assertRaisesRegex(ReplayConfigurationError, "unknown"):
            replay_configuration_from_mapping(unknown)

        malformed = static_configuration()
        malformed["schema_version"] = True
        with self.assertRaisesRegex(ReplayConfigurationError, "schema"):
            replay_configuration_from_mapping(malformed)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "duplicate.json"
            path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(ReplayConfigurationError, "Duplicate"):
                load_replay_configuration(path)

    def test_canonical_identity_is_order_independent(self):
        payload = static_configuration()
        reversed_payload = dict(reversed(list(payload.items())))
        configured = replay_configuration_from_mapping(payload)
        self.assertEqual(
            configured.fingerprint,
            replay_configuration_from_mapping(reversed_payload).fingerprint,
        )
        detached = configured.payload
        detached["market_data"]["feed"] = "IEX"
        self.assertEqual(configured.payload["market_data"]["feed"], "SIP")

    def test_each_experiment_axis_changes_identity(self):
        original = replay_configuration_from_mapping(static_configuration()).fingerprint
        mutations = (
            (("experiment_id",), "REPLAY.OTHER.V1"),
            (("market_data", "provider"), "POLYGON"),
            (("market_data", "feed"), "IEX"),
            (("market_data", "decision_bar_interval"), "30m"),
            (("market_data", "adjustment_mode"), "CAUSAL_SPLIT_ADJUSTED"),
            (("market_data", "adapter_identity"), "ALPACA.SIP.REPLAY.V2"),
            (("execution", "model"), "NEXT_ELIGIBLE_1M"),
            (("execution", "adapter_identity"), "HISTORICAL.PAPER.EXECUTION.V2"),
            (("execution", "semantic_version"), "NEXT.OPEN.V2"),
            (("income", "implementation_identity"), "INCOME.ROLE.V2"),
            (("income", "bootstrap_mode"), "CANONICAL_IMMEDIATE"),
            (("income", "availability_source"), "POINT_IN_TIME.QUALIFICATION.V2"),
            (("volatility", "source"), "OTHER.PREVIOUS.SESSION"),
            (("volatility", "adapter_identity"), "CBOE.VIX.REPLAY.V2"),
            (("volatility", "evidence_fingerprint"), FINGERPRINT_B),
            (("universe", "identity"), "STATIC.OTHER.UNIVERSE.V1"),
            (("universe", "manifest_reference"), "fixtures/other_universe.json"),
            (("universe", "manifest_fingerprint"), FINGERPRINT_A),
            (("universe", "retrospective_selection"), False),
            (("starting_account", "configuration_identity"), "FRESH.PAPER.ACCOUNT.V2"),
            (("starting_account", "currency"), "EUR"),
            (("starting_account", "starting_cash"), 90000.0),
            (("contributions", "schedule_identity"), "MONTHLY.CONTRIBUTIONS.V1"),
            (("contributions", "currency"), "EUR"),
            (("contributions", "amount"), 100.0),
            (("strategy", "identity"), "CANDIDATE.V2"),
            (("strategy", "configuration_fingerprint"), FINGERPRINT_B),
            (("strategy", "entry_semantics_fingerprint"), FINGERPRINT_C),
            (("runtime", "causal_driver_version"), "CAUSAL.DRIVER.V2"),
            (("runtime", "accounting_version"), "PAPER.ACCOUNTING.V2"),
            (("runtime", "execution_version"), "HISTORICAL.EXECUTION.V2"),
            (("dataset", "root_identity"), "research_data/other_snapshot"),
            (("dataset", "snapshot_fingerprint"), FINGERPRINT_A),
            (("dataset", "qualification_status"), "NOT_TRAINING_ELIGIBLE"),
        )
        for path, replacement in mutations:
            with self.subTest(path=path):
                changed = static_configuration()
                if len(path) == 1:
                    changed[path[0]] = replacement
                else:
                    changed[path[0]][path[1]] = replacement
                self.assertNotEqual(
                    replay_configuration_from_mapping(changed).fingerprint,
                    original,
                )

    def test_each_reconstitution_policy_axis_changes_identity(self):
        baseline = reconstituted_configuration()
        original = replay_configuration_from_mapping(baseline).fingerprint
        for field in (
            "eligibility_source", "selection_rule", "lookback",
            "reselection_cadence", "evidence_cutoff", "effective_time_boundary",
            "entry_removal_treatment",
        ):
            with self.subTest(field=field):
                changed = reconstituted_configuration()
                changed["universe"]["policy"][field] += ".ALT"
                self.assertNotEqual(
                    replay_configuration_from_mapping(changed).fingerprint,
                    original,
                )
        changed = reconstituted_configuration()
        changed["universe"]["policy"]["membership_count"] += 1
        self.assertNotEqual(
            replay_configuration_from_mapping(changed).fingerprint,
            original,
        )

    def test_static_universe_requires_explicit_evidence(self):
        payload = static_configuration()
        payload["universe"]["manifest_reference"] = None
        with self.assertRaises(ReplayConfigurationError):
            replay_configuration_from_mapping(payload)

    def test_reconstitution_requires_complete_policy_without_fallback(self):
        payload = reconstituted_configuration()
        del payload["universe"]["policy"]["entry_removal_treatment"]
        with self.assertRaisesRegex(ReplayConfigurationError, "missing"):
            replay_configuration_from_mapping(payload)

    def test_static_and_reconstituted_evidence_cannot_qualify_each_other(self):
        static = static_configuration()
        static["universe"]["policy"] = reconstituted_configuration()["universe"]["policy"]
        with self.assertRaisesRegex(ReplayConfigurationError, "Static"):
            replay_configuration_from_mapping(static)

        causal = reconstituted_configuration()
        causal["universe"]["manifest_reference"] = "frozen.json"
        causal["universe"]["manifest_fingerprint"] = FINGERPRINT_A
        with self.assertRaisesRegex(ReplayConfigurationError, "masquerade"):
            replay_configuration_from_mapping(causal)

    def test_adapter_choices_swap_between_experiments_not_inside_strategy(self):
        first = replay_configuration_from_mapping(static_configuration())
        changed = static_configuration()
        changed["market_data"]["adapter_identity"] = "ALPACA.IEX.REPLAY.V1"
        changed["market_data"]["feed"] = "IEX"
        changed["execution"]["adapter_identity"] = "ONE.MINUTE.EXECUTION.V1"
        changed["execution"]["model"] = "NEXT_ELIGIBLE_1M"
        second = replay_configuration_from_mapping(changed)
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        ReplayAdapterBindings(
            "ALPACA.SIP.REPLAY.V1", "HISTORICAL.PAPER.EXECUTION.V1",
            "CBOE.VIX.REPLAY.V1", "STATIC.TEST.UNIVERSE.V1",
        ).validate(first)
        ReplayAdapterBindings(
            "ALPACA.IEX.REPLAY.V1", "ONE.MINUTE.EXECUTION.V1",
            "CBOE.VIX.REPLAY.V1", "STATIC.TEST.UNIVERSE.V1",
        ).validate(second)
        with self.assertRaises(ReplayConfigurationError):
            ReplayAdapterBindings(
                "ALPACA.SIP.REPLAY.V1", "HISTORICAL.PAPER.EXECUTION.V1",
                "CBOE.VIX.REPLAY.V1", "STATIC.TEST.UNIVERSE.V1",
            ).validate(second)

    def test_authority_is_always_none(self):
        payload = static_configuration()
        payload["authority"]["broker"] = "PAPER"
        with self.assertRaisesRegex(ReplayConfigurationError, "authority"):
            replay_configuration_from_mapping(payload)


class ReplayCausalityAndRestartTests(unittest.TestCase):
    def test_candidate_port_preserves_scalar_contract_and_owns_no_universe(self):
        snapshot = load_candidate_v1_config()
        port = CandidateV1ReplayPort(snapshot)
        inputs = CandidateV1CausalInputs(
            index=20, current_close=11.0, current_volume=100000,
            current_fast=11.0, previous_fast=9.0, current_slow=10.0,
            previous_slow=10.0, current_rsi=60.0, previous_rsi=49.0,
            current_rmi=60.0, previous_rmi=49.0, current_sma=10.0,
            slope_sma=9.0, baseline_volume=80000.0, current_atr=1.0,
            prior_high=10.5, vix=20.0,
        )
        self.assertEqual(
            port.evaluate(inputs),
            evaluate_candidate_v1_causal(inputs=inputs, config=snapshot.bot_config),
        )
        self.assertEqual({item.name for item in fields(inputs)}, {
            "index", "current_close", "current_volume", "current_fast",
            "previous_fast", "current_slow", "previous_slow", "current_rsi",
            "previous_rsi", "current_rmi", "previous_rmi", "current_sma",
            "slope_sma", "baseline_volume", "current_atr", "prior_high", "vix",
        })
        self.assertFalse(hasattr(port, "archive"))
        self.assertFalse(hasattr(port, "universe"))

    def test_existing_portal_denies_future_bar(self):
        start = datetime(2025, 1, 2, 14, 30, tzinfo=timezone.utc)
        future = start + timedelta(minutes=15)
        clock = MarketClock((start, future))
        portal = CausalDataPortal(
            clock=clock,
            histories={
                "A": (
                    ReplayBar(start, 1, 2, 1, 2, 100),
                    ReplayBar(future, 2, 3, 2, 3, 100),
                ),
            },
        )
        with self.assertRaises(CausalAccessError):
            portal.bar_at("A", future)

    def test_gateway_denies_future_corporate_action_and_has_no_archive(self):
        boundary = datetime(2025, 1, 2, 15, 0, tzinfo=timezone.utc)
        gateway = CausalEvidenceGateway()
        future = CausalEvidenceEvent(
            event_id="ca-1", event_type="CORPORATE_ACTION",
            effective_time=boundary, available_time=boundary + timedelta(days=1),
            payload={"provider_event_id": "ca-1"},
        )
        with self.assertRaisesRegex(ReplayConfigurationError, "Future"):
            gateway.release(future, current_boundary=boundary)
        self.assertFalse(hasattr(gateway, "archive"))
        self.assertFalse(hasattr(gateway, "cursor"))

    def test_checkpoint_round_trip_and_configuration_mismatch(self):
        config = replay_configuration_from_mapping(static_configuration())
        checkpoint = ReplayCheckpoint(
            run_id="REPLAY.TEST.RUN.V1",
            configuration_fingerprint=config.fingerprint,
            last_completed_boundary_id="2025-01-02T15:00:00Z",
            causal_sequence=17,
            paper_state_fingerprint=FINGERPRINT_C,
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first_fingerprint = write_replay_checkpoint(root, checkpoint, config)
            restored = read_replay_checkpoint(root, config)
            self.assertEqual(restored, checkpoint)
            self.assertEqual(
                first_fingerprint,
                write_replay_checkpoint(root, restored, config),
            )
            changed = static_configuration()
            changed["contributions"]["amount"] = 10.0
            other = replay_configuration_from_mapping(changed)
            with self.assertRaisesRegex(ReplayConfigurationError, "configuration mismatch"):
                read_replay_checkpoint(root, other)

    def test_checkpoint_corruption_fails_closed(self):
        config = replay_configuration_from_mapping(static_configuration())
        checkpoint = ReplayCheckpoint(
            run_id="REPLAY.TEST.RUN.V1",
            configuration_fingerprint=config.fingerprint,
            last_completed_boundary_id=None,
            causal_sequence=0,
            paper_state_fingerprint=FINGERPRINT_A,
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_replay_checkpoint(root, checkpoint, config)
            path = root / "checkpoint.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["causal_sequence"] = 1
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                read_replay_checkpoint(root, config)


if __name__ == "__main__":
    unittest.main()
