import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from qpx_bot.wildcard.learner import (
    DevelopmentOnlyGruLearner,
    LearnerConfig,
    LearnerError,
    LearningCapsule,
    ZERO_AUTHORITY,
    compose_capsules,
    initialize_parameters,
    load_capsule,
    model_fingerprint,
    write_capsule,
)
from qpx_bot.wildcard.world import CausalBoundary


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def boundary(minutes: int, sequence: int = 0) -> CausalBoundary:
    stamp = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return CausalBoundary(stamp, stamp, sequence)


class WildcardLearnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LearnerConfig(3, 2, 4, ("NO_ACTION", "BUY", "SELL"),
                                    0.01, SHA_A, SHA_B, SHA_C)
        self.base = initialize_parameters(self.config, 7)
        self.base_fingerprint = model_fingerprint(self.config, self.base)

    def learner(self, seed: int = 11, **kwargs):
        return DevelopmentOnlyGruLearner(
            config=self.config, base_parameters=self.base,
            base_fingerprint=self.base_fingerprint, episode_id="episode-1",
            experiment_id="experiment-1", world_fingerprint=SHA_A,
            reward_policy_fingerprint=SHA_B, seed=seed, **kwargs,
        )

    def learned_capsule(self):
        learner = self.learner()
        learner.choose_action(state=(0.1, 0.2, 0.3), preference=(1.0, 0.5), boundary=boundary(0))
        learner.learn(reward=0.25, completion_boundary=boundary(15))
        return learner, learner.create_capsule(
            eligibility_boundary=boundary(30), code_revision="1" * 40,
            environment_fingerprint=SHA_C,
        )

    def compose(self, capsule, current):
        return compose_capsules(
            config=self.config, base_parameters=self.base,
            base_fingerprint=self.base_fingerprint, capsules=(capsule,),
            current_action_boundary=current, expected_experiment_id="experiment-1",
            expected_world_fingerprint=SHA_A,
            expected_reward_policy_fingerprint=SHA_B,
        )

    def test_deterministic_initialization_and_identical_input_action(self):
        self.assertEqual(initialize_parameters(self.config, 7), self.base)
        left = self.learner(seed=99)
        right = self.learner(seed=99)
        args = dict(state=(0.1, -0.2, 0.3), preference=(1.0, 0.0), boundary=boundary(0))
        self.assertEqual(left.choose_action(**args), right.choose_action(**args))
        self.assertEqual(left.hidden, right.hidden)

    def test_preference_is_model_input_and_contract_bound(self):
        learner = self.learner()
        learner.choose_action(state=(0.1, 0.2, 0.3), preference=(0.75, -0.5), boundary=boundary(0))
        self.assertEqual(learner.pending["x"], [0.1, 0.2, 0.3, 0.75, -0.5])
        self.assertEqual(learner.config.payload()["preference_contract_fingerprint"], SHA_B)

    def test_update_requires_strictly_later_reward_boundary(self):
        learner = self.learner()
        learner.choose_action(state=(0, 0, 0), preference=(0, 0), boundary=boundary(0))
        before = copy.deepcopy(learner.parameters)
        with self.assertRaisesRegex(LearnerError, "strictly after"):
            learner.learn(reward=1, completion_boundary=boundary(0))
        self.assertEqual(before, learner.parameters)
        learner.learn(reward=1, completion_boundary=boundary(15))
        self.assertNotEqual(before, learner.parameters)

    def test_action_cannot_advance_before_learned_evidence(self):
        learner = self.learner()
        learner.choose_action(state=(0, 0, 0), preference=(0, 0), boundary=boundary(0))
        learner.learn(reward=1, completion_boundary=boundary(15))
        with self.assertRaisesRegex(LearnerError, "strictly after learned evidence"):
            learner.choose_action(state=(0, 0, 0), preference=(0, 0), boundary=boundary(15))

    def test_episode_memory_is_destroyed(self):
        learner = self.learner()
        learner.choose_action(state=(1, 0, 0), preference=(1, 0), boundary=boundary(0))
        learner.learn(reward=1, completion_boundary=boundary(15))
        self.assertNotEqual(learner.hidden, [0.0] * 4)
        self.assertNotEqual(learner.parameters, learner.initial_parameters)
        learner.destroy_episode_memory()
        self.assertEqual(learner.hidden, [0.0] * 4)
        self.assertIsNone(learner.pending)
        self.assertEqual(learner.parameters, learner.initial_parameters)
        self.assertIsNone(learner.last_evidence_boundary)

    def test_capsule_is_ineligible_until_strictly_after_eligibility(self):
        _, capsule = self.learned_capsule()
        for current in (boundary(15), boundary(30)):
            with self.assertRaisesRegex(LearnerError, "not strictly eligible"):
                self.compose(capsule, current)
        composed = self.compose(capsule, boundary(45))
        self.assertEqual(model_fingerprint(self.config, composed),
                         capsule.payload["composed_model_fingerprint"])

    def test_capsule_composition_is_deterministic(self):
        _, capsule = self.learned_capsule()
        one = self.compose(capsule, boundary(45))
        two = self.compose(capsule, boundary(45))
        self.assertEqual(one, two)

    def test_corrupt_or_ambiguous_capsule_lineage_fails_closed(self):
        _, capsule = self.learned_capsule()
        corrupt = dict(capsule.payload)
        corrupt["parent_capsule_fingerprint"] = SHA_C
        with self.assertRaisesRegex(LearnerError, "fingerprint mismatch"):
            self.compose(LearningCapsule(corrupt), boundary(45))

    def test_capsule_from_another_experiment_is_rejected(self):
        _, capsule = self.learned_capsule()
        changed = dict(capsule.payload)
        changed["effective_experiment_identity"] = "another-experiment"
        core = {key: value for key, value in changed.items() if key != "capsule_fingerprint"}
        from qpx_bot.wildcard.learner import _fingerprint
        changed["capsule_fingerprint"] = _fingerprint(core)
        with self.assertRaisesRegex(LearnerError, "identity or lineage"):
            self.compose(LearningCapsule(changed), boundary(45))

    def test_checkpoint_restart_equivalence_with_pending_action(self):
        learner = self.learner()
        action = learner.choose_action(state=(0.1, 0.2, 0.3), preference=(0.4, 0.5),
                                       boundary=boundary(0))
        with tempfile.TemporaryDirectory() as temp:
            learner.checkpoint(Path(temp))
            restored = DevelopmentOnlyGruLearner.restore(
                Path(temp), config=self.config, base_parameters=self.base,
                base_fingerprint=self.base_fingerprint, capsules=(),
            )
            self.assertEqual(restored.pending["selected"], self.config.action_tokens.index(action))
            learner.learn(reward=-0.2, completion_boundary=boundary(15))
            restored.learn(reward=-0.2, completion_boundary=boundary(15))
            self.assertEqual(learner.parameters, restored.parameters)
            self.assertEqual(learner.hidden, restored.hidden)

    def test_checkpoint_fingerprint_mismatch_fails_closed(self):
        learner = self.learner()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            learner.checkpoint(directory)
            payload = json.loads((directory / "learner_state.json").read_text())
            payload["episode_id"] = "tampered"
            (directory / "learner_state.json").write_text(json.dumps(payload))
            with self.assertRaises(Exception):
                DevelopmentOnlyGruLearner.restore(
                    directory, config=self.config, base_parameters=self.base,
                    base_fingerprint=self.base_fingerprint, capsules=(),
                )

    def test_capsule_binds_optimizer_destruction_and_zero_authority(self):
        _, capsule = self.learned_capsule()
        self.assertEqual(capsule.payload["optimizer_state"]["status"], "DESTROYED")
        self.assertEqual(capsule.payload["authority"], ZERO_AUTHORITY)
        self.assertEqual(capsule.payload["development_state"], "DEVELOPMENT_ONLY")

    def test_capsule_is_checksummed_durable_evidence(self):
        _, capsule = self.learned_capsule()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "capsule.json"
            write_capsule(path, capsule)
            self.assertEqual(load_capsule(path).payload, capsule.payload)
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(Exception):
                load_capsule(path)

    def test_learner_exposes_no_archive_navigation(self):
        learner = self.learner()
        for name in ("archive", "read_archive", "list_archive", "search_archive"):
            self.assertFalse(hasattr(learner, name))


if __name__ == "__main__":
    unittest.main()
