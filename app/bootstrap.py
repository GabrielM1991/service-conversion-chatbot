from dataclasses import dataclass

from app.application.pipeline import (
    DeduplicationHandler,
    MessagePipeline,
    OptOutHandler,
    SanitizationHandler,
)
from app.application.services import ChatbotAgentFactory, ProcessIncomingMessage
from app.application.strategies import (
    BookAppointmentStrategy,
    FaqResponseStrategy,
    ProcessPaymentStrategy,
    UnknownIntentStrategy,
)
from app.domain.models import Tenant
from app.domain.ports import TenantRepository
from app.infrastructure.adapters import (
    ConsoleChatGateway,
    FakeCalendarGateway,
    FakePaymentGateway,
    InMemoryDeduplicationStore,
    InMemoryOptOutStore,
    InMemoryTenantRepository,
    KeywordIntentClassifier,
)
from app.infrastructure.event_bus import InMemoryEventBus


@dataclass(slots=True)
class Container:
    event_bus: InMemoryEventBus
    processor: ProcessIncomingMessage
    chat: ConsoleChatGateway
    tenants: TenantRepository


def build_container() -> Container:
    tenants = InMemoryTenantRepository(
        [
            Tenant(
                id="ClinicaDental_01",
                name="Clínica Dental Sonrisa",
                tone="cercano y profesional",
                services={"limpieza dental": 45, "ortodoncia": 60},
                knowledge={"precio": "La limpieza dental cuesta desde 50 USD."},
            ),
            Tenant(
                id="Reformas_01",
                name="Reformas Horizonte",
                tone="directo y resolutivo",
                services={"visita técnica": 60},
                knowledge={"zona": "Trabajamos en toda el área metropolitana."},
            ),
        ]
    )
    dedupe = InMemoryDeduplicationStore()
    opt_out = InMemoryOptOutStore()
    chat = ConsoleChatGateway()
    calendar = FakeCalendarGateway()
    payments = FakePaymentGateway()
    classifier = KeywordIntentClassifier()
    fallback = UnknownIntentStrategy()
    factory = ChatbotAgentFactory(
        tenants,
        classifier,
        [
            BookAppointmentStrategy(calendar),
            FaqResponseStrategy(),
            ProcessPaymentStrategy(payments),
        ],
        fallback,
        chat,
    )
    pipeline = MessagePipeline(
        [SanitizationHandler(), DeduplicationHandler(dedupe), OptOutHandler(opt_out)]
    )
    return Container(InMemoryEventBus(), ProcessIncomingMessage(pipeline, factory), chat, tenants)
