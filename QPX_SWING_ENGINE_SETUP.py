#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

ENGINE_FILE = os.path.join(
    ROOT,
    "swing_signal_engine.py"
)


def log(msg):
    print(
        datetime.datetime.now().isoformat(),
        msg
    )


def create_swing_engine():

    if os.path.exists(ENGINE_FILE):

        log(
            "Swing Signal Engine already exists"
        )

        return


    code = r'''
#!/usr/bin/env python3


class SwingSignalEngine:


    def __init__(self):

        self.signals = []


    def generate(self, features):

        signals = []


        for _, row in features.iterrows():


            signal = "HOLD"


            if (
                row.get("close", 0)
                >
                row.get("sma_5", 0)
                and
                row.get("volume_change", 0) > 0
            ):

                signal = "BUY"


            elif (
                row.get("close", 0)
                <
                row.get("sma_5", 0)
            ):

                signal = "SELL"



            signals.append(

                {
                    "symbol":
                        row.get("symbol"),

                    "timestamp":
                        row.get("timestamp"),

                    "side":
                        signal,

                    "price":
                        row.get("close"),

                    "confidence":
                        0.50
                }

            )


        self.signals = signals

        return signals



def run_signal_engine(features):

    engine = SwingSignalEngine()

    return engine.generate(
        features
    )

'''

    with open(
        ENGINE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(code)


    log(
        "Swing Signal Engine created"
    )



def main():

    log(
        "QPX SWING ENGINE SETUP START"
    )

    create_swing_engine()

    log(
        "QPX SWING ENGINE SETUP COMPLETE"
    )



if __name__ == "__main__":

    main()