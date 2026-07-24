import os
import sqlite3
import traceback

BASE = "/storage/emulated/0/QPX_ALPHA"
DB_PATH = os.path.join(BASE, "qpx_alpha.db")

FEATURE_ENGINE_PATH = os.path.join(BASE, "feature_engine.py")
VERIFY_STEP8 = os.path.join(BASE, "verify_step8_analytics_feature_engine.py")


FEATURE_ENGINE_CODE = r'''
"""
QPX Alpha Analytics Feature Engine
Step 8 Implementation

Uses existing validated market_data table.
Does not modify ingestion or database lifecycle.
"""

import sqlite3
import pandas as pd


class FeatureEngine:

    def __init__(self, db_path):
        self.db_path = db_path


    def load_market_data(self):
        conn = sqlite3.connect(self.db_path)

        query = """
        SELECT *
        FROM market_data
        """

        df = pd.read_sql_query(query, conn)

        conn.close()

        return df


    def calculate_features(self, df):

        result = df.copy()

        required = [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]

        available = set(result.columns)

        if all(x in available for x in required):

            result["price_change"] = (
                result["close"]
                -
                result["open"]
            )

            result["range"] = (
                result["high"]
                -
                result["low"]
            )

            result["volume_change"] = (
                result["volume"]
                .diff()
            )

            result["sma_5"] = (
                result["close"]
                .rolling(5)
                .mean()
            )

        return result


    def run(self):

        df = self.load_market_data()

        features = self.calculate_features(df)

        return features



def run_feature_engine(db_path):

    engine = FeatureEngine(db_path)

    return engine.run()
'''


def create_feature_engine():

    if os.path.exists(FEATURE_ENGINE_PATH):
        print("[INFO] feature_engine.py already exists")
        return

    with open(FEATURE_ENGINE_PATH, "w") as f:
        f.write(FEATURE_ENGINE_CODE)

    print("[OK] Created feature_engine.py")


def validate_database():

    if not os.path.exists(DB_PATH):
        print("[FAIL] Database missing")
        return False

    conn = sqlite3.connect(DB_PATH)

    tables = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        """
    ).fetchall()

    conn.close()

    names = [x[0] for x in tables]

    if "market_data" in names:
        print("[OK] market_data table available")
        return True

    print("[FAIL] market_data table missing")
    return False


def test_feature_engine():

    try:

        from feature_engine import FeatureEngine

        engine = FeatureEngine(DB_PATH)

        df = engine.run()

        print("[OK] Feature engine import successful")
        print("[OK] Feature calculation executed")
        print("[OK] Output rows:", len(df))

        return True

    except Exception:

        print("[FAIL] Feature engine execution error")
        traceback.print_exc()

        return False


def run_step8_validation():

    if not os.path.exists(VERIFY_STEP8):
        print("[INFO] Step 8 validator not found")
        return

    print("\n[INFO] Running Step 8 validator\n")

    os.system(
        f"python {VERIFY_STEP8}"
    )


if __name__ == "__main__":

    print("========================================")
    print("QPX Alpha Step 8 Feature Engine Repair")
    print("========================================")

    create_feature_engine()

    validate_database()

    test_feature_engine()

    run_step8_validation()

    print("\n========================================")
    print("Repair attempt complete")
    print("========================================")
