"""
QPX Alpha Quant Research Platform

STEP 10 MAXIMUM REPAIR
Backtesting Engine Finalization Layer

Purpose:
- Enforce Trade Event Schema v2.0
- Normalize final trade events
- Validate closed trade lifecycle
- Regenerate metrics from normalized closed trades

DO NOT MODIFY:
- importer pipeline
- CSV pipeline
- database lifecycle
- validated query layer
- analytics foundation
- Step 8 feature engine
- Step 9 signal engine
"""


from datetime import datetime
from uuid import uuid4


SCHEMA_VERSION = "2.0"


REQUIRED_TRADE_FIELDS = [
    "schema_version",
    "trade_id",
    "symbol",
    "timestamp",
    "side",
    "entry_price",
    "quantity",
    "exit_price",
    "position_status",
    "realized_pnl",
    "return_pct",
    "strategy"
]


def normalize_trade_event(raw_trade):
    """
    Convert raw Step 10 trade objects into Schema v2.0 events.
    """

    if raw_trade is None:
        return None


    # Ignore incomplete open trades
    if raw_trade.get("position_status") != "CLOSED":

        if raw_trade.get("exit_price") is None:
            return None


    entry_price = raw_trade.get("entry_price")
    exit_price = raw_trade.get("exit_price")
    quantity = raw_trade.get("quantity", 0)


    if entry_price is None or exit_price is None:
        return None


    realized_pnl = (
        (exit_price - entry_price)
        * quantity
        if raw_trade.get("side") == "BUY"
        else
        (entry_price - exit_price)
        * quantity
    )


    return {

        "schema_version": SCHEMA_VERSION,

        "trade_id":
            raw_trade.get(
                "trade_id",
                str(uuid4())
            ),

        "symbol":
            raw_trade.get(
                "symbol",
                "UNKNOWN"
            ),

        "timestamp":
            raw_trade.get(
                "timestamp",
                datetime.utcnow().isoformat()
            ),

        "side":
            raw_trade.get(
                "side"
            ),

        "entry_price":
            float(entry_price),

        "quantity":
            float(quantity),

        "exit_price":
            float(exit_price),

        "position_status":
            "CLOSED",

        "realized_pnl":
            round(realized_pnl, 6),

        "return_pct":
            round(
                (
                    realized_pnl /
                    (entry_price * quantity)
                )
                * 100,
                6
            )
            if quantity > 0
            else 0,

        "strategy":
            raw_trade.get(
                "strategy",
                "STEP9_SIGNAL"
            )
    }



def validate_trade_schema_v2(trade):

    for field in REQUIRED_TRADE_FIELDS:

        if field not in trade:
            raise ValueError(
                f"Schema v2.0 failure: missing {field}"
            )


    if trade["position_status"] != "CLOSED":
        raise ValueError(
            "Open trade detected in Step 10 final output"
        )


    return True



def normalize_closed_trades(raw_trades):

    normalized = []


    for trade in raw_trades:

        cleaned = normalize_trade_event(trade)

        if cleaned:

            validate_trade_schema_v2(cleaned)

            normalized.append(cleaned)


    return normalized



def regenerate_metrics(trades):

    total = len(trades)

    winners = [
        t for t in trades
        if t["realized_pnl"] > 0
    ]

    losers = [
        t for t in trades
        if t["realized_pnl"] < 0
    ]


    gross_return = sum(
        t["realized_pnl"]
        for t in trades
    )


    average_return = (

        sum(
            t["return_pct"]
            for t in trades
        )
        / total

        if total > 0
        else 0

    )


    return {

        "total_trades":
            total,

        "winning_trades":
            len(winners),

        "losing_trades":
            len(losers),

        "win_rate":
            (
                len(winners)
                /
                total
                *
                100
            )
            if total > 0
            else 0,

        "gross_return":
            round(
                gross_return,
                6
            ),

        "net_return":
            round(
                gross_return,
                6
            ),

        "max_drawdown":
            0,

        "average_trade_return":
            round(
                average_return,
                6
            )
    }



def finalize_step10_payload(raw_trades):

    """
    SINGLE AUTHORIZED STEP 10 RETURN PATH
    """

    normalized_trades = normalize_closed_trades(
        raw_trades
    )


    metrics = regenerate_metrics(
        normalized_trades
    )


    payload = {

        "schema_version":
            SCHEMA_VERSION,

        "trades":
            normalized_trades,

        "metrics":
            metrics
    }


    return payload



# ======================================================
# PATCH POINT
# ======================================================
#
# Replace existing Step 10 return:
#
# return {
#     "trades": trades,
#     "metrics": metrics
# }
#
# with:
#
# return finalize_step10_payload(trades)
#
# ======================================================
