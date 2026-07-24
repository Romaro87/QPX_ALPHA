
class SwingStrategyEvaluator:


    def __init__(self):
        self.results = []


    def evaluate(self, signals, data):

        trades = []

        for signal in signals:

            entry = signal.get(
                "price",
                0
            )

            side = signal.get(
                "side"
            )


            # Simple swing exit model
            exit_price = entry


            if side == "BUY":

                exit_price = entry * 1.01


            elif side == "SELL":

                exit_price = entry * 0.99


            pnl = exit_price - entry


            trades.append(
                {
                    "side": side,
                    "entry": entry,
                    "exit": exit_price,
                    "pnl": pnl
                }
            )


        self.results = trades

        return self.metrics()



    def metrics(self):

        total = len(
            self.results
        )


        wins = len(
            [
                x for x in self.results
                if x["pnl"] > 0
            ]
        )


        losses = len(
            [
                x for x in self.results
                if x["pnl"] < 0
            ]
        )


        pnl = sum(
            x["pnl"]
            for x in self.results
        )


        win_rate = 0

        if total:

            win_rate = (
                wins / total
            ) * 100


        return {

            "trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "return": pnl

        }



def run_evaluation(signals, data):

    return SwingStrategyEvaluator().evaluate(
        signals,
        data
    )
