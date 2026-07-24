
import sqlite3
import datetime


class PersistentPaperTrader:

    def __init__(self, db):

        self.db=db


    def execute(self, signal):

        conn=sqlite3.connect(self.db)

        cur=conn.cursor()


        cur.execute(
            """
            INSERT INTO paper_trades
            VALUES
            (NULL,?,?,?,?,?)
            """,
            (
                signal.get("timestamp"),
                signal.get("signal"),
                signal.get("score"),
                signal.get("confidence"),
                "SIMULATED"
            )
        )


        trade_id=cur.lastrowid

        conn.commit()

        conn.close()


        return trade_id
