#!/usr/bin/env python3

import os
import shutil
import re
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

TARGET = os.path.join(
    ROOT,
    "backtesting_engine.py"
)

BACKUP = os.path.join(
    ROOT,
    "backtesting_engine_before_deep_fix.py"
)


PATTERNS = [
    r"if\s+\w+\s*:",
    r"\w+\s*=\s*\w+\s+or\s+\[\]",
    r"\w+\s*=\s*\w+\s+or\s+None",
    r"return\s+\w+\s+or"
]


def main():

    print(
        "QPX STEP 12 BACKTEST DEEP SCAN"
    )


    if not os.path.exists(TARGET):

        print(
            "Backtesting engine missing"
        )

        return


    shutil.copy2(
        TARGET,
        BACKUP
    )


    print(
        "Backup:",
        BACKUP
    )


    with open(
        TARGET,
        "r",
        encoding="utf-8"
    ) as f:

        lines=f.readlines()


    found=[]


    for number,line in enumerate(lines,1):

        for pattern in PATTERNS:

            if re.search(
                pattern,
                line
            ):

                found.append(
                    (number,line.strip())
                )


    print(
        "\nPotential DataFrame checks:"
    )


    for item in found:

        print(
            item
        )


    print(
        "\nScan complete:",
        datetime.datetime.now()
    )


if __name__=="__main__":
    main()