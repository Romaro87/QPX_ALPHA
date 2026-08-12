"""Validated immutable registry for Shadow Matrix V1."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from qpx_bot.accelerators.dynamic_sizing import load_dynamic_sizing_config
from qpx_bot.shadow_matrix.models import AcceleratorSnapshot,ShadowConfiguration,ShadowRole,canonical_hash,freeze_json,thaw_json
DEFAULT_CONFIG_PATH=Path(__file__).with_name("configs")/"shadow_matrix_v1.json"
EXPECTED_IDS=("permanent_control","fixed_25","dynamic_25","fixed_40","dynamic_40","fixed_60","dynamic_60","fixed_90","dynamic_90")
@dataclass(frozen=True,slots=True)
class ShadowRegistry:
 configurations:tuple[ShadowConfiguration,...]; provenance:tuple[tuple[str,str],...]; matrix_version:str; automatic_promotion:bool
 def __post_init__(self):
  if not self.matrix_version.strip() or self.automatic_promotion is not False: raise ValueError("Shadow Matrix requires a version and forbids automatic promotion.")
  if tuple(c.shadow_id for c in self.configurations)!=EXPECTED_IDS: raise ValueError(f"Shadow Matrix V1 IDs/order must be exactly {EXPECTED_IDS!r}.")
  self._validate_pairs()
 def _validate_pairs(self):
  d={c.shadow_id:c for c in self.configurations}
  for cap in (25,40,60,90):
   f,x=d[f"fixed_{cap}"],d[f"dynamic_{cap}"]
   if f.hard_notional_cap!=cap/100 or x.hard_notional_cap!=cap/100: raise ValueError("Pair cap mismatch.")
   for k in ("strategy_id","strategy_reference_commit","starting_state_profile","starting_qdte_value","starting_swing_cash","starting_total_equity","hard_notional_cap"):
    if getattr(f,k)!=getattr(x,k): raise ValueError(f"{cap}% pair differs outside accelerator configuration.")
   if f.accelerators[0].enabled or not x.accelerators[0].enabled: raise ValueError("Fixed/dynamic enable state invalid.")
 @property
 def by_id(self)->Mapping[str,ShadowConfiguration]: return MappingProxyType({c.shadow_id:c for c in self.configurations})
 @property
 def dispatch_order(self): return tuple(c.shadow_id for c in self.configurations)
 @property
 def fingerprint(self): return canonical_hash({"configurations":[c.as_dict() for c in self.configurations],"provenance":dict(self.provenance),"matrix_version":self.matrix_version,"automatic_promotion":self.automatic_promotion})

def load_registry(path:Path=DEFAULT_CONFIG_PATH)->ShadowRegistry:
 p=json.loads(path.read_text()); base=load_dynamic_sizing_config(Path(__file__).parents[1]/"accelerators/configs/dynamic_sizing_v1.json"); paired=json.loads((Path(__file__).parents[1]/"accelerators/configs/dynamic_sizing_v1_paired_caps.json").read_text())
 authoritative=[{"upper_bound":t.upper_bound,"multiplier":t.multiplier} for t in base.risk_tiers]
 if p["accelerator_algorithms"]["dynamic_sizing_v1"]["risk_tiers"]!=authoritative: raise ValueError("Shadow tiers differ from authoritative Dynamic Sizing V1.")
 configs=[]
 for item in p["shadows"]:
  acc=[]
  for a in item["accelerators"]:
   cap=item["hard_notional_cap"]; params={"risk_tiers":authoritative,"maximum_position_notional_fraction":cap,"reduction_only":True}
   if a["enabled"]:
    key=str(round(cap*100)); expected=paired["caps"][key]
    if a["algorithm_version"]!=base.accelerator_version or a["configuration_version"]!=expected["configuration_version"] or expected["fraction"]!=cap: raise ValueError("Shadow Dynamic configuration differs from authoritative source.")
   acc.append(AcceleratorSnapshot(a["name"],a["enabled"],a["algorithm_version"],a["configuration_version"],a["configuration_fingerprint"],freeze_json(params)))
  configs.append(ShadowConfiguration(item["shadow_id"],ShadowRole(item["role"]),item["strategy_id"],item["strategy_reference_commit"],item["starting_state_profile"],item["starting_qdte_value"],item["starting_swing_cash"],item["starting_total_equity"],item["hard_notional_cap"],tuple(acc),item["governance_identity"]))
 return ShadowRegistry(tuple(configs),tuple(sorted(p["provenance"].items())),p["matrix_version"],p["automatic_promotion"])
