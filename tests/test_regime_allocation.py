import unittest
from dataclasses import fields
from datetime import datetime,timedelta,timezone
from pathlib import Path
from qpx_bot.accelerators.regime_allocation import *
class RegimeAllocationTests(unittest.TestCase):
 def config(self): return load_regime_allocation_config(Path("qpx_bot/accelerators/configs/regime_allocation_v1_foundation.json"))
 def context(self):
  now=datetime(2026,8,12,14,30,tzinfo=timezone.utc);return RegimeAllocationContext(now,now-timedelta(days=1),24,.125,.13,100,700,1000)
 def test_disabled_is_exact_authoritative_noop(self):
  d=RegimeAllocationV1(self.config()).decide(self.context());self.assertEqual((d.proposed_target_qdte_weight,d.proposed_target_swing_weight),(.125,.875));self.assertFalse(d.rebalance_eligibility)
 def test_only_previous_completed_vix_is_exposed_and_future_rejected(self):
  names={f.name for f in fields(RegimeAllocationContext)};self.assertIn("previous_completed_session_vix_close",names);self.assertFalse(any("future" in x or "current_session" in x for x in names));c=self.context()
  with self.assertRaises(ValueError): RegimeAllocationContext(c.decision_timestamp,c.decision_timestamp,24,.125,.13,100,700,1000)
 def test_invalid_vix_fails_closed(self):
  c=self.context()
  with self.assertRaises(ValueError): RegimeAllocationContext(c.decision_timestamp,c.vix_observation_timestamp,0,.125,.13,100,700,1000)
 def test_enabled_policy_not_declared(self):
  with self.assertRaisesRegex(ValueError,"Unknown"): RegimeAllocationConfig(True,"1.0.0","x","invented").validate()
 def test_deterministic_and_checkpoint_identity(self):
  a=RegimeAllocationV1(self.config());self.assertEqual(a.decide(self.context()),a.decide(self.context()));self.assertEqual(len(self.config().fingerprint),64)
 def test_candidate_baseline_and_vix_rules_unchanged(self):
  s=Path("QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL.py").read_text()
  for x in ("target_income_weight=0.125","VIX_EXCLUSION_LOW = 20.0","VIX_EXCLUSION_HIGH = 25.0","maximum_vix_for_entries=32.0"): self.assertIn(x,s)
 def test_no_entry_exit_or_liquidation_surface(self):
  names={f.name for f in fields(RegimeAllocationContext)};self.assertFalse(names&{"qualifying","entry_allowed","exit_reason","positions","portfolio","liquidate"})
 def test_qdte_execution_remains_cash_tolerance_mechanism(self):
  s=Path("QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL.py").read_text();self.assertIn("allocation_rebalance_tolerance=0.0025",s);self.assertIn("minimum_rebalance_trade=1.0",s);self.assertIn("qpx._apply_rebalance",s)
 def test_open_positions_retain_entry_configuration(self):
  s=Path("qpx_bot/shadow_matrix/state.py").read_text();self.assertIn("entry_snapshot:PositionEntrySnapshot",s)
 def test_top100_and_other_accelerators_remain_present(self):
  import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as m
  self.assertEqual(len(m._top100()),100)
  for p in ("dynamic_sizing.py","pyramiding.py","capacity_arbitration.py"): self.assertTrue((Path("qpx_bot/accelerators")/p).is_file())
 def test_exact_enabled_policy_set_boundaries_and_weights(self):
  self.assertEqual(tuple(POLICY_WEIGHTS),("stress_income_shift_v1","calm_swing_shift_v1","two_sided_ladder_v1"));self.assertEqual(BOUNDARIES,(20.,25.,32.));self.assertEqual(POLICY_WEIGHTS["stress_income_shift_v1"],(.125,.125,.25,.4));self.assertEqual(POLICY_WEIGHTS["calm_swing_shift_v1"],(.05,.125,.125,.125));self.assertEqual(POLICY_WEIGHTS["two_sided_ladder_v1"],(.05,.125,.25,.4))
 def test_exact_boundary_regimes(self):
  self.assertEqual([regime_for_vix(x) for x in (19.99,20,24.99,25,32,32.01)],["CALM","TRANSITION","TRANSITION","ELEVATED","ELEVATED","EXTREME"])
 def test_enabled_decision_is_deterministic_and_weekly_only(self):
  c=load_regime_allocation_config(Path("qpx_bot/accelerators/configs/regime_two_sided_ladder_v1.json"));a=RegimeAllocationV1(c);one=a.decide(self.context());self.assertEqual(one,a.decide(self.context()));self.assertEqual(one.weekly_rebalance_identity,"THURSDAY_WEEKLY_REBALANCE")
 def test_exact_45_registry_and_original_33_prefix(self):
  from qpx_bot.shadow_matrix.registry import load_registry,REGIME_IDS
  r=load_registry();self.assertEqual(len(r.configurations),45);self.assertEqual(r.dispatch_order[33:],REGIME_IDS);self.assertTrue(all(not a.enabled for a in r.by_id["permanent_control"].accelerators))
 def test_checkpoint_and_failure_isolation(self):
  from qpx_bot.shadow_matrix.registry import load_registry
  from qpx_bot.shadow_matrix.engine import ShadowMatrixEngine
  from qpx_bot.shadow_matrix.checkpoint import serialize_checkpoint,restore_checkpoint
  from qpx_bot.shadow_matrix.models import MarketEvent
  r=load_registry();e=ShadowMatrixEngine(r);s=e.states["regime_stress_25"];s.accelerator_state["regime_allocation"].update(current_regime="ELEVATED",latest_vix_identity="x",decision_history=["d"]);blob=serialize_checkpoint(e);self.assertEqual(serialize_checkpoint(restore_checkpoint(blob,r)),blob)
  def handler(event,state):
   if state.configuration.shadow_id=="regime_calm_40":raise RuntimeError("isolated")
   return "OK",{}
  e=ShadowMatrixEngine(r,handler=handler);e.dispatch(MarketEvent.create(sequence=1,timestamp=datetime(2026,8,12,tzinfo=timezone.utc),event_type="WEEKLY",payload={}));self.assertEqual(set(e.quarantines),{"regime_calm_40"});self.assertEqual(e.states["regime_stress_40"].event_sequence,1)
if __name__=="__main__": unittest.main()
