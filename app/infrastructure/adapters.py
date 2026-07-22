from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.domain.models import Intent, IntentResult, OutgoingMessage, Tenant, TimeSlot

logger = logging.getLogger("chatbot")


class InMemoryTenantRepository:
    def __init__(self, tenants: list[Tenant]) -> None:
        self._tenants = {tenant.id: tenant for tenant in tenants}

    async def get(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)


class InMemoryDeduplicationStore:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    async def mark_if_new(self, tenant_id: str, message_id: str) -> bool:
        key = (tenant_id, message_id)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


class InMemoryOptOutStore:
    def __init__(self) -> None:
        self._phones: set[tuple[str, str]] = set()

    async def is_opted_out(self, tenant_id: str, phone: str) -> bool:
        return (tenant_id, phone) in self._phones

    async def opt_out(self, tenant_id: str, phone: str) -> None:
        self._phones.add((tenant_id, phone))


class KeywordIntentClassifier:
    """Deterministic local adapter; replace with an LLM without changing the domain."""

    async def classify(self, message: str, tenant: Tenant) -> IntentResult:
        normalized = message.lower()
        service = next((name for name in tenant.services if name in normalized), None)
        if any(word in normalized for word in ("cita", "agendar", "reservar", "horario")):
            return IntentResult(Intent.BOOK_APPOINTMENT, service, 0.96)
        if any(word in normalized for word in ("pagar", "pago", "seña", "confirmar")):
            return IntentResult(Intent.PROCESS_PAYMENT, service, 0.93)
        if any(word in normalized for word in ("precio", "cuánto", "dónde", "servicio")):
            return IntentResult(Intent.FAQ, service, 0.88)
        return IntentResult(Intent.UNKNOWN, service, 0.4)


class FakeCalendarGateway:
    async def find_slots(
        self, tenant_id: str, service: str, duration_minutes: int, from_date: datetime
    ) -> list[TimeSlot]:
        logger.info(
            "Buscando huecos para '%s' en los próximos 3 días...",
            service,
            extra={"component": "GoogleCalendarAPI", "tenant": tenant_id},
        )
        first = (from_date + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        second = (from_date + timedelta(days=2)).replace(hour=11, minute=30, second=0, microsecond=0)
        slots = [TimeSlot(first, duration_minutes), TimeSlot(second, duration_minutes)]
        logger.debug(
            "Huecos encontrados: %s",
            [slot.starts_at.isoformat() for slot in slots],
            extra={"component": "GoogleCalendarAPI", "tenant": tenant_id},
        )
        return slots


class FakePaymentGateway:
    async def create_payment_link(self, tenant_id: str, phone: str) -> str:
        return f"https://pay.example.test/{tenant_id}/{phone[-4:]}"


class ConsoleChatGateway:
    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []

    async def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)
        logger.info(
            'Respuesta enviada a %s: "%s". Estatus: 200 OK.',
            message.customer_phone,
            message.text,
            extra={"component": "WhatsAppAPI", "tenant": message.tenant_id},
        )

