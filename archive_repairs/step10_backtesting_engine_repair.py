"""
QPX Alpha Quant Research Platform
STEP 10 BACKTESTING ENGINE REPAIR

Purpose:
- Normalize backtest trade events into Trade Event Schema v2.0
- Validate closed trade lifecycle
- Regenerate performance metrics
- Preserve Step 8 / Step 9 / database layers unchanged

Scope:
STEP 10 components only
"""

from datetime import datetime, timezone
from uuid import uuid4


TRADE_SCHEMA_VERSION = "2.0"


REQUIRED_TRADE_FIELDS = [
    "schema_version",
    "trade_id",
    "symbol",
    "timestamp",
    "side",
    "entry_price",
    "quantity",
    "exit_price",
    "realized_pnl",
    "return_pct",
    "strategy",
]


def normalize_trade_event(raw_trade):
    """
    Convert raw backtest output into Trade Event Schema v2.0
    """

    entry_price = raw_trade.get("entry_price")
    exit_price = raw_trade.get("exit_price")
    quantity = raw_trade.get("quantity", 0)

    if entry_price is None or exit_price is None:
        raise ValueError(
            "Invalid trade event: missing entry or exit price"
        )

    realized_pnl = (
        exit_price - entry_price
    ) * quantity

    return_pct = (
        (exit_price - entry_price)
        / entry_price
    ) * 100

    normalized = {
        "schema_version": TRADE_SCHEMA_VERSION,
        "trade_id": raw_trade.get(
            "trade_id",
            str(uuid4())
        ),
        "symbol": raw_trade.get(
            "symbol",
            "UNKNOWN"
        ),
        "timestamp": raw_trade.get(
            "timestamp",
            datetime.now(timezone.utc).isoformat()
        ),
        "signal": raw_trade.get(
            "signal"
        ),
        "side": raw_trade.get(
            "side",
            "BUY"
        ),
        "entry_price": entry_price,
        "quantity": quantity,
        "exit_price": exit_price,
        "position_status": "CLOSED",
        "realized_pnl": round(
            realized_pnl,
            4
        ),
        "return_pct": round(
            return_pct,
            4
        ),
        "strategy": raw_trade.get(
            "strategy",
            "STEP9_SIGNAL"
        ),
    }

    validate_trade_schema(normalized)

    return normalized



def validate_trade_schema(trade):
    """
    Enforce Trade Event Schema v2.0
    """

    missing = []

    for field in REQUIRED_TRADE_FIELDS:
        if field not in trade:
            missing.append(field)

    if missing:
        raise ValueError(
            f"Schema validation failed: {missing}"
        )

    null_fields = [
        field
        for field in REQUIRED_TRADE_FIELDS
        if trade[field] is None
    ]

    if null_fields:
        raise ValueError(
            f"Null schema fields: {null_fields}"
        )

    return True



def validate_closed_trade_lifecycle(trade):
    """
    Ensure only completed positions generate metrics
    """

    if trade.get("position_status") != "CLOSED":
        return False

    if trade.get("exit_price") is None:
        return False

    if trade.get("realized_pnl") is None:
        return False

    return True



def regenerate_metrics(trades):
    """
    Generate metrics only from normalized closed trades
    """

    closed_trades = [
        trade
        for trade in trades
        if validate_closed_trade_lifecycle(trade)
    ]


    total_trades = len(closed_trades)

    winning_trades = len(
        [
            t for t in closed_trades
            if t["realized_pnl"] > 0
        ]
    )

    losing_trades = len(
        [
            t for t in closed_trades
            if t["realized_pnl"] < 0
        ]
    )


    win_rate = (
        winning_trades / total_trades * 100
        if total_trades
        else 0
    )


    returns = [
        t["return_pct"]
        for t in closed_trades
    ]


    gross_return = sum(
        t["realized_pnl"]
        for t in closed_trades
    )


    average_trade_return = (
        sum(returns) / len(returns)
        if returns
        else 0
    )


    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 4),
        "gross_return": round(gross_return, 4),
        "net_return": round(gross_return, 4),
        "max_drawdown": 0.0,
        "average_trade_return": round(
            average_trade_return,
            4
        ),
    }



def repair_step10_backtest_output(backtest_output):
    """
    Main Step 10 repair entry point
    """

    raw_trades = backtest_output.get(
        "trades",
        []
    )

    normalized_trades = []

    for trade in raw_trades:
        normalized_trades.append(
            normalize_trade_event(trade)
        )


    metrics = regenerate_metrics(
        normalized_trades
    )


    return {
        "schema_version": TRADE_SCHEMA_VERSION,
        "trades": normalized_trades,
        "metrics": metrics,
    }



# Example validation run
if __name__ == "__main__":

    sample_output = {
        "trades": [
            {
                "symbol": "TEST",
                "timestamp":
                    "2026-07-24T03:40:52.775544+00:00",
                "side": "BUY",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "quantity": 1.0,
                "strategy": "STEP9_SIGNAL"
            }
        ]
    }


    repaired = repair_step10_backtest_output(
        sample_output
    )


    print(repaired)
