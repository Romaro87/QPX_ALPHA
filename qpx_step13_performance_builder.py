#!/usr/bin/env python3

import os
import sqlite3
import datetime


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
    "STEP13_5_PERFORMANCE_REPORT.txt"
)


def log(report, text):

    print(text)
    report.write(text + "\n")



def create_metrics_table():

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS performance_metrics (

            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            total_trades INTEGER,
            winning_trades INTEGER,
            losing_trades INTEGER,
            win_rate REAL,
            total_pnl REAL,
            average_pnl REAL,
            max_drawdown REAL

        )
        """
    )


    conn.commit()
    conn.close()



def calculate_metrics():

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


    pnl_values = [
        r[0]
        for r in rows
        if r[0] is not None
    ]


    total_trades = len(
        pnl_values
    )


    wins = len(
        [
            x for x in pnl_values
            if x > 0
        ]
    )


    losses = len(
        [
            x for x in pnl_values
            if x < 0
        ]
    )


    total_pnl = sum(
        pnl_values
    ) if pnl_values else 0


    average = (
        total_pnl / total_trades
        if total_trades
        else 0
    )


    win_rate = (
        wins / total_trades * 100
        if total_trades
        else 0
    )


    equity = 0
    peak = 0
    drawdown = 0


    for value in pnl_values:

        equity += value

        if equity > peak:

            peak = equity

        current_dd = peak - equity


        if current_dd > drawdown:

            drawdown = current_dd



    return {

        "total_trades": total_trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "average_pnl": average,
        "max_drawdown": drawdown

    }



def save_metrics(metrics):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        """
        INSERT INTO performance_metrics
        VALUES
        (NULL,?,?,?,?,?,?,?,?)
        """,
        (

            datetime.datetime.now().isoformat(),

            metrics["total_trades"],

            metrics["winning_trades"],

            metrics["losing_trades"],

            metrics["win_rate"],

            metrics["total_pnl"],

            metrics["average_pnl"],

            metrics["max_drawdown"]

        )
    )


    conn.commit()

    conn.close()



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
            "QPX STEP 13.5 PERFORMANCE BUILDER"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        create_metrics_table()


        log(
            report,
            "[PASS] Performance Table Ready"
        )


        metrics = calculate_metrics()


        save_metrics(
            metrics
        )


        for key,value in metrics.items():

            log(
                report,
                f"{key}: {value}"
            )


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
            "QPX STEP 13.5 STATUS: READY"
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