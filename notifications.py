import asyncio
from typing import List, Optional

_loop: Optional[asyncio.AbstractEventLoop] = None


def set_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


class NotificationBroadcaster:
    def __init__(self):
        self._queues: List[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def broadcast(self, event: dict):
        for q in list(self._queues):
            try:
                await q.put(event)
            except Exception:
                self.unsubscribe(q)

    def broadcast_sync(self, event: dict):
        """Appel depuis un endpoint synchrone (thread pool)."""
        if _loop and _loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(event), _loop)


broadcaster = NotificationBroadcaster()
