from core.portfolio.models import Position

position = Position(
    symbol="AAPL",
    quantity=10,
    average_cost=200.0,
    current_price=220.0,
)

print("Market Value:", position.market_value)
print("Unrealized Gain:", position.unrealized_gain)