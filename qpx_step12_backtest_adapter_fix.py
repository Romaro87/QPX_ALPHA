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
    "backtesting_engine_step12_backup.py"
)


def main():

    print(
        "QPX STEP 12 BACKTEST ADAPTER FIX"
    )


    if not os.path.exists(TARGET):

        print(
            "Backtesting engine not found"
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


    replacements = {

        "if historical_data:":

        "if historical_data is not None:",


        "if signals:":

        "if signals is not None:",


        "if df:":

        "if df is not None:"
    }


    changed=False


    for old,new in replacements.items():

        if old in content:

            content=content.replace(
                old,
                new
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
            "Backtesting engine updated"
        )

    else:

        print(
            "No direct boolean DataFrame checks found"
        )


    print(
        "Completed:",
        datetime.datetime.now()
    )


if __name__=="__main__":
    main()