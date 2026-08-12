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
  lot=ProfitSourceLedger(100,ordinary_unrestricted_swing_cash=500).record(c,ProfitRecyclingConfig(True,"1.0.0","x","x",1.0));self.assertEqual(lot.recyclable_amount,80)
 def test_losses_and_nontrade_sources_are_ineligible(self):
  for source,pnl in ((ProfitSource.SWING_REALIZED_LOSS,-20),(ProfitSource.QDTE_DISTRIBUTION,10),(ProfitSource.INCOME_REBALANCE_REALIZED_PNL,10),(ProfitSource.EXTERNAL_CONTRIBUTION,10),(ProfitSource.ORIGINAL_START_CAPITAL,100)):
   self.assertEqual(self.context(source=source,pnl=pnl,tax=0).eligible_net_profit,0)
 def test_unrealized_source_does_not_exist(self):self.assertNotIn("UNREALIZED",{x.value for x in ProfitSource})
 def test_duplicate_and_out_of_order_fail_closed(self):
  l=ProfitSourceLedger(1300);l.record(self.context(2),self.config())
  with self.assertRaisesRegex(ValueError,"DUPLICATE"):l.record(self.context(2),self.config())
  with self.assertRaisesRegex(ValueError,"OUT_OF_ORDER"):l.record(self.context(seq=1),self.config())
 def test_source_taxonomy_is_separate_and_no_double_count(self):
  l=ProfitSourceLedger(1300);l.record(self.context(1),self.config());l.record(self.context(2,ProfitSource.SWING_REALIZED_LOSS,-30,0),self.config());l.record(self.context(3,ProfitSource.QDTE_DISTRIBUTION,15,0),self.config());l.record(self.context(4,ProfitSource.INCOME_REBALANCE_REALIZED_PNL,5,0),self.config());l.record(self.context(5,ProfitSource.EXTERNAL_CONTRIBUTION,25,0),self.config());self.assertEqual((l.gross_realized_swing_profit,l.realized_swing_loss,l.net_realized_swing_profit_after_tax,l.qdte_distributions,l.income_rebalance_realized_pnl,l.external_contributions),(100,-30,80,15,5,25))
 def test_checkpoint_roundtrip_and_corruption(self):
  l=ProfitSourceLedger(1300);l.record(self.context(2),self.config());p=json.loads(json.dumps(l.as_dict()));self.assertEqual(ProfitSourceLedger.from_dict(p).as_dict(),l.as_dict());p["processed_source_event_ids"]=[]
  with self.assertRaises(ValueError):ProfitSourceLedger.from_dict(p)
 def test_principal_cannot_be_fabricated_or_recycled(self):
  l=ProfitSourceLedger(1300)
  lot=l.record(self.context(source=ProfitSource.ORIGINAL_START_CAPITAL,pnl=1300,tax=0),ProfitRecyclingConfig(True,"1.0.0","x","x",1.0));self.assertEqual(lot.recyclable_amount,0)
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
 def enabled(self,version="a",fraction=.5,minimum=0,mode=LossRecoveryMode.NONE,delay=0):return ProfitRecyclingConfig(True,"1.0.0",version,version,fraction,minimum,mode,delay,DelayUnit.EVENTS,Destination.SWING_REDEPLOYMENT_POOL,(ProfitSource.SWING_REALIZED_PROFIT,))
 def test_hot_swap_all_parameters_future_only_and_lot_provenance(self):
  a=self.enabled(fraction=.5);b=self.enabled("b",.75,25,LossRecoveryMode.RECOVER_REALIZED_SWING_LOSSES_FIRST,2);r=ProfitRecyclingRuntime(a,1300);r.decide(self.context(1));old=r.ledger.profit_lots[0];self.assertTrue(r.replace_config(b));r.decide(self.context(2));new=r.ledger.profit_lots[1];self.assertEqual((old.recycling_fraction,old.configuration_fingerprint),(.5,a.fingerprint));self.assertEqual((new.recycling_fraction,new.configuration_fingerprint,new.eligibility_event_sequence),(.75,b.fingerprint,4));self.assertNotEqual(a.fingerprint,b.fingerprint);self.assertEqual(a.fingerprint,self.enabled(fraction=.5).fingerprint)
 def test_runtime_enable_disable_and_invalid_atomic_replacement(self):
  r=ProfitRecyclingRuntime(self.config(),1300);self.assertTrue(r.replace_config(self.enabled()));active=r.active_config;bad=self.enabled(fraction=2);self.assertFalse(r.replace_config(bad));self.assertEqual(r.active_config,active);self.assertEqual(len(r.rejected_configurations),1)
 def test_destination_and_sources_fail_closed(self):
  p=asdict(self.enabled());p["destination"]="QDTE"
  with self.assertRaises(ValueError):ProfitRecyclingConfig.from_dict(p)
  p=asdict(self.enabled());p["eligible_profit_sources"]=["QDTE_DISTRIBUTION"]
  with self.assertRaises(ValueError):ProfitRecyclingConfig.from_dict(p)
 def test_zero_and_nonzero_delay_consumption_are_deterministic_no_cash_creation(self):
  for delay in (0,2):
   r=ProfitRecyclingRuntime(self.enabled(delay=delay),1300);r.decide(self.context(1));lot=r.ledger.profit_lots[0];before=500;event=1+delay;used=r.ledger.consume(lot.recyclable_amount,event,before);self.assertEqual(used,40);self.assertEqual(before,500);self.assertEqual(r.ledger.recycled_profit_balance,0)
 def test_consumption_cannot_bypass_authoritative_limits(self):
  r=ProfitRecyclingRuntime(self.enabled(),1300);r.decide(self.context(1))
  for amount,cash in ((41,500),(40,39)):
   with self.assertRaises(ValueError):r.ledger.consume(amount,1,cash)
 def test_runtime_checkpoint_payload_preserves_configs_lots_and_decisions(self):
  r=ProfitRecyclingRuntime(self.enabled(),1300);r.decide(self.context(1));r.replace_config(self.enabled("b",.75));r.decide(self.context(2));p=json.loads(json.dumps(r.as_dict()));self.assertEqual(p["active_configuration_fingerprint"],r.active_config.fingerprint);self.assertEqual([x["configuration_fingerprint"] for x in p["ledger"]["profit_lots"]],[self.enabled().fingerprint,self.enabled("b",.75).fingerprint]);self.assertEqual(len(p["decision_history"]),2)
if __name__=="__main__":unittest.main()
