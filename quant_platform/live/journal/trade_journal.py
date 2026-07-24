
from datetime import datetime


class TradeJournal:

    def __init__(self, database):
        self.database = database


    def record_trade(
        self,
        symbol,
        entry,
        exit,
        quantity,
        side,
        pnl
    ):

        self.database.execute(
        """
        INSERT INTO trades
        (
        symbol,
        entry_price,
        exit_price,
        quantity,
        side,
        pnl,
        timestamp
        )
        VALUES(?,?,?,?,?,?,?)
        """,

        (
        symbol,
        entry,
        exit,
        quantity,
        side,
        pnl,
        datetime.now().isoformat()
        ))

