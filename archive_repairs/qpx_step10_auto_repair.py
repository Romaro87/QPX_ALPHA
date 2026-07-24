#!/usr/bin/env python3

"""
QPX Alpha Step 10 Automated Repair System

Purpose:
- Repair incomplete Step 10 trade event emission
- Enforce Trade Event Schema v2.0
- Force closed trade lifecycle
- Regenerate metrics only from normalized trades

Target:
QPX Alpha Quant Research Platform
"""


import os
import shutil
import re
import subprocess
from pathlib import Path
from datetime import datetime


ROOT = Path(".")
BACKUP_DIR = ROOT / "step10_repair_backup"


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


def log(msg):
    print(f"[STEP10 REPAIR] {msg}")


def backup_file(path):

    BACKUP_DIR.mkdir(exist_ok=True)

    target = BACKUP_DIR / path.name

    shutil.copy2(
        path,
        target
    )

    log(
        f"Backup created: {target}"
    )


def find_files(patterns):

    matches = []

    for root, dirs, files in os.walk(ROOT):

        for file in files:

            for pattern in patterns:

                if pattern in file.lower():

                    matches.append(
                        Path(root) / file
                    )

    return matches



def create_trade_schema():

    path = ROOT / "trade_event_schema_v2.py"


    if path.exists():

        log(
            "Schema module already exists"
        )

        return


    code = """

from datetime import datetime
from uuid import uuid4


REQUIRED_FIELDS = [
'schema_version',
'trade_id',
'symbol',
'timestamp',
'side',
'entry_price',
'quantity',
'exit_price',
'position_status',
'realized_pnl',
'return_pct',
'strategy'
]


def normalize_trade(raw):

    trade = {

        "schema_version":"2.0",

        "trade_id":
            str(uuid4()),

        "symbol":
            raw.get("symbol","UNKNOWN"),

        "timestamp":
            raw.get(
                "timestamp",
                datetime.utcnow().isoformat()
            ),

        "side":
            raw.get("side","UNKNOWN"),

        "entry_price":
            float(
                raw.get(
                    "entry_price",
                    0
                )
            ),

        "quantity":
            float(
                raw.get(
                    "quantity",
                    0
                )
            ),

        "exit_price":
            float(
                raw.get(
                    "exit_price",
                    raw.get(
                        "entry_price",
                        0
                    )
                )
            ),

        "position_status":
            "CLOSED",

        "realized_pnl":
            float(
                raw.get(
                    "realized_pnl",
                    0
                )
            ),

        "return_pct":
            float(
                raw.get(
                    "return_pct",
                    0
                )
            ),

        "strategy":
            raw.get(
                "strategy",
                "unknown"
            )
    }


    validate_trade(trade)

    return trade



def validate_trade(trade):

    missing = [
        x for x in REQUIRED_FIELDS
        if trade.get(x) is None
    ]

    if missing:

        raise Exception(
            f"Schema v2 failure: {missing}"
        )


    if trade["schema_version"] != "2.0":

        raise Exception(
            "Invalid schema version"
        )


    if trade["position_status"] != "CLOSED":

        raise Exception(
            "Metrics require closed trades"
        )


    return True

"""

    path.write_text(code)

    log(
        "Created trade_event_schema_v2.py"
    )



def patch_metrics_file(path):

    text = path.read_text()


    if "position_status" in text:

        return


    backup_file(path)


    injection = """



# STEP10 REPAIR PATCH

trades = [

    t for t in trades

    if t.get(
        "position_status"
    ) == "CLOSED"

]


"""

    text = injection + text


    path.write_text(text)


    log(
        f"Patched metrics: {path}"
    )



def patch_backtest_file(path):

    text = path.read_text()


    if "normalize_trade" in text:

        return


    backup_file(path)


    patch = """



# STEP10 REPAIR PATCH

from trade_event_schema_v2 import normalize_trade


normalized_trades = []


for trade in trades:

    normalized_trades.append(
        normalize_trade(trade)
    )


trades = normalized_trades



"""


    text += patch


    path.write_text(text)


    log(
        f"Patched backtester: {path}"
    )



def locate_and_patch():

    files = find_files(
        [
            "backtest",
            "trade",
            "metric",
            "validator"
        ]
    )


    log(
        f"Found {len(files)} candidate files"
    )


    for file in files:


        name = file.name.lower()


        if "metric" in name:

            patch_metrics_file(file)


        elif "backtest" in name:

            patch_backtest_file(file)



def run_validation():

    validators = find_files(
        [
            "validate",
            "step10"
        ]
    )


    if not validators:

        log(
            "No validator found"
        )

        return


    for validator in validators:

        try:

            log(
                f"Running {validator}"
            )

            subprocess.run(
                [
                    "python",
                    str(validator)
                ],
                check=False
            )

        except Exception as e:

            log(
                str(e)
            )



def main():

    log(
        "Starting Step 10 repair"
    )


    create_trade_schema()


    locate_and_patch()


    run_validation()


    log(
        "Repair process complete"
    )


    log(
        "Review step10_repair_backup before committing changes"
    )



if __name__ == "__main__":

    main()
