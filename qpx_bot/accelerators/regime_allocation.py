"""Fixed, causal Regime Allocation V1 research accelerator."""
from __future__ import annotations
import hashlib,json,math
from dataclasses import asdict,dataclass
from datetime import datetime
from pathlib import Path
VERSION="1.0.0";BOUNDARIES=(20.0,25.0,32.0);REGIMES=("CALM","TRANSITION","ELEVATED","EXTREME")
BASELINE_QDTE_WEIGHT=.125;BASELINE_SWING_WEIGHT=.875
POLICY_WEIGHTS={"stress_income_shift_v1":(.125,.125,.25,.40),"calm_swing_shift_v1":(.05,.125,.125,.125),"two_sided_ladder_v1":(.05,.125,.25,.40)}
@dataclass(frozen=True,slots=True)
class RegimeAllocationConfig:
 enabled:bool;accelerator_version:str;configuration_version:str;policy_identity:str|None;boundaries:tuple[float,...]=BOUNDARIES;qdte_weights:tuple[float,...]=()
 def validate(self):
  if type(self.enabled) is not bool or self.accelerator_version!=VERSION:raise ValueError("Unsupported Regime Allocation version/configuration")
  if self.boundaries!=BOUNDARIES:raise ValueError("Regime boundaries are immutable")
  if not self.enabled:
   if self.policy_identity is not None or self.qdte_weights:raise ValueError("Disabled foundation cannot declare a policy")
   return
  if self.policy_identity not in POLICY_WEIGHTS or self.configuration_version!=self.policy_identity:raise ValueError("Unknown Regime Allocation policy")
  if self.qdte_weights!=POLICY_WEIGHTS[self.policy_identity] or len(self.qdte_weights)!=4:raise ValueError("Regime weights are immutable and complete")
  if any(not 0<=x<=1 or not math.isclose(x+(1-x),1.0) for x in self.qdte_weights):raise ValueError("Invalid allocation weights")
 @property
 def fingerprint(self):
  payload=asdict(self) if self.enabled else {"enabled":self.enabled,"accelerator_version":self.accelerator_version,"configuration_version":self.configuration_version,"policy_identity":self.policy_identity}
  return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
@dataclass(frozen=True,slots=True)
class RegimeAllocationContext:
 decision_timestamp:datetime;vix_observation_timestamp:datetime;previous_completed_session_vix_close:float;current_qdte_target:float;current_actual_qdte_weight:float;swing_cash:float;swing_market_value:float;investable_equity:float;weekly_rebalance_identity:str="THURSDAY_WEEKLY_REBALANCE"
 def __post_init__(self):
  if self.decision_timestamp.tzinfo is None or self.vix_observation_timestamp.tzinfo is None or self.vix_observation_timestamp>=self.decision_timestamp:raise ValueError("VIX must be from a previous completed session")
  for name in ("previous_completed_session_vix_close","current_qdte_target","current_actual_qdte_weight","swing_cash","swing_market_value","investable_equity"):
   v=getattr(self,name)
   if type(v) not in (int,float) or not math.isfinite(v) or v<0:raise ValueError(f"Invalid {name}")
  if self.previous_completed_session_vix_close<=0 or self.investable_equity<=0 or not self.weekly_rebalance_identity:raise ValueError("Invalid causal context")
def regime_for_vix(v):
 if type(v) not in (int,float) or not math.isfinite(v) or v<=0:raise ValueError("Invalid previous-session VIX")
 if v<20:return "CALM"
 if v<25:return "TRANSITION"
 if v<=32:return "ELEVATED"
 return "EXTREME"
@dataclass(frozen=True,slots=True)
class RegimeAllocationDecision:
 accelerator_version:str;configuration_fingerprint:str;policy_identity:str|None;decision_timestamp:datetime;vix_observation_timestamp:datetime;causal_vix_value:float;regime_identity:str;prior_target_qdte_weight:float;proposed_target_qdte_weight:float;proposed_target_swing_weight:float;rebalance_eligibility:bool;weekly_rebalance_identity:str;allocator_action:str;qdte_market_value_traded:float|None;resulting_actual_qdte_weight:float|None;decision_id:str
class RegimeAllocationV1:
 def __init__(self,c):c.validate();self.config=c
 def decide(self,c):
  regime=regime_for_vix(c.previous_completed_session_vix_close) if self.config.enabled else "DISABLED_NO_REGIME";target=POLICY_WEIGHTS[self.config.policy_identity][REGIMES.index(regime)] if self.config.enabled else BASELINE_QDTE_WEIGHT
  core={"accelerator_version":VERSION,"configuration_fingerprint":self.config.fingerprint,"policy_identity":self.config.policy_identity,"decision_timestamp":c.decision_timestamp.isoformat(),"vix_observation_timestamp":c.vix_observation_timestamp.isoformat(),"causal_vix_value":c.previous_completed_session_vix_close,"regime_identity":regime,"prior_target_qdte_weight":c.current_qdte_target,"proposed_target_qdte_weight":target,"proposed_target_swing_weight":1-target,"rebalance_eligibility":self.config.enabled,"weekly_rebalance_identity":c.weekly_rebalance_identity,"allocator_action":"TARGET_PROPOSED" if self.config.enabled else "DISABLED_EXACT_NO_OP","qdte_market_value_traded":None,"resulting_actual_qdte_weight":None}
  return RegimeAllocationDecision(**{k:v for k,v in core.items() if not k.endswith("timestamp")},decision_timestamp=c.decision_timestamp,vix_observation_timestamp=c.vix_observation_timestamp,decision_id=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":")).encode()).hexdigest())
def load_regime_allocation_config(path:Path):
 p=json.loads(path.read_text());p["boundaries"]=tuple(p.get("boundaries",BOUNDARIES));p["qdte_weights"]=tuple(p.get("qdte_weights",()));c=RegimeAllocationConfig(**p);c.validate();return c
