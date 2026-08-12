import copy, unittest
from datetime import datetime, timezone
from qpx_bot.shadow_matrix import MarketEvent, ShadowMatrixEngine, load_registry, restore_checkpoint, serialize_checkpoint
from qpx_bot.shadow_matrix.registry import ARBITRATION_IDS, PYRAMID_IDS, LEGACY_IDS

class ShadowCapacityArbitrationTests(unittest.TestCase):
 def test_existing_seventeen_unchanged_and_exact_33(self):
  r=load_registry();self.assertEqual(r.dispatch_order[:17],LEGACY_IDS+PYRAMID_IDS);self.assertEqual(r.dispatch_order[17:],ARBITRATION_IDS);self.assertEqual(len(r.configurations),33)
  for cap in (25,40,60,90):
   for policy in ("frozen_order","breakout_strength","trend_strength","volume_confirmation"):
    c=r.by_id[f"{policy}_{cap}"];self.assertEqual({a.name:a.enabled for a in c.accelerators},{"dynamic_sizing":False,"pyramiding":False,"capacity_arbitration":True})
  self.assertTrue(all(not a.enabled for a in r.by_id["permanent_control"].accelerators))
 def test_checkpoint_preserves_arbitration_metrics_and_state(self):
  r=load_registry();e=ShadowMatrixEngine(r);s=e.states["trend_strength_25"];s.accelerator_state["capacity_arbitration"]["last_decision_id"]="a"*64;s.performance_metrics.arbitration_events=3;s.performance_metrics.selected_score_distribution=[1.25]
  restored=restore_checkpoint(serialize_checkpoint(e),r);x=restored.states["trend_strength_25"];self.assertEqual(x.accelerator_state["capacity_arbitration"]["last_decision_id"],"a"*64);self.assertEqual(x.performance_metrics.arbitration_events,3);self.assertEqual(x.performance_metrics.selected_score_distribution,[1.25])
 def test_failure_quarantines_only_one_arbitration_shadow(self):
  def handler(event,state):
   if state.configuration.shadow_id=="trend_strength_40":raise ValueError("arbitration failure")
   return "ACK",None
  e=ShadowMatrixEngine(load_registry(),handler=handler);event=MarketEvent.create(sequence=1,timestamp=datetime(2026,8,12,tzinfo=timezone.utc),event_type="CLOSE",payload={});e.dispatch(event);self.assertIn("trend_strength_40",e.quarantines);self.assertEqual(e.states["frozen_order_40"].event_sequence,1)
if __name__=="__main__":unittest.main()
