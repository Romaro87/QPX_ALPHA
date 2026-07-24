#!/usr/bin/env python3

import sqlite3
import shutil
import os
from datetime import datetime

DB_PATH = "/storage/emulated/0/QPX_ALPHA/qpx_alpha.db"

BACKUP_PATH = (
    "/storage/emulated/0/QPX_ALPHA/"
    f"qpx_alpha.db.step5_schema_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
)


def backup_database():
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, BACKUP_PATH)
        print("[OK] Database backup created:")
        print(BACKUP_PATH)
    else:
        print("[FAIL] Database file not found:")
        print(DB_PATH)
        raise SystemExit(1)


def get_tables(conn):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    return {row[0] for row in cursor.fetchall()}


def restore_schema():

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    existing = get_tables(conn)

    print("\nExisting tables:")
    for table in sorted(existing):
        print(" -", table)

    required_schema = {

        "market_data": """
        CREATE TABLE IF NOT EXISTS market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        )
        """,

        "trades": """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            side TEXT,
            quantity REAL,
            price REAL
        )
        """,

        "portfolio_snapshots": """
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            total_value REAL,
            cash REAL
        )
        """
    }

    print("\nChecking required schema:")

    for table, sql in required_schema.items():

        if table in existing:
            print("[OK] Exists:", table)

        else:
            cursor.execute(sql)
            print("[CREATED]", table)

    conn.commit()

    final_tables = get_tables(conn)

    print("\nFinal schema check:")

    failed = False

    for table in required_schema:

        if table in final_tables:
            print("[OK]", table)

        else:
            print("[FAIL]", table)
            failed = True

    conn.close()

    if failed:
        print("\n[STOP] Schema restoration failed")
        raise SystemExit(1)

    print("\n[PASS] Step 5 database schema repair complete")
    print("[OK] Required tables available")
    print("[OK] Existing architecture preserved")
    print("[OK] Database schema additions only")


if __name__ == "__main__":

    print("====================================")
    print("QPX Alpha Step 5 Schema Restore v1")
    print("====================================")

    backup_database()
    restore_schema()
