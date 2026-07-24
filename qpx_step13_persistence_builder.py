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
    "STEP13_PERSISTENCE_REPORT.txt"
)


def log(report, text):

    print(text)

    report.write(
        text + "\n"
    )


def create_database():

    conn = sqlite3.connect(DB)

    cur = conn.cursor()


    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            timestamp TEXT,

            signal TEXT,

            score REAL,

            confidence REAL,

            status TEXT

        )
        """
    )


    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            trade_id INTEGER,

            position_status TEXT,

            created TEXT

        )
        """
    )


    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_journal (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            event_time TEXT,

            event TEXT

        )
        """
    )


    conn.commit()

    conn.close()



def create_modules():

    files = {


"persistent_paper_trader.py": r'''
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
''',


"persistent_position_manager.py": r'''
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
''',


"persistent_journal.py": r'''
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
'''
    }


    for name,code in files.items():

        path=os.path.join(
            STEP13,
            name
        )

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(code)


        print(
            "[CREATED]",
            name
        )



def validate(report):

    conn=sqlite3.connect(DB)

    cur=conn.cursor()


    for table in [
        "paper_trades",
        "positions",
        "trade_journal"
    ]:

        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            AND name=?
            """,
            (table,)
        )


        if cur.fetchone():

            log(
                report,
                "[PASS] " + table
            )

        else:

            log(
                report,
                "[FAIL] " + table
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
            "QPX STEP 13.2 PERSISTENCE BUILDER"
        )

        log(
            report,
            datetime.datetime.now().isoformat()
        )

        log(
            report,
            "================================="
        )


        create_database()

        log(
            report,
            "[PASS] Simulation Database Created"
        )


        create_modules()


        validate(
            report
        )


        log(
            report,
            ""
        )

        log(
            report,
            "STEP 13.2 STATUS: READY"
        )

        log(
            report,
            "Database:"
        )

        log(
            report,
            DB
        )


if __name__=="__main__":

    main()