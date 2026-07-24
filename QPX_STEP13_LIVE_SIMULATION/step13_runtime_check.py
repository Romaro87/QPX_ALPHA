
from paper_trading_engine import PaperTradingEngine
from position_manager import PositionManager
from risk_controller import RiskController
from live_trade_journal import LiveTradeJournal


print("QPX STEP 13 MODULE CHECK")

modules = [
    PaperTradingEngine(),
    PositionManager(),
    RiskController(),
    LiveTradeJournal()
]


for module in modules:

    print(
        "[PASS]",
        module.__class__.__name__
    )


print("STEP 13 MODULE STATUS: READY")
