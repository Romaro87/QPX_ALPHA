"""Validated immutable registry for Shadow Matrix V1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from qpx_bot.shadow_matrix.models import AcceleratorSnapshot, ShadowConfiguration, ShadowRole, freeze_json


DEFAULT_CONFIG_PATH = Path(__file__).with_name("configs") / "shadow_matrix_v1.json"
EXPECTED_IDS = (
    "permanent_control",
    "fixed_25", "dynamic_25",
    "fixed_40", "dynamic_40",
    "fixed_60", "dynamic_60",
    "fixed_90", "dynamic_90",
)


@dataclass(frozen=True, slots=True)
class ShadowRegistry:
    configurations: tuple[ShadowConfiguration, ...]
    provenance: tuple[tuple[str, str], ...]
    matrix_version: str
    automatic_promotion: bool

    def __post_init__(self) -> None:
        if not self.matrix_version.strip() or self.automatic_promotion is not False:
            raise ValueError("Shadow Matrix requires a version and forbids automatic promotion.")
        ids = tuple(item.shadow_id for item in self.configurations)
        if ids != EXPECTED_IDS:
            raise ValueError(f"Shadow Matrix V1 IDs/order must be exactly {EXPECTED_IDS!r}.")
        if len(set(ids)) != len(ids):
            raise ValueError("Shadow IDs must be unique.")
        self._validate_pairs()

    def _validate_pairs(self) -> None:
        definitions = {item.shadow_id: item for item in self.configurations}
        for cap in (25, 40, 60, 90):
            fixed = definitions[f"fixed_{cap}"]
            dynamic = definitions[f"dynamic_{cap}"]
            if fixed.hard_notional_cap != cap / 100 or dynamic.hard_notional_cap != cap / 100:
                raise ValueError(f"{cap}% pair does not use its declared hard cap.")
            same_fields = (
                "strategy_id", "strategy_reference_commit", "starting_state_profile",
                "starting_qdte_value", "starting_swing_cash", "starting_total_equity",
                "hard_notional_cap",
            )
            if any(getattr(fixed, key) != getattr(dynamic, key) for key in same_fields):
                raise ValueError(f"{cap}% pair differs outside accelerator configuration.")
            fixed_accelerator = fixed.accelerators[0]
            dynamic_accelerator = dynamic.accelerators[0]
            if fixed_accelerator.enabled or not dynamic_accelerator.enabled:
                raise ValueError(f"{cap}% pair must have fixed OFF and dynamic ON.")
            if fixed_accelerator.name != dynamic_accelerator.name:
                raise ValueError(f"{cap}% pair accelerator identity differs.")

    @property
    def by_id(self) -> Mapping[str, ShadowConfiguration]:
        return MappingProxyType({item.shadow_id: item for item in self.configurations})


def load_registry(path: Path = DEFAULT_CONFIG_PATH) -> ShadowRegistry:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported Shadow Matrix registry schema.")
    configurations = []
    for item in payload["shadows"]:
        accelerators = tuple(
            AcceleratorSnapshot(
                name=accelerator["name"],
                enabled=accelerator["enabled"],
                algorithm_version=accelerator["algorithm_version"],
                configuration_version=accelerator["configuration_version"],
                configuration_fingerprint=accelerator["configuration_fingerprint"],
                parameters=freeze_json({
                    "risk_tiers": payload["accelerator_algorithms"]["dynamic_sizing_v1"]["risk_tiers"],
                    "maximum_position_notional_fraction": item["hard_notional_cap"],
                    "reduction_only": True,
                }),
            )
            for accelerator in item["accelerators"]
        )
        configurations.append(ShadowConfiguration(
            shadow_id=item["shadow_id"],
            role=ShadowRole(item["role"]),
            strategy_id=item["strategy_id"],
            strategy_reference_commit=item["strategy_reference_commit"],
            starting_state_profile=item["starting_state_profile"],
            starting_qdte_value=item["starting_qdte_value"],
            starting_swing_cash=item["starting_swing_cash"],
            starting_total_equity=item["starting_total_equity"],
            hard_notional_cap=item["hard_notional_cap"],
            accelerators=accelerators,
            governance_identity=item["governance_identity"],
        ))
    provenance = tuple(sorted(payload["provenance"].items()))
    return ShadowRegistry(
        tuple(configurations), provenance, payload["matrix_version"],
        payload["automatic_promotion"],
    )
