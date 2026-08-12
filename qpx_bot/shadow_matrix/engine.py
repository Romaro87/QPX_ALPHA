"""Deterministic fan-out with per-Shadow rollback and quarantine."""
from __future__ import annotations
import copy
from collections.abc import Callable
from datetime import datetime
from typing import Any
from qpx_bot.shadow_matrix.models import DecisionRecord,DivergenceRecord,MarketEvent,QuarantineRecord,RecoveryAuthorization,canonical_hash,freeze_json,thaw_json
from qpx_bot.shadow_matrix.state import ShadowState
ShadowHandler=Callable[[MarketEvent,ShadowState],tuple[str,Any]]
def acknowledge_event(event,state): return "EVENT_ACKNOWLEDGED_NO_STRATEGY_DECISION",{"event_type":event.event_type,"strategy_decision":None}

class ShadowMatrixEngine:
 def __init__(self,registry,*,handler=acknowledge_event):
  self.registry=registry; self._handler=handler; self.dispatch_order=registry.dispatch_order
  self.states={c.shadow_id:ShadowState.initial(c) for c in registry.configurations}; self.decision_log=[]; self.divergence_log=[]; self.quarantines={}; self.last_sequence=0; self.last_timestamp=None; self.seen_event_ids=set(); self.event_history=[]
 def dispatch(self,event):
  self._validate_event(event); outcomes={}
  for c in self.registry.configurations:
   sid=c.shadow_id; original=self.states[sid]; before=original.state_hash; before_cmp=original.comparison_hash
   if sid in self.quarantines: state=original; status="SHADOW_QUARANTINED_REPLAY_REQUIRED"; payload={"quarantine_id":self.quarantines[sid].quarantine_id}
   else:
    state=copy.deepcopy(original)
    try:
     status,payload=self._handler(event,state); state.event_sequence=event.sequence; state.last_event_id=event.event_id; state.performance_metrics.record_event(event.sequence); state.checkpoint_state["last_event_timestamp"]=event.timestamp.isoformat(); self.states[sid]=state
    except Exception as error:
     state=original; status="SHADOW_HANDLER_FAILED_QUARANTINED"; core={"shadow_id":sid,"failed_event_id":event.event_id,"failed_event_sequence":event.sequence,"failed_event_timestamp":event.timestamp.isoformat(),"last_successful_sequence":original.event_sequence,"state_hash":original.state_hash,"error_type":type(error).__name__,"error_message":str(error),"required_replay_from_sequence":original.event_sequence+1}; q=QuarantineRecord(sid,event.event_id,event.sequence,event.timestamp,original.event_sequence,original.state_hash,type(error).__name__,str(error),original.event_sequence+1,canonical_hash(core)); self.quarantines[sid]=q; payload={"quarantine_id":q.quarantine_id,"error_type":q.error_type,"error_message":q.error_message}
   outcomes[sid]=(c,before,before_cmp,state,status,payload)
  control=outcomes["permanent_control"]
  for sid in self.dispatch_order[1:]:
   item=outcomes[sid]; reasons=[]
   if control[4]!=item[4]: reasons.append("STATUS_DIFFERENCE")
   if control[3].comparison_hash!=item[3].comparison_hash: reasons.append("STATE_DIFFERENCE")
   core={"event_id":event.event_id,"event_sequence":event.sequence,"event_timestamp":event.timestamp.isoformat(),"control_shadow_id":"permanent_control","control_configuration_fingerprint":control[0].fingerprint,"comparison_shadow_id":sid,"comparison_configuration_fingerprint":item[0].fingerprint,"control_status":control[4],"comparison_status":item[4],"control_before_state_hash":control[2],"control_after_state_hash":control[3].comparison_hash,"comparison_before_state_hash":item[2],"comparison_after_state_hash":item[3].comparison_hash,"divergence_occurred":bool(reasons),"reasons":reasons,"details":{"promotion_evidence":False}}
   self.divergence_log.append(DivergenceRecord(event.event_id,event.sequence,event.timestamp,"permanent_control",control[0].fingerprint,sid,item[0].fingerprint,control[4],item[4],control[2],control[3].comparison_hash,item[2],item[3].comparison_hash,bool(reasons),tuple(reasons),freeze_json(core["details"]),canonical_hash(core)))
   if reasons and sid not in self.quarantines: item[3].performance_metrics.record_divergence()
  records=[]
  for sid in self.dispatch_order:
   c,before,_,state,status,payload=outcomes[sid]; fp=freeze_json(payload); core={"event_id":event.event_id,"event_sequence":event.sequence,"event_timestamp":event.timestamp.isoformat(),"shadow_id":sid,"shadow_configuration_fingerprint":c.fingerprint,"before_state_hash":before,"after_state_hash":state.state_hash,"accelerator_identities":[a.as_dict() for a in c.accelerators],"status":status,"result_payload":thaw_json(fp)}; records.append(DecisionRecord(event.event_id,event.sequence,event.timestamp,sid,c.fingerprint,before,state.state_hash,c.accelerators,status,fp,canonical_hash(core)))
  self.decision_log.extend(records); self.last_sequence=event.sequence; self.last_timestamp=event.timestamp; self.seen_event_ids.add(event.event_id); self.event_history.append({"sequence":event.sequence,"timestamp":event.timestamp.isoformat(),"event_id":event.event_id,"event_type":event.event_type,"payload":thaw_json(event.payload)}); return tuple(records)
 def prepare_recovery(self,shadow_id,events,*,handler=None):
  if shadow_id not in self.quarantines: raise ValueError("Shadow is not quarantined.")
  q=self.quarantines[shadow_id]; expected=self.event_history[q.required_replay_from_sequence-1:]; events=tuple(events)
  if [e.event_id for e in events] != [e["event_id"] for e in expected]: raise ValueError("Recovery requires exact contiguous event replay.")
  state=copy.deepcopy(self.states[shadow_id]); use=handler or self._handler
  for event in events:
   use(event,state); state.event_sequence=event.sequence; state.last_event_id=event.event_id; state.performance_metrics.record_event(event.sequence); state.checkpoint_state["last_event_timestamp"]=event.timestamp.isoformat()
  auth=RecoveryAuthorization.create(shadow_id=shadow_id,quarantine_id=q.quarantine_id,replayed_from_sequence=q.required_replay_from_sequence,replayed_through_sequence=self.last_sequence,recovered_state_hash=state.state_hash,last_event_id=state.last_event_id,registry_fingerprint=self.registry.fingerprint); return state,auth
 def rejoin_shadow(self,state,authorization):
  q=self.quarantines.get(authorization.shadow_id)
  expected=RecoveryAuthorization.create(shadow_id=authorization.shadow_id,quarantine_id=authorization.quarantine_id,replayed_from_sequence=authorization.replayed_from_sequence,replayed_through_sequence=authorization.replayed_through_sequence,recovered_state_hash=authorization.recovered_state_hash,last_event_id=authorization.last_event_id,registry_fingerprint=authorization.registry_fingerprint)
  if q is None or expected!=authorization or q.quarantine_id!=authorization.quarantine_id or authorization.registry_fingerprint!=self.registry.fingerprint or authorization.replayed_through_sequence!=self.last_sequence or state.state_hash!=authorization.recovered_state_hash or state.event_sequence!=self.last_sequence: raise ValueError("Invalid deterministic recovery authorization.")
  self.states[authorization.shadow_id]=copy.deepcopy(state); del self.quarantines[authorization.shadow_id]
 def _validate_event(self,event):
  if event.event_id in self.seen_event_ids: raise ValueError("Duplicate market event")
  if event.sequence!=self.last_sequence+1: raise ValueError(f"Non-monotonic event sequence: expected {self.last_sequence+1}, received {event.sequence}.")
  if self.last_timestamp is not None and event.timestamp<=self.last_timestamp: raise ValueError("Market event timestamps must be strictly increasing.")
