"""Additive live-paper valuation and recorded-event performance; no trading authority."""
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


def event_totals(records: list[dict]) -> dict[str, Any]:
    entries = closed = wins = losses = 0
    positive = negative = 0.0
    unknown = False
    rejections: dict[str, int] = {}
    for record in records:
        kind, details = record["event_type"], record["details"]
        if kind == "SIMULATED_ENTRY_FILLED":
            entries += 1
        if kind in {"SIMULATED_EXIT_FILLED", "SIMULATED_OPEN_EXIT_FILLED"}:
            closed += 1
            if "realized_pnl" not in details:
                unknown = True
                continue
            pnl = float(details["realized_pnl"])
            wins += pnl > 0
            losses += pnl < 0
            positive += max(0.0, pnl)
            negative += max(0.0, -pnl)
        if kind in {
            "IEX_RESEARCH_ENTRY_EXECUTION_MISSED",
            "LIVE_PAPER_ENTRY_EXECUTION_MISSED",
        }:
            reason = str(details["reason"])
            rejections[reason] = rejections.get(reason, 0) + 1
    return {
        "filled_entries": entries, "closed_trades": closed,
        "wins": None if unknown else wins, "losses": None if unknown else losses,
        "win_rate": wins / closed if closed and not unknown else None,
        "profit_factor": positive / negative if negative and not unknown else None,
        "profit_factor_unavailable_reason": (
            "LEGACY_EXIT_PNL_NOT_RECORDED" if unknown else
            "NO_LOSING_TRADES" if not negative else None
        ),
        "realized_trade_pnl": None if unknown else positive - negative,
        "rejections_by_reason": rejections,
        "dividends_recorded": sum(float(r["details"]["entitled_shares"]) * float(r["details"]["rate"])
                                  for r in records if r["event_type"] == "QDTE_DIVIDEND_ENTITLEMENT_RECORDED"),
        "dividends_released": sum(float(r["details"]["cash"]) for r in records
                                  if r["event_type"] == "QDTE_DIVIDEND_CASH_RELEASED"),
    }


def account_metrics(state: Mapping[str, Any], observed: datetime) -> dict[str, Any]:
    marks = state.get("account_marks", {})
    positions = state.get("positions", {})
    required = {"QDTE", *positions}
    missing = sorted(required - marks.keys())
    qdte_mark = marks.get("QDTE", {}).get("price")
    qdte_value = state["qdte_shares"] * qdte_mark if qdte_mark is not None else None
    swing = sum(p["shares"] * marks[s]["price"] for s, p in positions.items()) if not missing else None
    cash, tax = float(state["cash"]), float(state.get("tax_reserve_cash", 0.0))
    equity = cash + tax + qdte_value + swing if not missing else None
    cost = float(state.get("qdte_cost", 0)) + sum(p["shares"] * p["entry_price"] for p in positions.values())
    actions = state.get("qdte_corporate_actions", {}).values()
    recorded = sum(float(e["entitlement"]["entitled_shares"]) * float(e["entitlement"]["rate"])
                   for e in actions if e.get("entitlement"))
    released = sum(float(e.get("cash_released", 0)) for e in state.get("qdte_corporate_actions", {}).values())
    stamp = min((marks[s]["market_data_timestamp"] for s in required), default=None) if not missing else None
    return {
        "reporting_timestamp": observed.astimezone(timezone.utc).isoformat(),
        "market_data_timestamp": stamp, "marks": dict(marks), "missing_marks": missing,
        "valuation_status": "MISSING_MARKS" if missing else "LAST_OBSERVED_MARKS",
        "marked_equity": equity,
        "starting_equity": state.get("contributed_capital"),
        "net_pnl": equity - float(state["contributed_capital"]) if equity is not None and "contributed_capital" in state else None,
        "realized_pnl": state.get("realized_pnl", 0.0),
        "unrealized_pnl": qdte_value + swing - cost if not missing else None,
        "cash": cash, "tax_reserve": tax, "qdte_shares": state["qdte_shares"],
        "qdte_mark": qdte_mark, "qdte_market_value": qdte_value, "swing_market_value": swing,
        "open_position_count": len(positions), "pending_entry_count": len(state.get("pending", {})),
        "dividends_recorded": recorded, "dividends_released": released,
        "dividends_pending": recorded - released,
    }


def performance(state: dict, records: list[dict], observed: datetime, market_timezone) -> dict:
    metrics = account_metrics(state, observed)
    day = observed.astimezone(market_timezone).date()
    start_day = day - timedelta(days=13)
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=market_timezone)
    window = [r for r in records if datetime.fromisoformat(r["observed_at_utc"]) >= start]
    baseline = state.setdefault("performance_baseline", {
        "recording_started_at": observed.isoformat(), "marked_equity": metrics["marked_equity"],
    })
    daily = state.setdefault("daily_marked_equity", {})
    prior = [value for key, value in daily.items() if key < start_day.isoformat()]
    initial = max(prior, key=lambda value: value["timestamp"]) if prior else None
    if metrics["marked_equity"] is not None:
        daily[day.isoformat()] = {"timestamp": observed.isoformat(), "equity": metrics["marked_equity"]}
    return {
        "current": metrics, "account_to_date": event_totals(records),
        "window_14_calendar_days": {
            "start_inclusive": start.isoformat(), "end_inclusive": observed.isoformat(),
            **event_totals(window),
            "starting_equity": initial["equity"] if initial else None,
            "starting_equity_mark_timestamp": initial["timestamp"] if initial else None,
            "net_equity_change": metrics["marked_equity"] - initial["equity"] if initial and metrics["marked_equity"] is not None else None,
            "equity_unavailable_reason": None if initial else "NO_PERSISTED_MARK_AT_WINDOW_START",
        },
        "recording_baseline": baseline,
    }
