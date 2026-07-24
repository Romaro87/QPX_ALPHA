#!/usr/bin/env python3

import os
import sqlite3
import shutil
import glob
import datetime
import traceback

BASE = "/storage/emulated/0/QPX_ALPHA"
DB = os.path.join(BASE, "qpx_alpha.db")

IMPORTER = os.path.join(
    BASE,
    "quant_platform/mobile/csv_importer.py"
)

BACKUP = DB + ".backup_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def log(msg):
    print(msg)


def backup_database():
    if os.path.exists(DB):
        shutil.copy2(DB, BACKUP)
        log("[OK] Database backup created:")
        log(BACKUP)


def repair_schema():

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
        AND name='market_data'
    """)

    exists = cur.fetchone()

    if not exists:
        log("[WARN] market_data missing - creating")

        cur.execute("""
        CREATE TABLE market_data(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        )
        """)

    else:
        log("[OK] market_data exists")

    cur.execute("PRAGMA table_info(market_data)")
    cols = {row[1] for row in cur.fetchall()}

    required = {
        "timestamp": "TEXT",
        "symbol": "TEXT",
        "open": "REAL",
        "high": "REAL",
        "low": "REAL",
        "close": "REAL",
        "volume": "REAL"
    }

    for name, dtype in required.items():

        if name not in cols:
            log(
                f"[REPAIR] Adding missing column {name}"
            )

            cur.execute(
                f"ALTER TABLE market_data ADD COLUMN {name} {dtype}"
            )

    conn.commit()
    conn.close()

    log("[OK] Schema reconciliation complete")


def locate_csv():

    patterns = [
        "*.csv",
        "**/*.csv"
    ]

    found = []

    for p in patterns:
        found.extend(
            glob.glob(
                os.path.join(BASE, p),
                recursive=True
            )
        )

    found = [
        x for x in found
        if "backup" not in x.lower()
    ]

    if not found:
        raise RuntimeError(
            "No CSV fixture found"
        )

    log("[OK] CSV found:")
    log(found[0])

    return found[0]


def run_import(csv):

    try:

        from quant_platform.mobile import csv_importer

        if hasattr(csv_importer, "import_csv"):

            log("[OK] Calling import_csv")

            result = csv_importer.import_csv(csv)

            log(
                "[OK] Import result:"
            )

            log(str(result))

            return

        elif hasattr(
            csv_importer,
            "import_market_data"
        ):

            log("[OK] Calling import_market_data")

            result = csv_importer.import_market_data(csv)

            log(str(result))

            return

        else:
            raise RuntimeError(
                "No importer entry point found"
            )

    except Exception:
        traceback.print_exc()
        raise


def verify():

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM market_data"
    )

    count = cur.fetchone()[0]

    conn.close()

    log(
        f"[CHECK] market_data rows: {count}"
    )

    if count == 0:
        raise RuntimeError(
            "INSERT path still produced zero rows"
        )

    log(
        "[PASS] market_data contains rows"
    )


def main():

    log("====================================")
    log("QPX Alpha Step 5 Import Repair v3")
    log("====================================")

    backup_database()

    repair_schema()

    csv = locate_csv()

    run_import(csv)

    verify()

    log("------------------------------------")
    log(
        "[PASS] Step 5 Import Pipeline Repair Complete"
    )


if __name__ == "__main__":
    main()
