import json,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from qpx_bot.accelerators.profit_recycling import *
class ProfitRecyclingTests(unittest.TestCase):
 def config(self):return load_profit_recycling_config(Path("qpx_bot/accelerators/configs/profit_recycling_v1_foundation.json"))
 def context(self,seq=1,source=ProfitSource.SWING_REALIZED_PROFIT,pnl=100,tax=20):
  now=datetime(2026,8,12,tzinfo=timezone.utc)+timedelta(seconds=seq);eid=__import__('hashlib').sha256(f"event-{seq}".encode()).hexdigest();return ProfitRecyclingContext(now,eid,seq,source,pnl,tax,500,0,1300)
 def test_disabled_exact_noop_and_determinism(self):
  a=ProfitRecyclingV1(self.config());c=self.context();d=a.decide(c);self.assertEqual(d,a.decide(c));self.assertEqual(d.source_cash_balance_before,d.source_cash_balance_after);self.assertEqual(d.destination_amount,0)
 def test_authoritative_net_profit_and_tax_protection(self):
  c=self.context();self.assertEqual(c.eligible_net_profit,80);d=ProfitRecyclingV1(self.config()).decide(c);self.assertEqual((d.gross_realized_amount,d.attributable_tax_reserve,d.eligible_net_profit),(100,20,80))
  with self.assertRaises(ValueError):ProfitSourceLedger(100).record(c,81)
 def test_losses_and_nontrade_sources_are_ineligible(self):
  for source,pnl in ((ProfitSource.SWING_REALIZED_LOSS,-20),(ProfitSource.QDTE_DISTRIBUTION,10),(ProfitSource.INCOME_REBALANCE_REALIZED_PNL,10),(ProfitSource.EXTERNAL_CONTRIBUTION,10),(ProfitSource.ORIGINAL_START_CAPITAL,100)):
   self.assertEqual(self.context(source=source,pnl=pnl,tax=0).eligible_net_profit,0)
 def test_unrealized_source_does_not_exist(self):self.assertNotIn("UNREALIZED",{x.value for x in ProfitSource})
 def test_duplicate_and_out_of_order_fail_closed(self):
  l=ProfitSourceLedger(1300);l.record(self.context(2))
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):l.record(self.context(2))
  with self.assertRaisesRegex(ValueError,"OUT_OF_ORDER"):l.record(self.context(seq=1))
 def test_source_taxonomy_is_separate_and_no_double_count(self):
  l=ProfitSourceLedger(1300);l.record(self.context(1));l.record(self.context(2,ProfitSource.SWING_REALIZED_LOSS,-30,0));l.record(self.context(3,ProfitSource.QDTE_DISTRIBUTION,15,0));l.record(self.context(4,ProfitSource.INCOME_REBALANCE_REALIZED_PNL,5,0));l.record(self.context(5,ProfitSource.EXTERNAL_CONTRIBUTION,25,0));self.assertEqual((l.gross_realized_swing_profit,l.realized_swing_loss,l.net_realized_swing_profit_after_tax,l.qdte_distributions,l.income_rebalance_realized_pnl,l.external_contributions),(100,-30,80,15,5,25))
 def test_checkpoint_roundtrip_and_corruption(self):
  l=ProfitSourceLedger(1300);l.record(self.context(2));p=json.loads(json.dumps(l.as_dict()));self.assertEqual(ProfitSourceLedger.from_dict(p).as_dict(),l.as_dict());p["seen_event_ids"]=[]
  with self.assertRaises(ValueError):ProfitSourceLedger.from_dict(p)
 def test_principal_cannot_be_fabricated_or_recycled(self):
  l=ProfitSourceLedger(1300)
  with self.assertRaises(ValueError):l.record(self.context(source=ProfitSource.ORIGINAL_START_CAPITAL,pnl=1300,tax=0),1)
 def test_portfolio_authoritative_accounting_source_unchanged(self):
  s=Path("qpx_bot/portfolio.py").read_text();self.assertIn("self.cash += proceeds - tax_reserved",s);self.assertIn("self.tax_reserve_cash += tax_reserved",s);self.assertIn("self.realized_pnl += pnl",s);self.assertIn("tax_reserved=tax_reserved",s)
 def test_no_position_or_future_surface(self):
  names=set(ProfitRecyclingContext.__dataclass_fields__);self.assertFalse(names&{"positions","future_returns","future_prices","unrealized_pnl","dividend_opportunity"})
 def test_existing_45_registry_unchanged(self):
  from qpx_bot.shadow_matrix.registry import load_registry
  r=load_registry();self.assertEqual(len(r.configurations),45);self.assertTrue(all(not a.enabled for a in r.by_id["permanent_control"].accelerators))
 def test_shadow_checkpoint_and_failure_isolation(self):
  from qpx_bot.shadow_matrix.registry import load_registry
  from qpx_bot.shadow_matrix.engine import ShadowMatrixEngine
  from qpx_bot.shadow_matrix.checkpoint import serialize_checkpoint,restore_checkpoint
  from qpx_bot.shadow_matrix.models import MarketEvent
  r=load_registry();e=ShadowMatrixEngine(r);e.states["fixed_25"].accelerator_state["profit_recycling"]={"enabled":False,"ledger":ProfitSourceLedger(1300).as_dict()};blob=serialize_checkpoint(e);self.assertEqual(serialize_checkpoint(restore_checkpoint(blob,r)),blob)
  def handler(event,state):
   if state.configuration.shadow_id=="regime_stress_25":raise RuntimeError("isolated profit ledger failure")
   return "OK",{}
  e=ShadowMatrixEngine(r,handler=handler);e.dispatch(MarketEvent.create(sequence=1,timestamp=datetime(2026,8,12,tzinfo=timezone.utc),event_type="CLOSE",payload={}));self.assertEqual(set(e.quarantines),{"regime_stress_25"});self.assertEqual(e.states["fixed_25"].event_sequence,1)
 def test_protected_accelerators_and_top100_present(self):
  import QPX_RUN_CAPACITY_ARBITRATION_SHADOW_MATRIX as m
  self.assertEqual(len(m._top100()),100)
  for p in ("dynamic_sizing.py","pyramiding.py","capacity_arbitration.py","regime_allocation.py"):self.assertTrue((Path("qpx_bot/accelerators")/p).is_file())
if __name__=="__main__":unittest.main()
