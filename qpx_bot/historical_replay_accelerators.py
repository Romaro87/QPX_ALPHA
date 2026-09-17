"""Configuration-bound accelerator bundle for causal historical replay."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any, Mapping

from qpx_bot.accelerators.dynamic_sizing import (
    DynamicSizingConfig,
    DynamicSizingV1,
    load_dynamic_sizing_config,
)
from qpx_bot.accelerators.profit_recycling import (
    ProfitRecyclingConfig,
    ProfitRecyclingRuntime,
    ProfitSourceLedger,
    load_profit_recycling_config,
)
from qpx_bot.accelerators.pyramiding import (
    PyramidingConfig,
    PyramidingV1,
    load_pyramiding_config,
)
from qpx_bot.accelerators.regime_allocation import (
    RegimeAllocationConfig,
    RegimeAllocationV1,
    load_regime_allocation_config,
)
from qpx_bot.historical_paper_replay import ReplayConfigurationError


@dataclass(frozen=True, slots=True)
class HistoricalReplayAccelerators:
    profit_recycling_config: ProfitRecyclingConfig
    dynamic_sizing_config: DynamicSizingConfig
    pyramiding_config: PyramidingConfig
    regime_allocation_config: RegimeAllocationConfig

    @property
    def dynamic_sizing(self) -> DynamicSizingV1:
        return DynamicSizingV1(self.dynamic_sizing_config)

    @property
    def pyramiding(self) -> PyramidingV1:
        return PyramidingV1(self.pyramiding_config)

    @property
    def regime_allocation(self) -> RegimeAllocationV1:
        return RegimeAllocationV1(self.regime_allocation_config)

    @property
    def fingerprints(self) -> dict[str, str]:
        return {
            "profit_recycling": self.profit_recycling_config.fingerprint,
            "dynamic_sizing": self.dynamic_sizing_config.fingerprint,
            "pyramiding": self.pyramiding_config.fingerprint,
            "regime_allocation": self.regime_allocation_config.fingerprint,
        }


def _source(root: Path, raw: Mapping[str, Any], name: str) -> Path:
    path = (root / str(raw["configuration_path"])).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ReplayConfigurationError(f"{name} configuration escapes repository root.")
    return path


def load_historical_replay_accelerators(
    payload: Mapping[str, Any], *, root: Path, sha256: Any,
) -> HistoricalReplayAccelerators | None:
    """Load and bind the exact accelerator evidence declared by config V2."""
    raw = payload.get("accelerators")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ReplayConfigurationError("Accelerator configuration is malformed.")
    for name, item in raw.items():
        if not isinstance(item, Mapping):
            raise ReplayConfigurationError(f"{name} accelerator configuration is malformed.")
        path = _source(root, item, name)
        if sha256(path) != item["source_file_sha256"]:
            raise ReplayConfigurationError(f"{name} accelerator source checksum mismatch.")

    profit = load_profit_recycling_config(_source(root, raw["profit_recycling"], "profit_recycling"))
    dynamic_raw = raw["dynamic_sizing"]
    dynamic_source = load_dynamic_sizing_config(_source(root, dynamic_raw, "dynamic_sizing"))
    paired_path = (root / str(dynamic_raw["paired_caps_path"])).resolve()
    if not paired_path.is_relative_to(root.resolve()) or sha256(paired_path) != dynamic_raw["paired_caps_file_sha256"]:
        raise ReplayConfigurationError("Dynamic Sizing paired-cap evidence checksum mismatch.")
    paired = json.loads(paired_path.read_text(encoding="utf-8"))
    if (
        paired.get("algorithm") != "dynamic_sizing"
        or paired.get("source_configuration") != Path(dynamic_raw["configuration_path"]).name
        or paired.get("only_treatment_variable") != "maximum_position_notional_fraction"
    ):
        raise ReplayConfigurationError("Dynamic Sizing paired-cap contract is incompatible.")
    cap = paired.get("caps", {}).get(str(dynamic_raw["paired_cap"]))
    if not isinstance(cap, Mapping) or float(cap.get("fraction", -1)) != 0.90:
        raise ReplayConfigurationError("Dynamic Sizing 90% paired cap is absent.")
    dynamic = replace(
        dynamic_source,
        configuration_version=str(cap["configuration_version"]),
        maximum_position_notional_fraction=float(cap["fraction"]),
    )
    dynamic.validate()
    pyramid = load_pyramiding_config(_source(root, raw["pyramiding"], "pyramiding"))
    regime = load_regime_allocation_config(_source(root, raw["regime_allocation"], "regime_allocation"))
    bundle = HistoricalReplayAccelerators(profit, dynamic, pyramid, regime)
    for name, fingerprint in bundle.fingerprints.items():
        if fingerprint != raw[name]["configuration_fingerprint"]:
            raise ReplayConfigurationError(f"{name} accelerator fingerprint mismatch.")
    return bundle


def restore_profit_runtime(
    config: ProfitRecyclingConfig, starting_capital: float,
    ledger: Mapping[str, Any],
) -> ProfitRecyclingRuntime:
    runtime = ProfitRecyclingRuntime(config, starting_capital)
    runtime.ledger = ProfitSourceLedger.from_dict(ledger)
    return runtime
