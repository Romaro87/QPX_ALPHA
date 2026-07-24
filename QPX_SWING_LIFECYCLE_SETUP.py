#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

FILE = os.path.join(
    ROOT,
    "swing_trade_lifecycle.py"
)


def log(msg):
    print(
        datetime.datetime.now().isoformat(),
        msg
    )


def create():

    if os.path.exists(FILE):
        log("Lifecycle engine already exists")
        return


    code = r'''
class SwingTradeLifecycle:


    def __init__(
        self,
        hold_period=5,
        stop_loss=0.02,
        take_profit=0.04
    ):

        self.hold_period = hold_period
        self.stop_loss = stop_loss
        self.take_profit = take_profit



    def process(self, signals, data):

        trades = []


        for signal in signals:

            entry = signal.get(
                "price",
                0
            )

            side = signal.get(
                "side"
            )


            if side == "BUY":

                exit_price = entry * (
                    1 + self.take_profit
                )

            elif side == "SELL":

                exit_price = entry * (
                    1 - self.take_profit
                )

            else:

                continue



            if side == "BUY":

                pnl = exit_price - entry

            else:

                pnl = entry - exit_price



            result = "WIN"

            if pnl <= 0:

                result = "LOSS"



            trades.append(
                {
                    "side": side,
                    "entry": entry,
                    "exit": exit_price,
                    "pnl": pnl,
                    "result": result
                }
            )


        return trades



    def metrics(self, trades):

        total = len(trades)

        wins = len(
            [
                t for t in trades
                if t["result"] == "WIN"
            ]
        )


        losses = total - wins


        pnl = sum(
            t["pnl"]
            for t in trades
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
'''


    with open(
        FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(code)


    log(
        "Swing lifecycle engine created"
    )



if __name__ == "__main__":

    log(
        "QPX SWING LIFECYCLE SETUP START"
    )

    create()

    log(
        "QPX SWING LIFECYCLE SETUP COMPLETE"
    )