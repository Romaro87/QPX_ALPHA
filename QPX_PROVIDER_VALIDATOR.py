#!/usr/bin/env python3

import os
import csv
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CSV_FILE = os.path.join(ROOT, "historical_data.csv")

REPORT = os.path.join(
    ROOT,
    "QPX_PROVIDER_VALIDATION_REPORT.txt"
)

REQUIRED = {
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume"
}


def log(report, text):
    print(text)
    report.write(text + "\n")


def classify_response():

    if not os.path.exists(CSV_FILE):
        return False, "CSV file not found"

    with open(
        CSV_FILE,
        "r",
        encoding="utf-8",
        errors="replace"
    ) as f:

        lines = f.readlines()

    if not lines:
        return False, "Downloaded file is empty"

    header = lines[0].strip().lower()

    if "timestamp" in header:

        reader = csv.reader(lines)
        headers = next(reader)

        headers = {
            h.strip().lower()
            for h in headers
        }

        missing = REQUIRED - headers

        if missing:
            return False, (
                "Missing columns: "
                + ", ".join(sorted(missing))
            )

        rows = max(0, len(lines) - 1)

        return True, (
            "Valid historical CSV (" +
            str(rows) +
            " rows)"
        )

    text = "\n".join(lines[:10]).lower()

    if "invalid api call" in text:
        return False, "Alpha Vantage rejected the request"

    if "api key" in text:
        return False, "API key problem detected"

    if "thank you for using alpha vantage" in text:
        return False, "API rate limit reached"

    return False, "Unknown response format"


def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:

        log(report, "==============================")
        log(report, "QPX PROVIDER VALIDATION")
        log(report, datetime.datetime.now().isoformat())
        log(report, "==============================")

        ok, message = classify_response()

        if ok:
            log(report, "VALIDATION: PASS")
        else:
            log(report, "VALIDATION: FAIL")

        log(report, message)

        log(report, "STATUS: COMPLETE")


if __name__ == "__main__":
    main()