from __future__ import annotations

from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from app.domain.models import IncomingMessage
from app.infrastructure.event_bus import RedisStreamEventBus, deserialize_event, serialize_event
from app.infrastructure.redis_adapters import RedisDeduplicationStore, RedisOptOutStore


def message(message_id: str = "wamid-redis-1") -> IncomingMessage:
    return IncomingMessage(
        message_id=message_id,
        tenant_id="ClinicaDental_01",
        customer_phone="+584121234567",
        text="Quiero una cita para limpieza dental",
        received_at=datetime.now(timezone.utc),
    )


@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_deduplication_is_tenant_scoped_and_persistent(redis_client) -> None:
    store = RedisDeduplicationStore(redis_client, ttl_seconds=60)

    assert await store.mark_if_new("tenant-a", "same-id") is True
    assert await store.mark_if_new("tenant-a", "same-id") is False
    assert await store.mark_if_new("tenant-b", "same-id") is True


@pytest.mark.asyncio
async def test_opt_out_is_tenant_scoped(redis_client) -> None:
    store = RedisOptOutStore(redis_client)

    await store.opt_out("tenant-a", "+584121234567")

    assert await store.is_opted_out("tenant-a", "+584121234567") is True
    assert await store.is_opted_out("tenant-b", "+584121234567") is False


def test_event_serialization_round_trip() -> None:
    original = message()

    restored = deserialize_event(serialize_event(original))

    assert restored == original


@pytest.mark.asyncio
async def test_worker_processes_and_acknowledges_event(redis_client) -> None:
    processed: list[IncomingMessage] = []

    class Processor:
        async def execute(self, event: IncomingMessage) -> None:
            processed.append(event)

    bus = RedisStreamEventBus(redis_client, consumer="worker-test", claim_idle_ms=1)
    await bus.publish(message())
    await bus._ensure_group()
    entry_id, fields = await _read_one(redis_client, bus)

    await bus._process_entry(Processor(), entry_id, fields)

    assert await _pending_count(redis_client, bus) == 0
    assert [event.message_id for event in processed] == ["wamid-redis-1"]


@pytest.mark.asyncio
async def test_exhausted_retries_are_sent_to_dlq(redis_client) -> None:
    class FailingProcessor:
        async def execute(self, event: IncomingMessage) -> None:
            raise RuntimeError("calendar unavailable")

    bus = RedisStreamEventBus(
        redis_client,
        consumer="worker-failing",
        max_retries=1,
        retry_base_delay=0,
        claim_idle_ms=1,
    )
    await bus.publish(message("wamid-failing"))
    await bus._ensure_group()

    first_id, first_fields = await _read_one(redis_client, bus)
    await bus._process_entry(FailingProcessor(), first_id, first_fields)
    retry_id, retry_fields = await _read_one(redis_client, bus)
    await bus._process_entry(FailingProcessor(), retry_id, retry_fields)

    entries = await redis_client.xrange(bus.dlq_stream)
    assert entries[0][1]["attempts"] == "2"
    assert "calendar unavailable" in entries[0][1]["error"]


@pytest.mark.asyncio
async def test_new_worker_recovers_abandoned_pending_event(redis_client) -> None:
    processed: list[str] = []

    class Processor:
        async def execute(self, event: IncomingMessage) -> None:
            processed.append(event.message_id)

    crashed = RedisStreamEventBus(redis_client, consumer="crashed-worker")
    await crashed.publish(message("wamid-abandoned"))
    await crashed._ensure_group()
    await _read_one(redis_client, crashed)  # Delivered but intentionally not acknowledged.
    assert await _pending_count(redis_client, crashed) == 1

    replacement = RedisStreamEventBus(
        redis_client, consumer="replacement-worker", claim_idle_ms=0
    )
    await replacement._recover_pending(Processor())

    assert processed == ["wamid-abandoned"]
    assert await _pending_count(redis_client, replacement) == 0


async def _pending_count(client, bus: RedisStreamEventBus) -> int:
    summary = await client.xpending(bus.stream, bus.group)
    return summary["pending"]


async def _read_one(client, bus: RedisStreamEventBus):
    batches = await client.xreadgroup(
        bus.group, bus.consumer, {bus.stream: ">"}, count=1
    )
    return batches[0][1][0]
