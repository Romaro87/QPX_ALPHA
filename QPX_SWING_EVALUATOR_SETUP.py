#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

FILE = os.path.join(
    ROOT,
    "swing_strategy_evaluator.py"
)


def log(text):
    print(
        datetime.datetime.now().isoformat(),
        text
    )


def create():

    if os.path.exists(FILE):

        log(
            "Evaluator already exists"
        )
        return


    code = r'''
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
'''


    with open(
        FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(code)


    log(
        "Swing evaluator created"
    )



if __name__ == "__main__":

    log(
        "QPX SWING EVALUATOR SETUP START"
    )

    create()

    log(
        "QPX SWING EVALUATOR SETUP COMPLETE"
    )