from core.events import event_bus


def market_updated(symbol, price):

    print(f"{symbol} updated to {price}")


event_bus.subscribe("MARKET_UPDATED", market_updated)

event_bus.publish(
    "MARKET_UPDATED",
    symbol="AAPL",
    price=210.45
)
