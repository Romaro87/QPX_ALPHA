
import sqlite3
import datetime


class PersistentJournal:

    def __init__(self, db):

        self.db=db


    def record(self,event):

        conn=sqlite3.connect(self.db)

        cur=conn.cursor()


        cur.execute(
            """
            INSERT INTO trade_journal
            VALUES
            (NULL,?,?)
            """,
            (
                datetime.datetime.now().isoformat(),
                str(event)
            )
        )


        conn.commit()

        conn.close()
