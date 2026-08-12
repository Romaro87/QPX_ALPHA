#!/usr/bin/env python3
"""Fixed-policy, resumable Capacity Arbitration V1 historical experiment."""
from __future__ import annotations
import csv,json
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import QPX_RUN_DYNAMIC_SIZING_PAIRED_CAPS as paired
import QPX_RUN_DYNAMIC_SIZING_ROBUSTNESS as compact
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.accelerators.capacity_arbitration import CapacityArbitrationConfig,CapacityArbitrationContext,CapacityArbitrationV1,CapacityCandidate,POLICIES,selection_divergence,tie_identity
from qpx_bot.portfolio import Portfolio

ROOT=Path(__file__).resolve().parent
REPORT_PARENT=ROOT/"reports/qpx_capacity_arbitration_v1_shadow_matrix"
SUMMARY_PATH=ROOT/"docs/research_results/CAPACITY_ARBITRATION_V1_SHADOW_MATRIX_2026-08-12.json"
PERIODS=paired.PERIODS;CAP_ORDER=paired.CAP_ORDER;POLICY_ORDER=POLICIES

class ArbitrationRunState:
 def __init__(self):
  self.decisions=[];self.divergences=[];self.inputs={};self.selected=set();self.filled=set();self.signal_events=0;self.collision_candidates=0;self.selected_ranks=[];self.deferred_ranks=[];self.selected_scores=[];self.deferred_scores=[]

def _top100():
 payload=json.loads(strict.baseline.SELECTION_PATH.read_text(encoding="utf-8"));symbols=tuple(str(x).strip().upper() for x in payload["top100"])
 if len(symbols)!=100 or len(set(symbols))!=100:raise RuntimeError("Frozen Top100 identity changed.")
 return symbols

@contextmanager
def arbitration_scope(policy):
 state=ArbitrationRunState();top100=_top100();ranks={s:i+1 for i,s in enumerate(top100)};accelerator=CapacityArbitrationV1(CapacityArbitrationConfig(policy));original_inputs=strict.strict_entry_inputs;original_choose=strict.choose_without_ranking;original_open=Portfolio.open_position
 def tracked_inputs(**kwargs):
  value=original_inputs(**kwargs)
  if value is not None:state.inputs[(kwargs["timestamp"],kwargs["symbol"].upper())]=value
  return value
 def choose(*,signal_bar,qualifying,available_slots):
  symbols=tuple(dict.fromkeys(str(x).strip().upper() for x in qualifying if str(x).strip()));state.signal_events+=bool(symbols)
  items=[]
  for symbol in symbols:
   value=state.inputs.get((signal_bar,symbol))
   if value is None:raise ValueError("MISSING_CAUSAL_INPUT_FAIL_CLOSED")
   items.append(CapacityCandidate(symbol,value.current_close,value.prior_high,value.current_atr,value.current_fast,value.current_slow,value.current_volume,value.baseline_volume,ranks[symbol],tie_identity(signal_bar,symbol)))
  context=CapacityArbitrationContext(signal_bar,available_slots,tuple(items));decision=accelerator.decide(context)
  if len(items)>available_slots:
   state.decisions.append(decision);state.collision_candidates+=len(items);control=original_choose(signal_bar=signal_bar,qualifying=symbols,available_slots=available_slots)[0];state.divergences.append(selection_divergence(decision,control))
   score_by={x.symbol:x.priority for x in decision.scores}
   state.selected_ranks.extend(ranks[x] for x in decision.selected_candidates);state.deferred_ranks.extend(ranks[x] for x in decision.deferred_candidates)
   if policy not in ("hash_control","frozen_order"):
    state.selected_scores.extend(float(score_by[x]) for x in decision.selected_candidates);state.deferred_scores.extend(float(score_by[x]) for x in decision.deferred_candidates)
  state.selected.update((signal_bar,x) for x in decision.selected_candidates)
  return decision.selected_candidates,decision.deferred_candidates
 def tracked_open(self,**kwargs):
  position=original_open(self,**kwargs);symbol=position.symbol;matches=[x for x in state.selected if x[1]==symbol]
  if matches:state.filled.add(max(matches,key=lambda x:x[0]))
  return position
 strict.strict_entry_inputs=tracked_inputs;strict.choose_without_ranking=choose;Portfolio.open_position=tracked_open
 try:yield state,accelerator
 finally:strict.strict_entry_inputs=original_inputs;strict.choose_without_ranking=original_choose;Portfolio.open_position=original_open

def _trade_risk(destination):
 rows=list(csv.DictReader((destination/"trades.csv").open(newline="",encoding="utf-8")));losses=[x for x in rows if float(x["PnL"])<0];gaps=[x for x in losses if x["ExitReason"]=="STOP_GAP"]
 def item(row):return None if row is None else {"symbol":row["Symbol"],"pnl":float(row["PnL"]),"exit_reason":row["ExitReason"],"entry_timestamp":row["EntryTimestampMarket"],"exit_timestamp":row["ExitTimestampMarket"]}
 return {"largest_trade_loss":item(min(losses,key=lambda x:float(x["PnL"]),default=None)),"largest_overnight_gap_loss":item(min(gaps,key=lambda x:float(x["PnL"]),default=None)),"overnight_gap_loss_count":len(gaps),"overnight_gap_loss_total":sum(float(x["PnL"]) for x in gaps)}

def run_arm(period,cap,policy):
 destination=REPORT_PARENT/period/f"{policy}_{cap}";result_path=destination/"capacity_arbitration.json"
 if result_path.exists():return json.loads(result_path.read_text())
 with paired.run_scope(period,cap),compact.output_paths(destination),arbitration_scope(policy) as (state,accelerator):result,summary=strict.run_strict()
 compact.verify_summary(summary);metrics=compact.compact_result(result,equity_path=destination/"equity.csv");metrics.update(_trade_risk(destination));collisions=len(state.decisions);different=sum(x.hash_selected!=x.alternative_selected for x in state.divergences);metrics.update(arbitration_events=collisions,capacity_constrained_events=collisions,signal_events=state.signal_events,percentage_signal_events_constrained=(collisions/state.signal_events if state.signal_events else 0.0),qualifying_candidates_at_collision=state.collision_candidates,average_competing_candidates=(state.collision_candidates/collisions if collisions else 0.0),selected_candidates=sum(len(x.selected_candidates) for x in state.decisions),deferred_candidates=sum(len(x.deferred_candidates) for x in state.decisions),fills_after_selection=len(state.filled),post_selection_entry_rejections=max(0,len(state.selected)-len(state.filled)),average_selected_frozen_rank=(sum(state.selected_ranks)/len(state.selected_ranks) if state.selected_ranks else None),average_deferred_frozen_rank=(sum(state.deferred_ranks)/len(state.deferred_ranks) if state.deferred_ranks else None),selected_frozen_rank_distribution=state.selected_ranks,deferred_frozen_rank_distribution=state.deferred_ranks,selected_score_distribution=state.selected_scores,deferred_score_distribution=state.deferred_scores,selection_divergence_from_hash_control=different,selection_divergence_rate=(different/collisions if collisions else 0.0))
 record={"schema_version":1,"period":period,"cap":float(cap)/100,"policy":policy,"policy_version":"1.0.0","configuration_fingerprint":accelerator.config.fingerprint,"dataset_fingerprint":summary["dataset_fingerprint"],"causal_gates":summary["gate"],"metrics":metrics,"divergences":[asdict(x)|{"event_timestamp":x.event_timestamp.isoformat()} for x in state.divergences]};strict.atomic_json(result_path,record);return record

def assemble():
 matrix={p:{c:{policy:run_arm(p,c,policy) for policy in POLICY_ORDER} for c in CAP_ORDER} for p in PERIODS};payload={"schema_version":1,"experiment":"capacity_arbitration_v1_shadow_matrix","policies":POLICY_ORDER,"fingerprints":{p:CapacityArbitrationConfig(p).fingerprint for p in POLICY_ORDER},"periods":{k:[v[0].isoformat(),v[1].isoformat()] for k,v in PERIODS.items()},"matrix":matrix};strict.atomic_json(SUMMARY_PATH,payload);return payload

if __name__=="__main__":assemble()
