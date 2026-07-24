#!/usr/bin/env python3

import os
import sqlite3
import importlib
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "qpx_runtime_healthcheck_v2_report.txt"
)


DATABASES = [
    os.path.join(ROOT, "qpx_alpha.db"),
    os.path.join(ROOT, "qpx_mobile.db")
]


CORE_FILES = [
    "main.py",
    "database.py",
    "query_engine.py",
    "feature_engine.py",
    "signal_engine.py",
    "backtesting_engine.py",
    "trade_event_schema_v2.py"
]


MODULES = [
    "feature_engine",
    "signal_engine",
    "backtesting_engine"
]


def log(report, text):
    print(text)
    report.write(text + "\n")


def check_files(report):

    result = True

    log(report, "\nCORE FILE CHECK")

    for file in CORE_FILES:

        path = os.path.join(ROOT, file)

        if os.path.exists(path):

            log(
                report,
                f"[PASS] {file}"
            )

        else:

            log(
                report,
                f"[FAIL] Missing {file}"
            )

            result = False

    return result



def find_databases():

    return [
        db for db in DATABASES
        if os.path.exists(db)
    ]



def validate_database(path, report):

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


        cur.execute(
            """
            SELECT COUNT(*)
            FROM market_data
            """
        )

        market_rows = cur.fetchone()[0]


        conn.close()


        log(
            report,
            f"\n[PASS] DATABASE {os.path.basename(path)}"
        )

        log(
            report,
            f"Tables: {tables}"
        )

        log(
            report,
            f"Market rows: {market_rows}"
        )


        required = [
            "market_data",
            "trades",
            "portfolio_snapshots"
        ]


        missing = [
            t for t in required
            if t not in tables
        ]


        if missing:

            log(
                report,
                f"[FAIL] Missing tables {missing}"
            )

            return False


        return True


    except Exception as e:

        log(
            report,
            f"[FAIL] Database error {e}"
        )

        return False



def check_modules(report):

    result=True

    log(
        report,
        "\nMODULE CHECK"
    )


    for module in MODULES:

        try:

            importlib.import_module(
                module
            )

            log(
                report,
                f"[PASS] MODULE {module}"
            )


        except Exception as e:

            log(
                report,
                f"[FAIL] MODULE {module}: {e}"
            )

            result=False


    return result



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
            "QPX STEP 11 RUNTIME HEALTH CHECK V2"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        results.append(
            check_files(report)
        )


        databases=find_databases()


        if not databases:

            log(
                report,
                "[FAIL] No QPX database found"
            )

            results.append(False)


        else:

            database_ok=False


            for db in databases:

                if validate_database(
                    db,
                    report
                ):

                    database_ok=True


            results.append(
                database_ok
            )


        results.append(
            check_modules(report)
        )


        log(
            report,
            "\n================================="
        )


        if all(results):

            log(
                report,
                "QPX SYSTEM STATUS: READY"
            )

        else:

            log(
                report,
                "QPX SYSTEM STATUS: NEEDS REVIEW"
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