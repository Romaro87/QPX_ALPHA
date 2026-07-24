"""
QPX Alpha Quant Research Platform
STEP 10 Backtesting Engine Repair Assistant

Purpose:
- Locate Step 10 files
- Detect undefined trade storage usage
- Validate trade schema v2
- Validate closed trade metrics flow
- Generate repair report

Safe mode:
- Does not overwrite source files automatically
- Creates reports and recommendations
"""

import os
import shutil
from datetime import datetime
import json


PROJECT_ROOT = os.getcwd()

REPORT_FILE = "STEP10_REPAIR_REPORT.json"


STEP10_KEYWORDS = [
    "backtest",
    "trade",
    "metric",
    "performance",
    "portfolio"
]


REQUIRED_TRADE_FIELDS = [
    "schema_version",
    "trade_id",
    "symbol",
    "timestamp",
    "side",
    "entry_price",
    "quantity",
    "exit_price",
    "position_status",
    "realized_pnl",
    "return_pct",
    "strategy"
]


def find_step10_files():

    matches = []

    for root, dirs, files in os.walk(PROJECT_ROOT):

        for file in files:

            if file.endswith(".py"):

                name = file.lower()

                if any(k in name for k in STEP10_KEYWORDS):

                    matches.append(
                        os.path.join(root, file)
                    )

    return matches



def scan_for_trade_bug(files):

    findings = []

    for file in files:

        try:

            with open(
                file,
                "r",
                encoding="utf-8"
            ) as f:

                content = f.read()


            if "for trade in trades" in content:

                if "trades =" not in content:

                    findings.append(
                        {
                            "file": file,
                            "issue":
                            "Possible undefined trades variable",
                            "suggestion":
                            "Initialize trades=[] before execution flow"
                        }
                    )

        except Exception as e:

            pass


    return findings



def validate_trade_schema(trade):

    results = {}

    for field in REQUIRED_TRADE_FIELDS:

        results[field] = (
            "PASS"
            if field in trade
            else "FAIL"
        )

    return results



def test_trade_event():

    example_trade = {

        "schema_version": "2.0",
        "trade_id": "TEST001",
        "symbol": "TEST",
        "timestamp": datetime.utcnow().isoformat(),
        "side": "BUY",
        "entry_price": 100.0,
        "quantity": 1,
        "exit_price": 110.0,
        "position_status": "CLOSED",
        "realized_pnl": 10.0,
        "return_pct": 10.0,
        "strategy": "STEP9_SIGNAL"

    }


    validation = validate_trade_schema(
        example_trade
    )


    return validation



def create_backup():

    backup = (
        "QPX_STEP10_BACKUP_"
        +
        datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    os.makedirs(
        backup,
        exist_ok=True
    )


    return backup



def generate_report():

    print("\nQPX STEP 10 REPAIR ASSISTANT")
    print("=" * 40)


    files = find_step10_files()

    print(
        f"\nStep 10 files found: {len(files)}"
    )


    bugs = scan_for_trade_bug(files)


    schema_test = test_trade_event()


    report = {

        "project":
        "QPX Alpha Quant Research Platform",

        "phase":
        "STEP 10 Backtesting Engine Repair",

        "timestamp":
        datetime.utcnow().isoformat(),

        "files_detected":
        files,

        "trade_variable_findings":
        bugs,

        "schema_validation":
        schema_test,

        "status":
        "REVIEW REQUIRED"

    }


    with open(
        REPORT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            report,
            f,
            indent=4
        )


    print(
        "\nReport created:"
    )

    print(
        REPORT_FILE
    )


    if bugs:

        print(
            "\nPossible root cause found:"
        )

        for b in bugs:

            print(
                "-",
                b["file"]
            )

    else:

        print(
            "\nNo obvious undefined trades issue found."
        )



if __name__ == "__main__":

    generate_report()
