#!/usr/bin/env python3

import os
import sqlite3
import datetime
import sys


ROOT = "/storage/emulated/0/QPX_ALPHA"

STEP13 = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION"
)

DB = os.path.join(
    STEP13,
    "qpx_step13_simulation.db"
)

REPORT = os.path.join(
    STEP13,
    "STEP13_4_LIFECYCLE_TEST_REPORT.txt"
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
            "QPX STEP 13.4 LIFECYCLE TEST"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        try:

            from paper_trading_lifecycle import (
                PaperTradingLifecycle
            )


            engine = PaperTradingLifecycle(
                DB
            )


            log(
                report,
                "[PASS] Lifecycle Engine Loaded"
            )


        except Exception as e:

            log(
                report,
                "[FAIL] Engine Load: " + str(e)
            )

            return



        # Open trade

        trade_id = engine.open_trade(
            "QPX_TEST",
            100.0
        )


        log(
            report,
            "[PASS] Trade Opened ID: "
            + str(trade_id)
        )



        # Close trade

        pnl = engine.close_trade(
            trade_id,
            105.0
        )


        log(
            report,
            "[PASS] Trade Closed"
        )


        log(
            report,
            "P/L: "
            + str(pnl)
        )



        # Verify database

        conn = sqlite3.connect(
            DB
        )

        cur = conn.cursor()


        cur.execute(
            """
            SELECT
            symbol,
            side,
            entry,
            exit,
            pnl,
            status

            FROM lifecycle_trades

            WHERE id=?

            """,
            (trade_id,)
        )


        trade = cur.fetchone()


        conn.close()



        if trade:

            log(
                report,
                "[PASS] Trade Record Verified"
            )

            log(
                report,
                str(trade)
            )


            status = "OPERATIONAL"


        else:

            log(
                report,
                "[FAIL] Trade Record Missing"
            )

            status = "NEEDS REVIEW"



        log(
            report,
            ""
        )

        log(
            report,
            "================================="
        )

        log(
            report,
            "QPX STEP 13.4 STATUS: "
            + status
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