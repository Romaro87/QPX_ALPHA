
class SwingSignalEngineV2:


    def __init__(self):

        self.signals = []



    def generate(self, features):

        signals = []


        for _, row in features.iterrows():


            close = row.get(
                "close",
                0
            )

            sma = row.get(
                "sma_5",
                0
            )


            momentum = row.get(
                "price_change",
                0
            )


            volume = row.get(
                "volume_change",
                0
            )


            trading_signal = "HOLD"

            confidence = 0.0



            # BUY setup
            if (

                close > sma

                and momentum > 0

                and volume >= 0

            ):

                trading_signal = "BUY"

                confidence = 0.70



            # SELL setup
            elif (

                close < sma

                and momentum < 0

            ):

                trading_signal = "SELL"

                confidence = 0.70



            signals.append(

                {

                    "symbol":
                        row.get("symbol"),

                    "timestamp":
                        row.get("timestamp"),

                    "side":
                        trading_signal,

                    "price":
                        close,

                    "confidence":
                        confidence

                }

            )


        self.signals = signals

        return signals



def run_signal_engine_v2(features):

    engine = SwingSignalEngineV2()

    return engine.generate(
        features
    )
