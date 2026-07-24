#!/usr/bin/env python3

import os
import subprocess
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

REPORT = os.path.join(
    ROOT,
    "QPX_MASTER_DATA_PIPELINE_REPORT.txt"
)


def write(report, text):

    print(text)
    report.write(text + "\n")


def run_script(script):

    path = os.path.join(
        ROOT,
        script
    )

    if os.path.exists(path):

        subprocess.run(
            [
                "python",
                path
            ]
        )

        return True

    return False



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
            "QPX MASTER DATA PIPELINE"
        )

        write(
            report,
            datetime.datetime.now().isoformat()
        )

        write(
            report,
            "=============================="
        )


        csv = os.path.join(
            ROOT,
            "historical_data.csv"
        )


        if os.path.exists(csv):

            write(
                report,
                "Historical CSV found"
            )

            run_script(
                "QPX_HISTORICAL_IMPORTER.py"
            )

        else:

            write(
                report,
                "Historical CSV missing"
            )

            write(
                report,
                "Waiting for market data"
            )


        write(
            report,
            "Running readiness check"
        )


        run_script(
            "QPX_DATA_READINESS_CHECKER.py"
        )


        write(
            report,
            "Running expansion check"
        )


        run_script(
            "QPX_DATA_EXPANSION_MANAGER.py"
        )


        write(
            report,
            "Pipeline complete"
        )


        write(
            report,
            "STATUS: COMPLETE"
        )



if __name__ == "__main__":

    main()