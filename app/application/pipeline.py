from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import Protocol

from app.domain.models import IncomingMessage
from app.domain.ports import DeduplicationStore, OptOutStore


class PipelineStatus(StrEnum):
    CONTINUE = "continue"
    DUPLICATE = "duplicate"
    OPTED_OUT = "opted_out"


class MessageHandler(Protocol):
    async def handle(self, message: IncomingMessage) -> tuple[PipelineStatus, IncomingMessage]: ...


class SanitizationHandler:
    async def handle(self, message: IncomingMessage) -> tuple[PipelineStatus, IncomingMessage]:
        clean_text = " ".join(message.text.strip().split())
        return PipelineStatus.CONTINUE, replace(message, text=clean_text)


class DeduplicationHandler:
    def __init__(self, store: DeduplicationStore) -> None:
        self._store = store

    async def handle(self, message: IncomingMessage) -> tuple[PipelineStatus, IncomingMessage]:
        is_new = await self._store.mark_if_new(message.tenant_id, message.message_id)
        status = PipelineStatus.CONTINUE if is_new else PipelineStatus.DUPLICATE
        return status, message


class OptOutHandler:
    COMMANDS = {"BAJA", "STOP", "CANCELAR"}

    def __init__(self, store: OptOutStore) -> None:
        self._store = store

    async def handle(self, message: IncomingMessage) -> tuple[PipelineStatus, IncomingMessage]:
        if message.text.upper() in self.COMMANDS:
            await self._store.opt_out(message.tenant_id, message.customer_phone)
            return PipelineStatus.OPTED_OUT, message
        if await self._store.is_opted_out(message.tenant_id, message.customer_phone):
            return PipelineStatus.OPTED_OUT, message
        return PipelineStatus.CONTINUE, message


class MessagePipeline:
    def __init__(self, handlers: list[MessageHandler]) -> None:
        self._handlers = handlers

    async def execute(self, message: IncomingMessage) -> tuple[PipelineStatus, IncomingMessage]:
        current = message
        for handler in self._handlers:
            status, current = await handler.handle(current)
            if status is not PipelineStatus.CONTINUE:
                return status, current
        return PipelineStatus.CONTINUE, current

