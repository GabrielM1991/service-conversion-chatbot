from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.application.services import ProcessIncomingMessage
from app.domain.models import IncomingMessage

logger = logging.getLogger("chatbot")


class MessageEventBus(Protocol):
    async def publish(self, event: IncomingMessage) -> None: ...

    async def consume_forever(self, processor: ProcessIncomingMessage) -> None: ...


def serialize_event(event: IncomingMessage) -> str:
    return json.dumps(
        {
            "message_id": event.message_id,
            "tenant_id": event.tenant_id,
            "customer_phone": event.customer_phone,
            "text": event.text,
            "received_at": event.received_at.isoformat(),
        },
        ensure_ascii=False,
    )


def deserialize_event(payload: str) -> IncomingMessage:
    data = json.loads(payload)
    return IncomingMessage(
        message_id=data["message_id"],
        tenant_id=data["tenant_id"],
        customer_phone=data["customer_phone"],
        text=data["text"],
        received_at=datetime.fromisoformat(data["received_at"]),
    )


class InMemoryEventBus:
    """Fast local adapter used when Redis is not configured."""

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


class RedisStreamEventBus:
    def __init__(
        self,
        client: Redis,
        stream: str = "whatsapp_messages",
        dlq_stream: str = "whatsapp_messages_dlq",
        group: str = "chatbot_workers",
        consumer: str = "worker-1",
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        claim_idle_ms: int = 60_000,
        block_ms: int | None = 5_000,
    ) -> None:
        self._client = client
        self.stream = stream
        self.dlq_stream = dlq_stream
        self.group = group
        self.consumer = consumer
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.claim_idle_ms = claim_idle_ms
        self.block_ms = block_ms

    async def publish(self, event: IncomingMessage) -> None:
        await self._client.xadd(
            self.stream,
            {"payload": serialize_event(event), "attempt": "0"},
            maxlen=10_000,
            approximate=True,
        )
        logger.info(
            "Evento publicado en Redis Stream: %s",
            event.message_id,
            extra={"component": "RedisStream", "tenant": event.tenant_id},
        )

    async def consume_forever(self, processor: ProcessIncomingMessage) -> None:
        await self._ensure_group()
        await self._recover_pending(processor)
        logger.info(
            "Worker listo. Stream=%s Group=%s Consumer=%s",
            self.stream,
            self.group,
            self.consumer,
            extra={"component": "RedisWorker", "tenant": "-"},
        )
        while True:
            batches = await self._client.xreadgroup(
                self.group,
                self.consumer,
                {self.stream: ">"},
                count=10,
                block=self.block_ms,
            )
            for _, entries in batches:
                for entry_id, fields in entries:
                    await self._process_entry(processor, entry_id, fields)

    async def _ensure_group(self) -> None:
        try:
            await self._client.xgroup_create(self.stream, self.group, id="0-0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise

    async def _recover_pending(self, processor: ProcessIncomingMessage) -> None:
        pending = await self._client.xpending(self.stream, self.group)
        pending_count = pending["pending"] if isinstance(pending, dict) else pending[0]
        if pending_count == 0:
            return
        start_id = "0-0"
        while True:
            result = await self._client.xautoclaim(
                self.stream,
                self.group,
                self.consumer,
                min_idle_time=self.claim_idle_ms,
                start_id=start_id,
                count=20,
            )
            start_id = result[0]
            entries = result[1]
            for entry_id, fields in entries:
                await self._process_entry(processor, entry_id, fields)
            if not entries or start_id == "0-0":
                break

    async def _process_entry(
        self, processor: ProcessIncomingMessage, entry_id: str, fields: dict[str, str]
    ) -> None:
        payload = fields["payload"]
        event = deserialize_event(payload)
        attempt = int(fields.get("attempt", "0"))
        try:
            await processor.execute(event)
        except Exception as error:
            await self._handle_failure(entry_id, payload, event, attempt, error)
            return
        await self._client.xack(self.stream, self.group, entry_id)
        logger.info(
            "Evento confirmado: %s",
            event.message_id,
            extra={"component": "RedisWorker", "tenant": event.tenant_id},
        )

    async def _handle_failure(
        self,
        entry_id: str,
        payload: str,
        event: IncomingMessage,
        attempt: int,
        error: Exception,
    ) -> None:
        next_attempt = attempt + 1
        if next_attempt > self.max_retries:
            await self._client.xadd(
                self.dlq_stream,
                {
                    "payload": payload,
                    "attempts": str(next_attempt),
                    "error": f"{type(error).__name__}: {error}"[:500],
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                },
                maxlen=10_000,
                approximate=True,
            )
            logger.exception(
                "Evento enviado a DLQ después de %s intentos: %s",
                next_attempt,
                event.message_id,
                extra={"component": "RedisDLQ", "tenant": event.tenant_id},
            )
        else:
            delay = self.retry_base_delay * (2 ** (next_attempt - 1))
            if delay:
                await asyncio.sleep(delay)
            await self._client.xadd(
                self.stream,
                {"payload": payload, "attempt": str(next_attempt)},
                maxlen=10_000,
                approximate=True,
            )
            logger.warning(
                "Evento reencolado. Intento=%s Mensaje=%s",
                next_attempt,
                event.message_id,
                extra={"component": "RedisRetry", "tenant": event.tenant_id},
            )
        await self._client.xack(self.stream, self.group, entry_id)
