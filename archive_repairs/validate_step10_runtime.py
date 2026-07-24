

from backtesting_engine import BacktestEngine


print("="*50)
print("STEP 10 RUNTIME VALIDATION")
print("="*50)


engine = BacktestEngine()


signals = [
    {
        "symbol":"TEST",
        "timestamp":"2026-07-24",
        "side":"BUY",
        "price":100,
        "quantity":1
    }
]


result = engine.run(
    signals=signals,
    historical_data=[]
)


assert "trades" in result

assert "metrics" in result


print("Trade storage:")
print(engine.trades)


print("Metrics:")
print(engine.metrics)


print()
print("STEP 10 BASIC ENGINE TEST PASS")

