"""DEVELOPMENT_ONLY causal GRU learner and immutable learning capsules.

The learner has no archive, broker, live, promotion, capital, or apprenticeship
authority.  It accepts only fixed-size causal vectors and complete boundaries.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state
from qpx_bot.wildcard.world import CausalBoundary


LEARNER_SEMANTIC_VERSION = "QPX_WILDCARD_CAUSAL_GRU_POLICY_V1"
CAPSULE_SCHEMA_VERSION = 1
CHECKPOINT_SCHEMA_VERSION = 1
DEVELOPMENT_STATE = "DEVELOPMENT_ONLY"
ZERO_AUTHORITY = {
    "promotion": "NONE", "live": "NONE", "broker": "NONE", "capital": "NONE",
}
CAPSULE_KEYS = frozenset({
    "schema_version", "semantic_version", "development_state", "capsule_identity",
    "base_model_fingerprint", "parent_capsule_fingerprint", "composition_sequence",
    "parent_composed_model_fingerprint", "composed_model_fingerprint",
    "maximum_evidence_boundary", "eligibility_boundary", "episode_identity",
    "effective_experiment_identity", "world_fingerprint", "reward_policy_fingerprint",
    "feature_state_contract_fingerprint", "preference_contract_fingerprint",
    "action_space_fingerprint", "learning_algorithm_config_fingerprint",
    "architecture_fingerprint", "parameter_delta", "optimizer_state",
    "deterministic_composition", "rng_seed", "rng_state_at_seal", "code_revision",
    "environment_fingerprint", "authority", "capsule_fingerprint",
})


class LearnerError(RuntimeError):
    pass


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _boundary_payload(value: CausalBoundary) -> dict[str, Any]:
    return value.payload()


def _boundary(raw: Mapping[str, Any]) -> CausalBoundary:
    from datetime import datetime
    return CausalBoundary(
        datetime.fromisoformat(str(raw["effective_time"])),
        datetime.fromisoformat(str(raw["available_time"])),
        int(raw["sequence"]),
    )


class DeterministicRng:
    """Small specified 64-bit generator; state is directly checkpointable."""

    def __init__(self, state: int) -> None:
        if type(state) is not int or not 0 <= state < 2**64:
            raise LearnerError("RNG state must be an unsigned 64-bit integer.")
        self.state = state

    def uniform(self) -> float:
        self.state = (6364136223846793005 * self.state + 1442695040888963407) % 2**64
        return (self.state >> 11) / float(1 << 53)


@dataclass(frozen=True, slots=True)
class LearnerConfig:
    state_size: int
    preference_size: int
    hidden_size: int
    action_tokens: tuple[str, ...]
    learning_rate: float
    state_contract_fingerprint: str
    preference_contract_fingerprint: str
    action_space_fingerprint: str

    def __post_init__(self) -> None:
        if min(self.state_size, self.preference_size, self.hidden_size) <= 0:
            raise LearnerError("Learner vector dimensions must be positive.")
        if len(self.action_tokens) < 2 or len(set(self.action_tokens)) != len(self.action_tokens):
            raise LearnerError("Action tokens must be a unique ordered vocabulary.")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise LearnerError("Learning rate must be positive and finite.")
        for value in (
            self.state_contract_fingerprint,
            self.preference_contract_fingerprint,
            self.action_space_fingerprint,
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise LearnerError("Contract fingerprints must be lowercase SHA-256 values.")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.payload())

    def payload(self) -> dict[str, Any]:
        return {
            "semantic_version": LEARNER_SEMANTIC_VERSION,
            "model_family": "SMALL_GRU_SOFTMAX_POLICY",
            "algorithm": "ONLINE_ONE_BOUNDARY_REWARD_MODULATED_SGD_TRUNCATED_BPTT_1",
            "state_size": self.state_size,
            "preference_size": self.preference_size,
            "hidden_size": self.hidden_size,
            "action_tokens": list(self.action_tokens),
            "learning_rate": self.learning_rate,
            "state_contract_fingerprint": self.state_contract_fingerprint,
            "preference_contract_fingerprint": self.preference_contract_fingerprint,
            "action_space_fingerprint": self.action_space_fingerprint,
        }


def _shape(config: LearnerConfig) -> dict[str, int]:
    inputs = config.state_size + config.preference_size
    hidden = config.hidden_size
    actions = len(config.action_tokens)
    return {
        "Wz": hidden * inputs, "Uz": hidden * hidden, "bz": hidden,
        "Wr": hidden * inputs, "Ur": hidden * hidden, "br": hidden,
        "Wn": hidden * inputs, "Un": hidden * hidden, "bn": hidden,
        "Wo": actions * hidden, "bo": actions,
    }


def _validate_parameters(config: LearnerConfig, parameters: Mapping[str, Sequence[float]]) -> dict[str, list[float]]:
    expected = _shape(config)
    if set(parameters) != set(expected):
        raise LearnerError("Model parameter names do not match the architecture.")
    output: dict[str, list[float]] = {}
    for name, size in expected.items():
        values = list(parameters[name])
        if len(values) != size or any(not math.isfinite(float(value)) for value in values):
            raise LearnerError(f"Model parameter {name} has invalid shape or values.")
        output[name] = [float(value) for value in values]
    return output


def initialize_parameters(config: LearnerConfig, seed: int) -> dict[str, list[float]]:
    rng = DeterministicRng(seed)
    result: dict[str, list[float]] = {}
    for name, size in _shape(config).items():
        if name.startswith("b"):
            result[name] = [0.0] * size
        else:
            result[name] = [(rng.uniform() * 2.0 - 1.0) * 0.05 for _ in range(size)]
    return result


def _matrix_vector(values: Sequence[float], rows: int, columns: int, vector: Sequence[float]) -> list[float]:
    return [sum(values[row * columns + col] * vector[col] for col in range(columns))
            for row in range(rows)]


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


def _softmax(values: Sequence[float]) -> list[float]:
    maximum = max(values)
    exponents = [math.exp(value - maximum) for value in values]
    total = sum(exponents)
    return [value / total for value in exponents]


def model_fingerprint(config: LearnerConfig, parameters: Mapping[str, Sequence[float]]) -> str:
    return _fingerprint({"architecture_fingerprint": config.fingerprint,
                         "parameters": _validate_parameters(config, parameters)})


@dataclass(frozen=True, slots=True)
class LearningCapsule:
    payload: Mapping[str, Any]

    @property
    def fingerprint(self) -> str:
        return str(self.payload["capsule_fingerprint"])


def write_capsule(path: Path, capsule: LearningCapsule) -> None:
    value = dict(capsule.payload)
    declared = value.pop("capsule_fingerprint", None)
    if set(capsule.payload) != CAPSULE_KEYS or declared != _fingerprint(value):
        raise LearnerError("Refusing to persist an invalid learning capsule.")
    path = Path(path)
    write_checksummed_state(path, path.with_suffix(path.suffix + ".sha256"),
                            _canon(dict(capsule.payload)))


def load_capsule(path: Path) -> LearningCapsule:
    path = Path(path)
    encoded = read_checksummed_state(path, path.with_suffix(path.suffix + ".sha256"),
                                     label="Wildcard learning capsule")
    try:
        value = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as exc:
        raise LearnerError("Learning capsule is malformed.") from exc
    if not isinstance(value, dict) or set(value) != CAPSULE_KEYS:
        raise LearnerError("Learning capsule schema fields are invalid.")
    declared = value.pop("capsule_fingerprint", None)
    if declared != _fingerprint(value):
        raise LearnerError("Learning capsule fingerprint mismatch.")
    value["capsule_fingerprint"] = declared
    return LearningCapsule(value)


def compose_capsules(
    *, config: LearnerConfig, base_parameters: Mapping[str, Sequence[float]],
    base_fingerprint: str, capsules: Sequence[LearningCapsule],
    current_action_boundary: CausalBoundary, expected_experiment_id: str,
    expected_world_fingerprint: str, expected_reward_policy_fingerprint: str,
) -> dict[str, list[float]]:
    parameters = _validate_parameters(config, base_parameters)
    if model_fingerprint(config, parameters) != base_fingerprint:
        raise LearnerError("Base model fingerprint mismatch.")
    parent_capsule: str | None = None
    for sequence, capsule in enumerate(capsules, start=1):
        value = dict(capsule.payload)
        if set(value) != CAPSULE_KEYS:
            raise LearnerError("Capsule schema fields are invalid.")
        declared = value.pop("capsule_fingerprint", None)
        if declared != _fingerprint(value):
            raise LearnerError("Capsule fingerprint mismatch.")
        if (
            value.get("schema_version") != CAPSULE_SCHEMA_VERSION
            or value.get("semantic_version") != LEARNER_SEMANTIC_VERSION
            or value.get("development_state") != DEVELOPMENT_STATE
            or value.get("architecture_fingerprint") != config.fingerprint
            or value.get("base_model_fingerprint") != base_fingerprint
            or value.get("parent_capsule_fingerprint") != parent_capsule
            or value.get("composition_sequence") != sequence
            or value.get("authority") != ZERO_AUTHORITY
            or value.get("effective_experiment_identity") != expected_experiment_id
            or value.get("world_fingerprint") != expected_world_fingerprint
            or value.get("reward_policy_fingerprint") != expected_reward_policy_fingerprint
            or value.get("feature_state_contract_fingerprint") != config.state_contract_fingerprint
            or value.get("preference_contract_fingerprint") != config.preference_contract_fingerprint
            or value.get("action_space_fingerprint") != config.action_space_fingerprint
            or value.get("learning_algorithm_config_fingerprint") != config.fingerprint
            or value.get("optimizer_state") != {"status": "DESTROYED", "reason": "PLAIN_SGD_HAS_NO_PERSISTENT_STATE"}
        ):
            raise LearnerError("Capsule identity or lineage is invalid.")
        maximum = _boundary(value["maximum_evidence_boundary"])
        eligibility = _boundary(value["eligibility_boundary"])
        if not maximum < eligibility or not eligibility < current_action_boundary:
            raise LearnerError("Capsule is not strictly eligible at the action boundary.")
        if value.get("parent_composed_model_fingerprint") != model_fingerprint(config, parameters):
            raise LearnerError("Capsule parent model does not match composed lineage.")
        delta = _validate_parameters(config, value["parameter_delta"])
        parameters = {name: [left + right for left, right in zip(parameters[name], delta[name])]
                      for name in parameters}
        if value.get("composed_model_fingerprint") != model_fingerprint(config, parameters):
            raise LearnerError("Capsule composed-model fingerprint mismatch.")
        parent_capsule = str(declared)
    return parameters


class DevelopmentOnlyGruLearner:
    """Toy/proof learner. Its public surface intentionally contains no archive API."""

    def __init__(
        self, *, config: LearnerConfig, base_parameters: Mapping[str, Sequence[float]],
        base_fingerprint: str, episode_id: str, experiment_id: str,
        world_fingerprint: str, reward_policy_fingerprint: str, seed: int,
        capsules: Sequence[LearningCapsule] = (),
        action_boundary: CausalBoundary | None = None,
    ) -> None:
        self.config = config
        self.base_parameters = _validate_parameters(config, base_parameters)
        self.base_fingerprint = base_fingerprint
        self.capsules = tuple(capsules)
        if action_boundary is None:
            self.parameters = _validate_parameters(config, base_parameters)
            if model_fingerprint(config, self.parameters) != base_fingerprint:
                raise LearnerError("Base model fingerprint mismatch.")
        else:
            self.parameters = compose_capsules(
                config=config, base_parameters=base_parameters, base_fingerprint=base_fingerprint,
                capsules=capsules, current_action_boundary=action_boundary,
                expected_experiment_id=experiment_id,
                expected_world_fingerprint=world_fingerprint,
                expected_reward_policy_fingerprint=reward_policy_fingerprint,
            )
        self.episode_id = episode_id
        self.experiment_id = experiment_id
        self.world_fingerprint = world_fingerprint
        self.reward_policy_fingerprint = reward_policy_fingerprint
        self.seed = seed
        self.rng = DeterministicRng(seed)
        self.hidden = [0.0] * config.hidden_size
        self.pending: dict[str, Any] | None = None
        self.last_evidence_boundary: CausalBoundary | None = None
        self.initial_parameters = {name: list(values) for name, values in self.parameters.items()}

    def _validate_vector(self, values: Sequence[float], size: int, label: str) -> list[float]:
        result = [float(value) for value in values]
        if len(result) != size or any(not math.isfinite(value) for value in result):
            raise LearnerError(f"{label} vector is malformed.")
        return result

    def choose_action(
        self, *, state: Sequence[float], preference: Sequence[float],
        boundary: CausalBoundary,
    ) -> str:
        if self.pending is not None:
            raise LearnerError("A prior action is still awaiting causal reward.")
        if self.last_evidence_boundary is not None and boundary <= self.last_evidence_boundary:
            raise LearnerError("Action boundary must be strictly after learned evidence.")
        x = self._validate_vector(state, self.config.state_size, "State") + self._validate_vector(
            preference, self.config.preference_size, "Preference")
        h0 = list(self.hidden)
        h = self.config.hidden_size
        i = len(x)
        def gate(prefix: str) -> list[float]:
            wx = _matrix_vector(self.parameters[f"W{prefix}"], h, i, x)
            uh = _matrix_vector(self.parameters[f"U{prefix}"], h, h, h0)
            return [_sigmoid(wx[n] + uh[n] + self.parameters[f"b{prefix}"][n]) for n in range(h)]
        z = gate("z")
        r = gate("r")
        wxn = _matrix_vector(self.parameters["Wn"], h, i, x)
        uhn = _matrix_vector(self.parameters["Un"], h, h, [r[n] * h0[n] for n in range(h)])
        nvec = [math.tanh(wxn[n] + uhn[n] + self.parameters["bn"][n]) for n in range(h)]
        self.hidden = [(1.0 - z[n]) * nvec[n] + z[n] * h0[n] for n in range(h)]
        logits = _matrix_vector(self.parameters["Wo"], len(self.config.action_tokens), h, self.hidden)
        logits = [value + self.parameters["bo"][n] for n, value in enumerate(logits)]
        probabilities = _softmax(logits)
        draw = self.rng.uniform()
        cumulative = 0.0
        selected = len(probabilities) - 1
        for index, probability in enumerate(probabilities):
            cumulative += probability
            if draw < cumulative:
                selected = index
                break
        self.pending = {"x": x, "h0": h0, "h": list(self.hidden), "z": z, "r": r,
                        "n": nvec, "probabilities": probabilities, "selected": selected,
                        "action_boundary": _boundary_payload(boundary)}
        return self.config.action_tokens[selected]

    def learn(self, *, reward: float, completion_boundary: CausalBoundary) -> None:
        if self.pending is None:
            raise LearnerError("No causally pending action exists.")
        action_boundary = _boundary(self.pending["action_boundary"])
        if completion_boundary <= action_boundary:
            raise LearnerError("Reward evidence must be strictly after the action boundary.")
        reward = float(reward)
        if not math.isfinite(reward):
            raise LearnerError("Reward must be finite.")
        p = self.pending
        hsize = self.config.hidden_size
        isize = self.config.state_size + self.config.preference_size
        actions = len(self.config.action_tokens)
        dlogits = [-reward * value for value in p["probabilities"]]
        dlogits[p["selected"]] += reward
        old_wo = list(self.parameters["Wo"])
        lr = self.config.learning_rate
        for action in range(actions):
            for hidden in range(hsize):
                self.parameters["Wo"][action * hsize + hidden] += lr * dlogits[action] * p["h"][hidden]
            self.parameters["bo"][action] += lr * dlogits[action]
        dh = [sum(old_wo[action * hsize + hidden] * dlogits[action] for action in range(actions))
              for hidden in range(hsize)]
        dn = [dh[j] * (1.0 - p["z"][j]) * (1.0 - p["n"][j] ** 2) for j in range(hsize)]
        dz = [dh[j] * (p["h0"][j] - p["n"][j]) * p["z"][j] * (1.0 - p["z"][j])
              for j in range(hsize)]
        old_un = list(self.parameters["Un"])
        drh = [sum(old_un[row * hsize + col] * dn[row] for row in range(hsize))
               for col in range(hsize)]
        dr = [drh[j] * p["h0"][j] * p["r"][j] * (1.0 - p["r"][j]) for j in range(hsize)]
        for prefix, gradient, recurrent_input in (
            ("n", dn, [p["r"][j] * p["h0"][j] for j in range(hsize)]),
            ("z", dz, p["h0"]), ("r", dr, p["h0"]),
        ):
            for row in range(hsize):
                for col in range(isize):
                    self.parameters[f"W{prefix}"][row * isize + col] += lr * gradient[row] * p["x"][col]
                for col in range(hsize):
                    self.parameters[f"U{prefix}"][row * hsize + col] += lr * gradient[row] * recurrent_input[col]
                self.parameters[f"b{prefix}"][row] += lr * gradient[row]
        self.last_evidence_boundary = completion_boundary
        self.pending = None

    def destroy_episode_memory(self) -> None:
        self.parameters = {name: list(values) for name, values in self.initial_parameters.items()}
        self.hidden = [0.0] * self.config.hidden_size
        self.pending = None
        self.rng = DeterministicRng(self.seed)
        self.last_evidence_boundary = None

    def create_capsule(self, *, eligibility_boundary: CausalBoundary, code_revision: str,
                       environment_fingerprint: str) -> LearningCapsule:
        if self.pending is not None or self.last_evidence_boundary is None:
            raise LearnerError("Capsule requires a reconciled episode learning boundary.")
        if not self.last_evidence_boundary < eligibility_boundary:
            raise LearnerError("Capsule eligibility must be strictly after maximum evidence.")
        parent_capsule = self.capsules[-1].fingerprint if self.capsules else None
        core = {
            "schema_version": CAPSULE_SCHEMA_VERSION,
            "semantic_version": LEARNER_SEMANTIC_VERSION,
            "development_state": DEVELOPMENT_STATE,
            "capsule_identity": _fingerprint({
                "base": self.base_fingerprint, "parent": parent_capsule,
                "episode": self.episode_id, "experiment": self.experiment_id,
                "world": self.world_fingerprint, "reward": self.reward_policy_fingerprint,
                "evidence": _boundary_payload(self.last_evidence_boundary),
                "eligibility": _boundary_payload(eligibility_boundary),
            }),
            "base_model_fingerprint": self.base_fingerprint,
            "parent_capsule_fingerprint": parent_capsule,
            "composition_sequence": len(self.capsules) + 1,
            "parent_composed_model_fingerprint": model_fingerprint(self.config, self.initial_parameters),
            "composed_model_fingerprint": model_fingerprint(self.config, self.parameters),
            "maximum_evidence_boundary": _boundary_payload(self.last_evidence_boundary),
            "eligibility_boundary": _boundary_payload(eligibility_boundary),
            "episode_identity": self.episode_id,
            "effective_experiment_identity": self.experiment_id,
            "world_fingerprint": self.world_fingerprint,
            "reward_policy_fingerprint": self.reward_policy_fingerprint,
            "feature_state_contract_fingerprint": self.config.state_contract_fingerprint,
            "preference_contract_fingerprint": self.config.preference_contract_fingerprint,
            "action_space_fingerprint": self.config.action_space_fingerprint,
            "learning_algorithm_config_fingerprint": self.config.fingerprint,
            "architecture_fingerprint": self.config.fingerprint,
            "parameter_delta": {name: [current - initial for current, initial in zip(values, self.initial_parameters[name])]
                                for name, values in self.parameters.items()},
            "optimizer_state": {"status": "DESTROYED", "reason": "PLAIN_SGD_HAS_NO_PERSISTENT_STATE"},
            "deterministic_composition": "UNIQUE_PARENT_CHAIN_ASCENDING_SEQUENCE_ADDITIVE_DELTA_V1",
            "rng_seed": self.seed,
            "rng_state_at_seal": self.rng.state,
            "code_revision": code_revision,
            "environment_fingerprint": environment_fingerprint,
            "authority": dict(ZERO_AUTHORITY),
        }
        return LearningCapsule({**core, "capsule_fingerprint": _fingerprint(core)})

    def checkpoint(self, directory: Path) -> str:
        core = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "semantic_version": LEARNER_SEMANTIC_VERSION,
            "development_state": DEVELOPMENT_STATE,
            "config": self.config.payload(),
            "config_fingerprint": self.config.fingerprint,
            "base_model_fingerprint": self.base_fingerprint,
            "capsule_fingerprints": [capsule.fingerprint for capsule in self.capsules],
            "episode_id": self.episode_id,
            "experiment_id": self.experiment_id,
            "world_fingerprint": self.world_fingerprint,
            "reward_policy_fingerprint": self.reward_policy_fingerprint,
            "seed": self.seed,
            "rng_state": self.rng.state,
            "parameters": self.parameters,
            "initial_parameters": self.initial_parameters,
            "hidden": self.hidden,
            "pending": self.pending,
            "last_evidence_boundary": (_boundary_payload(self.last_evidence_boundary)
                                       if self.last_evidence_boundary else None),
            "authority": dict(ZERO_AUTHORITY),
        }
        payload = {**core, "checkpoint_fingerprint": _fingerprint(core)}
        encoded = _canon(payload)
        directory = Path(directory)
        write_checksummed_state(directory / "learner_state.json", directory / "learner_state.sha256", encoded)
        return payload["checkpoint_fingerprint"]

    @classmethod
    def restore(cls, directory: Path, *, config: LearnerConfig,
                base_parameters: Mapping[str, Sequence[float]], base_fingerprint: str,
                capsules: Sequence[LearningCapsule]) -> "DevelopmentOnlyGruLearner":
        encoded = read_checksummed_state(Path(directory) / "learner_state.json",
                                         Path(directory) / "learner_state.sha256",
                                         label="Wildcard learner checkpoint")
        payload = json.loads(encoded)
        declared = payload.pop("checkpoint_fingerprint", None)
        if declared != _fingerprint(payload):
            raise LearnerError("Learner checkpoint fingerprint mismatch.")
        if (
            payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION
            or payload.get("semantic_version") != LEARNER_SEMANTIC_VERSION
            or payload.get("development_state") != DEVELOPMENT_STATE
            or payload.get("config_fingerprint") != config.fingerprint
            or payload.get("config") != config.payload()
            or payload.get("base_model_fingerprint") != base_fingerprint
            or payload.get("capsule_fingerprints") != [capsule.fingerprint for capsule in capsules]
            or payload.get("authority") != ZERO_AUTHORITY
        ):
            raise LearnerError("Learner checkpoint identity is invalid.")
        learner = cls(config=config, base_parameters=base_parameters,
                      base_fingerprint=base_fingerprint, episode_id=payload["episode_id"],
                      experiment_id=payload["experiment_id"], world_fingerprint=payload["world_fingerprint"],
                      reward_policy_fingerprint=payload["reward_policy_fingerprint"],
                      seed=int(payload["seed"]), capsules=capsules)
        learner.parameters = _validate_parameters(config, payload["parameters"])
        learner.initial_parameters = _validate_parameters(config, payload["initial_parameters"])
        expected_initial = (base_fingerprint if not capsules
                            else capsules[-1].payload.get("composed_model_fingerprint"))
        if model_fingerprint(config, learner.initial_parameters) != expected_initial:
            raise LearnerError("Learner checkpoint initial model does not match capsule lineage.")
        learner.hidden = learner._validate_vector(payload["hidden"], config.hidden_size, "Hidden")
        learner.pending = payload["pending"]
        learner.rng = DeterministicRng(int(payload["rng_state"]))
        learner.last_evidence_boundary = (_boundary(payload["last_evidence_boundary"])
                                          if payload["last_evidence_boundary"] else None)
        return learner
