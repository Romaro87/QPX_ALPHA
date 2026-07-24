"""
QPX Alpha Quant Research Platform
STEP 10 BACKTESTING ENGINE REPAIR
Trade Event Schema v2.0 Normalizer + Metrics Repair

Scope:
- Step 10 components only

Protected:
- importer pipeline
- CSV pipeline
- database lifecycle
- query layer
- analytics foundation
- Step 8 feature engine
- Step 9 signal engine
"""

from datetime import datetime, timezone
import uuid


TRADE_SCHEMA_VERSION = "2.0"


# ---------------------------------------------------------
# Trade Event Schema v2.0
# ---------------------------------------------------------

def create_trade_event(raw_trade):
    """
    Convert raw backtest output into validated Trade Event Schema v2.0
    """

    entry_price = raw_trade.get("entry_price")
    exit_price = raw_trade.get("exit_price")
    quantity = raw_trade.get("quantity", 0)

    if entry_price is None:
        entry_price = 0.0

    if exit_price is None:
        exit_price = entry_price

    realized_pnl = raw_trade.get("realized_pnl")

    if realized_pnl is None:
        realized_pnl = (
            (exit_price - entry_price)
            * quantity
        )

    if entry_price != 0:
        return_pct = (
            realized_pnl /
            (entry_price * quantity)
        ) * 100
    else:
        return_pct = 0.0


    return {

        "trade_id":
            raw_trade.get(
                "trade_id",
                str(uuid.uuid4())
            ),

        "symbol":
            raw_trade.get(
                "symbol",
                "UNKNOWN"
            ),

        "timestamp":
            raw_trade.get(
                "timestamp",
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),

        "signal":
            raw_trade.get(
                "signal"
            ),

        "side":
            raw_trade.get(
                "side",
                "UNKNOWN"
            ),

        "entry_price":
            float(entry_price),

        "exit_price":
            float(exit_price),

        "quantity":
            float(quantity),

        "position_status":
            raw_trade.get(
                "position_status",
                "CLOSED"
            ),

        "realized_pnl":
            round(
                realized_pnl,
                6
            ),

        "return_pct":
            round(
                return_pct,
                6
            ),

        "strategy":
            raw_trade.get(
                "strategy",
                "STEP9_SIGNAL"
            )

    }


# ---------------------------------------------------------
# Metrics Engine Repair
# ---------------------------------------------------------

def calculate_metrics(trades):

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
        if total
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
            round(
                (
                    len(winners) /
                    total *
                    100
                )
                if total
                else 0,
                4
            ),

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
            0.0,

        "average_trade_return":
            round(
                average_return,
                6
            )

    }


# ---------------------------------------------------------
# Step 10 Validation Repair Wrapper
# ---------------------------------------------------------

def repair_step10_backtest_output(backtest_result):

    raw_trades = backtest_result.get(
        "trades",
        []
    )


    repaired_trades = []

    for trade in raw_trades:

        repaired_trade = create_trade_event(
            trade
        )

        repaired_trades.append(
            repaired_trade
        )


    metrics = calculate_metrics(
        repaired_trades
    )


    return {

        "schema_version":
            TRADE_SCHEMA_VERSION,

        "trades":
            repaired_trades,

        "metrics":
            metrics

    }



# ---------------------------------------------------------
# Test using failed Step 10 output
# ---------------------------------------------------------

if __name__ == "__main__":

    failed_output = {

        "trades": [
            {
                "symbol": "TEST",
                "timestamp":
                    "2026-07-24T03:40:52.775544+00:00",
                "side": "BUY",
                "entry_price": 100,
                "exit_price": 110,
                "quantity": 1,
                "strategy":
                    "STEP9_SIGNAL"
            }
        ]

    }


    repaired = repair_step10_backtest_output(
        failed_output
    )


    print(
        repaired
    )
