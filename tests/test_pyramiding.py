from __future__ import annotations
import unittest
from datetime import datetime,timezone
from pathlib import Path
from qpx_bot.accelerators.pyramiding import PyramidingContext,PyramidingV1,load_pyramiding_config
ROOT=Path(__file__).parents[1]; CONFIG=ROOT/"qpx_bot/accelerators/configs/pyramiding_v1.json"; NOW=datetime(2026,8,12,tzinfo=timezone.utc)
def context(**changes):
 p=dict(decision_timestamp=NOW,event_id="a"*64,event_sequence=1,symbol="AMD",current_price=110.0,execution_price=110.0,current_atr=10.0,original_entry_price=100.0,original_entry_shares=10,current_shares=10,additions_count=0,pyramid_anchor_price=100.0,decision_time_total_equity=10000.0,available_cash=10000.0,active_portfolio_risk=20.0,maximum_active_portfolio_risk=100.0,current_position_active_risk=20.0,hard_notional_cap=.9);p.update(changes);return PyramidingContext(**p)
class PyramidingTests(unittest.TestCase):
 def setUp(self):self.a=PyramidingV1(load_pyramiding_config(CONFIG))
 def test_disabled_is_true_noop(self):self.assertEqual(PyramidingV1(load_pyramiding_config(CONFIG,enabled=False)).decide(context()).reason_codes,("DISABLED_NO_OP",))
 def test_trigger_boundary_and_no_averaging_down(self):
  self.assertFalse(self.a.decide(context(current_price=109.999)).accepted);self.assertTrue(self.a.decide(context()).accepted)
  for price in (99.0,100.0):self.assertFalse(self.a.decide(context(current_price=price,current_atr=.1)).accepted)
 def test_half_original_integer_and_below_one_fail_closed(self):
  self.assertEqual(self.a.decide(context(original_entry_shares=11)).accepted_shares,5)
  self.assertIn("BELOW_ONE_SHARE_FAIL_CLOSED",self.a.decide(context(original_entry_shares=1)).reason_codes)
 def test_two_additions_and_reset_anchor(self):
  self.assertIn("MAXIMUM_ADDITIONS_REACHED",self.a.decide(context(additions_count=2)).reason_codes)
  self.assertFalse(self.a.decide(context(additions_count=1,pyramid_anchor_price=110,current_price=119.9)).accepted)
  self.assertTrue(self.a.decide(context(additions_count=1,pyramid_anchor_price=110,current_price=120)).accepted)
 def test_cap_cash_and_risk_fail_closed(self):
  self.assertIn("HARD_NOTIONAL_CAP",self.a.decide(context(current_shares=9,hard_notional_cap=.9,decision_time_total_equity=1000)).reason_codes)
  self.assertIn("AVAILABLE_CASH",self.a.decide(context(available_cash=0)).reason_codes)
  self.assertIn("ACTIVE_RISK_CAP",self.a.decide(context(active_portfolio_risk=100)).reason_codes)
 def test_missing_atr_and_determinism(self):
  self.assertIn("MISSING_ATR_FAIL_CLOSED",self.a.decide(context(current_atr=None)).reason_codes)
  self.assertEqual(self.a.decide(context()),self.a.decide(context()))
  self.assertEqual(len(self.a.decide(context()).decision_id),64)
 def test_invalid_fixed_parameters_rejected(self):
  from dataclasses import replace
  with self.assertRaises(ValueError):PyramidingV1(replace(load_pyramiding_config(CONFIG),maximum_additions=3))
if __name__=="__main__":unittest.main()
