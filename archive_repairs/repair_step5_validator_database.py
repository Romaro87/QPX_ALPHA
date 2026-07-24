#!/usr/bin/env python3

import os
import shutil
import sqlite3

VALIDATOR = "/storage/emulated/0/QPX_ALPHA/verify_step5_import_pipeline.py"
BACKUP = VALIDATOR + ".step5_db_backup"

EXPECTED_DB = "/storage/emulated/0/QPX_ALPHA/qpx_alpha.db"


def backup_validator():
    if os.path.exists(VALIDATOR):
        shutil.copy2(VALIDATOR, BACKUP)
        print("[OK] Validator backup created:")
        print(BACKUP)
    else:
        print("[FAIL] Validator not found")
        raise SystemExit(1)


def validate_database():
    if not os.path.exists(EXPECTED_DB):
        print("[FAIL] Expected database missing:")
        print(EXPECTED_DB)
        raise SystemExit(1)

    conn = sqlite3.connect(EXPECTED_DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )

    tables = [row[0] for row in cur.fetchall()]

    conn.close()

    required = [
        "market_data",
        "trades",
        "portfolio_snapshots"
    ]

    for table in required:
        if table not in tables:
            print("[FAIL] Missing table:", table)
            raise SystemExit(1)

    print("[OK] QPX Alpha database confirmed")
    print("[OK] Tables detected:")
    for table in tables:
        print(" -", table)


def repair_validator_path():
    with open(VALIDATOR, "r", encoding="utf-8") as f:
        code = f.read()

    original = code

    replacements = [
        (
            'sqlite3.connect("qpx_alpha.db")',
            f'sqlite3.connect("{EXPECTED_DB}")'
        ),
        (
            "sqlite3.connect('qpx_alpha.db')",
            f'sqlite3.connect("{EXPECTED_DB}")'
        )
    ]

    for old, new in replacements:
        code = code.replace(old, new)

    if code == original:
        print("[OK] No direct database path replacement required")
    else:
        with open(VALIDATOR, "w", encoding="utf-8") as f:
            f.write(code)

        print("[OK] Validator database path repaired")


def main():
    print("====================================")
    print("QPX Alpha Step 5 Validator Repair")
    print("====================================")

    backup_validator()

    validate_database()

    repair_validator_path()

    print("------------------------------------")
    print("[OK] Step 5 validator repair complete")
    print("------------------------------------")
    print("Run:")
    print(
        "python3 /storage/emulated/0/QPX_ALPHA/verify_step5_import_pipeline.py"
    )


if __name__ == "__main__":
    main()
