from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import closing_prices, load_csv


project_root = Path(__file__).resolve().parents[1]
sample_file = (
    project_root
    / "qpx_bot"
    / "sample_data"
    / "sample.csv"
)

config = BotConfig()
config.validate()

candles = load_csv(sample_file)
prices = closing_prices(candles)

assert config.starting_cash == 1300.0
assert len(candles) == 10
assert candles[0].date < candles[-1].date
assert len(prices) == len(candles)
assert prices[0] == 100.50
assert prices[-1] == 109.70

print("QPX Bot Skeleton PASS")
