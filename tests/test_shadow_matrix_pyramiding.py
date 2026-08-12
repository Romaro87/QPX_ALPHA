import unittest
from datetime import datetime,timezone
from qpx_bot.shadow_matrix import MarketEvent,PositionEntrySnapshot,PyramidAdditionSnapshot,ShadowMatrixEngine,ShadowPosition,load_registry,serialize_checkpoint,restore_checkpoint
class ShadowPyramidingTests(unittest.TestCase):
 def test_exact_matrix_and_combinations(self):
  r=load_registry();self.assertEqual(len(r.configurations),45)
  self.assertEqual(r.dispatch_order[:17],("permanent_control","fixed_25","dynamic_25","fixed_40","dynamic_40","fixed_60","dynamic_60","fixed_90","dynamic_90","pyramid_25","pyramid_40","pyramid_60","pyramid_90","dynamic_pyramid_25","dynamic_pyramid_40","dynamic_pyramid_60","dynamic_pyramid_90"))
  for cap in (25,40,60,90):
   self.assertEqual({a.name:a.enabled for a in r.by_id[f"pyramid_{cap}"].accelerators},{"dynamic_sizing":False,"pyramiding":True,"capacity_arbitration":False,"regime_allocation":False})
   self.assertEqual({a.name:a.enabled for a in r.by_id[f"dynamic_pyramid_{cap}"].accelerators},{"dynamic_sizing":True,"pyramiding":True,"capacity_arbitration":False,"regime_allocation":False})
  self.assertTrue(all(not x.enabled for x in r.by_id["permanent_control"].accelerators))
 def test_position_additions_checkpoint_exactly(self):
  r=load_registry();e=ShadowMatrixEngine(r);s=e.states["pyramid_25"];now=datetime(2026,8,12,tzinfo=timezone.utc);event=MarketEvent.create(sequence=1,timestamp=now,event_type="CLOSE",payload={});snap=PositionEntrySnapshot(s.configuration,event.event_id,1)
  add=PyramidAdditionSnapshot(event.event_id,1,now,110.0,5,10.0,s.configuration.accelerators[1].configuration_fingerprint,"b"*64);s.positions["AMD"]=ShadowPosition("AMD",15,100.0,snap,original_entry_shares=10,original_entry_price=100,pyramid_anchor_price=110,pyramid_additions=[add]);restored=restore_checkpoint(serialize_checkpoint(e),r)
  self.assertEqual(restored.states["pyramid_25"].positions["AMD"].pyramid_additions,[add])
 def test_legacy_position_and_metrics_payloads_restore_with_pyramid_defaults(self):
  r=load_registry();state=ShadowMatrixEngine(r).states["pyramid_25"];now=datetime(2026,8,12,tzinfo=timezone.utc);event=MarketEvent.create(sequence=1,timestamp=now,event_type="CLOSE",payload={});snap=PositionEntrySnapshot(state.configuration,event.event_id,1);state.positions["AMD"]=ShadowPosition("AMD",10,100.0,snap)
  payload=state.to_checkpoint_dict();position=payload["positions"]["AMD"]
  for key in ("original_entry_shares","original_entry_price","pyramid_anchor_price","pyramid_additions"):position.pop(key)
  for key in tuple(payload["performance_metrics"]):
   if key.startswith("pyramid_") or key=="maximum_pyramid_additions_reached_count":payload["performance_metrics"].pop(key)
  restored=type(state).from_checkpoint_dict(payload,state.configuration);position=restored.positions["AMD"]
  self.assertEqual((position.original_entry_shares,position.original_entry_price,position.pyramid_anchor_price,position.pyramid_additions),(10,100.0,100.0,[]))
 def test_pyramid_failure_quarantines_only_that_shadow(self):
  def handler(event,state):
   if state.configuration.shadow_id=="pyramid_40":raise RuntimeError("pyramid failure")
   return "ACK",None
  e=ShadowMatrixEngine(load_registry(),handler=handler);event=MarketEvent.create(sequence=1,timestamp=datetime(2026,8,12,tzinfo=timezone.utc),event_type="CLOSE",payload={});before=e.states["pyramid_40"].state_hash;e.dispatch(event)
  self.assertEqual(e.states["pyramid_40"].state_hash,before);self.assertEqual(e.states["fixed_40"].event_sequence,1);self.assertIn("pyramid_40",e.quarantines)
if __name__=="__main__":unittest.main()
