"""Validated immutable registry for the 17-Shadow Pyramiding V1 matrix."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from qpx_bot.accelerators.dynamic_sizing import load_dynamic_sizing_config
from qpx_bot.accelerators.pyramiding import load_pyramiding_config
from qpx_bot.shadow_matrix.models import AcceleratorSnapshot,ShadowConfiguration,ShadowRole,canonical_hash,freeze_json
DEFAULT_CONFIG_PATH=Path(__file__).with_name("configs")/"shadow_matrix_v1.json"
PYRAMID_CONFIG_PATH=Path(__file__).with_name("configs")/"pyramiding_shadows_v1.json"
LEGACY_IDS=("permanent_control","fixed_25","dynamic_25","fixed_40","dynamic_40","fixed_60","dynamic_60","fixed_90","dynamic_90")
PYRAMID_IDS=("pyramid_25","dynamic_pyramid_25","pyramid_40","dynamic_pyramid_40","pyramid_60","dynamic_pyramid_60","pyramid_90","dynamic_pyramid_90")
EXPECTED_IDS=LEGACY_IDS+PYRAMID_IDS
@dataclass(frozen=True,slots=True)
class ShadowRegistry:
 configurations:tuple[ShadowConfiguration,...]; provenance:tuple[tuple[str,str],...]; matrix_version:str; automatic_promotion:bool
 def __post_init__(self):
  if not self.matrix_version.strip() or self.automatic_promotion is not False:raise ValueError("Shadow Matrix requires a version and forbids automatic promotion.")
  if tuple(x.shadow_id for x in self.configurations)!=EXPECTED_IDS:raise ValueError(f"Shadow IDs/order must be exactly {EXPECTED_IDS!r}.")
  self._validate()
 def _validate(self):
  d={x.shadow_id:x for x in self.configurations}
  if any(a.enabled for a in d["permanent_control"].accelerators):raise ValueError("permanent_control must keep all accelerators disabled.")
  for cap in (25,40,60,90):
   names=(f"fixed_{cap}",f"dynamic_{cap}",f"pyramid_{cap}",f"dynamic_pyramid_{cap}")
   if any(d[n].hard_notional_cap!=cap/100 for n in names):raise ValueError("Hard-cap family mismatch.")
   for name in names:
    if d[name].strategy_id!=d[f"fixed_{cap}"].strategy_id or d[name].starting_state_profile!=d[f"fixed_{cap}"].starting_state_profile:raise ValueError("Shadow family differs outside accelerators.")
   enabled={n:{a.name:a.enabled for a in d[n].accelerators} for n in names}
   expected={names[0]:{"dynamic_sizing":False,"pyramiding":False},names[1]:{"dynamic_sizing":True,"pyramiding":False},names[2]:{"dynamic_sizing":False,"pyramiding":True},names[3]:{"dynamic_sizing":True,"pyramiding":True}}
   if enabled!=expected:raise ValueError("Accelerator combination matrix differs.")
 @property
 def by_id(self)->Mapping[str,ShadowConfiguration]:return MappingProxyType({x.shadow_id:x for x in self.configurations})
 @property
 def dispatch_order(self):return tuple(x.shadow_id for x in self.configurations)
 @property
 def fingerprint(self):return canonical_hash({"configurations":[x.as_dict() for x in self.configurations],"provenance":dict(self.provenance),"matrix_version":self.matrix_version,"automatic_promotion":self.automatic_promotion})

def load_registry(path:Path=DEFAULT_CONFIG_PATH)->ShadowRegistry:
 root=Path(__file__).parents[1]; p=json.loads(path.read_text()); paired=json.loads((root/"accelerators/configs/dynamic_sizing_v1_paired_caps.json").read_text()); base=load_dynamic_sizing_config(root/"accelerators/configs/dynamic_sizing_v1.json"); pyramid=load_pyramiding_config(root/"accelerators/configs/pyramiding_v1.json"); extension=json.loads(PYRAMID_CONFIG_PATH.read_text())
 tiers=[{"upper_bound":x.upper_bound,"multiplier":x.multiplier} for x in base.risk_tiers]
 if p["accelerator_algorithms"]["dynamic_sizing_v1"]["risk_tiers"]!=tiers:raise ValueError("Shadow tiers differ from authoritative Dynamic Sizing V1.")
 if extension["configuration_fingerprint"]!=pyramid.fingerprint:raise ValueError("Pyramiding registry fingerprint differs from authoritative config.")
 def dynamic_snapshot(item,raw):
  cap=item["hard_notional_cap"]
  if raw["enabled"]:
   expected=paired["caps"][str(round(cap*100))]
   if raw["algorithm_version"]!=base.accelerator_version or raw["configuration_version"]!=expected["configuration_version"]:raise ValueError("Dynamic source identity differs.")
  return AcceleratorSnapshot(raw["name"],raw["enabled"],raw["algorithm_version"],raw["configuration_version"],raw["configuration_fingerprint"],freeze_json({"risk_tiers":tiers,"maximum_position_notional_fraction":cap,"reduction_only":True}))
 def pyramid_snapshot(enabled):return AcceleratorSnapshot("pyramiding",enabled,pyramid.accelerator_version,pyramid.configuration_version,load_pyramiding_config(root/"accelerators/configs/pyramiding_v1.json",enabled=enabled).fingerprint,freeze_json({"trigger_atr_multiple":1.0,"addition_fraction":0.5,"maximum_additions":2,"never_average_down":True}))
 configs=[]
 for item in p["shadows"]:
  acc=(dynamic_snapshot(item,item["accelerators"][0]),pyramid_snapshot(False)); configs.append(ShadowConfiguration(item["shadow_id"],ShadowRole(item["role"]),item["strategy_id"],item["strategy_reference_commit"],item["starting_state_profile"],item["starting_qdte_value"],item["starting_swing_cash"],item["starting_total_equity"],item["hard_notional_cap"],acc,item["governance_identity"]))
 base_by={x.shadow_id:x for x in configs}
 for definition in extension["shadows"]:
  cap=round(definition["cap"]*100); source=base_by[f"dynamic_{cap}" if definition["dynamic_sizing"] else f"fixed_{cap}"]; configs.append(ShadowConfiguration(definition["shadow_id"],ShadowRole.RESEARCH,source.strategy_id,source.strategy_reference_commit,source.starting_state_profile,source.starting_qdte_value,source.starting_swing_cash,source.starting_total_equity,source.hard_notional_cap,(source.accelerators[0],pyramid_snapshot(True)),definition["governance_identity"]))
 return ShadowRegistry(tuple(configs),tuple(sorted(p["provenance"].items())),p["matrix_version"]+"-pyramiding-v1",p["automatic_promotion"])
