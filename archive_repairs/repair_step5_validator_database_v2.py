#!/usr/bin/env python3
"""
QPX Alpha Step 5 Validator Database Repair v2

Purpose:
- Locate the actual validator database target
- Confirm qpx_alpha.db schema
- Repair validator DB path
- Preserve schema
- Create backup before modification
"""

import os
import shutil
import sqlite3


BASE_DIR = "/storage/emulated/0/QPX_ALPHA"

DATABASE = os.path.join(
    BASE_DIR,
    "qpx_alpha.db"
)

VALIDATOR = os.path.join(
    BASE_DIR,
    "verify_step5_import_pipeline.py"
)

BACKUP = VALIDATOR + ".step5_db_backup_v2"


REQUIRED_TABLES = [
    "market_data",
    "trades",
    "portfolio_snapshots"
]


def check_database(db_path):
    print("\nChecking database:")
    print(db_path)

    if not os.path.exists(db_path):
        print("[FAIL] Database missing")
        return False

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )

    tables = {
        row[0]
        for row in cur.fetchall()
    }

    conn.close()

    print("\nTables found:")
    for table in tables:
        print(" -", table)

    missing = [
        t for t in REQUIRED_TABLES
        if t not in tables
    ]

    if missing:
        print("\n[FAIL] Missing tables:")
        for m in missing:
            print(" -", m)
        return False

    print("\n[OK] Required schema confirmed")
    return True


def backup_validator():
    if not os.path.exists(VALIDATOR):
        print("[FAIL] Validator missing")
        return False

    shutil.copy2(
        VALIDATOR,
        BACKUP
    )

    print("[OK] Validator backup created:")
    print(BACKUP)

    return True


def repair_validator_path():

    with open(
        VALIDATOR,
        "r",
        encoding="utf-8"
    ) as f:
        code = f.read()


    old_patterns = [
        'sqlite3.connect("qpx_alpha.db")',
        "sqlite3.connect('qpx_alpha.db')",
        'DB_PATH = "qpx_alpha.db"',
        "DB_PATH = 'qpx_alpha.db'"
    ]


    changed = False


    for old in old_patterns:
        if old in code:

            if "DB_PATH" in old:

                code = code.replace(
                    old,
                    f'DB_PATH = "{DATABASE}"'
                )

            else:

                code = code.replace(
                    old,
                    f'sqlite3.connect("{DATABASE}")'
                )

            changed = True


    if changed:

        with open(
            VALIDATOR,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(code)

        print("[OK] Validator database path repaired")

    else:
        print("[INFO] No direct path replacement required")


def main():

    print("====================================")
    print("QPX Alpha Step 5 Validator Repair v2")
    print("====================================")


    if not backup_validator():
        return


    if not check_database(DATABASE):
        print(
            "\n[STOP] Database schema incomplete"
        )
        return


    repair_validator_path()


    print("\n====================================")
    print("[PASS] Validator database repair complete")
    print("====================================")


if __name__ == "__main__":
    main()
