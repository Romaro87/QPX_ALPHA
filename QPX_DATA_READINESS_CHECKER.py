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
    "QPX_DATA_READINESS_REPORT.txt"
)


MIN_ROWS = 100


def write(report, text):

    print(text)

    report.write(
        text + "\n"
    )


def check_database():

    result = {

        "rows": 0,
        "columns": [],
        "ohlc": False,
        "volume": False

    }


    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )

    tables = [
        x[0]
        for x in cur.fetchall()
    ]


    if "market_data" not in tables:

        conn.close()

        return result



    cur.execute(
        "PRAGMA table_info(market_data)"
    )


    columns = [

        x[1]
        for x in cur.fetchall()

    ]


    result["columns"] = columns



    cur.execute(
        "SELECT COUNT(*) FROM market_data"
    )


    result["rows"] = cur.fetchone()[0]



    required_price = [

        "open",
        "high",
        "low",
        "close"

    ]


    result["ohlc"] = all(

        x in columns

        for x in required_price

    )


    result["volume"] = (

        "volume" in columns

    )


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
            "QPX DATA READINESS REPORT"
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

            data = check_database()


            write(
                report,
                "Rows: "
                + str(data["rows"])
            )


            write(
                report,
                "Minimum Recommended: "
                + str(MIN_ROWS)
            )


            write(
                report,
                "OHLC Data: "
                + (
                    "PASS"
                    if data["ohlc"]
                    else "FAIL"
                )
            )


            write(
                report,
                "Volume Data: "
                + (
                    "PASS"
                    if data["volume"]
                    else "FAIL"
                )
            )


            if data["rows"] >= MIN_ROWS:

                write(
                    report,
                    "Swing Testing: READY"
                )


            else:

                write(
                    report,
                    "Swing Testing: NOT READY"
                )


                write(
                    report,
                    "Reason: Insufficient historical candles"
                )


            write(
                report,
                "STATUS: CHECK COMPLETE"
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