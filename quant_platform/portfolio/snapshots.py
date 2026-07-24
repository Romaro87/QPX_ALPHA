
from datetime import datetime


class PortfolioSnapshotManager:


    def __init__(self,storage):

        self.storage=storage


    def save(
        self,
        equity,
        cash,
        positions
    ):

        self.storage.connection.execute(
        """
        INSERT INTO portfolio_snapshots
        VALUES(NULL,?,?,?,?)
        """,
        (
        datetime.utcnow().isoformat(),
        equity,
        cash,
        str(positions)
        ))

        self.storage.connection.commit()
