"""ダッシュボード(SSE)へのイベント配信用の簡易イベントバス。"""

from __future__ import annotations

import asyncio
from typing import Any


class EventBus:
    def __init__(self):
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event_type: str, data: Any) -> None:
        event = {"type": event_type, "data": data}
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 遅い購読者は切り捨てる（次の接続で再同期される）
                self._subscribers.discard(q)
