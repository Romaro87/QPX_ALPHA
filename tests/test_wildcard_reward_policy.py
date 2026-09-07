from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

from qpx_bot.wildcard.reward_policy import (
    APPROVAL_AUTHORITY,
    CONSEQUENCE_CHANNELS,
    DEFAULT_APPROVAL_PATH,
    DEFAULT_POLICY_PATH,
    OPTIONAL_DISABLED_TERMS,
    REQUIRED_WORLD_CONTRACT_ID,
    ApprovedRewardPolicy,
    ConsequenceAvailability,
    RewardEmissionBoundary,
    RewardPolicyError,
    approved_policy_from_payloads,
    canonical_bytes,
    capture_approved_policy,
    experiment_identity,
    load_approved_policy,
    load_captured_policy,
    load_policy_content,
    policy_content_from_payload,
    required_consequence_channels,
    validate_consequence_availability,
)


class WildcardRewardPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy_payload = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
        cls.approval_payload = json.loads(
            DEFAULT_APPROVAL_PATH.read_text(encoding="utf-8")
        )

    def setUp(self) -> None:
        self.approved = load_approved_policy()

    def policy_copy(self) -> dict:
        return copy.deepcopy(self.policy_payload)

    def approval_for(self, policy_payload: dict) -> dict:
        approval = copy.deepcopy(self.approval_payload)
        approval["policy_content_fingerprint"] = policy_content_from_payload(
            policy_payload
        ).policy_content_fingerprint
        return approval

    def approve(self, policy_payload: dict, approval_payload: dict | None = None):
        return approved_policy_from_payloads(
            policy_payload,
            approval_payload or self.approval_for(policy_payload),
            verify_git_provenance=False,
        )

    def test_default_v1_exact_content(self) -> None:
        content = self.approved.content
        self.assertEqual(content.schema_version, 1)
        self.assertEqual(content.policy_name, "wildcard_default_v1")
        self.assertEqual(content.policy_version, "1.0.0")
        self.assertEqual(content.required_world_contract_id, REQUIRED_WORLD_CONTRACT_ID)
        self.assertEqual(content.term("growth").effective_weight, Decimal("1"))
        speed = content.term("speed_bonus")
        self.assertEqual(speed.effective_weight, Decimal("1"))
        self.assertEqual(
            speed.parameter_mapping["half_life_scheduled_market_minutes"], 24570
        )

    def test_default_optional_terms_are_exactly_disabled(self) -> None:
        for name in OPTIONAL_DISABLED_TERMS:
            with self.subTest(name=name):
                term = self.approved.content.term(name)
                self.assertEqual(
                    term.as_dict(),
                    {"enabled": False, "function_id": None, "parameters": None},
                )
                self.assertEqual(term.effective_weight, Decimal("0"))
                self.assertEqual(
                    term.effective_contribution_when_disabled, Decimal("0")
                )

    def test_equivalent_decimal_spellings_and_order_canonicalize_equally(self) -> None:
        payload = self.policy_copy()
        payload["terms"]["growth"]["parameters"]["weight"] = "1.000"
        payload["terms"]["speed_bonus"]["parameters"]["weight"] = "1.0"
        payload = dict(reversed(list(payload.items())))
        equivalent = policy_content_from_payload(payload)
        self.assertEqual(equivalent.canonical_bytes, self.approved.content.canonical_bytes)
        self.assertEqual(
            equivalent.policy_content_fingerprint,
            self.approved.content.policy_content_fingerprint,
        )

    def test_authoring_whitespace_does_not_change_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.json"
            path.write_text(json.dumps(self.policy_payload, indent=7), encoding="utf-8")
            loaded = load_policy_content(path)
        self.assertEqual(
            loaded.policy_content_fingerprint,
            self.approved.content.policy_content_fingerprint,
        )

    def test_parameter_change_changes_content_fingerprint(self) -> None:
        payload = self.policy_copy()
        payload["terms"]["growth"]["parameters"]["weight"] = "1.01"
        changed = policy_content_from_payload(payload)
        self.assertNotEqual(
            changed.policy_content_fingerprint,
            self.approved.content.policy_content_fingerprint,
        )

    def test_enable_state_change_changes_content_fingerprint(self) -> None:
        payload = self.policy_copy()
        payload["terms"]["growth"] = {
            "enabled": False,
            "function_id": None,
            "parameters": None,
        }
        changed = policy_content_from_payload(payload)
        self.assertNotEqual(
            changed.policy_content_fingerprint,
            self.approved.content.policy_content_fingerprint,
        )

    def test_fingerprints_repeat_across_reloads(self) -> None:
        again = load_approved_policy()
        self.assertEqual(
            again.content.policy_content_fingerprint,
            self.approved.content.policy_content_fingerprint,
        )
        self.assertEqual(
            again.reward_policy_fingerprint,
            self.approved.reward_policy_fingerprint,
        )

    def test_duplicate_json_field_rejects(self) -> None:
        raw = DEFAULT_POLICY_PATH.read_text(encoding="utf-8")
        raw = raw.replace(
            '"schema_version": 1,',
            '"schema_version": 1, "schema_version": 1,',
            1,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "duplicate.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaises(RewardPolicyError):
                load_policy_content(path)

    def test_unknown_missing_and_protected_fields_reject(self) -> None:
        for field in ("unknown", "broker_authority", "bankruptcy_definition"):
            with self.subTest(field=field):
                payload = self.policy_copy()
                payload[field] = True
                with self.assertRaises(RewardPolicyError):
                    policy_content_from_payload(payload)
        payload = self.policy_copy()
        del payload["terminal_policy_id"]
        with self.assertRaises(RewardPolicyError):
            policy_content_from_payload(payload)

    def test_malformed_decimal_forms_reject(self) -> None:
        values = ("+1", "1e0", " 1", "1 ", "01", ".1", "1.", "NaN", "Infinity")
        for value in values:
            with self.subTest(value=value):
                payload = self.policy_copy()
                payload["terms"]["growth"]["parameters"]["weight"] = value
                with self.assertRaises(RewardPolicyError):
                    policy_content_from_payload(payload)

    def test_json_float_and_nonfinite_reject(self) -> None:
        for value in (1.5, float("nan"), float("inf")):
            with self.subTest(value=value):
                payload = self.policy_copy()
                payload["terms"]["growth"]["parameters"]["weight"] = value
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "float.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(RewardPolicyError):
                        load_policy_content(path)

    def test_precision_magnitude_and_weight_domains_reject(self) -> None:
        values = (
            "0.0000000000001",
            "1234567890123456789",
            "1000000000000",
            "-0.01",
        )
        for value in values:
            with self.subTest(value=value):
                payload = self.policy_copy()
                payload["terms"]["growth"]["parameters"]["weight"] = value
                with self.assertRaises(RewardPolicyError):
                    policy_content_from_payload(payload)

    def test_negative_zero_canonicalizes_to_zero(self) -> None:
        payload = self.policy_copy()
        payload["terms"]["growth"]["parameters"]["weight"] = "-0.000"
        content = policy_content_from_payload(payload)
        self.assertEqual(content.term("growth").parameter_mapping["weight"], Decimal("0"))
        self.assertEqual(content.term("growth").as_dict()["parameters"]["weight"], "0")

    def test_time_constant_requires_positive_non_boolean_integer(self) -> None:
        for value in (0, -1, True, "24570"):
            with self.subTest(value=value):
                payload = self.policy_copy()
                payload["terms"]["speed_bonus"]["parameters"][
                    "half_life_scheduled_market_minutes"
                ] = value
                with self.assertRaises(RewardPolicyError):
                    policy_content_from_payload(payload)

    def test_disabled_term_cannot_carry_dormant_parameters(self) -> None:
        payload = self.policy_copy()
        payload["terms"]["cash_exposure"]["parameters"] = {"weight": "0"}
        with self.assertRaises(RewardPolicyError):
            policy_content_from_payload(payload)

    def test_unapproved_optional_function_rejects(self) -> None:
        payload = self.policy_copy()
        payload["terms"]["inactivity"] = {
            "enabled": True,
            "function_id": "inactivity_penalty_v1",
            "parameters": {"weight": "1"},
        }
        with self.assertRaises(RewardPolicyError):
            policy_content_from_payload(payload)

    def test_policy_terms_parameters_and_approval_are_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.approved.content.policy_name = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            self.approved.approval.approval_status = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            self.approved.content.term("growth").parameter_mapping["weight"] = Decimal("2")

    def test_bad_approval_authority_and_reference_reject(self) -> None:
        approval = copy.deepcopy(self.approval_payload)
        approval["approval_authority"] = "UNRECOGNIZED"
        with self.assertRaises(RewardPolicyError):
            self.approve(self.policy_copy(), approval)
        approval = copy.deepcopy(self.approval_payload)
        approval["approval_reference"]["commit"] = "abc"
        with self.assertRaises(RewardPolicyError):
            self.approve(self.policy_copy(), approval)

    def test_default_git_approval_provenance_is_verifiable(self) -> None:
        self.assertEqual(self.approved.approval.approval_authority, APPROVAL_AUTHORITY)
        self.assertEqual(
            self.approved.approval.approval_reference.document_path,
            "docs/adr/ADR-0012-wildcard-experimental-world-and-reward-contract.md",
        )

    def test_approval_content_fingerprint_mismatch_rejects(self) -> None:
        approval = copy.deepcopy(self.approval_payload)
        approval["policy_content_fingerprint"] = "0" * 64
        with self.assertRaises(RewardPolicyError):
            self.approve(self.policy_copy(), approval)

    def test_approval_provenance_change_changes_policy_fingerprint(self) -> None:
        approval = copy.deepcopy(self.approval_payload)
        approval["change_note"] = "Governed alternate approval evidence."
        changed = self.approve(self.policy_copy(), approval)
        self.assertEqual(
            changed.content.policy_content_fingerprint,
            self.approved.content.policy_content_fingerprint,
        )
        self.assertNotEqual(
            changed.reward_policy_fingerprint,
            self.approved.reward_policy_fingerprint,
        )

    def test_experiment_identity_binds_world_and_reward_policy(self) -> None:
        world_a = "1" * 64
        world_b = "2" * 64
        reward_a = self.approved.reward_policy_fingerprint
        reward_b = "3" * 64
        identity = experiment_identity(world_a, reward_a)
        self.assertEqual(identity, experiment_identity(world_a, reward_a))
        self.assertNotEqual(identity, experiment_identity(world_b, reward_a))
        self.assertNotEqual(identity, experiment_identity(world_a, reward_b))

    def test_capture_and_identical_reload_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            captured = capture_approved_policy(
                Path(temporary), self.approved, world_fingerprint="4" * 64
            )
            loaded = load_captured_policy(
                Path(temporary), expected_world_fingerprint="4" * 64
            )
        self.assertEqual(loaded, captured)

    def test_existing_capture_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            captured = capture_approved_policy(
                directory, self.approved, world_fingerprint="4" * 64
            )
            self.assertEqual(
                capture_approved_policy(
                    directory, self.approved, world_fingerprint="4" * 64
                ),
                captured,
            )
            payload = self.policy_copy()
            payload["terms"]["growth"]["parameters"]["weight"] = "2"
            changed = self.approve(payload)
            with self.assertRaises(RewardPolicyError):
                capture_approved_policy(
                    directory, changed, world_fingerprint="4" * 64
                )

    def test_missing_corrupt_and_world_mismatched_capture_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaises(RewardPolicyError):
                load_captured_policy(directory)
            capture_approved_policy(directory, self.approved, world_fingerprint="4" * 64)
            with self.assertRaises(RewardPolicyError):
                load_captured_policy(
                    directory, expected_world_fingerprint="5" * 64
                )
            (directory / "reward_policy.canonical.json").write_bytes(b"{}")
            with self.assertRaises(RewardPolicyError):
                load_captured_policy(directory)

    def test_consequence_schema_is_closed_and_strategy_neutral(self) -> None:
        self.assertEqual(
            {item.name for item in CONSEQUENCE_CHANNELS},
            {
                "delta_log_equity",
                "scheduled_market_minutes",
                "cash_exposure",
                "inactivity",
                "turnover",
                "concentration",
                "drawdown",
                "volatility",
                "modeled_cost",
            },
        )
        self.assertEqual(
            required_consequence_channels(self.approved.content),
            ("delta_log_equity", "scheduled_market_minutes"),
        )

    def test_enabled_terms_require_available_consequence_evidence(self) -> None:
        valid = {
            "delta_log_equity": ConsequenceAvailability.AVAILABLE,
            "scheduled_market_minutes": ConsequenceAvailability.AVAILABLE,
        }
        validate_consequence_availability(self.approved.content, valid)
        valid["delta_log_equity"] = ConsequenceAvailability.UNAVAILABLE_BLOCKING
        with self.assertRaises(RewardPolicyError):
            validate_consequence_availability(self.approved.content, valid)
        with self.assertRaises(RewardPolicyError):
            validate_consequence_availability(
                self.approved.content, {"unknown": ConsequenceAvailability.AVAILABLE}
            )

    def test_initial_boundary_establishes_baseline_without_reward(self) -> None:
        boundary = RewardEmissionBoundary(0, True, True, True, True, True)
        self.assertFalse(boundary.transition_reward_eligible)

    def test_later_boundary_is_post_reconciliation_pre_action(self) -> None:
        boundary = RewardEmissionBoundary(1, True, True, True, True, True)
        self.assertTrue(boundary.transition_reward_eligible)
        exposed = RewardEmissionBoundary(1, True, True, True, True, True, True)
        self.assertFalse(exposed.transition_reward_eligible)
        with self.assertRaises(RewardPolicyError):
            RewardEmissionBoundary(1, True, False, True, False, False)

    def test_canonical_bytes_are_compact_utf8_without_newline(self) -> None:
        encoded = canonical_bytes({"z": "e\u0301", "a": True})
        self.assertEqual(encoded, '{"a":true,"z":"é"}'.encode("utf-8"))
        self.assertFalse(encoded.endswith(b"\n"))

    def test_approved_policy_is_frozen(self) -> None:
        self.assertIsInstance(self.approved, ApprovedRewardPolicy)
        with self.assertRaises(FrozenInstanceError):
            self.approved.content = self.approved.content  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
