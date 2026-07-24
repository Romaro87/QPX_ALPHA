
from pathlib import Path
import pandas as pd


class MarketCache:

    def __init__(self, folder="market_cache"):

        self.folder=Path(folder)
        self.folder.mkdir(exist_ok=True)


    def save(self,symbol,data):

        data.to_csv(
            self.folder/f"{symbol}.csv",
            index=False
        )


    def load(self,symbol):

        path=self.folder/f"{symbol}.csv"

        if path.exists():

            return pd.read_csv(path)

        return None
