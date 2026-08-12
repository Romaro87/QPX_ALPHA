"""Source-aware Profit Recycling V1 accounting foundation; transfers disabled."""
from __future__ import annotations
import hashlib,json,math
from dataclasses import asdict,dataclass,field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
VERSION="1.0.0"
class ProfitSource(StrEnum):
 ORIGINAL_START_CAPITAL="ORIGINAL_START_CAPITAL";EXTERNAL_CONTRIBUTION="EXTERNAL_CONTRIBUTION";SWING_REALIZED_PROFIT="SWING_REALIZED_PROFIT";SWING_REALIZED_LOSS="SWING_REALIZED_LOSS";QDTE_DISTRIBUTION="QDTE_DISTRIBUTION";INCOME_REBALANCE_REALIZED_PNL="INCOME_REBALANCE_REALIZED_PNL";TAX_RESERVE="TAX_RESERVE";ORDINARY_SWING_CASH="ORDINARY_SWING_CASH"
@dataclass(frozen=True,slots=True)
class ProfitRecyclingConfig:
 enabled:bool;accelerator_version:str;configuration_version:str;policy_identity:str|None
 def validate(self):
  if type(self.enabled) is not bool or self.accelerator_version!=VERSION:raise ValueError("Unsupported Profit Recycling configuration")
  if self.enabled:raise ValueError("ENABLED_POLICY_NOT_DECLARED_OR_APPROVED")
  if self.policy_identity is not None:raise ValueError("Disabled foundation cannot declare policy")
 @property
 def fingerprint(self):return hashlib.sha256(json.dumps(asdict(self),sort_keys=True,separators=(",",":")).encode()).hexdigest()
@dataclass(frozen=True,slots=True)
class ProfitRecyclingContext:
 decision_timestamp:datetime;realized_event_id:str;event_sequence:int;realized_event_source:ProfitSource;gross_realized_pnl:float;tax_reserved:float;ordinary_investable_cash:float;recycled_profit_balance:float;current_portfolio_equity:float
 def __post_init__(self):
  if self.decision_timestamp.tzinfo is None or len(self.realized_event_id)!=64 or self.event_sequence<1:raise ValueError("Invalid causal event identity")
  for name in ("gross_realized_pnl","tax_reserved","ordinary_investable_cash","recycled_profit_balance","current_portfolio_equity"):
   v=getattr(self,name)
   if type(v) not in (int,float) or not math.isfinite(v):raise ValueError(f"Invalid {name}")
  if min(self.tax_reserved,self.ordinary_investable_cash,self.recycled_profit_balance,self.current_portfolio_equity)<0:raise ValueError("Balances cannot be negative")
  if self.realized_event_source==ProfitSource.SWING_REALIZED_PROFIT and self.gross_realized_pnl<=0:raise ValueError("Profit source must be positive")
  if self.realized_event_source==ProfitSource.SWING_REALIZED_LOSS and self.gross_realized_pnl>=0:raise ValueError("Loss source must be negative")
  if self.tax_reserved>max(0,self.gross_realized_pnl):raise ValueError("Tax reserve exceeds positive realized gain")
 @property
 def eligible_net_profit(self):return max(0.,self.gross_realized_pnl-self.tax_reserved) if self.realized_event_source==ProfitSource.SWING_REALIZED_PROFIT else 0.
@dataclass(frozen=True,slots=True)
class ProfitRecyclingDecision:
 accelerator_version:str;configuration_fingerprint:str;policy_identity:str|None;timestamp:datetime;source_event_id:str;source_type:str;gross_realized_amount:float;attributable_tax_reserve:float;eligible_net_profit:float;amount_proposed_for_recycling:float;source_cash_balance_before:float;source_cash_balance_after:float;destination_identity:str;destination_amount:float;cumulative_recycled_amount:float;decision_reason:str;decision_id:str
@dataclass(frozen=True,slots=True)
class ProfitLedgerEntry:
 event_id:str;event_sequence:int;timestamp:str;source_type:str;gross_amount:float;tax_reserved:float;eligible_net_profit:float;recycled_amount:float;entry_id:str
@dataclass(slots=True)
class ProfitSourceLedger:
 original_start_capital:float;external_contributions:float=0.;gross_realized_swing_profit:float=0.;realized_swing_loss:float=0.;net_realized_swing_profit_after_tax:float=0.;qdte_distributions:float=0.;income_rebalance_realized_pnl:float=0.;tax_reserve_cash:float=0.;ordinary_unrestricted_swing_cash:float=0.;recycled_profit_balance:float=0.;already_recycled_amount:float=0.;entries:list[ProfitLedgerEntry]=field(default_factory=list);seen_event_ids:set[str]=field(default_factory=set);last_event_sequence:int=0
 def __post_init__(self):
  for v in (self.original_start_capital,self.external_contributions,self.gross_realized_swing_profit,self.net_realized_swing_profit_after_tax,self.qdte_distributions,self.tax_reserve_cash,self.ordinary_unrestricted_swing_cash,self.recycled_profit_balance,self.already_recycled_amount):
   if not math.isfinite(v) or v<0:raise ValueError("Corrupted profit ledger balance")
  if not math.isfinite(self.realized_swing_loss) or not math.isfinite(self.income_rebalance_realized_pnl):raise ValueError("Corrupted signed ledger balance")
 def record(self,c:ProfitRecyclingContext,recycled_amount=0.):
  if c.realized_event_id in self.seen_event_ids:raise ValueError("DUPLICATE_REALIZED_EVENT")
  if c.event_sequence<=self.last_event_sequence:raise ValueError("OUT_OF_ORDER_REALIZED_EVENT")
  if recycled_amount<0 or recycled_amount>c.eligible_net_profit or recycled_amount>c.ordinary_investable_cash:raise ValueError("Recycled amount exceeds eligible cash")
  source=c.realized_event_source
  if source==ProfitSource.SWING_REALIZED_PROFIT:self.gross_realized_swing_profit+=c.gross_realized_pnl;self.net_realized_swing_profit_after_tax+=c.eligible_net_profit
  elif source==ProfitSource.SWING_REALIZED_LOSS:self.realized_swing_loss+=c.gross_realized_pnl
  elif source==ProfitSource.QDTE_DISTRIBUTION:self.qdte_distributions+=c.gross_realized_pnl
  elif source==ProfitSource.INCOME_REBALANCE_REALIZED_PNL:self.income_rebalance_realized_pnl+=c.gross_realized_pnl
  elif source==ProfitSource.EXTERNAL_CONTRIBUTION:self.external_contributions+=c.gross_realized_pnl
  elif source==ProfitSource.TAX_RESERVE:self.tax_reserve_cash+=c.tax_reserved
  self.recycled_profit_balance+=recycled_amount;self.already_recycled_amount+=recycled_amount;self.ordinary_unrestricted_swing_cash=c.ordinary_investable_cash-recycled_amount;core={"event_id":c.realized_event_id,"event_sequence":c.event_sequence,"timestamp":c.decision_timestamp.isoformat(),"source_type":source.value,"gross_amount":c.gross_realized_pnl,"tax_reserved":c.tax_reserved,"eligible_net_profit":c.eligible_net_profit,"recycled_amount":recycled_amount};entry=ProfitLedgerEntry(**core,entry_id=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":")).encode()).hexdigest());self.entries.append(entry);self.seen_event_ids.add(c.realized_event_id);self.last_event_sequence=c.event_sequence;return entry
 def as_dict(self):return asdict(self)|{"seen_event_ids":sorted(self.seen_event_ids)}
 @classmethod
 def from_dict(cls,p):
  p=dict(p);p["entries"]=[ProfitLedgerEntry(**x) for x in p.get("entries",[])];p["seen_event_ids"]=set(p.get("seen_event_ids",[]));obj=cls(**p)
  if obj.seen_event_ids!={x.event_id for x in obj.entries} or obj.last_event_sequence!=(obj.entries[-1].event_sequence if obj.entries else 0):raise ValueError("Corrupted profit ledger continuity")
  return obj
class ProfitRecyclingV1:
 def __init__(self,c):c.validate();self.config=c
 def decide(self,c):
  eligible=c.eligible_net_profit;core={"accelerator_version":VERSION,"configuration_fingerprint":self.config.fingerprint,"policy_identity":None,"timestamp":c.decision_timestamp.isoformat(),"source_event_id":c.realized_event_id,"source_type":c.realized_event_source.value,"gross_realized_amount":c.gross_realized_pnl,"attributable_tax_reserve":c.tax_reserved,"eligible_net_profit":eligible,"amount_proposed_for_recycling":0.,"source_cash_balance_before":c.ordinary_investable_cash,"source_cash_balance_after":c.ordinary_investable_cash,"destination_identity":"NONE_DISABLED","destination_amount":0.,"cumulative_recycled_amount":c.recycled_profit_balance,"decision_reason":"DISABLED_EXACT_NO_OP"};return ProfitRecyclingDecision(**{k:v for k,v in core.items() if k!="timestamp"},timestamp=c.decision_timestamp,decision_id=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":")).encode()).hexdigest())
def load_profit_recycling_config(path:Path):c=ProfitRecyclingConfig(**json.loads(path.read_text()));c.validate();return c
