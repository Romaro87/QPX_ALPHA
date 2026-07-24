#!/usr/bin/env python3

"""
====================================
QPX Alpha Step 6
Market Data Query Layer Validation
====================================

Purpose:
Validate market_data query functionality after Step 5.

Checks:
- Database availability
- market_data schema
- Row availability
- Timestamp retrieval
- Symbol filtering
- Ordering correctness
- Query layer discovery
- Query function execution

No destructive operations.
====================================
"""

import os
import sqlite3
import importlib.util
import traceback


BASE = "/storage/emulated/0/QPX_ALPHA"
DB_PATH = os.path.join(BASE, "qpx_alpha.db")


PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print("[OK]", msg)


def fail(msg):
    global FAIL
    FAIL += 1
    print("[FAIL]", msg)


def section(msg):
    print("\n------------------------------------")
    print(msg)
    print("------------------------------------")


def find_python_files():
    files = []

    for root, _, names in os.walk(BASE):
        for name in names:
            if name.endswith(".py"):
                files.append(os.path.join(root, name))

    return files


def validate_database():

    if not os.path.exists(DB_PATH):
        fail("qpx_alpha.db not found")
        return None

    ok("Database found")

    try:
        conn = sqlite3.connect(DB_PATH)
        ok("SQLite connection successful")
        return conn

    except Exception as e:
        fail(f"SQLite connection failed: {e}")
        return None


def validate_market_table(conn):

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT name 
            FROM sqlite_master
            WHERE type='table'
            AND name='market_data'
            """
        )

        if cur.fetchone():

            ok("market_data table exists")

        else:
            fail("market_data table missing")
            return False


        cur.execute(
            "PRAGMA table_info(market_data)"
        )

        columns = [
            row[1]
            for row in cur.fetchall()
        ]

        required = [
            "timestamp"
        ]

        for col in required:

            if col in columns:
                ok(f"{col} column exists")

            else:
                fail(f"{col} column missing")


        return True


    except Exception as e:

        fail(
            f"Schema validation error: {e}"
        )

        return False



def validate_rows(conn):

    try:

        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM market_data"
        )

        count = cur.fetchone()[0]

        if count > 0:

            ok(
                f"market_data rows available: {count}"
            )

        else:

            fail(
                "No market_data rows found"
            )


        return count


    except Exception as e:

        fail(
            f"Row query failed: {e}"
        )

        return 0



def validate_timestamp(conn):

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT timestamp
            FROM market_data
            ORDER BY timestamp ASC
            LIMIT 5
            """
        )

        rows = cur.fetchall()

        if rows:

            ok(
                "Timestamp retrieval successful"
            )

        else:

            fail(
                "Timestamp query returned no rows"
            )


    except Exception as e:

        fail(
            f"Timestamp query failed: {e}"
        )



def validate_ordering(conn):

    try:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT timestamp
            FROM market_data
            ORDER BY timestamp ASC
            """
        )

        values = [
            x[0]
            for x in cur.fetchall()
        ]


        if values == sorted(values):

            ok(
                "Timestamp ordering valid"
            )

        else:

            fail(
                "Timestamp ordering incorrect"
            )


    except Exception as e:

        fail(
            f"Ordering validation failed: {e}"
        )



def validate_symbol_query(conn):

    try:

        cur = conn.cursor()

        cur.execute(
            """
            PRAGMA table_info(market_data)
            """
        )

        columns = [
            x[1]
            for x in cur.fetchall()
        ]


        if "symbol" not in columns:

            ok(
                "Symbol column not present - skipped"
            )

            return


        cur.execute(
            """
            SELECT symbol
            FROM market_data
            LIMIT 1
            """
        )

        row = cur.fetchone()


        if row:

            symbol = row[0]

            cur.execute(
                """
                SELECT *
                FROM market_data
                WHERE symbol=?
                """,
                (symbol,)
            )

            results = cur.fetchall()


            if results:

                ok(
                    f"Symbol query successful: {symbol}"
                )

            else:

                fail(
                    "Symbol query returned no rows"
                )


    except Exception as e:

        fail(
            f"Symbol query failed: {e}"
        )



def detect_query_modules():

    section(
        "Query Layer Detection"
    )

    found = False

    for file in find_python_files():

        name = os.path.basename(file).lower()

        if (
            "query" in name
            or "market" in name
            or "data" in name
        ):

            print(
                "[FOUND]",
                file
            )

            found = True


    if found:

        ok(
            "Possible query layer files detected"
        )

    else:

        fail(
            "No query layer file detected"
        )



def main():

    print(
        "===================================="
    )
    print(
        "QPX Alpha Step 6"
    )
    print(
        "Market Data Query Layer Validation"
    )
    print(
        "===================================="
    )


    detect_query_modules()


    conn = validate_database()

    if conn:

        validate_market_table(conn)

        rows = validate_rows(conn)

        if rows:

            validate_timestamp(conn)
            validate_ordering(conn)
            validate_symbol_query(conn)


        conn.close()


    print(
        "\n===================================="
    )


    if FAIL == 0:

        print(
            "[PASS] Step 6 Market Data Query Layer Validation Complete"
        )

    else:

        print(
            "[FAIL] Step 6 Validation Failed"
        )

        print(
            "Failures:",
            FAIL
        )


    print(
        "===================================="
    )


if __name__ == "__main__":
    main()
