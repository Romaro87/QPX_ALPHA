"""Fixed, causal, reduction-safe Pyramiding V1 research accelerator."""
from __future__ import annotations
import hashlib,json,math
from dataclasses import asdict,dataclass
from datetime import datetime
from pathlib import Path

@dataclass(frozen=True,slots=True)
class PyramidingConfig:
 enabled:bool; accelerator_version:str; configuration_version:str
 trigger_atr_multiple:float; addition_fraction:float; maximum_additions:int
 def validate(self):
  if type(self.enabled) is not bool: raise ValueError("enabled must be boolean.")
  if not self.accelerator_version.strip() or not self.configuration_version.strip(): raise ValueError("Pyramiding versions are required.")
  if self.trigger_atr_multiple!=1.0 or self.addition_fraction!=0.5 or self.maximum_additions!=2: raise ValueError("Pyramiding V1 parameters are immutable.")
 @property
 def fingerprint(self): return hashlib.sha256(json.dumps(asdict(self),sort_keys=True,separators=(",",":")).encode()).hexdigest()

@dataclass(frozen=True,slots=True)
class PyramidingContext:
 decision_timestamp:datetime; event_id:str; event_sequence:int; symbol:str
 current_price:float; execution_price:float; current_atr:float|None; original_entry_price:float
 original_entry_shares:int; current_shares:int; additions_count:int
 pyramid_anchor_price:float; decision_time_total_equity:float; available_cash:float
 active_portfolio_risk:float; maximum_active_portfolio_risk:float
 current_position_active_risk:float; hard_notional_cap:float
 def __post_init__(self):
  if self.decision_timestamp.tzinfo is None: raise ValueError("Decision timestamp must be timezone-aware.")
  if not self.symbol.strip() or len(self.event_id)!=64 or self.event_sequence<1: raise ValueError("Causal event identity is required.")
  if type(self.original_entry_shares) is not int or self.original_entry_shares<1 or type(self.current_shares) is not int or self.current_shares<1 or type(self.additions_count) is not int or self.additions_count<0: raise ValueError("Share/addition state is invalid.")
  for name in ("current_price","execution_price","original_entry_price","pyramid_anchor_price","decision_time_total_equity","available_cash","active_portfolio_risk","maximum_active_portfolio_risk","current_position_active_risk","hard_notional_cap"):
   value=getattr(self,name)
   if type(value) not in (int,float) or not math.isfinite(value) or value<0: raise ValueError(f"{name} must be a non-negative scalar.")
  if self.current_atr is not None and (type(self.current_atr) not in (int,float) or not math.isfinite(self.current_atr) or self.current_atr<=0): raise ValueError("ATR must be positive when available.")

@dataclass(frozen=True,slots=True)
class PyramidingDecision:
 accelerator_name:str; accelerator_version:str; configuration_version:str; configuration_fingerprint:str; enabled:bool
 decision_timestamp:datetime; event_id:str; event_sequence:int; symbol:str; current_price:float; execution_price:float; atr_used:float|None
 original_entry_price:float; original_entry_shares:int; current_shares:int; additions_before:int; anchor_before:float
 target_shares:int; accepted_shares:int; accepted_notional:float; reason_codes:tuple[str,...]; decision_id:str
 @property
 def accepted(self): return self.accepted_shares>0

class PyramidingV1:
 def __init__(self,config:PyramidingConfig): config.validate(); self.config=config
 def decide(self,c:PyramidingContext)->PyramidingDecision:
  cfg=self.config; target=max(1,math.floor(c.original_entry_shares*cfg.addition_fraction)); reasons=[]; accepted=target
  if not cfg.enabled: accepted=0; reasons=["DISABLED_NO_OP"]
  elif c.current_atr is None: accepted=0; reasons=["MISSING_ATR_FAIL_CLOSED"]
  elif c.additions_count>=cfg.maximum_additions: accepted=0; reasons=["MAXIMUM_ADDITIONS_REACHED"]
  elif c.current_price<=c.original_entry_price: accepted=0; reasons=["POSITION_NOT_WINNING"]
  elif c.current_price+1e-12 < c.pyramid_anchor_price+c.current_atr*cfg.trigger_atr_multiple: accepted=0; reasons=["TRIGGER_NOT_REACHED"]
  else:
   cap_shares=max(0,math.floor(c.decision_time_total_equity*c.hard_notional_cap/c.execution_price)-c.current_shares)
   cash_shares=max(0,math.floor(c.available_cash/c.execution_price))
   risk_per_share=c.current_position_active_risk/c.current_shares
   risk_shares=(max(0,math.floor((c.maximum_active_portfolio_risk-c.active_portfolio_risk)/risk_per_share)) if risk_per_share>0 else target)
   accepted=min(target,cap_shares,cash_shares,risk_shares)
   if accepted<target:
    if cap_shares<target: reasons.append("HARD_NOTIONAL_CAP")
    if cash_shares<target: reasons.append("AVAILABLE_CASH")
    if risk_shares<target: reasons.append("ACTIVE_RISK_CAP")
   if accepted<1: accepted=0; reasons.append("BELOW_ONE_SHARE_FAIL_CLOSED")
   if accepted: reasons.append("PYRAMID_ADDITION_ACCEPTED")
  core={"accelerator_name":"pyramiding","accelerator_version":cfg.accelerator_version,"configuration_version":cfg.configuration_version,"configuration_fingerprint":cfg.fingerprint,"enabled":cfg.enabled,"decision_timestamp":c.decision_timestamp.isoformat(),"event_id":c.event_id,"event_sequence":c.event_sequence,"symbol":c.symbol.upper(),"current_price":c.current_price,"execution_price":c.execution_price,"atr_used":c.current_atr,"original_entry_price":c.original_entry_price,"original_entry_shares":c.original_entry_shares,"current_shares":c.current_shares,"additions_before":c.additions_count,"anchor_before":c.pyramid_anchor_price,"target_shares":target,"accepted_shares":accepted,"accepted_notional":accepted*c.execution_price,"reason_codes":reasons}
  return PyramidingDecision(**{k:v for k,v in core.items() if k not in ("decision_timestamp","reason_codes")},decision_timestamp=c.decision_timestamp,reason_codes=tuple(reasons),decision_id=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":")).encode()).hexdigest())

def load_pyramiding_config(path:Path,*,enabled:bool|None=None):
 p=json.loads(path.read_text()); c=PyramidingConfig(p["enabled"] if enabled is None else enabled,p["accelerator_version"],p["configuration_version"],p["trigger_atr_multiple"],p["addition_fraction"],p["maximum_additions"]); c.validate(); return c
