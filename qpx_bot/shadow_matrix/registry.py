"""Validated immutable registry for the 17-Shadow Pyramiding V1 matrix."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from qpx_bot.accelerators.dynamic_sizing import load_dynamic_sizing_config
from qpx_bot.accelerators.pyramiding import load_pyramiding_config
from qpx_bot.accelerators.capacity_arbitration import CapacityArbitrationConfig, POLICIES
from qpx_bot.shadow_matrix.models import AcceleratorSnapshot,ShadowConfiguration,ShadowRole,canonical_hash,freeze_json
DEFAULT_CONFIG_PATH=Path(__file__).with_name("configs")/"shadow_matrix_v1.json"
PYRAMID_CONFIG_PATH=Path(__file__).with_name("configs")/"pyramiding_shadows_v1.json"
ARBITRATION_CONFIG_PATH=Path(__file__).with_name("configs")/"capacity_arbitration_shadows_v1.json"
LEGACY_IDS=("permanent_control","fixed_25","dynamic_25","fixed_40","dynamic_40","fixed_60","dynamic_60","fixed_90","dynamic_90")
PYRAMID_IDS=("pyramid_25","pyramid_40","pyramid_60","pyramid_90","dynamic_pyramid_25","dynamic_pyramid_40","dynamic_pyramid_60","dynamic_pyramid_90")
ARBITRATION_IDS=tuple(f"{policy}_{cap}" for cap in (25,40,60,90) for policy in ("frozen_order","breakout_strength","trend_strength","volume_confirmation"))
EXPECTED_IDS=LEGACY_IDS+PYRAMID_IDS+ARBITRATION_IDS
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
   fixed=d[f"fixed_{cap}"]
   for policy in ("frozen_order","breakout_strength","trend_strength","volume_confirmation"):
    item=d[f"{policy}_{cap}"]
    if item.hard_notional_cap!=fixed.hard_notional_cap:raise ValueError("Arbitration cap differs from matching fixed control.")
    if any(getattr(item,field)!=getattr(fixed,field) for field in ("strategy_id","strategy_reference_commit","starting_state_profile","starting_qdte_value","starting_swing_cash","starting_total_equity")):raise ValueError("Arbitration Shadow differs outside policy identity.")
    enabled={a.name:a.enabled for a in item.accelerators}
    if enabled!={"dynamic_sizing":False,"pyramiding":False,"capacity_arbitration":True}:raise ValueError("Arbitration Shadow crossed accelerator boundaries.")
  for cap in (25,40,60,90):
   names=(f"fixed_{cap}",f"dynamic_{cap}",f"pyramid_{cap}",f"dynamic_pyramid_{cap}")
   if any(d[n].hard_notional_cap!=cap/100 for n in names):raise ValueError("Hard-cap family mismatch.")
   immutable_fields=("strategy_id","strategy_reference_commit","starting_state_profile","starting_qdte_value","starting_swing_cash","starting_total_equity","hard_notional_cap")
   for name in names:
    if any(getattr(d[name],field)!=getattr(d[f"fixed_{cap}"],field) for field in immutable_fields):raise ValueError("Shadow family differs outside accelerators.")
   enabled={n:{a.name:a.enabled for a in d[n].accelerators} for n in names}
   expected={names[0]:{"dynamic_sizing":False,"pyramiding":False,"capacity_arbitration":False},names[1]:{"dynamic_sizing":True,"pyramiding":False,"capacity_arbitration":False},names[2]:{"dynamic_sizing":False,"pyramiding":True,"capacity_arbitration":False},names[3]:{"dynamic_sizing":True,"pyramiding":True,"capacity_arbitration":False}}
   if enabled!=expected:raise ValueError("Accelerator combination matrix differs.")
 @property
 def by_id(self)->Mapping[str,ShadowConfiguration]:return MappingProxyType({x.shadow_id:x for x in self.configurations})
 @property
 def dispatch_order(self):return tuple(x.shadow_id for x in self.configurations)
 @property
 def fingerprint(self):return canonical_hash({"configurations":[x.as_dict() for x in self.configurations],"provenance":dict(self.provenance),"matrix_version":self.matrix_version,"automatic_promotion":self.automatic_promotion})

def load_registry(path:Path=DEFAULT_CONFIG_PATH)->ShadowRegistry:
 root=Path(__file__).parents[1]; p=json.loads(path.read_text()); paired=json.loads((root/"accelerators/configs/dynamic_sizing_v1_paired_caps.json").read_text()); base=load_dynamic_sizing_config(root/"accelerators/configs/dynamic_sizing_v1.json"); pyramid=load_pyramiding_config(root/"accelerators/configs/pyramiding_v1.json"); extension=json.loads(PYRAMID_CONFIG_PATH.read_text()); arbitration_extension=json.loads(ARBITRATION_CONFIG_PATH.read_text())
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
 def arbitration_snapshot(policy,enabled):
  config=CapacityArbitrationConfig(policy);return AcceleratorSnapshot("capacity_arbitration",enabled,config.policy_version,policy,config.fingerprint,freeze_json({"policy":policy,"no_tunable_coefficients":True}))
 configs=[]
 for item in p["shadows"]:
  acc=(dynamic_snapshot(item,item["accelerators"][0]),pyramid_snapshot(False),arbitration_snapshot("hash_control",False)); configs.append(ShadowConfiguration(item["shadow_id"],ShadowRole(item["role"]),item["strategy_id"],item["strategy_reference_commit"],item["starting_state_profile"],item["starting_qdte_value"],item["starting_swing_cash"],item["starting_total_equity"],item["hard_notional_cap"],acc,item["governance_identity"]))
 base_by={x.shadow_id:x for x in configs}
 for definition in extension["shadows"]:
  cap=round(definition["cap"]*100); source=base_by[f"dynamic_{cap}" if definition["dynamic_sizing"] else f"fixed_{cap}"]; configs.append(ShadowConfiguration(definition["shadow_id"],ShadowRole.RESEARCH,source.strategy_id,source.strategy_reference_commit,source.starting_state_profile,source.starting_qdte_value,source.starting_swing_cash,source.starting_total_equity,source.hard_notional_cap,(source.accelerators[0],pyramid_snapshot(True),arbitration_snapshot("hash_control",False)),definition["governance_identity"]))
 for definition in arbitration_extension["shadows"]:
  cap=round(definition["cap"]*100);source=base_by[f"fixed_{cap}"];policy=definition["policy"];configs.append(ShadowConfiguration(definition["shadow_id"],ShadowRole.RESEARCH,source.strategy_id,source.strategy_reference_commit,source.starting_state_profile,source.starting_qdte_value,source.starting_swing_cash,source.starting_total_equity,source.hard_notional_cap,(source.accelerators[0],pyramid_snapshot(False),arbitration_snapshot(policy,True)),definition["shadow_id"].upper()+"_RESEARCH"))
 return ShadowRegistry(tuple(configs),tuple(sorted(p["provenance"].items())),p["matrix_version"]+"-pyramiding-v1-capacity-arbitration-v1",p["automatic_promotion"])
