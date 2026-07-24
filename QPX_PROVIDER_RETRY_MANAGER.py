#!/usr/bin/env python3

"""
QPX Provider Retry Manager

Runs the Alpha Vantage pipeline and automatically retries
when the provider reports a rate-limit response.
"""

import os
import time
import subprocess
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

PIPELINE = os.path.join(
    ROOT,
    "QPX_ALPHA_VANTAGE_PIPELINE.py"
)

VALIDATION = os.path.join(
    ROOT,
    "QPX_PROVIDER_VALIDATION_REPORT.txt"
)

REPORT = os.path.join(
    ROOT,
    "QPX_PROVIDER_RETRY_REPORT.txt"
)

MAX_RETRIES = 3

WAIT_SECONDS = 60


def log(report, text):

    print(text)

    report.write(
        text + "\n"
    )


def validation_status():

    if not os.path.exists(VALIDATION):
        return "missing"

    with open(
        VALIDATION,
        "r",
        encoding="utf-8",
        errors="ignore"
    ) as f:

        text = f.read().lower()

    if "validation: pass" in text:
        return "pass"

    if "rate limit" in text:
        return "rate_limit"

    if "api key" in text:
        return "api_key"

    return "failed"


def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:

        log(report, "=" * 30)
        log(report, "QPX PROVIDER RETRY MANAGER")
        log(report, datetime.datetime.now().isoformat())
        log(report, "=" * 30)

        for attempt in range(1, MAX_RETRIES + 1):

            log(report, "")
            log(report, f"Attempt {attempt}")

            subprocess.run(
                ["python", PIPELINE]
            )

            status = validation_status()

            log(report, f"Validation Status: {status}")

            if status == "pass":

                log(report, "")
                log(report, "Historical data downloaded.")
                log(report, "STATUS: SUCCESS")
                return

            if status == "api_key":

                log(report, "")
                log(report, "API key problem detected.")
                log(report, "Stopping retries.")
                return

            if status == "rate_limit":

                if attempt < MAX_RETRIES:

                    log(
                        report,
                        f"Waiting {WAIT_SECONDS} seconds before retry..."
                    )

                    time.sleep(WAIT_SECONDS)

                    continue

                log(report, "")
                log(report, "Maximum retries reached.")
                log(report, "STATUS: RATE LIMITED")
                return

            log(report, "")
            log(report, "Unexpected validation failure.")
            return


if __name__ == "__main__":
    main()