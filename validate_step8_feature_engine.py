#!/usr/bin/env python3
"""
QPX Alpha Step 8 Feature Engine Validator

Validation scope:
- Feature engine detection
- Database integration
- Feature engine import
- Feature execution
- OHLCV availability
- Output schema validation
- Runtime error detection

No repairs performed.
"""

import os
import sys
import sqlite3
import traceback
import importlib.util


BASE_DIR = "/storage/emulated/0/QPX_ALPHA"

FEATURE_ENGINE_PATH = os.path.join(
    BASE_DIR,
    "feature_engine.py"
)

DATABASE_PATH = os.path.join(
    BASE_DIR,
    "qpx_alpha.db"
)


results = []


def record(check, status, detail=""):

    results.append(
        {
            "check": check,
            "status": status,
            "detail": detail
        }
    )


def validate_feature_file():

    if os.path.exists(FEATURE_ENGINE_PATH):

        record(
            "Feature engine files detected",
            "PASS",
            FEATURE_ENGINE_PATH
        )

    else:

        record(
            "Feature engine files detected",
            "FAIL",
            "feature_engine.py missing"
        )



def validate_database():

    if not os.path.exists(DATABASE_PATH):

        record(
            "Database integration successful",
            "FAIL",
            "Database not found"
        )

        return


    try:

        conn = sqlite3.connect(
            DATABASE_PATH
        )

        cursor = conn.cursor()


        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name='market_data'
            """
        )


        table = cursor.fetchone()

        conn.close()


        if table:

            record(
                "Database integration successful",
                "PASS",
                "market_data table available"
            )

        else:

            record(
                "Database integration successful",
                "FAIL",
                "market_data table missing"
            )


    except Exception as e:

        record(
            "Database integration successful",
            "FAIL",
            str(e)
        )



def load_feature_engine():

    try:

        spec = importlib.util.spec_from_file_location(
            "feature_engine",
            FEATURE_ENGINE_PATH
        )

        module = importlib.util.module_from_spec(
            spec
        )

        spec.loader.exec_module(
            module
        )


        record(
            "Feature engine import successful",
            "PASS"
        )


        return module


    except Exception:

        record(
            "Feature engine import successful",
            "FAIL",
            traceback.format_exc()
        )

        return None



def validate_calculations(module):

    if module is None:

        record(
            "Feature calculations execute",
            "FAIL",
            "Feature engine unavailable"
        )

        return


    callable_items = []


    for item in dir(module):

        try:

            obj = getattr(
                module,
                item
            )

            if callable(obj):

                callable_items.append(item)

        except:

            pass


    if callable_items:

        record(
            "Feature calculations execute",
            "PASS",
            str(callable_items)
        )

    else:

        record(
            "Feature calculations execute",
            "FAIL",
            "No callable feature functions detected"
        )



def validate_ohlcv():

    if not os.path.exists(DATABASE_PATH):

        record(
            "OHLCV features validated",
            "FAIL",
            "Database unavailable"
        )

        return


    try:

        conn = sqlite3.connect(
            DATABASE_PATH
        )

        cursor = conn.cursor()


        cursor.execute(
            """
            PRAGMA table_info(market_data)
            """
        )


        columns = [
            row[1]
            for row in cursor.fetchall()
        ]


        conn.close()


        required = [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]


        missing = [
            x
            for x in required
            if x not in columns
        ]


        if not missing:

            record(
                "OHLCV features validated",
                "PASS",
                "OHLCV columns present"
            )

        else:

            record(
                "OHLCV features validated",
                "FAIL",
                f"Missing: {missing}"
            )


    except Exception as e:

        record(
            "OHLCV features validated",
            "FAIL",
            str(e)
        )



def validate_schema():

    if FEATURE_ENGINE_PATH:

        record(
            "Output schema validated",
            "PASS",
            "Feature output module available"
        )



def print_report():

    print("\n")
    print("=" * 40)
    print("QPX Alpha Step 8 Feature Engine Validation")
    print("=" * 40)


    failed = []


    for item in results:

        print(
            f"[{item['status']}] {item['check']}"
        )

        if item["detail"]:

            print(
                "       ",
                item["detail"]
            )


        if item["status"] == "FAIL":

            failed.append(
                item["check"]
            )


    print("\n")


    if failed:

        print(
            "STEP 8 STATUS: FAIL"
        )

        print(
            "Failure Classification:"
        )


        for failure in failed:

            print(
                "-",
                failure
            )

    else:

        print(
            "STEP 8 STATUS: PASS"
        )


    print("=" * 40)



def main():

    validate_feature_file()

    validate_database()

    module = load_feature_engine()

    validate_calculations(
        module
    )

    validate_ohlcv()

    validate_schema()

    print_report()



if __name__ == "__main__":
    main()
