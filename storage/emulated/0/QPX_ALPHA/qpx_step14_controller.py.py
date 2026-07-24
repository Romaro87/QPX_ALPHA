#!/usr/bin/env python3

import os
import time
import shutil
import datetime
import subprocess


ROOT = "/storage/emulated/0/QPX_ALPHA"

STEP13_DIR = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION"
)

STEP14_1_REPORT = os.path.join(
    STEP13_DIR,
    "STEP14_1_MONITOR_REPORT.txt"
)

ARCHIVE_DIR = os.path.join(
    ROOT,
    "REPORT_ARCHIVE"
)

STEP14_2_DIR = os.path.join(
    ROOT,
    "QPX_STEP14_2"
)

STEP14_2_SCRIPT = os.path.join(
    STEP14_2_DIR,
    "step14_2.py"
)

STEP14_2_REPORT = os.path.join(
    STEP14_2_DIR,
    "STEP14_2_REPORT.txt"
)


def log(msg):
    print(
        datetime.datetime.now().isoformat(),
        msg
    )


def validate_step14_1():

    if not os.path.exists(STEP14_1_REPORT):
        return False

    with open(
        STEP14_1_REPORT,
        "r",
        encoding="utf-8"
    ) as f:

        data = f.read()

    return (
        "QPX STEP 14.1 STATUS: OPERATIONAL"
        in data
    )


def archive_step14_1():

    os.makedirs(
        ARCHIVE_DIR,
        exist_ok=True
    )

    stamp = datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    shutil.copy(
        STEP14_1_REPORT,
        os.path.join(
            ARCHIVE_DIR,
            f"STEP14_1_{stamp}.txt"
        )
    )


def create_step14_2():

    os.makedirs(
        STEP14_2_DIR,
        exist_ok=True
    )

    if os.path.exists(STEP14_2_SCRIPT):
        return


    code = r'''
import os
import datetime
import sqlite3


ROOT = "/storage/emulated/0/QPX_ALPHA"

DB = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION",
    "qpx_step13_simulation.db"
)

REPORT = os.path.join(
    ROOT,
    "QPX_STEP14_2",
    "STEP14_2_REPORT.txt"
)


def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as f:

        f.write("===============================\n")
        f.write("QPX STEP 14.2 VALIDATION\n")
        f.write(
            datetime.datetime.now().isoformat()
            + "\n"
        )
        f.write("===============================\n\n")


        if os.path.exists(DB):

            f.write(
                "Database: OK\n"
            )

            try:

                conn = sqlite3.connect(DB)

                cur = conn.cursor()

                cur.execute(
                    "SELECT COUNT(*) FROM lifecycle_trades"
                )

                count = cur.fetchone()[0]

                conn.close()


                f.write(
                    "Lifecycle trades: "
                    + str(count)
                    + "\n"
                )

                f.write(
                    "STATUS: OPERATIONAL\n"
                )

            except Exception as e:

                f.write(
                    "Database check failed\n"
                )

                f.write(
                    str(e)
                )

        else:

            f.write(
                "Database missing\n"
            )


if __name__ == "__main__":
    main()
'''

    with open(
        STEP14_2_SCRIPT,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(code)


    log(
        "STEP14.2 module created"
    )


def launch_step14_2():

    subprocess.Popen(
        [
            "python",
            STEP14_2_SCRIPT
        ]
    )

    log(
        "STEP14.2 launched"
    )


def main():

    log(
        "QPX STEP14 AUTOMATION START"
    )


    if validate_step14_1():

        log(
            "STEP14.1 validated"
        )

        archive_step14_1()

        log(
            "STEP14.1 archived"
        )

        create_step14_2()

        launch_step14_2()

    else:

        log(
            "STEP14.1 validation failed"
        )


if __name__ == "__main__":
    main()