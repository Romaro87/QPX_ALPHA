#!/usr/bin/env python3

import os
import csv
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

FILE = os.path.join(
    ROOT,
    "historical_data.csv"
)


def main():

    print(
        datetime.datetime.now().isoformat(),
        "QPX DATA TEMPLATE CREATOR START"
    )


    if os.path.exists(FILE):

        print(
            "Template already exists:"
        )

        print(
            FILE
        )

        return


    headers = [
        "timestamp",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]


    sample_rows = [

        [
            "2026-01-01",
            "TEST",
            100,
            102,
            99,
            101,
            5000
        ],

        [
            "2026-01-02",
            "TEST",
            101,
            104,
            100,
            103,
            6200
        ]

    ]


    with open(
        FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:


        writer = csv.writer(f)

        writer.writerow(
            headers
        )

        writer.writerows(
            sample_rows
        )


    print(
        "Historical CSV template created"
    )

    print(
        FILE
    )


    print(
        "Replace sample rows with real market data"
    )



if __name__ == "__main__":

    main()