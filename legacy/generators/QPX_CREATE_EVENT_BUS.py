from pathlib import Path
import textwrap

ROOT = Path("/storage/emulated/0/QPX_ALPHA")

EVENTS = ROOT / "core" / "events"
EVENTS.mkdir(parents=True, exist_ok=True)

(EVENTS / "__init__.py").write_text(
    "from .bus import EventBus, event_bus\n",
    encoding="utf-8"
)

bus_source = textwrap.dedent("""
from collections import defaultdict
from typing import Callable, Any

from core.logger import get_logger

logger = get_logger(__name__)


class EventBus:

    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event_name: str, callback: Callable[..., Any]):
        self._subscribers[event_name].append(callback)
        logger.info(f"Subscribed to event: {event_name}")

    def publish(self, event_name: str, **kwargs):
        logger.info(f"Publishing event: {event_name}")

        for callback in self._subscribers[event_name]:
            try:
                callback(**kwargs)
            except Exception as exc:
                logger.exception(
                    f"Error while handling '{event_name}': {exc}"
                )


event_bus = EventBus()
""").strip()

(EVENTS / "bus.py").write_text(
    bus_source + "\n",
    encoding="utf-8"
)

test_source = textwrap.dedent("""
from core.events import event_bus


def market_updated(symbol, price):

    print(f"{symbol} updated to {price}")


event_bus.subscribe("MARKET_UPDATED", market_updated)

event_bus.publish(
    "MARKET_UPDATED",
    symbol="AAPL",
    price=210.45
)
""").strip()

(ROOT / "test_event_bus.py").write_text(
    test_source + "\n",
    encoding="utf-8"
)

print("=" * 60)
print("Event Bus Created")
print("=" * 60)
print("Created:")
print(" core/events/bus.py")
print(" test_event_bus.py")
print()
print("Run:")
print("python test_event_bus.py")