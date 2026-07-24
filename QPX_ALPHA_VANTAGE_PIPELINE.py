#!/usr/bin/env python3

import os
import json
import subprocess
import sqlite3
import datetime
import urllib.request
import urllib.parse
import csv

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONFIG = os.path.join(ROOT, "qpx_provider.json")
CSV_FILE = os.path.join(ROOT, "historical_data.csv")
REPORT = os.path.join(ROOT, "QPX_ALPHA_VANTAGE_PIPELINE_REPORT.txt")


def log(report, text):
    print(text)
    report.write(text + "\n")


def load_config():
    if not os.path.exists(CONFIG):
        raise FileNotFoundError(
            "Missing qpx_provider.json"
        )

    with open(CONFIG, "r") as f:
        return json.load(f)


def download_history(cfg):

    symbol = cfg.get("symbol", "SPY")
    api_key = cfg.get("api_key", "")

    if not api_key:
        raise ValueError("API key missing")

    params = urllib.parse.urlencode({
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": symbol,
        "outputsize": "full",
        "datatype": "csv",
        "apikey": api_key
    })

    url = (
        "https://www.alphavantage.co/query?"
        + params
    )

    urllib.request.urlretrieve(
        url,
        CSV_FILE
    )


def validate_csv():

    if not os.path.exists(CSV_FILE):
        return False

    with open(
        CSV_FILE,
        newline="",
        encoding="utf-8"
    ) as f:

        reader = csv.reader(f)

        headers = next(reader)

    required = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    return all(
        h in headers
        for h in required
    )


def run(script):

    full = os.path.join(
        ROOT,
        script
    )

    if os.path.exists(full):

        subprocess.run(
            ["python", full]
        )


def main():

    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:

        log(report, "==============================")
        log(report, "QPX ALPHA VANTAGE PIPELINE")
        log(report, datetime.datetime.now().isoformat())
        log(report, "==============================")

        try:

            cfg = load_config()

            log(
                report,
                "Provider: Alpha Vantage"
            )

            download_history(cfg)

            if validate_csv():

                log(
                    report,
                    "Historical download successful"
                )

            else:

                raise Exception(
                    "Downloaded CSV failed validation"
                )

            run(
                "QPX_HISTORICAL_IMPORTER.py"
            )

            run(
                "QPX_DATA_READINESS_CHECKER.py"
            )

            run(
                "QPX_ADAPTIVE_SWING_V2_RUNNER.py"
            )

            log(
                report,
                "PIPELINE COMPLETE"
            )

        except Exception as e:

            log(
                report,
                "ERROR"
            )

            log(
                report,
                str(e)
            )


if __name__ == "__main__":
    main()