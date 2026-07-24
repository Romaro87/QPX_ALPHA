
from datetime import datetime


class TradeJournal:


    def __init__(self,storage):

        self.storage=storage



    def record(
        self,
        symbol,
        side,
        quantity,
        price,
        strategy
    ):

        trade={

        "timestamp":
        datetime.utcnow().isoformat(),

        "symbol":symbol,

        "side":side,

        "quantity":quantity,

        "price":price,

        "strategy":strategy

        }


        self.storage.insert_trade(trade)
