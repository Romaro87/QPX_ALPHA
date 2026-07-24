#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "QPX_SWING_TEST_REPORT.txt"
)


def log(report, text):

    print(text)

    report.write(
        text + "\n"
    )


def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:


        log(
            report,
            "=============================="
        )

        log(
            report,
            "QPX SWING PIPELINE TEST"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "=============================="
        )


        try:

            from feature_engine import FeatureEngine
            from swing_signal_engine import SwingSignalEngine
            from backtesting_engine import BacktestEngine


            log(
                report,
                "Feature Engine loaded"
            )

            log(
                report,
                "Swing Signal Engine loaded"
            )

            log(
                report,
                "Backtesting Engine loaded"
            )


            db = os.path.join(
                ROOT,
                "qpx_alpha.db"
            )


            features = FeatureEngine(
                db
            ).run()


            log(
                report,
                "Features generated: "
                + str(len(features))
            )


            signals = SwingSignalEngine().generate(
                features
            )


            log(
                report,
                "Signals generated: "
                + str(len(signals))
            )


            results = BacktestEngine().run(
                signals=signals,
                historical_data=features
            )


            metrics = results["metrics"]


            log(
                report,
                "Backtest complete"
            )


            log(
                report,
                "Trades: "
                + str(
                    metrics["total_trades"]
                )
            )


            log(
                report,
                "Return: "
                + str(
                    metrics["return"]
                )
            )


            log(
                report,
                "Drawdown: "
                + str(
                    metrics["drawdown"]
                )
            )


            log(
                report,
                "STATUS: OPERATIONAL"
            )


        except Exception as e:


            log(
                report,
                "ERROR:"
            )

            log(
                report,
                str(e)
            )


if __name__ == "__main__":
    main()