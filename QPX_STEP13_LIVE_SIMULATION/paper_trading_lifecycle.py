

import sqlite3
import datetime


class PaperTradingLifecycle:


    def __init__(self, db):

        self.db=db



    def open_trade(self, symbol, price):

        conn=sqlite3.connect(self.db)

        cur=conn.cursor()


        cur.execute(
            """
            INSERT INTO lifecycle_trades
            (symbol,side,entry,status,created)
            VALUES (?,?,?,?,?)
            """,
            (
                symbol,
                "BUY",
                price,
                "OPEN",
                datetime.datetime.now().isoformat()
            )
        )


        trade_id=cur.lastrowid

        conn.commit()
        conn.close()

        return trade_id



    def close_trade(self, trade_id, price):

        conn=sqlite3.connect(self.db)

        cur=conn.cursor()


        cur.execute(
            """
            SELECT entry
            FROM lifecycle_trades
            WHERE id=?
            """,
            (trade_id,)
        )


        entry=cur.fetchone()[0]


        pnl=price-entry


        cur.execute(
            """
            UPDATE lifecycle_trades

            SET exit=?,
                pnl=?,
                status='CLOSED'

            WHERE id=?

            """,
            (
                price,
                pnl,
                trade_id
            )
        )


        conn.commit()
        conn.close()


        return pnl



    def hold(self):

        return "NO ACTION"

