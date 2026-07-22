from __future__ import annotations

import logging

from app.application.pipeline import MessagePipeline, PipelineStatus
from app.application.strategies import IntentStrategy
from app.domain.models import IncomingMessage, Tenant
from app.domain.ports import ChatGateway, IntentClassifier, TenantRepository

logger = logging.getLogger("chatbot")


class ChatbotAgent:
    def __init__(
        self,
        tenant: Tenant,
        classifier: IntentClassifier,
        strategies: dict[str, IntentStrategy],
        fallback: IntentStrategy,
        chat: ChatGateway,
    ) -> None:
        self._tenant = tenant
        self._classifier = classifier
        self._strategies = strategies
        self._fallback = fallback
        self._chat = chat

    async def handle(self, message: IncomingMessage) -> None:
        result = await self._classifier.classify(message.text, self._tenant)
        logger.debug(
            "Intención detectada: '%s'. Servicio: '%s'.",
            result.intent,
            result.service,
            extra={"component": "IA_Agent", "tenant": self._tenant.id},
        )
        strategy = self._strategies.get(result.intent.value, self._fallback)
        outgoing = await strategy.execute(message, self._tenant, result)
        await self._chat.send(outgoing)


class ChatbotAgentFactory:
    def __init__(
        self,
        tenants: TenantRepository,
        classifier: IntentClassifier,
        strategies: list[IntentStrategy],
        fallback: IntentStrategy,
        chat: ChatGateway,
    ) -> None:
        self._tenants = tenants
        self._classifier = classifier
        self._strategies = {strategy.intent.value: strategy for strategy in strategies}
        self._fallback = fallback
        self._chat = chat

    async def create(self, tenant_id: str) -> ChatbotAgent:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise LookupError(f"Tenant no encontrado: {tenant_id}")
        return ChatbotAgent(
            tenant, self._classifier, self._strategies, self._fallback, self._chat
        )


class ProcessIncomingMessage:
    def __init__(self, pipeline: MessagePipeline, factory: ChatbotAgentFactory) -> None:
        self._pipeline = pipeline
        self._factory = factory

    async def execute(self, message: IncomingMessage) -> PipelineStatus:
        status, clean_message = await self._pipeline.execute(message)
        if status is not PipelineStatus.CONTINUE:
            logger.info(
                "Mensaje detenido por pipeline: %s",
                status,
                extra={"component": "MessagePipeline", "tenant": message.tenant_id},
            )
            return status
        agent = await self._factory.create(clean_message.tenant_id)
        await agent.handle(clean_message)
        return status

