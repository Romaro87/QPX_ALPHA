"""Causal Regime Allocation V1 foundation; enabled policy intentionally undeclared."""
from __future__ import annotations
import hashlib, json, math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
BASELINE_QDTE_WEIGHT=.125; BASELINE_SWING_WEIGHT=.875
@dataclass(frozen=True,slots=True)
class RegimeAllocationConfig:
 enabled:bool; accelerator_version:str; configuration_version:str; policy_identity:str|None
 def validate(self):
  if type(self.enabled) is not bool: raise ValueError("enabled must be boolean")
  if self.accelerator_version!="1.0.0" or not self.configuration_version.strip(): raise ValueError("invalid V1 identity")
  if self.enabled: raise ValueError("ENABLED_POLICY_NOT_DECLARED_OR_APPROVED")
  if self.policy_identity is not None: raise ValueError("disabled foundation cannot declare policy")
 @property
 def fingerprint(self): return hashlib.sha256(json.dumps(asdict(self),sort_keys=True,separators=(",",":")).encode()).hexdigest()
@dataclass(frozen=True,slots=True)
class RegimeAllocationContext:
 decision_timestamp:datetime; vix_observation_timestamp:datetime; previous_completed_session_vix_close:float
 current_qdte_target:float; current_actual_qdte_weight:float; swing_cash:float; swing_market_value:float; investable_equity:float
 def __post_init__(self):
  if self.decision_timestamp.tzinfo is None or self.vix_observation_timestamp.tzinfo is None or self.vix_observation_timestamp>=self.decision_timestamp: raise ValueError("VIX must be from a previous completed session")
  for name in ("previous_completed_session_vix_close","current_qdte_target","current_actual_qdte_weight","swing_cash","swing_market_value","investable_equity"):
   v=getattr(self,name)
   if type(v) not in (int,float) or not math.isfinite(v) or v<0: raise ValueError(f"invalid {name}")
  if self.previous_completed_session_vix_close<=0 or self.investable_equity<=0 or self.current_qdte_target>1 or self.current_actual_qdte_weight>1: raise ValueError("invalid causal allocation context")
@dataclass(frozen=True,slots=True)
class RegimeAllocationDecision:
 accelerator_version:str; configuration_fingerprint:str; event_timestamp:datetime; vix_observation_timestamp:datetime; causal_vix_value:float
 prior_target_qdte_weight:float; proposed_target_qdte_weight:float; prior_target_swing_weight:float; proposed_target_swing_weight:float
 regime_identity:str; rebalance_allowed:bool; allocator_action:str; decision_id:str
class RegimeAllocationV1:
 def __init__(self,config): config.validate(); self.config=config
 def decide(self,c):
  if not math.isclose(c.current_qdte_target,BASELINE_QDTE_WEIGHT,abs_tol=1e-12): raise ValueError("disabled allocator requires Candidate V1 target")
  core={"accelerator_version":self.config.accelerator_version,"configuration_fingerprint":self.config.fingerprint,"event_timestamp":c.decision_timestamp.isoformat(),"vix_observation_timestamp":c.vix_observation_timestamp.isoformat(),"causal_vix_value":c.previous_completed_session_vix_close,"prior_target_qdte_weight":.125,"proposed_target_qdte_weight":.125,"prior_target_swing_weight":.875,"proposed_target_swing_weight":.875,"regime_identity":"DISABLED_NO_REGIME","rebalance_allowed":False,"allocator_action":"DISABLED_EXACT_NO_OP"}
  return RegimeAllocationDecision(**{k:v for k,v in core.items() if not k.endswith("timestamp")},event_timestamp=c.decision_timestamp,vix_observation_timestamp=c.vix_observation_timestamp,decision_id=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":")).encode()).hexdigest())
def load_regime_allocation_config(path:Path):
 c=RegimeAllocationConfig(**json.loads(path.read_text()));c.validate();return c
