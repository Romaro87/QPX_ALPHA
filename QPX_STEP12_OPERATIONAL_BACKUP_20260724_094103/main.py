
from quant_platform.data.sqlite_store import SQLiteStore
from quant_platform.live.trade_journal import TradeJournal


print("QPX Alpha v0.8 Mobile Core")
print("--------------------------")


db = SQLiteStore(
    "qpx_alpha.db"
)


journal = TradeJournal(db)


journal.record(
    symbol="AAPL",
    side="BUY",
    quantity=10,
    price=190.50,
    strategy="InstitutionalMomentum"
)


print("SQLite ready")
print("Trade journal ready")
print("QPX Alpha Mobile Core operational")
