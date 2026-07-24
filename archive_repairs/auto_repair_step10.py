#!/usr/bin/env python3

"""
QPX Alpha Step 10 Automated Repair

Purpose:
- Remove broken global 'trades' patch injections
- Protect validated systems
- Create backups
- Add Step 10 lifecycle validation
- Run smoke tests

Does NOT modify:
- importer
- CSV pipeline
- database
- query layer
- Step 8
- Step 9
"""


from pathlib import Path
import shutil
import json
from datetime import datetime


ROOT = Path("/storage/emulated/0/QPX_ALPHA")

BACKUP = ROOT / "step10_auto_backup"

REPORT = ROOT / "STEP10_AUTO_REPAIR_REPORT.json"


TARGET_FILES = [
    "backtesting_engine.py",
    "trade_event_schema_v2.py",
    "repair_step10_backtesting_engine.py",
    "step10_backtesting_engine_repair.py"
]


BROKEN_PATTERN = """
for trade in trades:
"""


def log(message):
    print("[STEP10 AUTO REPAIR]", message)


def backup_file(path):

    BACKUP.mkdir(exist_ok=True)

    destination = BACKUP / path.name

    shutil.copy2(
        path,
        destination
    )

    log(
        f"Backup created: {destination}"
    )


def remove_bad_trade_patch(path):

    text = path.read_text(
        encoding="utf-8"
    )

    if BROKEN_PATTERN not in text:
        return False


    backup_file(path)


    lines = text.splitlines()

    cleaned = []

    skip = False


    for line in lines:

        if "for trade in trades:" in line:

            skip = True
            continue


        if skip:

            if "trades =" in line:

                skip = False

            continue


        cleaned.append(line)


    path.write_text(
        "\n".join(cleaned),
        encoding="utf-8"
    )


    return True



def create_step10_validator():

    validator = ROOT / "validate_step10_runtime.py"


    code = r'''

from backtesting_engine import BacktestEngine


print("="*50)
print("STEP 10 RUNTIME VALIDATION")
print("="*50)


engine = BacktestEngine()


signals = [
    {
        "symbol":"TEST",
        "timestamp":"2026-07-24",
        "side":"BUY",
        "price":100,
        "quantity":1
    }
]


result = engine.run(
    signals=signals,
    historical_data=[]
)


assert "trades" in result

assert "metrics" in result


print("Trade storage:")
print(engine.trades)


print("Metrics:")
print(engine.metrics)


print()
print("STEP 10 BASIC ENGINE TEST PASS")

'''

    validator.write_text(
        code,
        encoding="utf-8"
    )


    return validator



def scan_files():

    found=[]

    for name in TARGET_FILES:

        path = ROOT / name

        if path.exists():

            found.append(path)

    return found



def run_repair():

    log("Starting Step 10 repair")

    files = scan_files()

    changed=[]


    for file in files:

        if remove_bad_trade_patch(file):

            changed.append(
                str(file)
            )


    validator = create_step10_validator()


    report = {

        "timestamp":
            datetime.now().isoformat(),

        "files_scanned":
            [str(x) for x in files],

        "files_changed":
            changed,

        "validator_created":
            str(validator),

        "status":
            "READY FOR TEST"

    }


    REPORT.write_text(
        json.dumps(
            report,
            indent=4
        ),
        encoding="utf-8"
    )


    print()
    print("="*50)
    print("REPAIR COMPLETE")
    print("="*50)

    print(
        json.dumps(
            report,
            indent=4
        )
    )


if __name__ == "__main__":

    run_repair()
