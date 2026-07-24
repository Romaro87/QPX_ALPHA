
"""
QPX Alpha Backtesting Engine
Step 10 Layer
"""


class BacktestEngine:

    def __init__(self):
        self.trades = []
        self.metrics = {}

    def run(self, signals=None, historical_data=None):

        signals = signals or []
        historical_data = historical_data or []

        for signal in signals:

            trade = {
                "symbol": signal.get("symbol"),
                "timestamp": signal.get("timestamp"),
                "side": signal.get("side"),
                "entry_price": signal.get("price"),
                "quantity": signal.get("quantity", 1),
            }

            self.trades.append(trade)

        self.metrics = self.generate_metrics()

        return {
            "trades": self.trades,
            "metrics": self.metrics
        }


    def generate_metrics(self):

        total_trades = len(self.trades)

        return {
            "total_trades": total_trades,
            "winning_trades": 0,
            "losing_trades": 0,
            "return": 0.0,
            "drawdown": 0.0
        }


def run_backtest(signals=None, historical_data=None):

    engine = BacktestEngine()

    return engine.run(
        signals=signals,
        historical_data=historical_data
    )




# STEP10 REPAIR PATCH

from trade_event_schema_v2 import normalize_trade


normalized_trades = []


for trade in trades:

    normalized_trades.append(
        normalize_trade(trade)
    )


trades = normalized_trades



