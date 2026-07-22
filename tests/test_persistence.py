from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.application.pipeline import PipelineStatus
from app.bootstrap import build_container
from app.config import Settings
from app.domain.models import IncomingMessage, IntentResult, OutgoingMessage
from app.infrastructure.orm import Base
from app.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyTenantRepository,
)


class RecordingConversationRepository:
    def __init__(self) -> None:
        self.incoming: list[IncomingMessage] = []
        self.outgoing: list[tuple[IncomingMessage, OutgoingMessage, IntentResult]] = []

    async def record_incoming(self, message: IncomingMessage) -> None:
        self.incoming.append(message)

    async def record_outgoing(
        self, incoming: IncomingMessage, outgoing: OutgoingMessage, intent: IntentResult
    ) -> None:
        self.outgoing.append((incoming, outgoing, intent))


def incoming(message_id: str) -> IncomingMessage:
    return IncomingMessage(
        message_id,
        "ClinicaDental_01",
        "+584121234567",
        "Quiero una cita para limpieza dental",
        datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_only_accepted_messages_are_persisted() -> None:
    recorder = RecordingConversationRepository()
    container = build_container(conversations_override=recorder)
    message = incoming("wamid-persist-1")

    first = await container.processor.execute(message)
    duplicate = await container.processor.execute(message)

    assert first is PipelineStatus.CONTINUE
    assert duplicate is PipelineStatus.DUPLICATE
    assert len(recorder.incoming) == 1
    assert len(recorder.outgoing) == 1
    assert recorder.outgoing[0][2].intent.value == "agendar_cita"


def test_schema_has_all_tenant_aggregate_tables() -> None:
    assert set(Base.metadata.tables) == {
        "tenants",
        "services",
        "customers",
        "conversations",
        "messages",
        "appointments",
    }
    for table_name in ("services", "customers", "conversations", "messages", "appointments"):
        assert "tenant_id" in Base.metadata.tables[table_name].columns


def test_cross_tenant_links_and_provider_ids_have_composite_guards() -> None:
    messages = Base.metadata.tables["messages"]
    unique_names = {
        constraint.name
        for constraint in messages.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_names = {
        constraint.name
        for constraint in messages.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "uq_messages_provider_id" in unique_names
    assert "ck_messages_direction" in check_names


@pytest.mark.asyncio
async def test_postgres_configuration_selects_sqlalchemy_adapters_without_connecting() -> None:
    container = build_container(
        Settings(database_url="postgresql+asyncpg://user:pass@localhost:5432/chatbot")
    )
    try:
        assert container.storage_mode == "postgresql"
        assert isinstance(container.tenants, SqlAlchemyTenantRepository)
        assert isinstance(container.conversations, SqlAlchemyConversationRepository)
    finally:
        await container.close()
