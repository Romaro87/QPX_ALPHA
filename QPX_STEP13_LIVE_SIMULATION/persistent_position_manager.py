
import sqlite3
import datetime


class PersistentPositionManager:

    def __init__(self, db):

        self.db=db


    def open(self, trade_id):

        conn=sqlite3.connect(self.db)

        cur=conn.cursor()


        cur.execute(
            """
            INSERT INTO positions
            VALUES
            (NULL,?,?,?)
            """,
            (
                trade_id,
                "OPEN",
                datetime.datetime.now().isoformat()
            )
        )


        conn.commit()

        conn.close()
