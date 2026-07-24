
import sqlite3
import json
from pathlib import Path


class SQLiteStore:

    def __init__(self, db_path="qpx_alpha.db"):

        self.db_path = Path(db_path)

        self.connection = sqlite3.connect(
            self.db_path
        )

        self.initialize()


    def initialize(self):

        c = self.connection.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            price REAL,
            strategy TEXT,
            metadata TEXT
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots(
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            equity REAL,
            cash REAL,
            positions TEXT
        )
        """)


        self.connection.commit()



    def insert_trade(self, trade):

        self.connection.execute(
        """
        INSERT INTO trades
        VALUES(NULL,?,?,?,?,?,?,?)
        """,
        (
            trade["timestamp"],
            trade["symbol"],
            trade["side"],
            trade["quantity"],
            trade["price"],
            trade["strategy"],
            json.dumps(trade.get("metadata",{}))
        ))

        self.connection.commit()
