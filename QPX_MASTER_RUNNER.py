#!/usr/bin/env python3

import os
import datetime
import subprocess


ROOT = "/storage/emulated/0/QPX_ALPHA"

CONTROLLER = os.path.join(
    ROOT,
    "qpx_step14_controller.py"
)


def log(text):
    print(
        datetime.datetime.now().isoformat(),
        text
    )


def create_controller():

    if os.path.exists(CONTROLLER):
        return


    controller_code = r'''
#!/usr/bin/env python3

import os
import time
import datetime
import subprocess
import shutil


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION",
    "STEP14_1_MONITOR_REPORT.txt"
)


ARCHIVE = os.path.join(
    ROOT,
    "REPORT_ARCHIVE"
)


STEP14_2 = os.path.join(
    ROOT,
    "QPX_STEP14_2",
    "step14_2.py"
)


def log(text):

    print(
        datetime.datetime.now().isoformat(),
        text
    )


def main():

    log("STEP14 CONTROLLER START")


    if os.path.exists(REPORT):

        with open(REPORT) as f:
            data = f.read()


        if "OPERATIONAL" in data:

            log("STEP14.1 validated")


            os.makedirs(
                ARCHIVE,
                exist_ok=True
            )


            shutil.copy(
                REPORT,
                os.path.join(
                    ARCHIVE,
                    "STEP14_1_BACKUP.txt"
                )
            )


            log("STEP14.1 archived")


            if os.path.exists(STEP14_2):

                subprocess.run(
                    [
                        "python",
                        STEP14_2
                    ]
                )

                log("STEP14.2 launched")

            else:

                log(
                    "STEP14.2 not found"
                )

        else:

            log(
                "STEP14.1 not operational"
            )

    else:

        log(
            "STEP14.1 report missing"
        )


if __name__ == "__main__":
    main()

'''


    with open(
        CONTROLLER,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(controller_code)


    log(
        "Controller automatically created"
    )



def main():

    log(
        "QPX ALPHA MASTER RUNNER START"
    )


    create_controller()


    subprocess.run(
        [
            "python",
            CONTROLLER
        ]
    )


    log(
        "QPX ALPHA PIPELINE COMPLETE"
    )



if __name__ == "__main__":
    main()