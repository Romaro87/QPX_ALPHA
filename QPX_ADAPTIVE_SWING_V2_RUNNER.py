#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "QPX_ADAPTIVE_SWING_V2_REPORT.txt"
)


def write(report, text):

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


        write(
            report,
            "=============================="
        )

        write(
            report,
            "QPX ADAPTIVE SWING V2 PIPELINE"
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
            from swing_signal_calibrator import SwingSignalCalibrator
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
                "Features: "
                + str(len(features))
            )


            calibrator = SwingSignalCalibrator()


            calibration = calibrator.suggest_thresholds(
                features
            )


            write(
                report,
                "Calibration complete"
            )


            write(
                report,
                "Momentum threshold: "
                + str(
                    calibration["min_momentum"]
                )
            )


            write(
                report,
                "Volume threshold: "
                + str(
                    calibration["min_volume_change"]
                )
            )


            signals = SwingSignalEngineV2().generate(
                features
            )


            write(
                report,
                "V2 Signals: "
                + str(len(signals))
            )


            buy = len(
                [
                    s for s in signals
                    if s["side"] == "BUY"
                ]
            )


            sell = len(
                [
                    s for s in signals
                    if s["side"] == "SELL"
                ]
            )


            hold = len(
                [
                    s for s in signals
                    if s["side"] == "HOLD"
                ]
            )


            write(
                report,
                "BUY: "
                + str(buy)
            )

            write(
                report,
                "SELL: "
                + str(sell)
            )

            write(
                report,
                "HOLD: "
                + str(hold)
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
                "Lifecycle complete"
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
                "STATUS: OPERATIONAL"
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