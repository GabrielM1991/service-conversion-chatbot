from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

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
from app.config import Settings, load_settings
from app.domain.models import Tenant
from app.domain.ports import ConversationRepository, TenantRepository
from app.infrastructure.adapters import (
    ConsoleChatGateway,
    FakeCalendarGateway,
    FakePaymentGateway,
    InMemoryDeduplicationStore,
    InMemoryOptOutStore,
    InMemoryTenantRepository,
    KeywordIntentClassifier,
    NoOpConversationRepository,
)
from app.infrastructure.database import create_database_engine, create_session_factory
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyTenantRepository,
)


@dataclass(slots=True)
class Container:
    event_bus: InMemoryEventBus
    processor: ProcessIncomingMessage
    chat: ConsoleChatGateway
    tenants: TenantRepository
    conversations: ConversationRepository
    storage_mode: str
    database_engine: AsyncEngine | None = None

    async def close(self) -> None:
        if self.database_engine is not None:
            await self.database_engine.dispose()


def build_container(
    settings: Settings | None = None,
    conversations_override: ConversationRepository | None = None,
) -> Container:
    runtime_settings = settings or load_settings()
    engine: AsyncEngine | None = None
    if runtime_settings.database_url:
        engine = create_database_engine(runtime_settings.database_url)
        session_factory = create_session_factory(engine)
        tenants: TenantRepository = SqlAlchemyTenantRepository(session_factory)
        conversations = SqlAlchemyConversationRepository(session_factory)
        storage_mode = "postgresql"
    else:
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
        conversations = NoOpConversationRepository()
        storage_mode = "memory"
    if conversations_override is not None:
        conversations = conversations_override
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
        conversations,
    )
    pipeline = MessagePipeline(
        [SanitizationHandler(), DeduplicationHandler(dedupe), OptOutHandler(opt_out)]
    )
    return Container(
        InMemoryEventBus(),
        ProcessIncomingMessage(pipeline, factory, conversations),
        chat,
        tenants,
        conversations,
        storage_mode,
        engine,
    )
