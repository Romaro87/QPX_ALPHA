#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "QPX_SIGNAL_ANALYSIS_REPORT.txt"
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
            "QPX SIGNAL ANALYSIS"
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
                "Features analyzed: "
                + str(len(features))
            )


            signals = SwingSignalEngine().generate(
                features
            )


            buy = 0
            sell = 0
            hold = 0


            for signal in signals:

                side = signal.get(
                    "side"
                )


                if side == "BUY":

                    buy += 1


                elif side == "SELL":

                    sell += 1


                else:

                    hold += 1



            executable = buy + sell


            write(
                report,
                "Total signals: "
                + str(len(signals))
            )

            write(
                report,
                "BUY signals: "
                + str(buy)
            )

            write(
                report,
                "SELL signals: "
                + str(sell)
            )

            write(
                report,
                "HOLD signals: "
                + str(hold)
            )

            write(
                report,
                "Executable trades: "
                + str(executable)
            )


            if executable == 0:

                write(
                    report,
                    "Recommendation: Review signal thresholds"
                )

            else:

                write(
                    report,
                    "Recommendation: Continue lifecycle testing"
                )


            write(
                report,
                "STATUS: ANALYSIS COMPLETE"
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