#!/usr/bin/env python3
"""
QPX Alpha Quant Research Platform
Remaining Verification Pipeline

Purpose:
    Execute validation checks for remaining QPX Alpha development steps.

Rules:
    - Do not delete database
    - Do not modify validated components
    - Capture failures by layer
    - Continue only when prerequisites pass
"""

import os
import sqlite3
import traceback
import importlib.util
from datetime import datetime


BASE = "/storage/emulated/0/QPX_ALPHA"
DB_PATH = os.path.join(BASE, "qpx_alpha.db")


RESULTS = []


def check(label, function):
    try:
        function()
        RESULTS.append((label, "PASS"))
        print(f"[OK] {label}")
        return True
    except Exception as e:
        RESULTS.append((label, f"FAIL: {e}"))
        print(f"[FAIL] {label}")
        print(f"       {e}")
        return False


def file_exists(name):
    path = os.path.join(BASE, name)
    if not os.path.exists(path):
        raise FileNotFoundError(path)


def database_check():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='market_data'"
    )

    if cur.fetchone() is None:
        raise Exception("market_data table missing")

    cur.execute("PRAGMA table_info(market_data)")
    cols = [x[1] for x in cur.fetchall()]

    required = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume"
    ]

    for col in required:
        if col not in cols:
            raise Exception(f"Missing column: {col}")

    conn.close()


def import_check(module_file):
    path = os.path.join(BASE, module_file)

    if not os.path.exists(path):
        raise FileNotFoundError(path)

    module_name = module_file.replace(".py", "")

    spec = importlib.util.spec_from_file_location(
        module_name,
        path
    )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def run_sql_validation():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            symbol,
            COUNT(*),
            AVG(close),
            MAX(high),
            MIN(low)
        FROM market_data
        GROUP BY symbol
        """
    )

    rows = cur.fetchall()

    if not rows:
        raise Exception("No analytics rows returned")

    conn.close()


def main():

    print("=" * 40)
    print("QPX Alpha Remaining Verification")
    print("=" * 40)

    print("\nSTEP 8 — Analytics Feature Engine")
    
    check(
        "Step 8 verification script detected",
        lambda: file_exists(
            "verify_step8_analytics_feature_engine.py"
        )
    )

    check(
        "Database validation",
        database_check
    )

    check(
        "Analytics feature SQL execution",
        run_sql_validation
    )


    print("\nSTEP 9+ — Remaining Layer Discovery")

    candidates = [
        "feature_engine.py",
        "analytics_engine.py",
        "signal_engine.py",
        "backtest_engine.py",
        "risk_engine.py"
    ]

    for item in candidates:
        path = os.path.join(BASE, item)

        if os.path.exists(path):
            print(f"[FOUND] {item}")
        else:
            print(f"[INFO] Missing optional component: {item}")


    print("\n====================================")
    print("VALIDATION SUMMARY")
    print("====================================")

    failed = [
        x for x in RESULTS
        if x[1] != "PASS"
    ]

    if failed:
        print("[FAIL] Validation incomplete")
        for item in failed:
            print(item)
    else:
        print("[PASS] Remaining verification complete")


if __name__ == "__main__":
    main()
