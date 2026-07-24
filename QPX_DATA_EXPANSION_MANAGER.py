#!/usr/bin/env python3

import os
import sqlite3
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

DB = os.path.join(
    ROOT,
    "qpx_alpha.db"
)

REPORT = os.path.join(
    ROOT,
    "QPX_DATA_EXPANSION_REPORT.txt"
)


TARGET_ROWS = 100



def write(report, text):

    print(text)

    report.write(
        text + "\n"
    )



def inspect_data():

    result = {

        "exists": False,
        "rows": 0,
        "columns": []

    }


    if not os.path.exists(DB):

        return result


    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )


    tables = [

        x[0]
        for x in cur.fetchall()

    ]


    if "market_data" in tables:

        result["exists"] = True


        cur.execute(
            "PRAGMA table_info(market_data)"
        )


        result["columns"] = [

            x[1]
            for x in cur.fetchall()

        ]


        cur.execute(
            "SELECT COUNT(*) FROM market_data"
        )


        result["rows"] = cur.fetchone()[0]


    conn.close()


    return result



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
            "QPX DATA EXPANSION MANAGER"
        )

        write(
            report,
            datetime.datetime.now().isoformat()
        )

        write(
            report,
            "=============================="
        )


        data = inspect_data()


        write(
            report,
            "Market Data Table: "
            + (
                "FOUND"
                if data["exists"]
                else "MISSING"
            )
        )


        write(
            report,
            "Current Rows: "
            + str(data["rows"])
        )


        write(
            report,
            "Target Rows: "
            + str(TARGET_ROWS)
        )


        if data["rows"] >= TARGET_ROWS:

            write(
                report,
                "Data Status: READY"
            )


            write(
                report,
                "Swing Testing: UNLOCKED"
            )


        else:

            remaining = TARGET_ROWS - data["rows"]


            write(
                report,
                "Data Status: NEEDS EXPANSION"
            )


            write(
                report,
                "Additional Rows Needed: "
                + str(remaining)
            )


            write(
                report,
                "Swing Testing: LOCKED"
            )


        write(
            report,
            "STATUS: EXPANSION CHECK COMPLETE"
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