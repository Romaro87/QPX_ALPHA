from __future__ import annotations
import unittest
from datetime import datetime, timezone
from qpx_bot.accelerators.capacity_arbitration import *
from qpx_bot.intraday_six_paper import choose_without_ranking

NOW=datetime(2026,8,12,tzinfo=timezone.utc)
def candidate(symbol,rank=1,**changes):
 p=dict(current_close=110.0,prior_high=100.0,current_atr=5.0,current_fast=105.0,current_slow=100.0,current_volume=200.0,baseline_volume=100.0,frozen_top100_rank=rank,tie_break_identity=tie_identity(NOW,symbol));p.update(changes);return CapacityCandidate(symbol=symbol,**p)
def decision(policy,candidates,slots=1):return CapacityArbitrationV1(CapacityArbitrationConfig(policy)).decide(CapacityArbitrationContext(NOW,slots,tuple(candidates)))

class CapacityArbitrationTests(unittest.TestCase):
 def test_exact_policies_have_no_coefficients_or_search_surface(self):
  self.assertEqual(POLICIES,("hash_control","frozen_order","breakout_strength","trend_strength","volume_confirmation"));self.assertEqual(set(CapacityArbitrationConfig.__dataclass_fields__),{"policy","policy_version"})
 def test_hash_control_exactly_matches_existing_behavior(self):
  symbols=("TSLA","AMD","AAPL");expected=choose_without_ranking(signal_bar=NOW,qualifying=symbols,available_slots=2);actual=decision("hash_control",[candidate(x,i+1) for i,x in enumerate(symbols)],2);self.assertEqual((actual.selected_candidates,actual.deferred_candidates),expected)
 def test_all_fit_preserves_existing_hash_order_and_defers_none(self):
  items=[candidate("AMD",2),candidate("AAPL",1)];d=decision("frozen_order",items,2);self.assertEqual((d.selected_candidates,d.deferred_candidates),choose_without_ranking(signal_bar=NOW,qualifying=("AMD","AAPL"),available_slots=2))
 def test_frozen_order_uses_existing_rank(self):self.assertEqual(decision("frozen_order",[candidate("AMD",2),candidate("AAPL",1)]).selected_candidates,("AAPL",))
 def test_exact_score_formulas(self):
  a=candidate("AMD",current_close=112,prior_high=100,current_atr=4,current_fast=108,current_slow=100,current_volume=300,baseline_volume=120)
  self.assertEqual(decision("breakout_strength",[a],0).scores[0].priority,3);self.assertEqual(decision("trend_strength",[a],0).scores[0].priority,2);self.assertEqual(decision("volume_confirmation",[a],0).scores[0].priority,2.5)
 def test_invalid_denominators_fail_closed(self):
  for policy in ("breakout_strength","trend_strength"):
   with self.assertRaisesRegex(ValueError,"INVALID_ATR"):decision(policy,[candidate("AMD",current_atr=0)],0)
  with self.assertRaisesRegex(ValueError,"INVALID_BASELINE"):decision("volume_confirmation",[candidate("AMD",baseline_volume=0)],0)
 def test_equal_scores_use_exact_hash_tie(self):
  items=[candidate("AMD",1),candidate("AAPL",2)];expected=choose_without_ranking(signal_bar=NOW,qualifying=("AMD","AAPL"),available_slots=1)[0]
  for policy in ("breakout_strength","trend_strength","volume_confirmation"):self.assertEqual(decision(policy,items).selected_candidates,expected)
 def test_identical_causal_inputs_are_deterministic(self):
  items=[candidate("AMD",1),candidate("AAPL",2)];self.assertEqual(decision("trend_strength",items),decision("trend_strength",items))
 def test_selection_is_subset_of_qualifying_candidates(self):
  items=[candidate("AMD",1),candidate("AAPL",2)];d=decision("frozen_order",items);self.assertTrue(set(d.selected_candidates)<=set(x.symbol for x in items))
 def test_divergence_is_deterministic_and_direct(self):
  d=decision("frozen_order",[candidate("AMD",2),candidate("AAPL",1)]);x=selection_divergence(d,("AMD",));self.assertEqual(x.displaced_symbols,("AMD",));self.assertEqual(x.replacement_symbols,("AAPL",));self.assertEqual(len(x.divergence_id),64)
if __name__=="__main__":unittest.main()
