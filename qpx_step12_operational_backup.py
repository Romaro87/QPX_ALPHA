#!/usr/bin/env python3

import os
import shutil
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"


def timestamp():

    return datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )


BACKUP_DIR = os.path.join(
    ROOT,
    "QPX_STEP12_OPERATIONAL_BACKUP_" + timestamp()
)


FILES = [

    # Core runtime
    "main.py",
    "database.py",
    "query_engine.py",

    # Engines
    "feature_engine.py",
    "signal_engine.py",
    "backtesting_engine.py",
    "trade_event_schema_v2.py",

    # Database
    "qpx_alpha.db",
    "qpx_mobile.db",

    # Step 12 validation
    "qpx_step12_auto_fix.py",
    "qpx_step12_pipeline_smoke_test_v3.py",
    "qpx_step12_pipeline_smoke_test_v4.py",
    "qpx_step12_auto_fix_report.txt",

    # Health reports
    "qpx_runtime_healthcheck_v2_report.txt",
    "qpx_step11_consolidation_report.txt"

]


def copy_file(src, dest):

    if os.path.exists(src):

        shutil.copy2(
            src,
            dest
        )

        return True

    return False



def main():

    print(
        "================================="
    )

    print(
        "QPX STEP 12 OPERATIONAL BACKUP"
    )

    print(
        "================================="
    )


    os.makedirs(
        BACKUP_DIR,
        exist_ok=True
    )


    manifest=[]


    for file in FILES:

        source=os.path.join(
            ROOT,
            file
        )


        destination=os.path.join(
            BACKUP_DIR,
            file
        )


        if copy_file(
            source,
            destination
        ):

            print(
                "[BACKUP]",
                file
            )

            manifest.append(
                file
            )

        else:

            print(
                "[SKIP]",
                file
            )


    # Save manifest

    manifest_file=os.path.join(
        BACKUP_DIR,
        "BACKUP_MANIFEST.txt"
    )


    with open(
        manifest_file,
        "w",
        encoding="utf-8"
    ) as f:


        f.write(
            "QPX STEP 12 OPERATIONAL BACKUP\n"
        )

        f.write(
            datetime.datetime.now().isoformat()
            + "\n\n"
        )


        for item in manifest:

            f.write(
                item + "\n"
            )


    print()

    print(
        "================================="
    )

    print(
        "BACKUP COMPLETE"
    )

    print(
        "================================="
    )

    print(
        "Location:"
    )

    print(
        BACKUP_DIR
    )

    print()

    print(
        "Manifest:"
    )

    print(
        manifest_file
    )



if __name__ == "__main__":

    main()