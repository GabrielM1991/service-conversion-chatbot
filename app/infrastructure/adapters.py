from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from app.domain.models import IncomingMessage, Intent, IntentResult, OutgoingMessage, Tenant, TimeSlot
from app.domain.ports import IntentClassifier

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

    async def classify(
        self, message: str, tenant: Tenant, customer_phone: str | None = None
    ) -> IntentResult:
        normalized = message.lower()
        service = next((name for name in tenant.services if name in normalized), None)
        if any(
            phrase in normalized
            for phrase in ("persona", "humano", "asesor", "hablar con alguien", "reclamo")
        ):
            return IntentResult(Intent.HUMAN_HANDOFF, service, 0.99, requires_human=True)
        if any(word in normalized for word in ("cita", "agendar", "reservar", "horario")):
            return IntentResult(Intent.BOOK_APPOINTMENT, service, 0.96)
        if any(word in normalized for word in ("pagar", "pago", "seña", "confirmar")):
            return IntentResult(Intent.PROCESS_PAYMENT, service, 0.93)
        if any(word in normalized for word in ("precio", "cuánto", "dónde", "servicio")):
            return IntentResult(Intent.FAQ, service, 0.88)
        return IntentResult(Intent.UNKNOWN, service, 0.4)


class ResilientIntentClassifier:
    """Falls back to local rules and guards low-confidence model decisions."""

    def __init__(
        self,
        primary: IntentClassifier,
        fallback: IntentClassifier,
        minimum_confidence: float = 0.72,
    ) -> None:
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_confidence debe estar entre 0 y 1")
        self._primary = primary
        self._fallback = fallback
        self._minimum_confidence = minimum_confidence

    async def classify(
        self, message: str, tenant: Tenant, customer_phone: str | None = None
    ) -> IntentResult:
        try:
            result = await self._primary.classify(message, tenant, customer_phone)
        except Exception as error:
            logger.warning(
                "Clasificador LLM no disponible; se usa fallback local. Error=%s",
                type(error).__name__,
                extra={"component": "LLMFallback", "tenant": tenant.id},
            )
            local = await self._fallback.classify(message, tenant, customer_phone)
            return replace(local, source="rules_fallback", fallback_used=True)

        if result.requires_human or result.confidence < self._minimum_confidence:
            logger.info(
                "Guardrail de derivación activado. Confianza=%.2f SolicitudHumana=%s",
                result.confidence,
                result.requires_human,
                extra={"component": "LLMGuardrail", "tenant": tenant.id},
            )
            return replace(
                result,
                intent=Intent.HUMAN_HANDOFF,
                requires_human=True,
            )
        return result


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


class NoOpConversationRepository:
    async def record_incoming(self, message: IncomingMessage) -> None:
        return None

    async def record_outgoing(
        self, incoming: IncomingMessage, outgoing: OutgoingMessage, intent: IntentResult
    ) -> None:
        return None
