from __future__ import annotations

import asyncio
import logging

from app.application.services import ProcessIncomingMessage
from app.domain.models import IncomingMessage

logger = logging.getLogger("chatbot")


class InMemoryEventBus:
    """Async queue with the same boundary a RabbitMQ/SQS adapter would implement."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()

    async def publish(self, event: IncomingMessage) -> None:
        await self._queue.put(event)

    async def consume_forever(self, processor: ProcessIncomingMessage) -> None:
        while True:
            event = await self._queue.get()
            try:
                await processor.execute(event)
            except Exception:
                logger.exception(
                    "Error procesando mensaje %s",
                    event.message_id,
                    extra={"component": "MessageWorker", "tenant": event.tenant_id},
                )
            finally:
                self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

