from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.domain.models import IncomingMessage, IntentResult, OutgoingMessage, Tenant
from app.infrastructure.database import tenant_session
from app.infrastructure.orm import (
    ConversationRow,
    ConversationStatus,
    CustomerRow,
    MessageRow,
    ServiceRow,
    TenantRow,
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
            return Tenant(row.id, row.name, row.tone, services, dict(row.knowledge))


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
