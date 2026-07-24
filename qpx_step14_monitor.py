#!/usr/bin/env python3

import os
import sqlite3
import datetime
import time


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
    "STEP14_1_MONITOR_REPORT.txt"
)


def log(report, text):

    print(text)
    report.write(text + "\n")



def collect_metrics():

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        """
        SELECT pnl
        FROM lifecycle_trades
        WHERE status='CLOSED'
        """
    )

    rows = cur.fetchall()


    conn.close()


    pnl = [
        r[0]
        for r in rows
        if r[0] is not None
    ]


    total = sum(pnl) if pnl else 0

    trades = len(pnl)

    wins = len(
        [
            x for x in pnl
            if x > 0
        ]
    )

    losses = len(
        [
            x for x in pnl
            if x < 0
        ]
    )


    return {

        "trades": trades,

        "wins": wins,

        "losses": losses,

        "total_pnl": total,

        "equity": 10000 + total

    }



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
            "QPX STEP 14.1 LIVE MONITOR"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        cycles = 3


        for i in range(1, cycles + 1):


            metrics = collect_metrics()


            log(
                report,
                ""
            )


            log(
                report,
                "HEARTBEAT "
                + str(i)
            )


            log(
                report,
                "Time: "
                + datetime.datetime.now().isoformat()
            )


            log(
                report,
                "Trades: "
                + str(metrics["trades"])
            )


            log(
                report,
                "Wins: "
                + str(metrics["wins"])
            )


            log(
                report,
                "Losses: "
                + str(metrics["losses"])
            )


            log(
                report,
                "P/L: "
                + str(metrics["total_pnl"])
            )


            log(
                report,
                "Equity: "
                + str(metrics["equity"])
            )


            time.sleep(2)



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
            "QPX STEP 14.1 STATUS: OPERATIONAL"
        )


        log(
            report,
            "================================="
        )


    print()
    print("Report:")
    print(REPORT)



if __name__ == "__main__":

    main()