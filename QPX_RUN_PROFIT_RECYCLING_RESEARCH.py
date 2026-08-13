#!/usr/bin/env python3
"""Configuration-driven Profit Recycling research integration over protected Candidate V1."""
from __future__ import annotations
import argparse,hashlib,json
from contextlib import contextmanager
from dataclasses import asdict,dataclass,field,replace
from pathlib import Path
import QPX_RUN_DYNAMIC_SIZING_PAIRED_CAPS as paired
import QPX_RUN_DYNAMIC_SIZING_ROBUSTNESS as compact
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.accelerators.profit_recycling import ProfitRecyclingContext,ProfitRecyclingRuntime,ProfitSource,load_profit_recycling_config
from qpx_bot.portfolio import Portfolio
from qpx_bot.risk import calculate_position_size
ROOT=Path(__file__).resolve().parent

def causal_gates_pass(gates):
    """Return the authoritative causal qualification result, not diagnostic labels."""
    return isinstance(gates,dict) and gates.get("OVERALL_PORTFOLIO_QUALIFICATION")=="FULL_CAUSAL_ACCOUNTING_PASS"
@dataclass(slots=True)
class RunState:
 runtime:object;event_sequence:int=0;current_event_sequence:int=0;deferrals:int=0;reductions:int=0;used:float=0.;matured:float=0.;decisions:list=field(default_factory=list)
@contextmanager
def profit_recycling_scope(config_path):
 config=load_profit_recycling_config(Path(config_path));state=RunState(ProfitRecyclingRuntime(config,strict.candidate_config().starting_cash));original_close=Portfolio.close_position;original_size=strict.calculate_position_size;original_rebalance=strict.qpx._apply_rebalance;original_open=Portfolio.open_position
 def close(self,**kwargs):
  trade=original_close(self,**kwargs);state.event_sequence+=1;state.current_event_sequence=state.event_sequence;source=ProfitSource.SWING_REALIZED_PROFIT if trade.pnl>0 else ProfitSource.SWING_REALIZED_LOSS;event_id=hashlib.sha256(f"{trade.symbol}|{trade.entry_date}|{trade.exit_date}|{len(self.closed_trades)}|{trade.pnl:.12f}".encode()).hexdigest();c=ProfitRecyclingContext(__import__('datetime').datetime.combine(trade.exit_date,__import__('datetime').time(21),tzinfo=__import__('datetime').timezone.utc),event_id,state.event_sequence,source,trade.pnl,trade.tax_reserved,self.cash,state.runtime.ledger.recycled_profit_balance,self.cash+self.tax_reserve_cash);state.decisions.append(state.runtime.decide(c));return trade
 def size(**kwargs):
  state.current_event_sequence=max(state.current_event_sequence,state.event_sequence+1);deployable=state.runtime.ledger.available_swing_cash(kwargs["available_cash"],state.current_event_sequence);original_cash=kwargs["available_cash"];kwargs["available_cash"]=deployable;result=original_size(**kwargs)
  if deployable+1e-9<original_cash:state.reductions+=1
  if deployable<=0<original_cash:state.deferrals+=1
  return result
 def rebalance(**kwargs):
  state.event_sequence+=1;state.current_event_sequence=state.event_sequence;state.runtime.ledger.on_sleeve_rebalance(kwargs["portfolio"].cash,state.event_sequence);return original_rebalance(**kwargs)
 def opened(self,**kwargs):
  before=self.cash;position=original_open(self,**kwargs);cost=before-self.cash;available=state.runtime.ledger.available_swing_cash(before,state.current_event_sequence);used=min(cost,state.runtime.ledger.recycled_profit_balance) if cost<=available+1e-9 else 0.
  if used:state.runtime.ledger.consume(used,state.current_event_sequence,before);state.used+=used
  return position
 Portfolio.close_position=close;strict.calculate_position_size=size;strict.qpx._apply_rebalance=rebalance;Portfolio.open_position=opened
 try:yield state,config
 finally:Portfolio.close_position=original_close;strict.calculate_position_size=original_size;strict.qpx._apply_rebalance=original_rebalance;Portfolio.open_position=original_open
def run_arm(period,cap,config_path,output):
 destination=Path(output);path=destination/"profit_recycling.json"
 if path.exists():return json.loads(path.read_text())
 with paired.run_scope(period,cap),compact.output_paths(destination),profit_recycling_scope(config_path) as (s,c):result,summary=strict.run_strict()
 compact.verify_summary(summary);m=compact.compact_result(result,equity_path=destination/"equity.csv");l=s.runtime.ledger;m.update(gross_realized_swing_profit=l.gross_realized_swing_profit,tax_reserved=l.tax_reserve_cash,eligible_after_tax_profit=l.net_realized_swing_profit_after_tax,amount_immediately_recyclable=sum(x.recyclable_amount for x in l.profit_lots),amount_withheld=sum(x.eligible_net_profit-x.amount_proposed_for_recycling for x in s.decisions),number_of_profit_lots=len(l.profit_lots),amount_used_by_later_trades=l.already_recycled_amount,amount_released_at_sleeve_rebalance=l.released_at_sleeve_rebalance,unused_recycled_amount=l.recycled_profit_balance,profit_recycling_entry_deferrals=s.deferrals,profit_recycling_entry_reductions=s.reductions,configuration_history=s.runtime.config_history);record={"schema_version":1,"period":period,"cap":float(cap)/100,"configuration_fingerprint":c.fingerprint,"configuration":{k:(v.value if hasattr(v,'value') else [x.value for x in v] if isinstance(v,tuple) else v) for k,v in asdict(c).items()},"dataset_fingerprint":summary["dataset_fingerprint"],"causal_gates":summary["gate"],"metrics":m,"decision_ids":[x.decision_id for x in s.decisions]};strict.atomic_json(path,record);return record
def main():
 p=argparse.ArgumentParser();p.add_argument("--period",required=True);p.add_argument("--cap",required=True);p.add_argument("--config",required=True);p.add_argument("--output-directory",required=True);a=p.parse_args();print(run_arm(a.period,a.cap,a.config,a.output_directory))
if __name__=="__main__":main()
