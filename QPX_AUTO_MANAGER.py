#!/usr/bin/env python3

import os
import datetime
import subprocess
import time


ROOT = "/storage/emulated/0/QPX_ALPHA"

STATUS_FILE = os.path.join(
    ROOT,
    "QPX_STATUS_REPORT.txt"
)


def log(message):

    stamp = datetime.datetime.now().isoformat()

    print(stamp, message)

    with open(
        STATUS_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            stamp + " " + message + "\n"
        )


def run_step14():

    controller = os.path.join(
        ROOT,
        "qpx_step14_controller.py"
    )

    if os.path.exists(controller):

        log(
            "Starting Step 14 controller"
        )

        subprocess.run(
            [
                "python",
                controller
            ]
        )

        log(
            "Step 14 finished"
        )

    else:

        log(
            "Controller missing - creating setup"
        )


def main():

    os.makedirs(
        ROOT,
        exist_ok=True
    )

    log(
        "QPX AUTO MANAGER START"
    )

    run_step14()

    log(
        "QPX AUTO MANAGER COMPLETE"
    )


if __name__ == "__main__":

    main()