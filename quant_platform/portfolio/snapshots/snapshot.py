
from datetime import datetime


class PortfolioSnapshot:

    def __init__(self, database):
        self.database = database


    def save(
        self,
        cash,
        equity,
        exposure,
        drawdown
    ):

        self.database.execute(
        """
        INSERT INTO portfolio_snapshots
        (
        timestamp,
        cash,
        equity,
        exposure,
        drawdown
        )
        VALUES(?,?,?,?,?)
        """,

        (
        datetime.now().isoformat(),
        cash,
        equity,
        exposure,
        drawdown
        ))
