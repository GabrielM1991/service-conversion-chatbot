from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Intent(StrEnum):
    BOOK_APPOINTMENT = "agendar_cita"
    FAQ = "pregunta_frecuente"
    PROCESS_PAYMENT = "procesar_pago"
    HUMAN_HANDOFF = "derivar_humano"
    UNKNOWN = "desconocida"


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str
    name: str
    tone: str
    services: dict[str, int]
    knowledge: dict[str, str] = field(default_factory=dict)
    bot_name: str = "Asistente"
    welcome_message: str = "Hola, ¿cómo puedo ayudarte?"
    system_instructions: str = ""


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
    requires_human: bool = False
    source: str = "rules"
    model: str | None = None
    prompt_version: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    fallback_used: bool = False


@dataclass(frozen=True, slots=True)
class TimeSlot:
    starts_at: datetime
    duration_minutes: int


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    tenant_id: str
    customer_phone: str
    text: str


@dataclass(frozen=True, slots=True)
class ConversationEntry:
    id: str
    direction: str
    text: str
    created_at: datetime
    intent: str | None = None
    confidence: float | None = None
    ai_source: str | None = None
    requires_human: bool = False


@dataclass(frozen=True, slots=True)
class AIConfiguration:
    tenant_id: str
    provider: str = "openai"
    model: str = "gpt-5.6-sol"
    encrypted_api_key: str | None = None
    key_last_four: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    id: str
    tenant_id: str
    title: str
    kind: str
    status: str
    created_at: datetime
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int = 0
    storage_key: str | None = None
    extracted_text: str = ""
