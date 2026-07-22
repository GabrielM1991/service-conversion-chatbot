from __future__ import annotations

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.domain.models import (
    AIConfiguration,
    ConversationEntry,
    IncomingMessage,
    IntentResult,
    KnowledgeSource,
    OutgoingMessage,
    Tenant,
)
from app.infrastructure.database import tenant_session
from app.infrastructure.orm import (
    ConversationRow,
    ConversationStatus,
    CustomerRow,
    MessageRow,
    KnowledgeSourceRow,
    ServiceRow,
    TenantRow,
    TenantAIConfigurationRow,
)


class SqlAlchemyTenantRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, tenant_id: str) -> Tenant | None:
        async with tenant_session(self._session_factory, tenant_id) as session:
            statement = (
                select(TenantRow)
                .where(TenantRow.id == tenant_id, TenantRow.active.is_(True))
                .options(selectinload(TenantRow.services))
            )
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None:
                return None
            services = {
                service.name: service.duration_minutes
                for service in row.services
                if service.active
            }
            sources = list(
                await session.scalars(
                    select(KnowledgeSourceRow)
                    .where(
                        KnowledgeSourceRow.tenant_id == tenant_id,
                        KnowledgeSourceRow.status == "ready",
                        KnowledgeSourceRow.extracted_text != "",
                    )
                    .order_by(KnowledgeSourceRow.created_at.desc())
                    .limit(20)
                )
            )
            knowledge = dict(row.knowledge)
            remaining = 12_000
            for source in sources:
                excerpt = source.extracted_text[:remaining]
                if not excerpt:
                    break
                knowledge[source.title] = excerpt
                remaining -= len(excerpt)
            return Tenant(
                row.id,
                row.name,
                row.tone,
                services,
                knowledge,
                row.bot_name,
                row.welcome_message,
                row.system_instructions,
            )

    async def list_active(self) -> list[Tenant]:
        async with self._session_factory() as session:
            statement = (
                select(TenantRow)
                .where(TenantRow.active.is_(True))
                .options(selectinload(TenantRow.services))
                .order_by(TenantRow.name)
            )
            rows = list((await session.scalars(statement)).all())
            return [
                Tenant(
                    row.id,
                    row.name,
                    row.tone,
                    {
                        service.name: service.duration_minutes
                        for service in row.services
                        if service.active
                    },
                    dict(row.knowledge),
                    row.bot_name,
                    row.welcome_message,
                    row.system_instructions,
                )
                for row in rows
            ]

    async def update_profile(self, tenant: Tenant) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(TenantRow, tenant.id)
            if row is None:
                raise LookupError(f"Tenant no encontrado: {tenant.id}")
            row.name = tenant.name
            row.tone = tenant.tone
            row.bot_name = tenant.bot_name
            row.welcome_message = tenant.welcome_message
            row.system_instructions = tenant.system_instructions


class SqlAlchemyAIConfigurationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, tenant_id: str) -> AIConfiguration | None:
        async with tenant_session(self._session_factory, tenant_id) as session:
            row = await session.get(TenantAIConfigurationRow, tenant_id)
            if row is None:
                return None
            return AIConfiguration(
                row.tenant_id, row.provider, row.model, row.encrypted_api_key, row.key_last_four
            )

    async def save(self, configuration: AIConfiguration) -> None:
        async with tenant_session(self._session_factory, configuration.tenant_id) as session:
            row = await session.get(TenantAIConfigurationRow, configuration.tenant_id)
            if row is None:
                row = TenantAIConfigurationRow(tenant_id=configuration.tenant_id)
                session.add(row)
            row.provider = configuration.provider
            row.model = configuration.model
            row.encrypted_api_key = configuration.encrypted_api_key
            row.key_last_four = configuration.key_last_four


class SqlAlchemyKnowledgeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list(self, tenant_id: str) -> list[KnowledgeSource]:
        async with tenant_session(self._session_factory, tenant_id) as session:
            rows = list(
                await session.scalars(
                    select(KnowledgeSourceRow)
                    .where(KnowledgeSourceRow.tenant_id == tenant_id)
                    .order_by(KnowledgeSourceRow.created_at.desc())
                )
            )
            return [_knowledge_from_row(row) for row in rows]

    async def add(self, source: KnowledgeSource) -> None:
        async with tenant_session(self._session_factory, source.tenant_id) as session:
            session.add(
                KnowledgeSourceRow(
                    id=uuid.UUID(source.id), tenant_id=source.tenant_id, title=source.title,
                    kind=source.kind, status=source.status, filename=source.filename,
                    content_type=source.content_type, size_bytes=source.size_bytes,
                    storage_key=source.storage_key, extracted_text=source.extracted_text,
                )
            )

    async def get(self, tenant_id: str, source_id: str) -> KnowledgeSource | None:
        try:
            parsed_id = uuid.UUID(source_id)
        except ValueError:
            return None
        async with tenant_session(self._session_factory, tenant_id) as session:
            row = await session.get(KnowledgeSourceRow, parsed_id)
            return _knowledge_from_row(row) if row and row.tenant_id == tenant_id else None

    async def delete(self, tenant_id: str, source_id: str) -> KnowledgeSource | None:
        try:
            parsed_id = uuid.UUID(source_id)
        except ValueError:
            return None
        async with tenant_session(self._session_factory, tenant_id) as session:
            row = await session.get(KnowledgeSourceRow, parsed_id)
            if row is None or row.tenant_id != tenant_id:
                return None
            source = _knowledge_from_row(row)
            await session.delete(row)
            return source


def _knowledge_from_row(row: KnowledgeSourceRow) -> KnowledgeSource:
    return KnowledgeSource(
        str(row.id), row.tenant_id, row.title, row.kind, row.status, row.created_at,
        row.filename, row.content_type, row.size_bytes, row.storage_key, row.extracted_text,
    )


class SqlAlchemyServiceRepository:
    """Small explicit repository used by integration tests and future admin use cases."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_names(self, tenant_id: str) -> list[str]:
        async with tenant_session(self._session_factory, tenant_id) as session:
            result = await session.scalars(
                select(ServiceRow.name)
                .where(ServiceRow.tenant_id == tenant_id, ServiceRow.active.is_(True))
                .order_by(ServiceRow.name)
            )
            return list(result)


class SqlAlchemyConversationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_incoming(self, message: IncomingMessage) -> None:
        async with tenant_session(self._session_factory, message.tenant_id) as session:
            conversation = await self._get_or_create_conversation(
                session, message.tenant_id, message.customer_phone
            )
            duplicate = await session.scalar(
                select(MessageRow.id).where(
                    MessageRow.tenant_id == message.tenant_id,
                    MessageRow.provider_message_id == message.message_id,
                )
            )
            if duplicate is None:
                session.add(
                    MessageRow(
                        id=uuid.uuid4(),
                        tenant_id=message.tenant_id,
                        conversation_id=conversation.id,
                        provider_message_id=message.message_id,
                        direction="inbound",
                        body=message.text,
                    )
                )

    async def record_outgoing(
        self, incoming: IncomingMessage, outgoing: OutgoingMessage, intent: IntentResult
    ) -> None:
        async with tenant_session(self._session_factory, incoming.tenant_id) as session:
            conversation = await self._get_or_create_conversation(
                session, incoming.tenant_id, incoming.customer_phone
            )
            session.add(
                MessageRow(
                    id=uuid.uuid4(),
                    tenant_id=incoming.tenant_id,
                    conversation_id=conversation.id,
                    provider_message_id=f"out:{uuid.uuid4()}",
                    direction="outbound",
                    body=outgoing.text,
                    intent=intent.intent.value,
                    intent_confidence=intent.confidence,
                    requires_human=intent.requires_human,
                    ai_source=intent.source,
                    ai_model=intent.model,
                    prompt_version=intent.prompt_version,
                    input_tokens=intent.input_tokens,
                    output_tokens=intent.output_tokens,
                    ai_latency_ms=intent.latency_ms,
                    fallback_used=intent.fallback_used,
                )
            )

    async def list_recent(
        self, tenant_id: str, phone: str, limit: int = 50
    ) -> list[ConversationEntry]:
        async with tenant_session(self._session_factory, tenant_id) as session:
            statement = (
                select(MessageRow)
                .join(
                    ConversationRow,
                    and_(
                        ConversationRow.tenant_id == MessageRow.tenant_id,
                        ConversationRow.id == MessageRow.conversation_id,
                    ),
                )
                .join(
                    CustomerRow,
                    and_(
                        CustomerRow.tenant_id == ConversationRow.tenant_id,
                        CustomerRow.id == ConversationRow.customer_id,
                    ),
                )
                .where(
                    MessageRow.tenant_id == tenant_id,
                    CustomerRow.phone == phone,
                )
                .order_by(MessageRow.created_at.desc())
                .limit(limit)
            )
            rows = list((await session.scalars(statement)).all())
            return [
                ConversationEntry(
                    id=row.provider_message_id,
                    direction=row.direction,
                    text=row.body,
                    created_at=row.created_at,
                    intent=row.intent,
                    confidence=row.intent_confidence,
                    ai_source=row.ai_source,
                    requires_human=bool(row.requires_human),
                )
                for row in reversed(rows)
            ]

    async def _get_or_create_conversation(
        self, session: AsyncSession, tenant_id: str, phone: str
    ) -> ConversationRow:
        customer = await session.scalar(
            select(CustomerRow).where(
                CustomerRow.tenant_id == tenant_id, CustomerRow.phone == phone
            )
        )
        if customer is None:
            customer = CustomerRow(id=uuid.uuid4(), tenant_id=tenant_id, phone=phone)
            session.add(customer)
            await session.flush()

        conversation = await session.scalar(
            select(ConversationRow)
            .where(
                ConversationRow.tenant_id == tenant_id,
                ConversationRow.customer_id == customer.id,
                ConversationRow.status == ConversationStatus.OPEN,
            )
            .order_by(ConversationRow.created_at.desc())
            .limit(1)
        )
        if conversation is None:
            conversation = ConversationRow(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                customer_id=customer.id,
                status=ConversationStatus.OPEN,
            )
            session.add(conversation)
            await session.flush()
        return conversation
