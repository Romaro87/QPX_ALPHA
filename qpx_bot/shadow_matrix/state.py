"""Independent, serializable mutable state owned by one Shadow."""
from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
from typing import Any
from qpx_bot.shadow_matrix.metrics import ShadowMetrics
from qpx_bot.shadow_matrix.models import PositionEntrySnapshot,ShadowConfiguration,canonical_hash

@dataclass(frozen=True,slots=True)
class PyramidAdditionSnapshot:
 event_id:str; event_sequence:int; timestamp:datetime; fill_price:float; shares_added:int; atr_used:float; accelerator_configuration_fingerprint:str; decision_id:str
 def as_dict(self): return {"event_id":self.event_id,"event_sequence":self.event_sequence,"timestamp":self.timestamp.isoformat(),"fill_price":self.fill_price,"shares_added":self.shares_added,"atr_used":self.atr_used,"accelerator_configuration_fingerprint":self.accelerator_configuration_fingerprint,"decision_id":self.decision_id}
 @classmethod
 def from_dict(cls,p): return cls(p["event_id"],p["event_sequence"],datetime.fromisoformat(p["timestamp"]),p["fill_price"],p["shares_added"],p["atr_used"],p["accelerator_configuration_fingerprint"],p["decision_id"])

@dataclass(slots=True)
class ShadowPosition:
 symbol:str; shares:int; entry_price:float; entry_snapshot:PositionEntrySnapshot; management_state:dict[str,Any]=field(default_factory=dict)
 original_entry_shares:int|None=None; original_entry_price:float|None=None; pyramid_anchor_price:float|None=None; pyramid_additions:list[PyramidAdditionSnapshot]=field(default_factory=list)
 def __post_init__(self):
  if self.original_entry_shares is None:self.original_entry_shares=self.shares
  if self.original_entry_price is None:self.original_entry_price=self.entry_price
  if self.pyramid_anchor_price is None:self.pyramid_anchor_price=self.entry_price
 def as_dict(self): return {"symbol":self.symbol,"shares":self.shares,"entry_price":self.entry_price,"entry_snapshot":self.entry_snapshot.as_dict(),"management_state":self.management_state,"original_entry_shares":self.original_entry_shares,"original_entry_price":self.original_entry_price,"pyramid_anchor_price":self.pyramid_anchor_price,"pyramid_additions":[x.as_dict() for x in self.pyramid_additions]}
 @classmethod
 def from_dict(cls,p): return cls(p["symbol"],p["shares"],p["entry_price"],PositionEntrySnapshot.from_dict(p["entry_snapshot"]),p.get("management_state",{}),p.get("original_entry_shares"),p.get("original_entry_price"),p.get("pyramid_anchor_price"),[PyramidAdditionSnapshot.from_dict(x) for x in p.get("pyramid_additions",[])])

@dataclass(slots=True)
class ShadowState:
 configuration:ShadowConfiguration; swing_cash:float; qdte_state:dict[str,Any]; tax_reserve:float=0.0; positions:dict[str,ShadowPosition]=field(default_factory=dict); pending_orders:dict[str,dict[str,Any]]=field(default_factory=dict); accelerator_state:dict[str,dict[str,Any]]=field(default_factory=dict); performance_metrics:ShadowMetrics=field(default_factory=ShadowMetrics); event_sequence:int=0; last_event_id:str|None=None; checkpoint_state:dict[str,Any]=field(default_factory=dict)
 @classmethod
 def initial(cls,c): return cls(c,float(c.starting_swing_cash),{"market_value":float(c.starting_qdte_value),"shares":None,"entitlements":{},"settlements":{}},accelerator_state={a.name:{"enabled":a.enabled,"configuration_version":a.configuration_version,"decision_count":0} for a in c.accelerators},performance_metrics=ShadowMetrics(starting_equity=c.starting_total_equity,current_equity=c.starting_total_equity,ending_equity=c.starting_total_equity),checkpoint_state={"resume_authorized":False})
 def canonical_dict(self): return self.to_checkpoint_dict()
 def comparison_dict(self):
  d=self.to_checkpoint_dict(); [d.pop(x,None) for x in ("configuration","accelerator_state","event_sequence","last_event_id","checkpoint_state")]; return d
 @property
 def state_hash(self): return canonical_hash(self.canonical_dict())
 @property
 def comparison_hash(self): return canonical_hash(self.comparison_dict())
 def to_checkpoint_dict(self): return {"configuration":self.configuration.as_dict(),"swing_cash":self.swing_cash,"qdte_state":self.qdte_state,"tax_reserve":self.tax_reserve,"positions":{k:v.as_dict() for k,v in sorted(self.positions.items())},"pending_orders":self.pending_orders,"accelerator_state":self.accelerator_state,"performance_metrics":self.performance_metrics.as_dict(),"event_sequence":self.event_sequence,"last_event_id":self.last_event_id,"checkpoint_state":self.checkpoint_state}
 @classmethod
 def from_checkpoint_dict(cls,p,current_configuration):
  saved=ShadowConfiguration.from_dict(p["configuration"])
  if saved.fingerprint!=current_configuration.fingerprint:raise ValueError("Shadow configuration fingerprint differs.")
  return cls(current_configuration,p["swing_cash"],p["qdte_state"],p["tax_reserve"],{k:ShadowPosition.from_dict(v) for k,v in p["positions"].items()},p["pending_orders"],p["accelerator_state"],ShadowMetrics.from_dict(p["performance_metrics"]),p["event_sequence"],p["last_event_id"],p["checkpoint_state"])
