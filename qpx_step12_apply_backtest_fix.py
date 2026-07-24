#!/usr/bin/env python3

import os
import shutil
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

TARGET = os.path.join(
    ROOT,
    "backtesting_engine.py"
)

BACKUP = os.path.join(
    ROOT,
    "backtesting_engine_step12_final_backup.py"
)


def main():

    print(
        "QPX STEP 12 APPLY BACKTEST FIX"
    )


    if not os.path.exists(TARGET):

        print(
            "ERROR: backtesting_engine.py missing"
        )

        return


    shutil.copy2(
        TARGET,
        BACKUP
    )


    print(
        "Backup created:"
    )

    print(
        BACKUP
    )


    with open(
        TARGET,
        "r",
        encoding="utf-8"
    ) as f:

        content=f.read()


    old1 = (
        "signals = signals or []"
    )

    new1 = (
        "signals = [] if signals is None else signals"
    )


    old2 = (
        "historical_data = historical_data or []"
    )

    new2 = (
        "historical_data = [] if historical_data is None else historical_data"
    )


    changed=False


    if old1 in content:

        content=content.replace(
            old1,
            new1
        )

        changed=True


    if old2 in content:

        content=content.replace(
            old2,
            new2
        )

        changed=True


    with open(
        TARGET,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(content)


    if changed:

        print(
            "SUCCESS: Backtesting compatibility fixed"
        )

    else:

        print(
            "No matching lines found"
        )


    print(
        "Completed:",
        datetime.datetime.now()
    )


if __name__=="__main__":
    main()