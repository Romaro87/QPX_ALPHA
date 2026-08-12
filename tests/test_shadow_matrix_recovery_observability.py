from __future__ import annotations
import json, unittest
from datetime import datetime,timedelta,timezone
from qpx_bot.shadow_matrix.checkpoint import ShadowCheckpointError,restore_checkpoint,serialize_checkpoint
from qpx_bot.shadow_matrix.engine import ShadowMatrixEngine
from qpx_bot.shadow_matrix.models import MarketEvent,PositionEntrySnapshot
from qpx_bot.shadow_matrix.registry import load_registry
from qpx_bot.shadow_matrix.state import ShadowPosition

NOW=datetime(2026,8,12,tzinfo=timezone.utc)
def event(n): return MarketEvent.create(sequence=n,timestamp=NOW+timedelta(minutes=n),event_type="TEST",payload={"price":100+n})

class RecoveryObservabilityTests(unittest.TestCase):
 def test_checkpoint_round_trip_position_snapshot_and_next_event(self):
  e=ShadowMatrixEngine(load_registry()); first=event(1); e.dispatch(first)
  s=e.states["dynamic_25"]; s.positions["AMD"]=ShadowPosition("AMD",1,101.0,PositionEntrySnapshot(s.configuration,first.event_id,1,"decision"))
  data=serialize_checkpoint(e); self.assertEqual(data,serialize_checkpoint(e)); restored=restore_checkpoint(data,load_registry())
  self.assertEqual({k:v.state_hash for k,v in e.states.items()},{k:v.state_hash for k,v in restored.states.items()})
  self.assertEqual(restored.states["dynamic_25"].positions["AMD"].entry_snapshot,s.positions["AMD"].entry_snapshot)
  restored.dispatch(event(2)); self.assertEqual(restored.last_sequence,2)
  with self.assertRaisesRegex(ValueError,"expected 3"): restored.dispatch(event(4))
 def test_corruption_and_incompatible_registry_fail_closed(self):
  data=serialize_checkpoint(ShadowMatrixEngine(load_registry()))
  with self.assertRaises(ShadowCheckpointError): restore_checkpoint(data+b"x",load_registry())
  envelope=json.loads(data); envelope["payload"]["matrix_version"]="other"
  envelope["checksum"]="0"*64
  with self.assertRaises(ShadowCheckpointError): restore_checkpoint(json.dumps(envelope),load_registry())
 def test_divergence_records_are_deterministic(self):
  def handler(ev,state):
   if state.configuration.shadow_id=="dynamic_25": state.swing_cash+=1
   return "ACK",None
  a=ShadowMatrixEngine(load_registry(),handler=handler); b=ShadowMatrixEngine(load_registry(),handler=handler); a.dispatch(event(1)); b.dispatch(event(1))
  self.assertEqual(a.divergence_log,b.divergence_log); self.assertEqual(len(a.divergence_log),8)
  self.assertTrue(next(x for x in a.divergence_log if x.comparison_shadow_id=="dynamic_25").divergence_occurred)
 def test_failure_rolls_back_quarantines_and_recovery_requires_exact_replay(self):
  def bad(ev,state):
   state.swing_cash+=5
   if state.configuration.shadow_id=="dynamic_60": raise RuntimeError("boom")
   return "ACK",None
  e=ShadowMatrixEngine(load_registry(),handler=bad); before=e.states["dynamic_60"].state_hash; one=event(1); e.dispatch(one)
  self.assertEqual(before,e.states["dynamic_60"].state_hash); self.assertEqual(e.states["fixed_60"].event_sequence,1)
  with self.assertRaises(ValueError): e.prepare_recovery("dynamic_60",(),handler=lambda ev,s:("ACK",None))
  recovered,auth=e.prepare_recovery("dynamic_60",(one,),handler=lambda ev,s:("ACK",None)); e.rejoin_shadow(recovered,auth)
  self.assertNotIn("dynamic_60",e.quarantines); self.assertEqual(e.states["dynamic_60"].event_sequence,1)
 def test_metrics_are_isolated_and_checkpointable(self):
  e=ShadowMatrixEngine(load_registry()); e.states["fixed_25"].performance_metrics.record_trade(-4,overnight_gap=True); data=serialize_checkpoint(e); r=restore_checkpoint(data,load_registry())
  self.assertEqual(r.states["fixed_25"].performance_metrics.largest_trade_loss,-4)
  self.assertEqual(r.states["dynamic_25"].performance_metrics.trades,0)

if __name__=="__main__": unittest.main()
