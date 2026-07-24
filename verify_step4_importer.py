#!/usr/bin/env python3

import os
import sys
import sqlite3
import tempfile
import subprocess
import csv

BASE = "/storage/emulated/0/QPX_ALPHA"

IMPORTER = os.path.join(
    BASE,
    "quant_platform/mobile/csv_importer.py"
)

RUNNER = os.path.join(
    BASE,
    "mobile_runner.py"
)

BACKUP = IMPORTER + ".backup"


def check_file(path):
    if os.path.exists(path):
        print(f"[OK] Found: {path}")
        return True
    print(f"[FAIL] Missing: {path}")
    return False


def syntax_check():
    print("\n[VERIFY] Validate syntax")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            IMPORTER
        ],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("[OK] Importer syntax passes")
        return True

    print("[FAIL] Syntax error")
    print(result.stderr)
    return False


def sqlite_lifecycle_test():
    print("\n[TEST] SQLite lifecycle verification")

    db = tempfile.NamedTemporaryFile(
        suffix=".db",
        delete=False
    )

    db.close()

    try:
        conn = sqlite3.connect(db.name)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE market_data (
                symbol TEXT,
                timestamp TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL
            )
        """)

        cur.execute("""
            INSERT INTO market_data
            (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "TEST",
            "2026-01-01",
            1,
            2,
            0.5,
            1.5,
            100
        ))

        conn.commit()

        cur.execute(
            "SELECT timestamp FROM market_data WHERE symbol='TEST'"
        )

        value = cur.fetchone()[0]

        if value == "2026-01-01":
            print("[OK] market_data.timestamp accepts imported date values")
            return True

        print("[FAIL] timestamp value mismatch")
        return False

    except sqlite3.OperationalError as e:
        print("[FAIL] sqlite3.OperationalError:", e)
        return False

    finally:
        conn.close()
        os.remove(db.name)


def importer_runtime_check():
    print("\n[TEST] CSV importer runtime validation")

    if not check_file(RUNNER):
        return False

    result = subprocess.run(
        [
            sys.executable,
            RUNNER
        ],
        capture_output=True,
        text=True
    )

    output = result.stdout + result.stderr

    if "sqlite3.OperationalError" in output:
        print("[FAIL] sqlite3.OperationalError detected")
        print(output)
        return False

    print("[OK] Runner completed without sqlite3.OperationalError")

    return True


def main():
    print("QPX Alpha Step 4 Importer Schema Validation")
    print("=" * 45)

    checks = [
        check_file(IMPORTER),
        check_file(BACKUP),
        syntax_check(),
        sqlite_lifecycle_test(),
        importer_runtime_check()
    ]

    print("\nRESULT")
    print("=" * 45)

    if all(checks):
        print("[OK] Step 4 importer validation passed")
    else:
        print("[BLOCKED] Validation requires attention")


if __name__ == "__main__":
    main()
