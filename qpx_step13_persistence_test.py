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
    "STEP13_PERSISTENCE_TEST_REPORT.txt"
)


sys.path.insert(0, STEP13)



def log(report, text):

    print(text)

    report.write(
        text + "\n"
    )



def get_signal():

    return {

        "timestamp":
        datetime.datetime.now().isoformat(),

        "signal":
        "HOLD",

        "score":
        0.0,

        "confidence":
        0.0

    }



def insert_trade(signal):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        """
        INSERT INTO paper_trades
        (
        timestamp,
        signal,
        score,
        confidence,
        status
        )
        VALUES (?,?,?,?,?)
        """,
        (
            signal["timestamp"],
            signal["signal"],
            signal["score"],
            signal["confidence"],
            "SIMULATED"
        )
    )


    trade_id = cur.lastrowid


    conn.commit()

    conn.close()


    return trade_id



def insert_position(trade_id):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        """
        INSERT INTO positions
        (
        trade_id,
        position_status,
        created
        )
        VALUES (?,?,?)
        """,
        (
            trade_id,
            "OPEN",
            datetime.datetime.now().isoformat()
        )
    )


    conn.commit()

    conn.close()



def insert_journal(event):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        """
        INSERT INTO trade_journal
        (
        event_time,
        event
        )
        VALUES (?,?)
        """,
        (
            datetime.datetime.now().isoformat(),
            str(event)
        )
    )


    conn.commit()

    conn.close()



def verify_database():

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    results = {}


    for table in [

        "paper_trades",
        "positions",
        "trade_journal"

    ]:

        cur.execute(
            f"SELECT COUNT(*) FROM {table}"
        )

        results[table] = cur.fetchone()[0]


    conn.close()


    return results



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
            "QPX STEP 13.3 PERSISTENCE TEST"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        signal = get_signal()


        log(
            report,
            "[SIGNAL]"
        )

        log(
            report,
            str(signal)
        )


        trade_id = insert_trade(
            signal
        )


        log(
            report,
            "[PASS] Trade Stored ID: "
            + str(trade_id)
        )


        insert_position(
            trade_id
        )


        log(
            report,
            "[PASS] Position Stored"
        )


        insert_journal(
            signal
        )


        log(
            report,
            "[PASS] Journal Stored"
        )


        log(
            report,
            ""
        )

        log(
            report,
            "Restart Simulation..."
        )


        results = verify_database()


        for table,count in results.items():

            if count > 0:

                log(
                    report,
                    "[PASS] "
                    + table
                    + " records: "
                    + str(count)
                )

            else:

                log(
                    report,
                    "[FAIL] "
                    + table
                )


        log(
            report,
            ""
        )

        log(
            report,
            "================================="
        )


        if all(
            value > 0
            for value in results.values()
        ):

            log(
                report,
                "QPX STEP 13.3 STATUS: OPERATIONAL"
            )

        else:

            log(
                report,
                "QPX STEP 13.3 STATUS: NEEDS REVIEW"
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