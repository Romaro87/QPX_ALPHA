#!/usr/bin/env python3

"""
QPX Provider Failover Manager

Attempts providers in order until one succeeds.
"""

import json
import os
import subprocess
import datetime

ROOT = "/storage/emulated/0/QPX_ALPHA"

CONFIG = os.path.join(ROOT, "qpx_provider.json")

REPORT = os.path.join(
    ROOT,
    "QPX_PROVIDER_FAILOVER_REPORT.txt"
)


def log(report, text):

    print(text)
    report.write(text + "\n")


def load():

    with open(CONFIG, "r") as f:
        return json.load(f)


def run(script):

    path = os.path.join(ROOT, script)

    if not os.path.exists(path):
        return False

    result = subprocess.run(
        ["python", path]
    )

    return result.returncode == 0


def main():

    cfg = load()

    providers = cfg.get(
        "providers",
        []
    )

    with open(REPORT, "w") as report:

        log(report, "=" * 30)
        log(report, "QPX PROVIDER FAILOVER")
        log(report, datetime.datetime.now().isoformat())
        log(report, "=" * 30)

        for provider in providers:

            name = provider["name"]

            log(report, "")
            log(report, "Trying " + name)

            if name == "alpha_vantage":

                if run(
                    "QPX_ALPHA_VANTAGE_PIPELINE.py"
                ):

                    log(report, "SUCCESS")
                    return

            elif name == "csv":

                if os.path.exists(
                    os.path.join(
                        ROOT,
                        "historical_data.csv"
                    )
                ):

                    run(
                        "QPX_HISTORICAL_IMPORTER.py"
                    )

                    log(report, "CSV IMPORT SUCCESS")
                    return

        log(report, "")
        log(report, "No provider succeeded.")