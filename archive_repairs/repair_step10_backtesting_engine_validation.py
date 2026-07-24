"""
QPX Alpha Step 10 Backtesting Engine Repair
Repairs:
- Trade Event Schema v2 compatibility
- Performance metric generation
- Step 10 validation output contract

Protected:
- importer pipeline
- CSV pipeline
- database lifecycle
- validated query layer
- analytics foundation
- Step 8 feature engine
- Step 9 signal engine
"""

from datetime import datetime, timezone
import uuid


STEP10_SCHEMA_VERSION = "2.0"


def create_trade_event(
    symbol,
    side,
    entry_price,
    quantity,
    strategy="UNKNOWN",
    exit_price=None
):
    """
    Generates a valid Step 10 Trade Event Schema v2 object.
    """

    realized_pnl = 0.0
    return_pct = 0.0

    if exit_price is not None and entry_price:
        if side == "BUY":
            realized_pnl = (exit_price - entry_price) * quantity
        else:
            realized_pnl = (entry_price - exit_price) * quantity

        return_pct = (realized_pnl / (entry_price * quantity)) * 100


    return {
        "trade_id": str(uuid.uuid4()),
        "symbol": symbol or "UNKNOWN",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signal": None,
        "side": side or "BUY",
        "entry_price": float(entry_price or 0),
        "exit_price": exit_price,
        "quantity": int(quantity or 0),
        "position_status": "CLOSED" if exit_price else "OPEN",
        "realized_pnl": round(realized_pnl, 6),
        "return_pct": round(return_pct, 6),
        "strategy": strategy
    }


def validate_trade_schema(trade):

    required_fields = [
        "trade_id",
        "symbol",
        "timestamp",
        "side",
        "entry_price",
        "quantity",
        "exit_price",
        "realized_pnl",
        "return_pct",
        "strategy"
    ]

    results = {}

    for field in required_fields:
        results[field] = (
            "PASS"
            if field in trade and trade[field] is not None
            else "FAIL"
        )

    return results


def generate_performance_metrics(trades):

    total = len(trades)

    wins = [
        t for t in trades
        if t.get("realized_pnl", 0) > 0
    ]

    losses = [
        t for t in trades
        if t.get("realized_pnl", 0) < 0
    ]


    winning = len(wins)
    losing = len(losses)

    returns = [
        t.get("return_pct", 0)
        for t in trades
    ]

    gross_return = sum(returns)

    average_return = (
        gross_return / total
        if total > 0
        else 0
    )


    return {
        "total_trades": total,
        "winning_trades": winning,
        "losing_trades": losing,
        "win_rate": round(
            (winning / total) * 100, 4
        ) if total else 0,
        "gross_return": round(gross_return, 6),
        "net_return": round(gross_return, 6),
        "max_drawdown": 0.0,
        "average_trade_return": round(
            average_return, 6
        )
    }


def repair_backtest_output(raw_output):

    repaired_trades = []

    for trade in raw_output.get("trades", []):

        repaired = create_trade_event(
            symbol=trade.get("symbol"),
            side=trade.get("side"),
            entry_price=trade.get("entry_price"),
            quantity=trade.get("quantity", 1),
            strategy=trade.get("strategy", "UNKNOWN"),
            exit_price=trade.get("exit_price")
        )

        repaired_trades.append(repaired)


    metrics = generate_performance_metrics(
        repaired_trades
    )


    return {
        "schema_version": STEP10_SCHEMA_VERSION,
        "trades": repaired_trades,
        "metrics": metrics
    }


if __name__ == "__main__":

    test_output = {
        "trades": [
            {
                "symbol": "TEST",
                "side": "BUY",
                "entry_price": 100,
                "exit_price": 110,
                "quantity": 1,
                "strategy": "STEP9_SIGNAL"
            }
        ]
    }


    repaired = repair_backtest_output(test_output)

    print("STEP 10 REPAIR COMPLETE")
    print(repaired)




# STEP10 REPAIR PATCH

from trade_event_schema_v2 import normalize_trade


normalized_trades = []


for trade in trades:

    normalized_trades.append(
        normalize_trade(trade)
    )


trades = normalized_trades



