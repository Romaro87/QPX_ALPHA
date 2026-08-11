from core.portfolio import Portfolio
from core.portfolio.models import Position

portfolio = Portfolio()

portfolio.deposit(5000)

portfolio.add_position(
    Position(
        symbol="AAPL",
        quantity=10,
        average_cost=200,
        current_price=220,
    )
)

assert portfolio.buying_power == 5000
assert portfolio.invested_value == 2200
assert portfolio.total_value == 7200
assert portfolio.total_unrealized_gain == 200

print("Portfolio Engine PASS")