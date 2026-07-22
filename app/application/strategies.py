from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.domain.models import IncomingMessage, Intent, IntentResult, OutgoingMessage, Tenant
from app.domain.ports import CalendarGateway, PaymentGateway


class IntentStrategy(ABC):
    intent: Intent

    @abstractmethod
    async def execute(
        self, message: IncomingMessage, tenant: Tenant, result: IntentResult
    ) -> OutgoingMessage: ...


class BookAppointmentStrategy(IntentStrategy):
    intent = Intent.BOOK_APPOINTMENT

    def __init__(self, calendar: CalendarGateway) -> None:
        self._calendar = calendar

    async def execute(
        self, message: IncomingMessage, tenant: Tenant, result: IntentResult
    ) -> OutgoingMessage:
        service = result.service or next(iter(tenant.services))
        duration = tenant.services.get(service, 60)
        slots = await self._calendar.find_slots(
            tenant.id, service, duration, datetime.now(timezone.utc)
        )
        if not slots:
            text = "No encontré horarios disponibles. Un asesor te contactará muy pronto."
        else:
            options = " o ".join(slot.starts_at.strftime("%d-%b %H:%M") for slot in slots[:2])
            text = f"Tengo disponible {options}. ¿Cuál te va mejor?"
        return OutgoingMessage(tenant.id, message.customer_phone, text)


class FaqResponseStrategy(IntentStrategy):
    intent = Intent.FAQ

    async def execute(
        self, message: IncomingMessage, tenant: Tenant, result: IntentResult
    ) -> OutgoingMessage:
        answer = next(
            (value for key, value in tenant.knowledge.items() if key.lower() in message.text.lower()),
            "Puedo ayudarte con servicios, precios y disponibilidad. ¿Qué deseas consultar?",
        )
        return OutgoingMessage(tenant.id, message.customer_phone, answer)


class ProcessPaymentStrategy(IntentStrategy):
    intent = Intent.PROCESS_PAYMENT

    def __init__(self, payments: PaymentGateway) -> None:
        self._payments = payments

    async def execute(
        self, message: IncomingMessage, tenant: Tenant, result: IntentResult
    ) -> OutgoingMessage:
        link = await self._payments.create_payment_link(tenant.id, message.customer_phone)
        return OutgoingMessage(
            tenant.id, message.customer_phone, f"Puedes confirmar tu reserva aquí: {link}"
        )


class HumanHandoffStrategy(IntentStrategy):
    intent = Intent.HUMAN_HANDOFF

    async def execute(
        self, message: IncomingMessage, tenant: Tenant, result: IntentResult
    ) -> OutgoingMessage:
        return OutgoingMessage(
            tenant.id,
            message.customer_phone,
            "Quiero asegurarme de ayudarte correctamente. Un asesor humano continuará contigo pronto.",
        )


class UnknownIntentStrategy(IntentStrategy):
    intent = Intent.UNKNOWN

    async def execute(
        self, message: IncomingMessage, tenant: Tenant, result: IntentResult
    ) -> OutgoingMessage:
        if result.requires_human:
            return OutgoingMessage(
                tenant.id,
                message.customer_phone,
                "No tengo suficiente certeza para responderte bien. Un asesor humano continuará contigo pronto.",
            )
        return OutgoingMessage(
            tenant.id,
            message.customer_phone,
            f"Hola, soy {tenant.bot_name}, asistente de {tenant.name}. "
            "¿Buscas información o quieres agendar?",
        )
