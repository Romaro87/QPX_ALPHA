
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
