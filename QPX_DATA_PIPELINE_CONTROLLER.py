#!/usr/bin/env python3

import json
import datetime
import traceback

from QPX_DOWNLOAD_HISTORICAL_CSV import download
from QPX_VALIDATE_HISTORICAL_DATA import validate

ROOT = "/storage/emulated/0/QPX_ALPHA"
REPORT = ROOT + "/QPX_DATA_PIPELINE_REPORT.json"


def stage(name, func):
    print(f"\n=== {name} ===")

    try:
        result = func()

        if result is False:
            return {
                "stage": name,
                "status": "FAIL"
            }

        if isinstance(result, tuple):
            ok, message = result

            return {
                "stage": name,
                "status": "PASS" if ok else "FAIL",
                "message": message
            }

        return {
            "stage": name,
            "status": "PASS"
        }

    except Exception as e:

        return {
            "stage": name,
            "status": "ERROR",
            "message": str(e),
            "traceback": traceback.format_exc()
        }


def main():

    report = {
        "timestamp": datetime.datetime.now().isoformat(),
        "stages": []
    }

    download_result = stage(
        "Download Historical Data",
        download
    )

    report["stages"].append(download_result)

    if download_result["status"] != "PASS":

        report["status"] = "FAILED"

    else:

        validation_result = stage(
            "Validate Historical Data",
            validate
        )

        report["stages"].append(validation_result)

        report["status"] = (
            "PASS"
            if validation_result["status"] == "PASS"
            else "FAILED"
        )

    with open(REPORT, "w") as f:
        json.dump(report, f, indent=4)

    print("\n===========================")
    print("PIPELINE:", report["status"])
    print("===========================")
    print(REPORT)


if __name__ == "__main__":
    main()