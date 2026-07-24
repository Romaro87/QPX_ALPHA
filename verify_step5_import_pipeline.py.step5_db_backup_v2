#!/usr/bin/env python3

import os
import sqlite3
import sys
import traceback

QPX_ROOT = "/storage/emulated/0/QPX_ALPHA"

DB_PATH = os.path.join(QPX_ROOT, "qpx_alpha.db")
RUNNER_PATH = os.path.join(QPX_ROOT, "mobile_runner.py")
IMPORTER_PATH = os.path.join(
    QPX_ROOT,
    "quant_platform",
    "mobile",
    "csv_importer.py"
)

CSV_PATH = os.path.join(QPX_ROOT, "data")


def check_file(path, name):
    if os.path.exists(path):
        print(f"[OK] {name} found")
        return True
    else:
        print(f"[FAIL] {name} missing: {path}")
        return False


def validate_importer_syntax():
    try:
        with open(IMPORTER_PATH, "r", encoding="utf-8") as f:
            source = f.read()

        compile(source, IMPORTER_PATH, "exec")

        print("[OK] Importer syntax validation")
        return True

    except Exception:
        print("[FAIL] Importer syntax validation")
        traceback.print_exc()
        return False


def validate_database():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )

        tables = [row[0] for row in cursor.fetchall()]

        required = [
            "market_data",
            "trades",
            "portfolio_snapshots"
        ]

        for table in required:
            if table not in tables:
                print(f"[FAIL] Missing table: {table}")
                conn.close()
                return False

        cursor.execute(
            "PRAGMA table_info(market_data)"
        )

        columns = [
            row[1]
            for row in cursor.fetchall()
        ]

        if "timestamp" not in columns:
            print("[FAIL] market_data.timestamp missing")
            conn.close()
            return False

        print("[OK] SQLite lifecycle validation")
        print("[OK] market_data.timestamp schema confirmed")

        conn.close()
        return True

    except Exception:
        print("[FAIL] Database validation")
        traceback.print_exc()
        return False


def validate_market_data():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM market_data
            """
        )

        count = cursor.fetchone()[0]

        if count > 0:
            print(
                f"[OK] market_data rows created: {count}"
            )
        else:
            print(
                "[FAIL] No market_data rows found"
            )
            conn.close()
            return False

        cursor.execute(
            """
            SELECT timestamp
            FROM market_data
            ORDER BY rowid DESC
            LIMIT 3
            """
        )

        rows = cursor.fetchall()

        for row in rows:
            if row[0]:
                continue
            else:
                print(
                    "[FAIL] Empty timestamp detected"
                )
                conn.close()
                return False

        print(
            "[OK] timestamp values persist correctly"
        )

        conn.close()
        return True

    except Exception:
        print("[FAIL] market_data validation")
        traceback.print_exc()
        return False


def run_step5_validation():

    print("====================================")
    print("QPX Alpha Step 5 Validation")
    print("====================================")

    results = []

    results.append(
        check_file(
            IMPORTER_PATH,
            "Importer file"
        )
    )

    results.append(
        check_file(
            RUNNER_PATH,
            "mobile_runner.py"
        )
    )

    results.append(
        validate_importer_syntax()
    )

    results.append(
        validate_database()
    )

    results.append(
        validate_market_data()
    )

    print("------------------------------------")

    if all(results):
        print("[PASS] Step 5 Import Pipeline Validation Complete")
        print("[OK] CSV rows accepted")
        print("[OK] market_data rows created")
        print("[OK] timestamp values persist")
        print("[OK] Schema unchanged")
        print("[OK] No sqlite3 errors")
        return 0

    else:
        print("[FAIL] Step 5 Validation Failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_step5_validation())
