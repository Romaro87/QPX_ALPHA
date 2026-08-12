"""Independent, serializable mutable state owned by one Shadow."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from qpx_bot.shadow_matrix.metrics import ShadowMetrics
from qpx_bot.shadow_matrix.models import PositionEntrySnapshot, ShadowConfiguration, canonical_hash

@dataclass(slots=True)
class ShadowPosition:
    symbol: str; shares: int; entry_price: float; entry_snapshot: PositionEntrySnapshot
    management_state: dict[str, Any] = field(default_factory=dict)
    def as_dict(self):
        return {"symbol":self.symbol,"shares":self.shares,"entry_price":self.entry_price,"entry_snapshot":self.entry_snapshot.as_dict(),"management_state":self.management_state}
    @classmethod
    def from_dict(cls,p): return cls(p["symbol"],p["shares"],p["entry_price"],PositionEntrySnapshot.from_dict(p["entry_snapshot"]),p["management_state"])

@dataclass(slots=True)
class ShadowState:
    configuration: ShadowConfiguration; swing_cash: float; qdte_state: dict[str,Any]
    tax_reserve: float=0.0; positions: dict[str,ShadowPosition]=field(default_factory=dict)
    pending_orders: dict[str,dict[str,Any]]=field(default_factory=dict)
    accelerator_state: dict[str,dict[str,Any]]=field(default_factory=dict)
    performance_metrics: ShadowMetrics=field(default_factory=ShadowMetrics)
    event_sequence:int=0; last_event_id:str|None=None; checkpoint_state:dict[str,Any]=field(default_factory=dict)
    @classmethod
    def initial(cls,c):
        return cls(c,float(c.starting_swing_cash),{"market_value":float(c.starting_qdte_value),"shares":None,"entitlements":{},"settlements":{}},accelerator_state={a.name:{"enabled":a.enabled,"configuration_version":a.configuration_version,"decision_count":0} for a in c.accelerators},performance_metrics=ShadowMetrics(starting_equity=c.starting_total_equity,current_equity=c.starting_total_equity,ending_equity=c.starting_total_equity),checkpoint_state={"resume_authorized":False})
    def canonical_dict(self):
        return self.to_checkpoint_dict()
    def comparison_dict(self):
        d=self.to_checkpoint_dict(); d.pop("configuration",None); d.pop("accelerator_state",None); d.pop("event_sequence",None); d.pop("last_event_id",None); d.pop("checkpoint_state",None); return d
    @property
    def state_hash(self): return canonical_hash(self.canonical_dict())
    @property
    def comparison_hash(self): return canonical_hash(self.comparison_dict())
    def to_checkpoint_dict(self):
        return {"configuration":self.configuration.as_dict(),"swing_cash":self.swing_cash,"qdte_state":self.qdte_state,"tax_reserve":self.tax_reserve,"positions":{k:v.as_dict() for k,v in sorted(self.positions.items())},"pending_orders":self.pending_orders,"accelerator_state":self.accelerator_state,"performance_metrics":self.performance_metrics.as_dict(),"event_sequence":self.event_sequence,"last_event_id":self.last_event_id,"checkpoint_state":self.checkpoint_state}
    @classmethod
    def from_checkpoint_dict(cls,p,current_configuration):
        saved=ShadowConfiguration.from_dict(p["configuration"])
        if saved.fingerprint != current_configuration.fingerprint: raise ValueError("Shadow configuration fingerprint differs.")
        return cls(current_configuration,p["swing_cash"],p["qdte_state"],p["tax_reserve"],{k:ShadowPosition.from_dict(v) for k,v in p["positions"].items()},p["pending_orders"],p["accelerator_state"],ShadowMetrics.from_dict(p["performance_metrics"]),p["event_sequence"],p["last_event_id"],p["checkpoint_state"])
