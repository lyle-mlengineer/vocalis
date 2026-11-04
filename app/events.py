import logging
from collections import defaultdict
from collections.abc import Callable

from app.domain import DomainEvent

logger = logging.getLogger("vocalis.events")


class DomainEventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Callable[[DomainEvent], None]]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Callable[[DomainEvent], None]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: DomainEvent) -> None:
        logger.info("Domain event: %s", event.name)
        for handler in self._handlers[type(event)]:
            handler(event)
