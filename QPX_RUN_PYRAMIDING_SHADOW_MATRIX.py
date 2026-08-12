#!/usr/bin/env python3
"""Fixed-parameter Pyramiding V1 historical Shadow experiment."""
from __future__ import annotations
import csv,hashlib,inspect,json
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import QPX_RUN_ACCELERATOR_DYNAMIC_SIZING as dynamic
import QPX_RUN_CHALLENGER_ACCOUNT_ROBUSTNESS as robustness
import QPX_RUN_DYNAMIC_SIZING_PAIRED_CAPS as paired
import QPX_RUN_DYNAMIC_SIZING_ROBUSTNESS as compact
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.accelerators.dynamic_sizing import DynamicSizingV1
from qpx_bot.accelerators.pyramiding import PyramidingContext,PyramidingV1,load_pyramiding_config
from qpx_bot.portfolio import ClosedTrade,Portfolio
from qpx_bot.risk import buy_fill

ROOT=Path(__file__).resolve().parent; CONFIG_PATH=ROOT/"qpx_bot/accelerators/configs/pyramiding_v1.json"; REPORT_PARENT=ROOT/"reports/qpx_pyramiding_v1_shadow_matrix"; SUMMARY_PATH=ROOT/"docs/research_results/PYRAMIDING_V1_SHADOW_MATRIX_2026-08-12.json"
PERIODS=paired.PERIODS; CAP_ORDER=paired.CAP_ORDER; TREATMENTS=("fixed","pyramid","dynamic","dynamic_pyramid")

def _event_id(sequence,timestamp,symbol,price,atr):return hashlib.sha256(json.dumps({"sequence":sequence,"timestamp":timestamp.isoformat(),"symbol":symbol,"price":price,"atr":atr},sort_keys=True,separators=(",",":")).encode()).hexdigest()

class PyramidRunState:
 def __init__(self):self.positions={};self.decisions=[];self.additions=[];self.attributable_pnl=0.0;self.sequence=0

def _instrumented_run(original,callback):
 source=inspect.getsource(original); marker="        if clock.index >= INITIALIZATION_MARKET_BARS:\n"
 insertion="        pyramid_callback(portfolio=portfolio, portal=portal, bar_time=bar_time, indicators=indicators, indices=indices, income_shares=income_shares, last_close=last_close, config=config)\n\n"
 if source.count(marker)!=1:raise RuntimeError("Strict runner Pyramiding insertion boundary changed.")
 namespace=dict(strict.__dict__);namespace["pyramid_callback"]=callback;exec(compile(source.replace(marker,insertion+marker),strict.__file__,"exec"),namespace);return namespace[original.__name__]

@contextmanager
def pyramiding_scope(accelerator,hard_cap):
 state=PyramidRunState(); original_run=strict.run_strict; original_open=Portfolio.open_position; original_close=Portfolio.close_position
 def tracked_open(self,**kwargs):
  position=original_open(self,**kwargs);state.positions[position.symbol]={"original_shares":position.shares,"original_price":position.entry_price,"anchor":position.entry_price,"additions":[]};return position
 def tracked_close(self,**kwargs):
  symbol=kwargs["symbol"].strip().upper(); meta=state.positions.get(symbol); closed=original_close(self,**kwargs)
  if not meta or not meta["additions"]:state.positions.pop(symbol,None);return closed
  correction=sum((meta["original_price"]-x["fill_price"])*x["shares_added"] for x in meta["additions"]); actual_pnl=closed.pnl+correction; old_tax=closed.tax_reserved; actual_tax=max(0.0,actual_pnl)*kwargs["config"].annual_tax_reserve_rate; self.realized_pnl+=correction;self.tax_reserve_cash+=actual_tax-old_tax;self.cash-=actual_tax-old_tax;state.attributable_pnl+=sum((closed.exit_price-x["fill_price"])*x["shares_added"] for x in meta["additions"]);state.positions.pop(symbol,None)
  fixed=ClosedTrade(closed.symbol,closed.entry_date,closed.exit_date,closed.shares,closed.entry_price,closed.exit_price,actual_pnl,actual_tax,closed.reason,actual_pnl/(closed.result_r and closed.pnl/closed.result_r or 1));self.closed_trades[-1]=fixed;return fixed
 def callback(*,portfolio,portal,bar_time,indicators,indices,income_shares,last_close,config):
  q=portal.completed_bar("QDTE"); qprice=q.close if q else last_close.get("QDTE",0.0); marks={};
  for symbol in portfolio.positions:
   b=portal.completed_bar(symbol);marks[symbol]=b.close if b else last_close.get(symbol,0.0)
  equity=portfolio.equity(marks)+income_shares*qprice
  for symbol,position in list(portfolio.positions.items()):
   completed=portal.completed_bar(symbol);idx=indices[symbol].get(bar_time);atr=(indicators[symbol].atr[idx] if completed is not None and idx is not None else None);meta=state.positions.get(symbol)
   if meta is None:continue
   state.sequence+=1;price=completed.close if completed is not None else 0.0;event_id=_event_id(state.sequence,bar_time,symbol,price,atr)
   decision=accelerator.decide(PyramidingContext(bar_time,event_id,state.sequence,symbol,price,buy_fill(price,config.slippage_rate),float(atr) if atr and atr>0 else None,meta["original_price"],meta["original_shares"],position.shares,len(meta["additions"]),meta["anchor"],equity,portfolio.cash,portfolio.active_risk(),equity*config.maximum_active_portfolio_risk,position.active_risk,hard_cap));state.decisions.append(decision)
   if not decision.accepted:continue
   fill=buy_fill(price,config.slippage_rate);shares=decision.accepted_shares;cost=fill*shares
   if cost>portfolio.cash+1e-9:raise RuntimeError("Accepted pyramid addition exceeded cash.")
   position.shares+=shares;portfolio.cash-=cost;meta["anchor"]=fill;addition={"event_id":event_id,"event_sequence":state.sequence,"timestamp":bar_time.isoformat(),"fill_price":fill,"shares_added":shares,"atr_used":atr,"accelerator_configuration_fingerprint":accelerator.config.fingerprint,"decision_id":decision.decision_id};meta["additions"].append(addition);state.additions.append({"symbol":symbol,**addition})
  
 Portfolio.open_position=tracked_open;Portfolio.close_position=tracked_close;strict.run_strict=_instrumented_run(original_run,callback)
 try:yield state
 finally:strict.run_strict=original_run;Portfolio.open_position=original_open;Portfolio.close_position=original_close

def run_arm(period,cap,treatment):
 destination=REPORT_PARENT/period/f"{treatment}_{cap}"; config=load_pyramiding_config(CONFIG_PATH,enabled="pyramid" in treatment); accelerator=PyramidingV1(config)
 with paired.run_scope(period,cap),compact.output_paths(destination):
  if "dynamic" in treatment:
   dc=paired.experimental_config(cap)
   with dynamic.enabled_accelerator_scope(DynamicSizingV1(dc),strict.candidate_config()) as ds:
    if "pyramid" in treatment:
     with pyramiding_scope(accelerator,float(cap)/100) as ps:result,summary=strict.run_strict()
    else:result,summary=strict.run_strict();ps=PyramidRunState()
  elif "pyramid" in treatment:
   with pyramiding_scope(accelerator,float(cap)/100) as ps:result,summary=strict.run_strict()
   ds=None
  else:result,summary=strict.run_strict();ps=PyramidRunState();ds=None
 compact.verify_summary(summary);metrics=compact.compact_result(result,equity_path=destination/"equity.csv");metrics.update(pyramid_opportunities=len(ps.decisions),pyramid_additions=len(ps.additions),pyramid_rejections=sum(not x.accepted for x in ps.decisions),pyramid_shares_added=sum(x["shares_added"] for x in ps.additions),pyramid_notional_added=sum(x["shares_added"]*x["fill_price"] for x in ps.additions),pyramid_attributable_pnl=ps.attributable_pnl,dynamic_interventions=(sum(x.final_requested_shares<x.base_requested_shares for x in ds.decisions) if ds else 0));record={"period":period,"cap":float(cap)/100,"treatment":treatment,"dataset_fingerprint":summary["dataset_fingerprint"],"causal_gates":summary["gate"],"pyramiding_configuration_fingerprint":config.fingerprint,"metrics":metrics};strict.atomic_json(destination/"pyramiding.json",record);return record

def run_all():
 matrix={}
 for period in PERIODS:
  matrix[period]={}
  for cap in CAP_ORDER:matrix[period][cap]={t:run_arm(period,cap,t) for t in TREATMENTS}
 payload={"schema_version":1,"experiment":"pyramiding_v1_shadow_matrix","parameters":asdict(load_pyramiding_config(CONFIG_PATH)),"configuration_fingerprint":load_pyramiding_config(CONFIG_PATH).fingerprint,"periods":{k:[v[0].isoformat(),v[1].isoformat()] for k,v in PERIODS.items()},"matrix":matrix};strict.atomic_json(SUMMARY_PATH,payload);return payload
if __name__=="__main__":run_all()
