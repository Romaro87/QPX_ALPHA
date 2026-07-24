#!/usr/bin/env python3

import os
import datetime
import sys


ROOT = "/storage/emulated/0/QPX_ALPHA"

STEP13 = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION"
)

REPORT = os.path.join(
    STEP13,
    "STEP13_INTEGRATION_REPORT.txt"
)


sys.path.insert(
    0,
    ROOT
)

sys.path.insert(
    0,
    STEP13
)



def log(report, text):

    print(text)

    report.write(
        text + "\n"
    )



def main():

    results=[]


    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:


        log(
            report,
            "================================="
        )

        log(
            report,
            "QPX STEP 13 INTEGRATION TEST"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        # Signal Engine

        try:

            from signal_engine import SignalEngine


            engine = SignalEngine()


            test_features = {}

            signal = engine.generate_signal(
                test_features
            )


            log(
                report,
                "[PASS] Signal Engine"
            )

            log(
                report,
                str(signal)
            )

            results.append(True)


        except Exception as e:

            log(
                report,
                f"[FAIL] Signal Engine: {e}"
            )

            signal=None

            results.append(False)



        # Paper Trading

        try:

            from paper_trading_engine import PaperTradingEngine


            trader = PaperTradingEngine()


            trade = trader.execute_signal(
                signal
            )


            log(
                report,
                "[PASS] Paper Trading Engine"
            )

            log(
                report,
                str(trade)
            )

            results.append(True)


        except Exception as e:

            log(
                report,
                f"[FAIL] Paper Trading Engine: {e}"
            )

            trade=None

            results.append(False)



        # Position Manager

        try:

            from position_manager import PositionManager


            manager = PositionManager()


            position = manager.open_position(
                trade
            )


            log(
                report,
                "[PASS] Position Manager"
            )

            log(
                report,
                str(position)
            )

            results.append(True)


        except Exception as e:

            log(
                report,
                f"[FAIL] Position Manager: {e}"
            )

            results.append(False)



        # Risk Controller

        try:

            from risk_controller import RiskController


            risk = RiskController()


            approved = risk.check_trade(
                trade
            )


            if approved:

                log(
                    report,
                    "[PASS] Risk Controller"
                )

                results.append(True)

            else:

                log(
                    report,
                    "[FAIL] Risk Controller rejected trade"
                )

                results.append(False)


        except Exception as e:

            log(
                report,
                f"[FAIL] Risk Controller: {e}"
            )

            results.append(False)



        # Journal

        try:

            from live_trade_journal import LiveTradeJournal


            journal = LiveTradeJournal()


            journal.record(
                trade
            )


            log(
                report,
                "[PASS] Live Trade Journal"
            )


            log(
                report,
                str(
                    journal.get_entries()
                )
            )

            results.append(True)


        except Exception as e:

            log(
                report,
                f"[FAIL] Trade Journal: {e}"
            )

            results.append(False)



        log(
            report,
            ""
        )

        log(
            report,
            "================================="
        )


        if all(results):

            log(
                report,
                "QPX STEP 13 STATUS: OPERATIONAL"
            )

        else:

            log(
                report,
                "QPX STEP 13 STATUS: NEEDS REVIEW"
            )


        log(
            report,
            "================================="
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