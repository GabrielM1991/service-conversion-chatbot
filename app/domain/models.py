from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Intent(StrEnum):
    BOOK_APPOINTMENT = "agendar_cita"
    FAQ = "pregunta_frecuente"
    PROCESS_PAYMENT = "procesar_pago"
    UNKNOWN = "desconocida"


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    name: str
    tone: str
    services: dict[str, int]
    knowledge: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    message_id: str
    tenant_id: str
    customer_phone: str
    text: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class IntentResult:
    intent: Intent
    service: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class TimeSlot:
    starts_at: datetime
    duration_minutes: int


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    tenant_id: str
    customer_phone: str
    text: str

