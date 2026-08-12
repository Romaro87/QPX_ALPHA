"""Hot-swappable, classification-only Profit Recycling V1 architecture."""
from __future__ import annotations
import hashlib,json,math
from dataclasses import asdict,dataclass,field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
VERSION="1.0.0"
def fingerprint(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
class ProfitSource(StrEnum):
 ORIGINAL_START_CAPITAL="ORIGINAL_START_CAPITAL";EXTERNAL_CONTRIBUTION="EXTERNAL_CONTRIBUTION";SWING_REALIZED_PROFIT="SWING_REALIZED_PROFIT";SWING_REALIZED_LOSS="SWING_REALIZED_LOSS";QDTE_DISTRIBUTION="QDTE_DISTRIBUTION";INCOME_REBALANCE_REALIZED_PNL="INCOME_REBALANCE_REALIZED_PNL";TAX_RESERVE="TAX_RESERVE";ORDINARY_SWING_CASH="ORDINARY_SWING_CASH"
class LossRecoveryMode(StrEnum):NONE="NONE";RECOVER_REALIZED_SWING_LOSSES_FIRST="RECOVER_REALIZED_SWING_LOSSES_FIRST"
class DelayUnit(StrEnum):EVENTS="EVENTS"
class Destination(StrEnum):SWING_REDEPLOYMENT_POOL="SWING_REDEPLOYMENT_POOL"
@dataclass(frozen=True,slots=True)
class ProfitRecyclingConfig:
 enabled:bool;accelerator_version:str;configuration_version:str;policy_identity:str|None;recycling_fraction:float=0.;minimum_recyclable_profit_dollars:float=0.;loss_recovery_mode:LossRecoveryMode=LossRecoveryMode.NONE;redeployment_delay:int=0;redeployment_delay_unit:DelayUnit=DelayUnit.EVENTS;destination:Destination=Destination.SWING_REDEPLOYMENT_POOL;eligible_profit_sources:tuple[ProfitSource,...]=(ProfitSource.SWING_REALIZED_PROFIT,)
 def validate(self):
  if type(self.enabled) is not bool or self.accelerator_version!=VERSION or not self.configuration_version.strip():raise ValueError("Unsupported Profit Recycling configuration")
  if type(self.recycling_fraction) not in (int,float) or not math.isfinite(self.recycling_fraction) or not 0<=self.recycling_fraction<=1:raise ValueError("Invalid recycling_fraction")
  if type(self.minimum_recyclable_profit_dollars) not in (int,float) or not math.isfinite(self.minimum_recyclable_profit_dollars) or self.minimum_recyclable_profit_dollars<0:raise ValueError("Invalid minimum threshold")
  if type(self.redeployment_delay) is not int or self.redeployment_delay<0:raise ValueError("Invalid causal delay")
  if self.destination!=Destination.SWING_REDEPLOYMENT_POOL or self.redeployment_delay_unit!=DelayUnit.EVENTS:raise ValueError("Unsupported V1 destination/delay unit")
  if self.eligible_profit_sources!=(ProfitSource.SWING_REALIZED_PROFIT,):raise ValueError("Only authoritative swing realized profit is eligible in V1")
  if self.enabled and not self.policy_identity:raise ValueError("Enabled configuration needs policy identity")
 @property
 def fingerprint(self):return fingerprint({k:(v.value if isinstance(v,StrEnum) else [x.value for x in v] if isinstance(v,tuple) else v) for k,v in asdict(self).items()})
 @classmethod
 def from_dict(cls,p):
  p=dict(p);p["loss_recovery_mode"]=LossRecoveryMode(p.get("loss_recovery_mode","NONE"));p["redeployment_delay_unit"]=DelayUnit(p.get("redeployment_delay_unit","EVENTS"));p["destination"]=Destination(p.get("destination","SWING_REDEPLOYMENT_POOL"));p["eligible_profit_sources"]=tuple(ProfitSource(x) for x in p.get("eligible_profit_sources",["SWING_REALIZED_PROFIT"]));c=cls(**p);c.validate();return c
@dataclass(frozen=True,slots=True)
class ProfitRecyclingContext:
 decision_timestamp:datetime;realized_event_id:str;event_sequence:int;realized_event_source:ProfitSource;gross_realized_pnl:float;tax_reserved:float;ordinary_investable_cash:float;recycled_profit_balance:float;current_portfolio_equity:float
 def __post_init__(self):
  if self.decision_timestamp.tzinfo is None or len(self.realized_event_id)!=64 or self.event_sequence<1:raise ValueError("Invalid causal event identity")
  for name in ("gross_realized_pnl","tax_reserved","ordinary_investable_cash","recycled_profit_balance","current_portfolio_equity"):
   v=getattr(self,name)
   if type(v) not in (int,float) or not math.isfinite(v):raise ValueError(f"Invalid {name}")
  if min(self.tax_reserved,self.ordinary_investable_cash,self.recycled_profit_balance,self.current_portfolio_equity)<0 or self.tax_reserved>max(0,self.gross_realized_pnl):raise ValueError("Invalid authoritative cash/tax state")
 @property
 def eligible_net_profit(self):return max(0.,self.gross_realized_pnl-self.tax_reserved) if self.realized_event_source==ProfitSource.SWING_REALIZED_PROFIT else 0.
@dataclass(frozen=True,slots=True)
class ProfitLot:
 source_event_id:str;source_event_sequence:int;realized_timestamp:str;gross_swing_profit:float;tax_reserved:float;eligible_after_tax_amount:float;configuration_fingerprint:str;recycling_fraction:float;recyclable_amount:float;withheld_until_rebalance_amount:float;eligibility_event_sequence:int;remaining_recyclable_amount:float;amount_consumed:float;amount_released_at_rebalance:float;status:str;lot_id:str
@dataclass(frozen=True,slots=True)
class ProfitRecyclingDecision:
 accelerator_version:str;configuration_fingerprint:str;policy_identity:str|None;timestamp:datetime;source_event_id:str;source_type:str;gross_realized_amount:float;attributable_tax_reserve:float;eligible_net_profit:float;amount_proposed_for_recycling:float;source_cash_balance_before:float;source_cash_balance_after:float;destination_identity:str;destination_amount:float;cumulative_recycled_amount:float;decision_reason:str;decision_id:str
@dataclass(slots=True)
class ProfitSourceLedger:
 original_start_capital:float;external_contributions:float=0.;gross_realized_swing_profit:float=0.;realized_swing_loss:float=0.;net_realized_swing_profit_after_tax:float=0.;qdte_distributions:float=0.;income_rebalance_realized_pnl:float=0.;tax_reserve_cash:float=0.;ordinary_unrestricted_swing_cash:float=0.;recycled_profit_balance:float=0.;withheld_profit_balance:float=0.;already_recycled_amount:float=0.;released_at_sleeve_rebalance:float=0.;loss_recovery_deficit:float=0.;profit_lots:list[ProfitLot]=field(default_factory=list);processed_source_event_ids:set[str]=field(default_factory=set);last_event_sequence:int=0
 def __post_init__(self):
  for v in (self.original_start_capital,self.external_contributions,self.gross_realized_swing_profit,self.net_realized_swing_profit_after_tax,self.qdte_distributions,self.tax_reserve_cash,self.ordinary_unrestricted_swing_cash,self.recycled_profit_balance,self.already_recycled_amount):
   if not math.isfinite(v) or v<0:raise ValueError("Corrupted profit ledger balance")
  if min(self.withheld_profit_balance,self.released_at_sleeve_rebalance,self.loss_recovery_deficit)<0 or self.recycled_profit_balance+self.withheld_profit_balance>self.ordinary_unrestricted_swing_cash+1e-9:raise ValueError("Classified profit exceeds authoritative cash")
 def record(self,c,config):
  config.validate()
  if c.realized_event_id in self.processed_source_event_ids:raise ValueError("DUPLICATE_REALIZED_EVENT")
  if c.event_sequence<=self.last_event_sequence:raise ValueError("OUT_OF_ORDER_REALIZED_EVENT")
  source=c.realized_event_source;eligible=c.eligible_net_profit
  if source==ProfitSource.SWING_REALIZED_PROFIT:self.gross_realized_swing_profit+=c.gross_realized_pnl;self.net_realized_swing_profit_after_tax+=eligible;self.tax_reserve_cash+=c.tax_reserved
  elif source==ProfitSource.SWING_REALIZED_LOSS:self.realized_swing_loss+=c.gross_realized_pnl;self.loss_recovery_deficit+=abs(c.gross_realized_pnl)
  elif source==ProfitSource.QDTE_DISTRIBUTION:self.qdte_distributions+=c.gross_realized_pnl
  elif source==ProfitSource.INCOME_REBALANCE_REALIZED_PNL:self.income_rebalance_realized_pnl+=c.gross_realized_pnl
  elif source==ProfitSource.EXTERNAL_CONTRIBUTION:self.external_contributions+=c.gross_realized_pnl
  candidate=eligible
  if config.loss_recovery_mode==LossRecoveryMode.RECOVER_REALIZED_SWING_LOSSES_FIRST:
   recovered=min(candidate,self.loss_recovery_deficit);self.loss_recovery_deficit-=recovered;candidate-=recovered
  recyclable=candidate*config.recycling_fraction if config.enabled and candidate>=config.minimum_recyclable_profit_dollars else 0.
  recyclable=min(recyclable,max(0.,c.ordinary_investable_cash-self.recycled_profit_balance-self.withheld_profit_balance));withheld=max(0.,eligible-recyclable);core={"source_event_id":c.realized_event_id,"source_event_sequence":c.event_sequence,"realized_timestamp":c.decision_timestamp.isoformat(),"gross_swing_profit":max(0,c.gross_realized_pnl),"tax_reserved":c.tax_reserved,"eligible_after_tax_amount":eligible,"configuration_fingerprint":config.fingerprint,"recycling_fraction":config.recycling_fraction,"recyclable_amount":recyclable,"withheld_until_rebalance_amount":withheld,"eligibility_event_sequence":c.event_sequence+config.redeployment_delay,"remaining_recyclable_amount":recyclable,"amount_consumed":0.,"amount_released_at_rebalance":0.,"status":"PENDING" if eligible else "INELIGIBLE"};lot=ProfitLot(**core,lot_id=fingerprint(core));self.profit_lots.append(lot);self.recycled_profit_balance+=recyclable;self.withheld_profit_balance+=withheld;self.ordinary_unrestricted_swing_cash=c.ordinary_investable_cash;self.processed_source_event_ids.add(c.realized_event_id);self.last_event_sequence=c.event_sequence;return lot
 def available_swing_cash(self,authoritative_cash,event_sequence):
  if authoritative_cash<0:raise ValueError("Authoritative cash cannot be negative")
  unavailable=self.withheld_profit_balance+sum(x.remaining_recyclable_amount for x in self.profit_lots if event_sequence<x.eligibility_event_sequence)
  if unavailable>authoritative_cash+1e-9:raise ValueError("Profit classifications exceed authoritative cash")
  return max(0.,authoritative_cash-unavailable)
 def consume(self,amount,event_sequence,authoritative_cash):
  if amount<0 or amount>authoritative_cash or amount>self.recycled_profit_balance:raise ValueError("Consumption exceeds classified/authoritative cash")
  remaining=amount;new=[]
  for lot in self.profit_lots:
   take=min(remaining,lot.remaining_recyclable_amount) if event_sequence>=lot.eligibility_event_sequence else 0.;remaining-=take;d=asdict(lot);d.update(remaining_recyclable_amount=lot.remaining_recyclable_amount-take,amount_consumed=lot.amount_consumed+take,status="CONSUMED" if lot.remaining_recyclable_amount==take else lot.status);new.append(ProfitLot(**d))
  if remaining>1e-9:raise ValueError("Eligible lots cannot satisfy consumption")
  self.profit_lots=new;self.recycled_profit_balance-=amount;self.already_recycled_amount+=amount;return amount
 def on_sleeve_rebalance(self,authoritative_cash,event_sequence):
  if self.withheld_profit_balance+self.recycled_profit_balance>authoritative_cash+1e-9:raise ValueError("Cannot settle classifications beyond authoritative cash")
  released=self.withheld_profit_balance+self.recycled_profit_balance;new=[]
  for lot in self.profit_lots:
   d=asdict(lot);d.update(amount_released_at_rebalance=lot.amount_released_at_rebalance+lot.withheld_until_rebalance_amount+lot.remaining_recyclable_amount,withheld_until_rebalance_amount=0.,remaining_recyclable_amount=0.,status="SETTLED_AT_SLEEVE_REBALANCE");new.append(ProfitLot(**d))
  self.profit_lots=new;self.withheld_profit_balance=0.;self.recycled_profit_balance=0.;self.released_at_sleeve_rebalance+=released;self.ordinary_unrestricted_swing_cash=authoritative_cash;self.last_event_sequence=max(self.last_event_sequence,event_sequence);return released
 def as_dict(self):return asdict(self)|{"processed_source_event_ids":sorted(self.processed_source_event_ids)}
 @classmethod
 def from_dict(cls,p):
  p=dict(p);p["profit_lots"]=[ProfitLot(**x) for x in p.get("profit_lots",[])];p["processed_source_event_ids"]=set(p.get("processed_source_event_ids",[]));o=cls(**p)
  if o.processed_source_event_ids!={x.source_event_id for x in o.profit_lots} or o.last_event_sequence!=(o.profit_lots[-1].source_event_sequence if o.profit_lots else 0):raise ValueError("Corrupted ledger continuity")
  return o
class ProfitRecyclingRuntime:
 def __init__(self,config,starting_capital):config.validate();self.active_config=config;self.config_history=[config.fingerprint];self.rejected_configurations=[];self.ledger=ProfitSourceLedger(starting_capital);self.decision_history=[]
 def replace_config(self,replacement):
  try:replacement.validate()
  except Exception as e:self.rejected_configurations.append({"fingerprint":fingerprint(asdict(replacement)),"reason":str(e)});return False
  self.active_config=replacement;self.config_history.append(replacement.fingerprint);return True
 def decide(self,c):
  lot=self.ledger.record(c,self.active_config);core={"accelerator_version":VERSION,"configuration_fingerprint":self.active_config.fingerprint,"policy_identity":self.active_config.policy_identity,"timestamp":c.decision_timestamp.isoformat(),"source_event_id":c.realized_event_id,"source_type":c.realized_event_source.value,"gross_realized_amount":c.gross_realized_pnl,"attributable_tax_reserve":c.tax_reserved,"eligible_net_profit":c.eligible_net_profit,"amount_proposed_for_recycling":lot.recyclable_amount,"source_cash_balance_before":c.ordinary_investable_cash,"source_cash_balance_after":c.ordinary_investable_cash,"destination_identity":self.active_config.destination.value,"destination_amount":lot.recyclable_amount,"cumulative_recycled_amount":self.ledger.recycled_profit_balance,"decision_reason":"CLASSIFIED_EXISTING_CASH" if lot.recyclable_amount else "DISABLED_OR_INELIGIBLE_NO_OP"};d=ProfitRecyclingDecision(**{k:v for k,v in core.items() if k!="timestamp"},timestamp=c.decision_timestamp,decision_id=fingerprint(core));self.decision_history.append(d);return d
 def as_dict(self):return {"active_config":asdict(self.active_config),"active_configuration_fingerprint":self.active_config.fingerprint,"config_history":self.config_history,"rejected_configurations":self.rejected_configurations,"ledger":self.ledger.as_dict(),"decision_history":[asdict(x)|{"timestamp":x.timestamp.isoformat()} for x in self.decision_history]}
class ProfitRecyclingV1:
 def __init__(self,c):c.validate();self.config=c
 def decide(self,c):return ProfitRecyclingRuntime(self.config,0).decide(c)
def load_profit_recycling_config(path:Path):return ProfitRecyclingConfig.from_dict(json.loads(path.read_text()))
