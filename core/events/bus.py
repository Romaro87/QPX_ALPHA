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
