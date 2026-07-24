#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "QPX_HISTORICAL_VALIDATION_REPORT.txt"
)


def write(report, text):

    print(text)

    report.write(text + "\n")


def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:


        write(
            report,
            "=============================="
        )

        write(
            report,
            "QPX HISTORICAL VALIDATION RUN"
        )

        write(
            report,
            datetime.datetime.now().isoformat()
        )

        write(
            report,
            "=============================="
        )


        try:

            from feature_engine import FeatureEngine
            from swing_signal_engine_v2 import SwingSignalEngineV2
            from swing_trade_lifecycle import SwingTradeLifecycle


            write(
                report,
                "Modules loaded"
            )


            db = os.path.join(
                ROOT,
                "qpx_alpha.db"
            )


            features = FeatureEngine(
                db
            ).run()


            write(
                report,
                "Historical rows: "
                + str(len(features))
            )


            if len(features) < 50:

                write(
                    report,
                    "WARNING: Dataset below recommended swing size"
                )


            signals = SwingSignalEngineV2().generate(
                features
            )


            write(
                report,
                "Signals generated: "
                + str(len(signals))
            )


            lifecycle = SwingTradeLifecycle()


            trades = lifecycle.process(
                signals,
                features
            )


            metrics = lifecycle.metrics(
                trades
            )


            write(
                report,
                "Trades: "
                + str(metrics["trades"])
            )


            write(
                report,
                "Wins: "
                + str(metrics["wins"])
            )


            write(
                report,
                "Losses: "
                + str(metrics["losses"])
            )


            write(
                report,
                "Win Rate: "
                + str(metrics["win_rate"])
                + "%"
            )


            write(
                report,
                "Return: "
                + str(metrics["return"])
            )


            write(
                report,
                "STATUS: VALIDATION COMPLETE"
            )


        except Exception as e:

            write(
                report,
                "ERROR"
            )

            write(
                report,
                str(e)
            )


    print()
    print(
        "Report:"
    )

    print(
        REPORT
    )


if __name__ == "__main__":
    main()