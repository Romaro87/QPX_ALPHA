#!/usr/bin/env python3

import os
import shutil
import datetime
import sqlite3


ROOT = "/storage/emulated/0/QPX_ALPHA"


STEP13_DIR = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION"
)


REPORT = os.path.join(
    ROOT,
    "qpx_step13_preparation_report.txt"
)


FILES = [

    "main.py",
    "database.py",
    "query_engine.py",

    "feature_engine.py",
    "signal_engine.py",
    "backtesting_engine.py",

    "trade_event_schema_v2.py",

    "qpx_alpha.db",
    "qpx_mobile.db"

]


def log(report, text):

    print(text)

    report.write(
        text + "\n"
    )



def backup_file(source, destination):

    if os.path.exists(source):

        shutil.copy2(
            source,
            destination
        )

        return True

    return False



def check_database(report):

    databases = [
        "qpx_alpha.db",
        "qpx_mobile.db"
    ]


    for db in databases:

        path = os.path.join(
            ROOT,
            db
        )


        if os.path.exists(path):

            try:

                conn = sqlite3.connect(path)

                cur = conn.cursor()


                cur.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type='table'
                    """
                )


                tables = [
                    x[0]
                    for x in cur.fetchall()
                ]


                conn.close()


                log(
                    report,
                    f"[PASS] {db}: {tables}"
                )


            except Exception as e:

                log(
                    report,
                    f"[FAIL] {db}: {e}"
                )


        else:

            log(
                report,
                f"[SKIP] {db} missing"
            )



def main():

    os.makedirs(
        STEP13_DIR,
        exist_ok=True
    )


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
            "QPX STEP 13 PREPARATION"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        log(
            report,
            ""
        )


        for file in FILES:

            source = os.path.join(
                ROOT,
                file
            )

            destination = os.path.join(
                STEP13_DIR,
                file
            )


            if backup_file(
                source,
                destination
            ):

                log(
                    report,
                    "[COPIED] " + file
                )

            else:

                log(
                    report,
                    "[MISSING] " + file
                )



        log(
            report,
            ""
        )


        check_database(
            report
        )


        checklist = os.path.join(
            STEP13_DIR,
            "STEP13_CHECKLIST.txt"
        )


        with open(
            checklist,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                """
QPX STEP 13 LIVE SIMULATION CHECKLIST

[ ] Paper trading engine
[ ] Live signal feed
[ ] Position manager
[ ] Risk controls
[ ] Performance tracking
[ ] Trade journal integration
[ ] Mobile dashboard
"""
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
            "STEP 13 PREPARATION COMPLETE"
        )

        log(
            report,
            "Workspace:"
        )

        log(
            report,
            STEP13_DIR
        )

        log(
            report,
            "================================="
        )



if __name__ == "__main__":

    main()