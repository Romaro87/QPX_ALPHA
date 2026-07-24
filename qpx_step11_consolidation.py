#!/usr/bin/env python3

import os
import shutil
import datetime
import subprocess
import sys


ROOT = "/storage/emulated/0/QPX_ALPHA"

ARCHIVE = os.path.join(ROOT, "archive_repairs")

REPORT = os.path.join(
    ROOT,
    "step11_consolidation_report.txt"
)


REPAIR_PATTERNS = [
    "repair_",
    "step10",
    "qpx_step10",
    "auto_repair"
]


CORE_FILES = [
    "main.py",
    "database.py",
    "query_engine.py",
    "feature_engine.py",
    "signal_engine.py",
    "backtesting_engine.py",
    "trade_event_schema_v2.py"
]


VALIDATORS = [
    "validate_step8_feature_engine.py",
    "validate_step9_signal_engine.py",
    "validate_step10_runtime.py",
    "validate_step11_runtime.py"
]


def log(msg, f):
    print(msg)
    f.write(msg + "\n")


def backup():
    stamp = datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    backup_dir = os.path.join(
        ROOT,
        f"QPX_STEP11_BACKUP_{stamp}"
    )

    os.makedirs(backup_dir)

    return backup_dir


def archive_repairs(report):
    os.makedirs(
        ARCHIVE,
        exist_ok=True
    )

    moved = []

    for file in os.listdir(ROOT):

        path = os.path.join(ROOT, file)

        if not os.path.isfile(path):
            continue

        lower = file.lower()

        if (
            any(x in lower for x in REPAIR_PATTERNS)
            and file != os.path.basename(__file__)
        ):

            destination = os.path.join(
                ARCHIVE,
                file
            )

            shutil.move(
                path,
                destination
            )

            moved.append(file)


    report.write(
        "\nARCHIVED REPAIR FILES\n"
    )

    for x in moved:
        report.write(
            f" - {x}\n"
        )


def detect_duplicates(report):

    report.write(
        "\nDUPLICATE ENGINE CHECK\n"
    )

    targets = [
        "backtesting_engine.py",
        "database.py",
        "query_engine.py"
    ]

    for target in targets:

        matches=[]

        for root, dirs, files in os.walk(ROOT):

            if target in files:

                matches.append(
                    os.path.join(root,target)
                )


        report.write(
            f"\n{target}\n"
        )

        for m in matches:
            report.write(
                f"  {m}\n"
            )


def check_core(report):

    report.write(
        "\nCORE FILE CHECK\n"
    )

    for f in CORE_FILES:

        path=os.path.join(ROOT,f)

        if os.path.exists(path):

            report.write(
                f"[OK] {f}\n"
            )

        else:

            report.write(
                f"[MISSING] {f}\n"
            )


def run_validators(report):

    report.write(
        "\nVALIDATOR RESULTS\n"
    )

    for validator in VALIDATORS:

        path=os.path.join(
            ROOT,
            validator
        )

        if not os.path.exists(path):

            report.write(
                f"[SKIP] {validator}\n"
            )
            continue


        report.write(
            f"\nRunning {validator}\n"
        )

        try:

            result=subprocess.run(
                [
                    sys.executable,
                    path
                ],
                capture_output=True,
                text=True,
                timeout=120
            )


            report.write(
                result.stdout
            )

            report.write(
                result.stderr
            )


            if result.returncode==0:
                report.write(
                    "\nSTATUS: PASS\n"
                )
            else:
                report.write(
                    "\nSTATUS: FAIL\n"
                )


        except Exception as e:

            report.write(
                f"ERROR {e}\n"
            )


def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:


        log(
            "QPX STEP 11 CONSOLIDATION",
            report
        )


        backup_dir=backup()

        log(
            f"\nBackup created: {backup_dir}",
            report
        )


        archive_repairs(report)


        detect_duplicates(report)


        check_core(report)


        run_validators(report)


        log(
            "\nCONSOLIDATION COMPLETE",
            report
        )


    print(
        "\nReport:",
        REPORT
    )


if __name__=="__main__":
    main()