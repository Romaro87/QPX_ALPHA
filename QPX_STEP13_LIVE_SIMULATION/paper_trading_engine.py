
class PaperTradingEngine:

    def __init__(self, starting_balance=10000):

        self.balance = starting_balance
        self.trades = []


    def execute_signal(self, signal):

        trade = {
            "signal": signal,
            "status": "SIMULATED"
        }

        self.trades.append(trade)

        return trade


    def get_trades(self):

        return self.trades
