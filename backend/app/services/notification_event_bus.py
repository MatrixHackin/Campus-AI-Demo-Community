from __future__ import annotations

import asyncio
from dataclasses import dataclass
from itertools import count
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class NotificationEvent:
    id: int
    target_username: str | None
    payload: dict[str, Any]


class NotificationEventBus:
    """In-process fanout for lightweight notification refresh signals."""

    def __init__(self) -> None:
        self._subscribers: dict[int, tuple[str, asyncio.AbstractEventLoop, asyncio.Queue[NotificationEvent]]] = {}
        self._subscriber_ids = count(1)
        self._event_ids = count(1)
        self._lock = Lock()

    def subscribe(self, username: str) -> tuple[int, asyncio.Queue[NotificationEvent]]:
        subscriber_id = next(self._subscriber_ids)
        queue: asyncio.Queue[NotificationEvent] = asyncio.Queue(maxsize=20)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers[subscriber_id] = (username, loop, queue)
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def publish_changed(self, target_username: str | None = None) -> None:
        event = NotificationEvent(
            id=next(self._event_ids),
            target_username=target_username,
            payload={'type': 'notification.changed'},
        )
        with self._lock:
            subscribers = list(self._subscribers.values())

        for username, loop, queue in subscribers:
            if target_username is not None and username != target_username:
                continue
            loop.call_soon_threadsafe(self._push_event, queue, event)

    @staticmethod
    def _push_event(queue: asyncio.Queue[NotificationEvent], event: NotificationEvent) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass
