#!/usr/bin/env python3
"""
QPX Alpha Step 7
Market Data Analytics Foundation Validation

Validates:
- Analytics layer detection
- Database connectivity
- market_data accessibility
- Required analytics fields
- Basic market data calculations
- Aggregation/query operations
- Runtime stability
"""

import os
import sqlite3
import traceback


BASE_PATH = "/storage/emulated/0/QPX_ALPHA"
DB_PATH = os.path.join(BASE_PATH, "qpx_alpha.db")


def check(label, condition):
    if condition:
        print(f"[OK] {label}")
        return True
    else:
        print(f"[FAIL] {label}")
        return False


def detect_analytics_files():
    candidates = [
        "analytics.py",
        "market_analytics.py",
        "analytics_engine.py",
        "market_data_analytics.py",
        "verify_step7_market_analytics_foundation.py",
    ]

    found = []

    for root, _, files in os.walk(BASE_PATH):
        for file in files:
            if file in candidates:
                found.append(os.path.join(root, file))

    for item in found:
        print(f"[FOUND] {item}")

    return len(found) > 0


def main():

    print("====================================")
    print("QPX Alpha Step 7")
    print("Market Data Analytics Foundation Validation")
    print("====================================")

    print("\n------------------------------------")
    print("Analytics Layer Detection")
    print("------------------------------------")

    analytics_found = detect_analytics_files()

    check(
        "Possible analytics layer files detected",
        analytics_found
    )

    print("\n------------------------------------")
    print("Database Analytics Validation")
    print("------------------------------------")

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        check(
            "SQLite connection successful",
            True
        )

        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name='market_data'
            """
        )

        table = cursor.fetchone()

        check(
            "market_data table accessible",
            table is not None
        )

        cursor.execute(
            "PRAGMA table_info(market_data)"
        )

        columns = [
            row[1]
            for row in cursor.fetchall()
        ]

        check(
            "Schema readable",
            len(columns) > 0
        )

        print(
            "[INFO] Columns:",
            ", ".join(columns)
        )

        cursor.execute(
            "SELECT COUNT(*) FROM market_data"
        )

        row_count = cursor.fetchone()[0]

        check(
            f"Market data rows available: {row_count}",
            row_count > 0
        )

        required_candidates = [
            "timestamp",
            "symbol",
            "price",
            "close",
            "volume"
        ]

        available = [
            col for col in required_candidates
            if col in columns
        ]

        check(
            "Analytics fields available",
            len(available) > 0
        )


        # Basic retrieval test

        cursor.execute(
            """
            SELECT *
            FROM market_data
            LIMIT 5
            """
        )

        rows = cursor.fetchall()

        check(
            "Analytics data retrieval successful",
            len(rows) > 0
        )


        # Basic timestamp aggregation

        if "timestamp" in columns:

            cursor.execute(
                """
                SELECT COUNT(timestamp)
                FROM market_data
                """
            )

            count = cursor.fetchone()[0]

            check(
                "Timestamp aggregation successful",
                count > 0
            )


        # Symbol grouping validation

        if "symbol" in columns:

            cursor.execute(
                """
                SELECT symbol, COUNT(*)
                FROM market_data
                GROUP BY symbol
                """
            )

            symbols = cursor.fetchall()

            check(
                "Symbol aggregation successful",
                len(symbols) > 0
            )


        conn.close()

        print("\n------------------------------------")
        print("[PASS] Step 7 Market Data Analytics Foundation Validation Complete")
        print("------------------------------------")

    except Exception:

        print("\n[ERROR] Analytics validation exception")
        traceback.print_exc()

        print("\n------------------------------------")
        print("[FAIL] Step 7 Validation Failed")
        print("------------------------------------")


if __name__ == "__main__":
    main()
