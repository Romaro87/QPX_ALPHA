#!/usr/bin/env python3

import os
import sqlite3
import importlib.util
import traceback
from datetime import datetime


BASE = "/storage/emulated/0/QPX_ALPHA"

DB_PATH = os.path.join(BASE, "qpx_alpha.db")

IMPORTER_PATH = os.path.join(
    BASE,
    "quant_platform",
    "mobile",
    "csv_importer.py"
)


CSV_SEARCH_PATHS = [
    BASE,
    os.path.join(BASE, "data"),
    os.path.join(BASE, "csv"),
    os.path.join(BASE, "imports"),
]


REQUIRED_TABLE = "market_data"


def log(msg):
    print(msg)


def find_csv():
    log("\n[SCAN] Searching CSV files")

    found = []

    for path in CSV_SEARCH_PATHS:
        if not os.path.exists(path):
            continue

        for root, dirs, files in os.walk(path):
            for f in files:
                if f.lower().endswith(".csv"):
                    found.append(os.path.join(root, f))

    if not found:
        log("[FAIL] No CSV files found")
        return None

    for item in found:
        log("[CSV] " + item)

    return found[0]


def inspect_csv(path):
    log("\n[CHECK] CSV validation")

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            log("[FAIL] Empty CSV")
            return False

        headers = lines[0].strip()

        log("CSV headers:")
        log(headers)

        log("CSV rows loaded:")
        log(str(len(lines)-1))

        return True

    except Exception:
        traceback.print_exc()
        return False


def load_importer():

    log("\n[LOAD] Importer")

    if not os.path.exists(IMPORTER_PATH):
        log("[FAIL] Importer missing")
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            "csv_importer",
            IMPORTER_PATH
        )

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        log("[OK] Importer loaded")

        return module

    except Exception:
        traceback.print_exc()
        return None


def database_count():

    try:
        conn = sqlite3.connect(DB_PATH)

        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) FROM market_data"
        )

        count = cur.fetchone()[0]

        conn.close()

        return count

    except Exception:
        return -1


def find_import_function(module):

    candidates = [
        "import_csv",
        "load_csv",
        "process_csv",
        "run_import",
        "import_market_data"
    ]

    for name in candidates:
        if hasattr(module, name):
            log("[OK] Import function found: " + name)
            return getattr(module, name)

    log("[FAIL] No import function detected")

    return None


def execute_import(import_func, csv_path):

    log("\n[RUN] Executing importer")

    before = database_count()

    log("market_data count before:")
    log(str(before))

    try:

        result = None

        try:
            result = import_func(csv_path)

        except TypeError:
            result = import_func(
                csv_file=csv_path
            )

        log("Importer result:")
        log(str(result))

    except Exception:
        traceback.print_exc()

        log("[FAIL] Import execution failed")
        return False


    after = database_count()

    log("\nINSERT validation")

    log("market_data count after:")
    log(str(after))


    if after > before:

        log("[OK] Rows created")
        return True

    else:

        log("[FAIL] No rows inserted")
        return False



def main():

    print("=" * 45)
    print("QPX ALPHA STEP 5 IMPORT PIPELINE REPAIR")
    print("=" * 45)


    csv = find_csv()

    if not csv:
        return


    if not inspect_csv(csv):
        return


    module = load_importer()

    if not module:
        return


    importer = find_import_function(module)

    if not importer:
        return


    success = execute_import(
        importer,
        csv
    )


    print("\n===================================")

    if success:

        print("[PASS] Import repair successful")

    else:

        print("[FAIL] Import repair incomplete")


    print("===================================")


if __name__ == "__main__":
    main()
