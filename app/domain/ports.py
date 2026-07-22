from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.models import IncomingMessage, IntentResult, OutgoingMessage, Tenant, TimeSlot


class TenantRepository(Protocol):
    async def get(self, tenant_id: str) -> Tenant | None: ...


class DeduplicationStore(Protocol):
    async def mark_if_new(self, tenant_id: str, message_id: str) -> bool: ...


class OptOutStore(Protocol):
    async def is_opted_out(self, tenant_id: str, phone: str) -> bool: ...

    async def opt_out(self, tenant_id: str, phone: str) -> None: ...


class IntentClassifier(Protocol):
    async def classify(self, message: str, tenant: Tenant) -> IntentResult: ...


class CalendarGateway(Protocol):
    async def find_slots(
        self, tenant_id: str, service: str, duration_minutes: int, from_date: datetime
    ) -> list[TimeSlot]: ...


class PaymentGateway(Protocol):
    async def create_payment_link(self, tenant_id: str, phone: str) -> str: ...


class ChatGateway(Protocol):
    async def send(self, message: OutgoingMessage) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, event: IncomingMessage) -> None: ...

