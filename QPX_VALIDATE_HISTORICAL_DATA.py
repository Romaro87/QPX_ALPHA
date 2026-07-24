#!/usr/bin/env python3

import os
import csv
import json
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CSV_FILE = os.path.join(ROOT, "historical_data.csv")
REPORT = os.path.join(ROOT, "QPX_HISTORICAL_DATA_VALIDATION.json")


def log(msg):
    print(datetime.datetime.now().isoformat(), msg)


def validate():

    result = {
        "timestamp": datetime.datetime.now().isoformat(),
        "status": "FAIL",
        "rows": 0,
        "columns": [],
        "errors": []
    }

    if not os.path.exists(CSV_FILE):
        result["errors"].append("historical_data.csv not found.")
        return result

    if os.path.getsize(CSV_FILE) < 100:
        result["errors"].append("CSV file is too small.")
        return result

    try:
        with open(CSV_FILE, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)

        if len(rows) < 2:
            result["errors"].append("CSV contains no data rows.")
            return result

        header = [h.strip().lower() for h in rows[0]]

        required = {
            "timestamp",
            "open",
            "high",
            "low",
            "close"
        }

        missing = sorted(required - set(header))

        if missing:
            result["errors"].append(
                "Missing columns: " + ", ".join(missing)
            )
            result["columns"] = header
            return result

        result["status"] = "PASS"
        result["rows"] = len(rows) - 1
        result["columns"] = header

        return result

    except Exception as e:
        result["errors"].append(str(e))
        return result


def main():

    log("QPX HISTORICAL DATA VALIDATOR START")

    report = validate()

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)

    if report["status"] == "PASS":
        log(f"Validated {report['rows']} rows")
        log("STATUS: PASS")
    else:
        log("STATUS: FAIL")
        for err in report["errors"]:
            log(err)

    log("Report:")
    log(REPORT)


if __name__ == "__main__":
    main()