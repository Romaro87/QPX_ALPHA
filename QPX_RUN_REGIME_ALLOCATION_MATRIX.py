#!/usr/bin/env python3
"""Predeclared, resumable Regime Allocation V1 research matrix."""
from __future__ import annotations
import csv,inspect,json
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import QPX_RUN_DYNAMIC_SIZING_PAIRED_CAPS as paired
import QPX_RUN_DYNAMIC_SIZING_ROBUSTNESS as compact
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.accelerators.regime_allocation import RegimeAllocationContext,RegimeAllocationV1,load_regime_allocation_config
ROOT=Path(__file__).resolve().parent;REPORT_PARENT=ROOT/"reports/qpx_regime_allocation_v1";SUMMARY_PATH=ROOT/"docs/research_results/REGIME_ALLOCATION_V1_MATRIX_2026-08-12.json"
PERIODS=paired.PERIODS;CAP_ORDER=paired.CAP_ORDER;POLICIES=("stress_income_shift_v1","calm_swing_shift_v1","two_sided_ladder_v1")
FILES={"stress_income_shift_v1":"regime_stress_income_shift_v1.json","calm_swing_shift_v1":"regime_calm_swing_shift_v1.json","two_sided_ladder_v1":"regime_two_sided_ladder_v1.json"}
class RunState:
 def __init__(self):self.decisions=[];self.regimes=Counter();self.previous=None;self.changes=0;self.trades=0;self.noops=0;self.minimum=0;self.partial=0;self.buys=0;self.sells=0;self.value=0.;self.pnl=0.;self.tax=0.;self.actual=Counter();self.targets=0.
@contextmanager
def regime_scope(policy):
 state=RunState();cfg=load_regime_allocation_config(ROOT/"qpx_bot/accelerators/configs"/FILES[policy]);accelerator=RegimeAllocationV1(cfg);original=strict.qpx._apply_rebalance
 def apply(**kwargs):
  if kwargs["target_income_weight"]==.125 and "bar_time" in inspect.currentframe().f_back.f_locals:
   frame=inspect.currentframe().f_back;day=frame.f_locals.get("bar_time").date();dates=frame.f_locals["vix_dates"];closes=frame.f_locals["vix_closes"];idx=__import__('bisect').bisect_left(dates,day)-1
   if idx<0:raise ValueError("MISSING_PREVIOUS_VIX_FAIL_CLOSED")
   obs=dates[idx];vix=strict.previous_vix_value(day=day,close_dates=dates,closes=closes);portfolio=kwargs["portfolio"];qdte=kwargs["income_shares"]*kwargs["qdte_price"];swing=portfolio.market_value(kwargs["position_prices"]);equity=qdte+swing+portfolio.cash
   context=RegimeAllocationContext(frame.f_locals["bar_time"],__import__('datetime').datetime.combine(obs,__import__('datetime').time(21),tzinfo=frame.f_locals["bar_time"].tzinfo),vix,.125,qdte/equity if equity else 0,portfolio.cash,swing,equity);decision=accelerator.decide(context);kwargs["target_income_weight"]=decision.proposed_target_qdte_weight;state.decisions.append(decision);state.regimes[decision.regime_identity]+=1;state.targets+=decision.proposed_target_qdte_weight
   if state.previous is not None and state.previous!=decision.regime_identity:state.changes+=1
   state.previous=decision.regime_identity
  result=original(**kwargs);reb=result[2]
  if state.decisions:
   if reb.action=="NONE":state.noops+=1
   else:state.trades+=1
   state.minimum+=int("MINIMUM" in reb.action);state.partial+=int(reb.action.startswith("BUY") and not reb.target_fully_reached);state.buys+=int(reb.shares_delta>0);state.sells+=int(reb.shares_delta<0);state.value+=reb.market_value_traded;state.pnl+=reb.realized_pnl;state.tax+=reb.tax_reserved;state.actual[state.previous]+=reb.after_income_weight
  return result
 strict.qpx._apply_rebalance=apply
 try:yield state,cfg
 finally:strict.qpx._apply_rebalance=original
def trade_risk(destination):
 rows=list(csv.DictReader((destination/"trades.csv").open()));losses=[r for r in rows if float(r["PnL"])<0];gaps=[r for r in losses if r["ExitReason"]=="STOP_GAP"];return {"largest_loss":min((float(r["PnL"]) for r in losses),default=None),"gap_loss_count":len(gaps),"gap_loss_total":sum(float(r["PnL"]) for r in gaps)}
def run_arm(period,cap,policy):
 destination=REPORT_PARENT/period/f"{policy}_{cap}";path=destination/"regime_allocation.json"
 if path.exists():return json.loads(path.read_text())
 with paired.run_scope(period,cap),compact.output_paths(destination),regime_scope(policy) as (s,cfg):result,summary=strict.run_strict()
 compact.verify_summary(summary);m=compact.compact_result(result,equity_path=destination/"equity.csv");m.update(trade_risk(destination));n=len(s.decisions);m.update(regime_allocation_decisions=n,regime_changes=s.changes,weekly_rebalances_considered=n,allocation_trades_executed=s.trades,allocation_noops_within_tolerance=s.noops,allocation_deferred_minimum_trade=s.minimum,allocation_partial_buys=s.partial,allocation_qdte_buys=s.buys,allocation_qdte_sells=s.sells,qdte_market_value_traded=s.value,allocation_realized_pnl=s.pnl,allocation_tax_reserved=s.tax,regime_decision_counts=dict(s.regimes),average_target_qdte_weight=s.targets/n if n else None,average_actual_qdte_weight_by_regime={k:s.actual[k]/s.regimes[k] for k in s.regimes if s.regimes[k]})
 record={"schema_version":1,"period":period,"cap":float(cap)/100,"policy":policy,"policy_version":"1.0.0","configuration_fingerprint":cfg.fingerprint,"dataset_fingerprint":summary["dataset_fingerprint"],"causal_gates":summary["gate"],"metrics":m,"decision_ids":[d.decision_id for d in s.decisions]};strict.atomic_json(path,record);return record
def assemble_from_parallel(manifest_path,output_path=SUMMARY_PATH):
 manifest=json.loads(Path(manifest_path).read_text());controls=json.loads((ROOT/"docs/research_results/CAPACITY_ARBITRATION_V1_SHADOW_MATRIX_2026-08-12.json").read_text());matrix={};comparisons={};fields=("ending_equity","cagr","eod_maximum_drawdown","intraday_maximum_drawdown","sharpe","sortino","total_return")
 for job in manifest["jobs"]:
  arm=json.loads(Path(job["result_artifact"]).read_text());period=arm["period"];cap=str(round(arm["cap"]*100));policy=arm["policy"];control=controls["matrix"][period][cap]["hash_control"];matrix.setdefault(period,{}).setdefault(cap,{})[policy]=arm;comparisons.setdefault(policy,{}).setdefault(cap,{})[period]={f:arm["metrics"][f]-control["metrics"][f] for f in fields}
 robustness={}
 for policy in POLICIES:
  robustness[policy]={}
  for field in ("total_return","eod_maximum_drawdown","intraday_maximum_drawdown","sharpe","sortino"):
   values=[comparisons[policy][cap][period][field] for cap in CAP_ORDER for period in PERIODS];lower=field.endswith("drawdown");robustness[policy][field]={"wins":sum(x<0 if lower else x>0 for x in values),"losses":sum(x>0 if lower else x<0 for x in values),"ties":sum(x==0 for x in values)}
 payload={"schema_version":1,"experiment":"regime_allocation_v1_predeclared_matrix","promotion_claim":False,"policies":list(POLICIES),"periods":list(PERIODS),"caps":list(CAP_ORDER),"jobs":60,"matrix":matrix,"differences_from_matching_hash_control":comparisons,"robustness":robustness};strict.atomic_json(Path(output_path),payload);return payload
