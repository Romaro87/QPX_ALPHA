#!/usr/bin/env python3

"""
QPX Alpha
Swing Strategy Engine V3

Adds:
- EMA 20
- EMA 50
- RSI 14
- ATR 14
- Risk Management
"""

import pandas as pd


class SwingStrategyV3:

    def __init__(self):
        self.name = "QPX Swing Strategy V3"

    def prepare(self, df):

        df = df.copy()

        # Trend

        df["ema20"] = (
            df["close"]
            .ewm(span=20)
            .mean()
        )

        df["ema50"] = (
            df["close"]
            .ewm(span=50)
            .mean()
        )

        # RSI

        delta = df["close"].diff()

        gain = delta.clip(lower=0)

        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()

        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss.replace(0, 1e-9)

        df["rsi"] = 100 - (
            100 / (1 + rs)
        )

        # ATR

        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs()
        ], axis=1).max(axis=1)

        df["atr"] = tr.rolling(14).mean()

        return df

    def generate_signals(self, df):

        signals = []

        for _, row in df.iterrows():

            signal = "HOLD"

            if (
                row["ema20"] > row["ema50"]
                and row["rsi"] < 35
            ):

                signal = "BUY"

            elif (
                row["ema20"] < row["ema50"]
                and row["rsi"] > 65
            ):

                signal = "SELL"

            stop = None
            target = None

            if signal == "BUY":

                stop = row["close"] - (
                    row["atr"] * 2
                )

                target = row["close"] + (
                    row["atr"] * 3
                )

            elif signal == "SELL":

                stop = row["close"] + (
                    row["atr"] * 2
                )

                target = row["close"] - (
                    row["atr"] * 3
                )

            signals.append({

                "timestamp": row.get("timestamp"),

                "signal": signal,

                "price": row["close"],

                "stop_loss": stop,

                "take_profit": target

            })

        return signals