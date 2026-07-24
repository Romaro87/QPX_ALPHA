#!/usr/bin/env python3

import os
import sqlite3
import datetime


ROOT = "/storage/emulated/0/QPX_ALPHA"

STEP13 = os.path.join(
    ROOT,
    "QPX_STEP13_LIVE_SIMULATION"
)

DB = os.path.join(
    STEP13,
    "qpx_step13_simulation.db"
)

REPORT = os.path.join(
    STEP13,
    "STEP13_4_LIFECYCLE_REPORT.txt"
)


def log(report, text):

    print(text)
    report.write(text + "\n")



def create_schema():

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS account (

            id INTEGER PRIMARY KEY,
            balance REAL

        )
        """
    )


    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS lifecycle_trades (

            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT,
            entry REAL,
            exit REAL,
            pnl REAL,
            status TEXT,
            created TEXT

        )
        """
    )


    cur.execute(
        """
        INSERT OR IGNORE INTO account
        VALUES (1,10000)
        """
    )


    conn.commit()
    conn.close()



def create_engine():

    path = os.path.join(
        STEP13,
        "paper_trading_lifecycle.py"
    )


    code = r'''

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

'''


    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(code)



def validate(report):

    conn=sqlite3.connect(DB)

    cur=conn.cursor()


    cur.execute(
        """
        SELECT balance
        FROM account
        """
    )


    balance=cur.fetchone()[0]


    log(
        report,
        "[PASS] Account balance: "
        + str(balance)
    )


    conn.close()



def main():

    os.makedirs(
        STEP13,
        exist_ok=True
    )


    with open(
        REPORT,
        "w",
        encoding="utf-8"
    ) as report:


        log(
            report,
            "================================="
        )

        log(
            report,
            "QPX STEP 13.4 LIFECYCLE BUILDER"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        create_schema()

        log(
            report,
            "[PASS] Lifecycle Database Schema"
        )


        create_engine()

        log(
            report,
            "[CREATED] paper_trading_lifecycle.py"
        )


        validate(report)


        log(
            report,
            ""
        )

        log(
            report,
            "QPX STEP 13.4 STATUS: READY"
        )

        log(
            report,
            "================================="
        )



if __name__=="__main__":

    main()