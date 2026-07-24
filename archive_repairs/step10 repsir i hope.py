"""
QPX Alpha Step 10 Backtesting Engine Schema Repair
Trade Event Schema v2.0 Enforcement

Scope:
- Final trade event normalization
- Closed trade lifecycle validation
- Metrics regeneration

Does NOT modify:
- importer
- CSV pipeline
- database lifecycle
- query layer
- Step 8
- Step 9
"""

from datetime import datetime, timezone
import uuid


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
    "realized_pnl",
    "return_pct",
    "strategy",
]


class Step10ValidationError(Exception):
    pass


def generate_trade_id():
    return str(uuid.uuid4())


def normalize_trade_event(raw_trade):
    """
    Converts Step 10 execution output into Trade Event Schema v2.0
    """

    return {
        "schema_version": SCHEMA_VERSION,

        "trade_id": raw_trade.get(
            "trade_id",
            generate_trade_id()
        ),

        "symbol": raw_trade.get("symbol"),

        "timestamp": raw_trade.get(
            "timestamp",
            datetime.now(timezone.utc).isoformat()
        ),

        "signal": raw_trade.get("signal"),

        "side": raw_trade.get("side"),

        "entry_price": float(
            raw_trade.get("entry_price", 0.0)
        ),

        "quantity": float(
            raw_trade.get("quantity", 0.0)
        ),

        "exit_price": float(
            raw_trade.get("exit_price", 0.0)
        ),

        "position_status": "CLOSED",

        "realized_pnl": float(
            raw_trade.get("realized_pnl", 0.0)
        ),

        "return_pct": float(
            raw_trade.get("return_pct", 0.0)
        ),

        "strategy": raw_trade.get(
            "strategy",
            "STEP9_SIGNAL"
        ),
    }


def validate_trade_schema(trade):
    """
    Hard validation gate.
    Prevents incomplete events from reaching metrics.
    """

    failures = []

    for field in REQUIRED_TRADE_FIELDS:

        if field not in trade:
            failures.append(
                f"missing:{field}"
            )

        elif trade[field] is None:
            failures.append(
                f"null:{field}"
            )

    if failures:
        raise Step10ValidationError(
            f"Trade Event Schema v2.0 failure: {failures}"
        )

    return True


def calculate_drawdown(returns):

    balance = 0
    peak = 0
    max_drawdown = 0

    for value in returns:

        balance += value

        if balance > peak:
            peak = balance

        drawdown = peak - balance

        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return max_drawdown


def regenerate_metrics(trades):

    closed_trades = [
        t for t in trades
        if t.get("position_status") == "CLOSED"
    ]


    pnl_values = [
        t["realized_pnl"]
        for t in closed_trades
    ]


    total = len(pnl_values)

    winners = [
        pnl for pnl in pnl_values
        if pnl > 0
    ]

    losers = [
        pnl for pnl in pnl_values
        if pnl < 0
    ]


    return {
        "total_trades": total,

        "winning_trades": len(winners),

        "losing_trades": len(losers),

        "win_rate": (
            len(winners) / total * 100
            if total
            else 0
        ),

        "gross_return": sum(pnl_values),

        "net_return": sum(pnl_values),

        "max_drawdown": calculate_drawdown(
            pnl_values
        ),

        "average_trade_return": (
            sum(pnl_values) / total
            if total
            else 0
        )
    }


def finalize_step10_backtest(raw_trade_events):
    """
    THIS IS THE REQUIRED REPAIR POINT.

    Call this immediately before returning:
        {
            "trades": [],
            "metrics": {}
        }
    """

    normalized_trades = []


    for raw_trade in raw_trade_events:

        trade = normalize_trade_event(
            raw_trade
        )

        validate_trade_schema(
            trade
        )

        normalized_trades.append(
            trade
        )


    metrics = regenerate_metrics(
        normalized_trades
    )


    return {
        "schema_version": SCHEMA_VERSION,
        "trades": normalized_trades,
        "metrics": metrics
    }


# -------------------------------------------------
# TEST WITH REPAIRED STEP 10 OUTPUT
# -------------------------------------------------

if __name__ == "__main__":

    repaired_trade = [

        {
            "trade_id":
                "f0395d96-3ac4-46f5-8524-28ffcdac5cf0",

            "symbol":
                "TEST",

            "timestamp":
                "2026-07-24T03:40:52.775544+00:00",

            "side":
                "BUY",

            "entry_price":
                100.0,

            "quantity":
                1.0,

            "exit_price":
                110.0,

            "realized_pnl":
                10.0,

            "return_pct":
                10.0,

            "strategy":
                "STEP9_SIGNAL"
        }
    ]


    result = finalize_step10_backtest(
        repaired_trade
    )


    print(result)
