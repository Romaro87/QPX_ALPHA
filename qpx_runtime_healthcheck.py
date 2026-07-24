#!/usr/bin/env python3

import os
import sqlite3
import importlib
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "qpx_runtime_healthcheck_report.txt"
)

DB_CANDIDATES = [
    os.path.join(ROOT, "qpx.db"),
    os.path.join(ROOT, "database.db"),
    os.path.join(ROOT, "data.db")
]


def write(report, msg):
    print(msg)
    report.write(msg + "\n")


def check_file(path, report):

    if os.path.exists(path):
        write(
            report,
            f"[PASS] FILE {os.path.basename(path)}"
        )
        return True

    write(
        report,
        f"[FAIL] FILE MISSING {path}"
    )
    return False


def find_database():

    for db in DB_CANDIDATES:
        if os.path.exists(db):
            return db

    return None


def check_database(report):

    db = find_database()

    if not db:

        write(
            report,
            "[WARN] No database file detected"
        )
        return False


    try:

        conn = sqlite3.connect(db)

        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )

        tables = cursor.fetchall()

        conn.close()

        write(
            report,
            f"[PASS] DATABASE {db}"
        )

        write(
            report,
            f"Tables detected: {len(tables)}"
        )

        return True


    except Exception as e:

        write(
            report,
            f"[FAIL] DATABASE ERROR {e}"
        )

        return False


def check_market_data(report):

    db = find_database()

    if not db:
        return False


    try:

        conn = sqlite3.connect(db)

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


        market_tables = [
            t for t in tables
            if "market" in t.lower()
            or "ohlcv" in t.lower()
            or "price" in t.lower()
        ]


        conn.close()


        if market_tables:

            write(
                report,
                f"[PASS] MARKET DATA TABLES {market_tables}"
            )
            return True


        write(
            report,
            "[WARN] No market table detected"
        )

        return False


    except Exception as e:

        write(
            report,
            f"[FAIL] MARKET CHECK {e}"
        )

        return False



def check_module(module, report):

    try:

        importlib.import_module(module)

        write(
            report,
            f"[PASS] MODULE {module}"
        )

        return True


    except Exception as e:

        write(
            report,
            f"[FAIL] MODULE {module}: {e}"
        )

        return False



def main():

    results=[]


    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:


        write(
            report,
            "================================="
        )

        write(
            report,
            "QPX STEP 11 RUNTIME HEALTH CHECK"
        )

        write(
            report,
            datetime.datetime.now().isoformat()
        )

        write(
            report,
            "================================="
        )


        core_files = [

            "main.py",

            "database.py",

            "query_engine.py",

            "feature_engine.py",

            "signal_engine.py",

            "backtesting_engine.py",

            "trade_event_schema_v2.py"

        ]


        for f in core_files:

            results.append(
                check_file(
                    os.path.join(ROOT,f),
                    report
                )
            )



        results.append(
            check_database(report)
        )


        results.append(
            check_market_data(report)
        )


        modules = [

            "feature_engine",

            "signal_engine",

            "backtesting_engine"

        ]


        for m in modules:

            results.append(
                check_module(
                    m,
                    report
                )
            )



        write(
            report,
            ""
        )


        if all(results):

            status = (
                "QPX SYSTEM STATUS: READY"
            )

        else:

            status = (
                "QPX SYSTEM STATUS: NEEDS REVIEW"
            )


        write(
            report,
            "================================="
        )

        write(
            report,
            status
        )

        write(
            report,
            "================================="
        )



    print()
    print(
        "Health report:"
    )
    print(
        REPORT
    )



if __name__ == "__main__":
    main()