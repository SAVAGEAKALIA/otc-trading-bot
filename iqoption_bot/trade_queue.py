import asyncio
from typing import Dict, Tuple
from dataclasses import dataclass, field
from .models import TradeRequest

class PriorityTradeQueue:
    """
    Priority-aware queue for trade execution.
    Higher priority items are processed first.
    
    Priority Scale:
    0 - Martingale (Highest)
    1 - Scanner
    2 - Telegram (Lowest)
    """
    
    PRIORITY_MARTINGALE = 0
    PRIORITY_SCANNER = 1
    PRIORITY_TELEGRAM = 2
    
    def __init__(self):
        self._queue = asyncio.PriorityQueue()
        self._counter = 0  # Tie-breaker for same priority
        self._source_map = {
            "martingale": self.PRIORITY_MARTINGALE,
            "scanner": self.PRIORITY_SCANNER,
            "telegram": self.PRIORITY_TELEGRAM
        }

    async def put(self, request: TradeRequest, source: str = "telegram"):
        """
        Add a trade request to the queue with a specific priority.
        Defaults to telegram priority if source is unknown.
        """
        priority = self._source_map.get(source.lower(), self.PRIORITY_TELEGRAM)
        
        # PriorityQueue sorts by the first element, then second, and so on.
        # We use a serial counter to prevent comparing TradeRequest objects (which would fail).
        self._counter += 1
        await self._queue.put((priority, self._counter, request))
        print(f"📥 Trade queued: {request.signal.asset} at priority {priority} (source: {source})")

    async def get(self) -> TradeRequest:
        """Get the highest priority trade request from the queue."""
        priority, count, request = await self._queue.get()
        return request

    def empty(self) -> bool:
        """Check if the queue is empty."""
        return self._queue.empty()

    def qsize(self) -> int:
        """Return the approximate size of the queue."""
        return self._queue.qsize()

    def task_done(self):
        """Inform the queue that a previously enqueued task is complete.
        Safely ignores extra calls to prevent ValueError from crashing the bot.
        """
        try:
            self._queue.task_done()
        except ValueError:
            # This happens if task_done() is called more times than items put into the queue
            pass
        except Exception as e:
            print(f"⚠️ Queue state warning: {e}")
