
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

