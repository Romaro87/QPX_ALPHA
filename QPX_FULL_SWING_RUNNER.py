#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "QPX_SWING_PERFORMANCE_REPORT.txt"
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
            "QPX FULL SWING EVALUATION"
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
            from swing_signal_engine import SwingSignalEngine
            from backtesting_engine import BacktestEngine
            from swing_strategy_evaluator import SwingStrategyEvaluator


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


            signals = SwingSignalEngine().generate(
                features
            )


            write(
                report,
                "Signals: "
                + str(len(signals))
            )


            backtest = BacktestEngine().run(
                signals=signals,
                historical_data=features
            )


            trades = backtest["trades"]


            metrics = SwingStrategyEvaluator().evaluate(
                signals,
                features
            )


            write(
                report,
                "Evaluation complete"
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