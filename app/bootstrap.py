from dataclasses import dataclass

from redis.asyncio import Redis
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
    HumanHandoffStrategy,
    ProcessPaymentStrategy,
    UnknownIntentStrategy,
)
from app.config import Settings, load_settings
from app.domain.models import Tenant
from app.domain.ports import (
    AIConfigurationRepository,
    ConversationRepository,
    DeduplicationStore,
    KnowledgeRepository,
    TenantRepository,
)
from app.infrastructure.adapters import (
    ConsoleChatGateway,
    FakeCalendarGateway,
    FakePaymentGateway,
    InMemoryDeduplicationStore,
    InMemoryConversationRepository,
    InMemoryAIConfigurationRepository,
    InMemoryKnowledgeRepository,
    InMemoryOptOutStore,
    InMemoryTenantRepository,
    KeywordIntentClassifier,
)
from app.infrastructure.database import create_database_engine, create_session_factory
from app.infrastructure.event_bus import InMemoryEventBus, MessageEventBus, RedisStreamEventBus
from app.infrastructure.knowledge import KnowledgeFileStore
from app.infrastructure.redis_adapters import RedisDeduplicationStore, RedisOptOutStore
from app.infrastructure.repositories import (
    SqlAlchemyAIConfigurationRepository,
    SqlAlchemyConversationRepository,
    SqlAlchemyKnowledgeRepository,
    SqlAlchemyTenantRepository,
)
from app.infrastructure.secrets import SecretCipher
from app.infrastructure.tenant_ai import TenantConfiguredIntentClassifier


@dataclass(slots=True)
class Container:
    event_bus: MessageEventBus
    processor: ProcessIncomingMessage
    chat: ConsoleChatGateway
    tenants: TenantRepository
    conversations: ConversationRepository
    ai_configurations: AIConfigurationRepository
    knowledge: KnowledgeRepository
    secret_cipher: SecretCipher
    file_store: KnowledgeFileStore
    deduplication: DeduplicationStore
    storage_mode: str
    broker_mode: str
    ai_mode: str
    app_env: str
    embedded_worker: bool
    max_upload_bytes: int
    database_engine: AsyncEngine | None = None
    redis_client: Redis | None = None

    async def close(self) -> None:
        if self.database_engine is not None:
            await self.database_engine.dispose()
        if self.redis_client is not None:
            await self.redis_client.aclose()


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
        ai_configurations: AIConfigurationRepository = SqlAlchemyAIConfigurationRepository(
            session_factory
        )
        knowledge: KnowledgeRepository = SqlAlchemyKnowledgeRepository(session_factory)
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
        conversations = InMemoryConversationRepository()
        ai_configurations = InMemoryAIConfigurationRepository()
        knowledge = InMemoryKnowledgeRepository()
        storage_mode = "memory"
    if conversations_override is not None:
        conversations = conversations_override
    redis_client: Redis | None = None
    if runtime_settings.redis_url:
        redis_client = Redis.from_url(runtime_settings.redis_url, decode_responses=True)
        dedupe: DeduplicationStore = RedisDeduplicationStore(
            redis_client, runtime_settings.deduplication_ttl_seconds
        )
        opt_out = RedisOptOutStore(redis_client)
        event_bus: MessageEventBus = RedisStreamEventBus(
            redis_client,
            stream=runtime_settings.event_stream,
            dlq_stream=runtime_settings.event_dlq_stream,
            group=runtime_settings.consumer_group,
            consumer=runtime_settings.consumer_name,
            max_retries=runtime_settings.max_event_retries,
        )
        broker_mode = "redis-streams"
        embedded_worker = False
        pipeline_handlers = [SanitizationHandler(), OptOutHandler(opt_out)]
    else:
        dedupe = InMemoryDeduplicationStore()
        opt_out = InMemoryOptOutStore()
        event_bus = InMemoryEventBus()
        broker_mode = "memory"
        embedded_worker = True
        pipeline_handlers = [
            SanitizationHandler(),
            DeduplicationHandler(dedupe),
            OptOutHandler(opt_out),
        ]
    chat = ConsoleChatGateway()
    calendar = FakeCalendarGateway()
    payments = FakePaymentGateway()
    local_classifier = KeywordIntentClassifier()
    cipher = SecretCipher(runtime_settings.tenant_secret_key)
    file_store = KnowledgeFileStore(runtime_settings.upload_dir)
    classifier = TenantConfiguredIntentClassifier(
        ai_configurations,
        cipher,
        local_classifier,
        runtime_settings.openai_api_key,
        runtime_settings.openai_model,
        runtime_settings.openai_prompt_version,
        runtime_settings.llm_minimum_confidence,
    )
    ai_mode = "tenant-configurable"
    fallback = UnknownIntentStrategy()
    factory = ChatbotAgentFactory(
        tenants,
        classifier,
        [
            BookAppointmentStrategy(calendar),
            FaqResponseStrategy(),
            ProcessPaymentStrategy(payments),
            HumanHandoffStrategy(),
        ],
        fallback,
        chat,
        conversations,
    )
    pipeline = MessagePipeline(pipeline_handlers)
    return Container(
        event_bus,
        ProcessIncomingMessage(pipeline, factory, conversations),
        chat,
        tenants,
        conversations,
        ai_configurations,
        knowledge,
        cipher,
        file_store,
        dedupe,
        storage_mode,
        broker_mode,
        ai_mode,
        runtime_settings.app_env,
        embedded_worker,
        runtime_settings.max_upload_bytes,
        engine,
        redis_client,
    )
