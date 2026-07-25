"""
============================================================
QPX DATA PROVIDER FRAMEWORK
Version 1.0
============================================================

Unified interface for all market data providers.

Supported Providers

• Yahoo Finance
• Alpha Vantage
• Polygon
• Twelve Data
• Finnhub
• Future Providers

Every provider returns the SAME format.

Author:
QPX Alpha
"""

from abc import ABC, abstractmethod
from datetime import datetime


# ============================================================
# Standard Response
# ============================================================

class MarketData:

    def __init__(self,
                 symbol,
                 timeframe,
                 rows,
                 provider,
                 timestamp=None):

        self.symbol = symbol
        self.timeframe = timeframe
        self.rows = rows
        self.provider = provider
        self.timestamp = timestamp or datetime.now()

    def __len__(self):
        return len(self.rows)

    def to_dict(self):

        return {

            "symbol": self.symbol,

            "provider": self.provider,

            "timeframe": self.timeframe,

            "timestamp": self.timestamp.isoformat(),

            "rows": self.rows

        }


# ============================================================
# Abstract Provider
# ============================================================

class DataProvider(ABC):

    name = "Unknown"

    @abstractmethod
    def historical(
        self,
        symbol,
        start,
        end,
        interval
    ):
        pass

    @abstractmethod
    def realtime(
        self,
        symbol
    ):
        pass

    @abstractmethod
    def fundamentals(
        self,
        symbol
    ):
        pass

    @abstractmethod
    def status(self):
        pass


# ============================================================
# Provider Registry
# ============================================================

class ProviderRegistry:

    def __init__(self):

        self.providers = {}

    def register(self, provider):

        self.providers[
            provider.name.lower()
        ] = provider

    def get(self, name):

        return self.providers.get(
            name.lower()
        )

    def available(self):

        return sorted(
            self.providers.keys()
        )


registry = ProviderRegistry()


# ============================================================
# Mock Provider
# ============================================================

class MockProvider(DataProvider):

    name = "Mock"

    def historical(
        self,
        symbol,
        start,
        end,
        interval
    ):

        rows = []

        for i in range(100):

            rows.append({

                "date": f"Day {i}",

                "open": 100 + i,

                "high": 101 + i,

                "low": 99 + i,

                "close": 100.5 + i,

                "volume": 100000 + i

            })

        return MarketData(

            symbol=symbol,

            timeframe=interval,

            rows=rows,

            provider=self.name

        )

    def realtime(self, symbol):

        return {

            "symbol": symbol,

            "price": 100.00,

            "provider": self.name

        }

    def fundamentals(self, symbol):

        return {

            "symbol": symbol,

            "market_cap": None,

            "pe_ratio": None,

            "provider": self.name

        }

    def status(self):

        return {

            "provider": self.name,

            "status": "ONLINE"

        }


registry.register(MockProvider())


# ============================================================
# Provider Manager
# ============================================================

class ProviderManager:

    def __init__(self,
                 default="Mock"):

        self.provider = registry.get(
            default
        )

    def set_provider(self,
                     name):

        p = registry.get(name)

        if p is None:

            raise ValueError(
                f"Unknown provider: {name}"
            )

        self.provider = p

    def historical(
        self,
        symbol,
        start,
        end,
        interval="1d"
    ):

        return self.provider.historical(

            symbol,

            start,

            end,

            interval

        )

    def realtime(
        self,
        symbol
    ):

        return self.provider.realtime(
            symbol
        )

    def fundamentals(
        self,
        symbol
    ):

        return self.provider.fundamentals(
            symbol
        )


# ============================================================
# Demo
# ============================================================

def main():

    print("=" * 60)
    print("QPX DATA PROVIDER FRAMEWORK")
    print("=" * 60)

    manager = ProviderManager()

    print()

    print("Providers")

    print(registry.available())

    print()

    history = manager.historical(

        "AAPL",

        "2024-01-01",

        "2024-12-31",

        "1d"

    )

    print("Rows")

    print(len(history))

    print()

    print(history.rows[0])

    print()

    print("Realtime")

    print(manager.realtime("AAPL"))

    print()

    print("Fundamentals")

    print(manager.fundamentals("AAPL"))

    print()

    print("STATUS : COMPLETE")


if __name__ == "__main__":
    main()