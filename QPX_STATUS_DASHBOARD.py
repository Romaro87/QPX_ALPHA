#!/usr/bin/env python3

import os
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

STEP14_REPORT = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION",
    "STEP14_1_MONITOR_REPORT.txt"
)

DASHBOARD = os.path.join(
    ROOT,
    "QPX_STATUS_DASHBOARD.txt"
)


def extract_value(text, label):

    for line in text.splitlines():

        if line.startswith(label):

            return line.replace(
                label,
                ""
            ).strip()

    return "N/A"


def main():

    status = "UNKNOWN"

    trades = "N/A"
    wins = "N/A"
    losses = "N/A"
    pnl = "N/A"
    equity = "N/A"


    if os.path.exists(STEP14_REPORT):

        with open(
            STEP14_REPORT,
            "r",
            encoding="utf-8"
        ) as f:

            data = f.read()


        if "OPERATIONAL" in data:
            status = "OPERATIONAL"


        trades = extract_value(
            data,
            "Trades:"
        )

        wins = extract_value(
            data,
            "Wins:"
        )

        losses = extract_value(
            data,
            "Losses:"
        )

        pnl = extract_value(
            data,
            "P/L:"
        )

        equity = extract_value(
            data,
            "Equity:"
        )


    with open(
        DASHBOARD,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "=============================\n"
        )

        f.write(
            "QPX ALPHA STATUS DASHBOARD\n"
        )

        f.write(
            "=============================\n\n"
        )

        f.write(
            "Last Update: "
            + datetime.datetime.now().isoformat()
            + "\n\n"
        )

        f.write(
            "System Status: "
            + status
            + "\n"
        )

        f.write(
            "Current Step: 14.2\n\n"
        )

        f.write(
            "Trades: "
            + trades
            + "\n"
        )

        f.write(
            "Wins: "
            + wins
            + "\n"
        )

        f.write(
            "Losses: "
            + losses
            + "\n"
        )

        f.write(
            "P/L: "
            + pnl
            + "\n"
        )

        f.write(
            "Equity: "
            + equity
            + "\n"
        )


    print(
        "Dashboard created:"
    )

    print(
        DASHBOARD
    )


if __name__ == "__main__":
    main()