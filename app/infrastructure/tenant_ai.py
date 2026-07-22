from __future__ import annotations

from dataclasses import replace

from app.domain.models import Intent, IntentResult, Tenant
from app.domain.ports import AIConfigurationRepository, IntentClassifier
from app.infrastructure.openai_adapter import OpenAIIntentClassifier
from app.infrastructure.secrets import SecretCipher


class TenantConfiguredIntentClassifier:
    def __init__(
        self,
        configurations: AIConfigurationRepository,
        cipher: SecretCipher,
        fallback: IntentClassifier,
        global_api_key: str | None,
        global_model: str,
        prompt_version: str,
        minimum_confidence: float,
    ) -> None:
        self._configurations = configurations
        self._cipher = cipher
        self._fallback = fallback
        self._global_api_key = global_api_key
        self._global_model = global_model
        self._prompt_version = prompt_version
        self._minimum_confidence = minimum_confidence

    async def classify(
        self, message: str, tenant: Tenant, customer_phone: str | None = None
    ) -> IntentResult:
        configuration = await self._configurations.get(tenant.id)
        api_key = self._global_api_key
        model = self._global_model
        if configuration is not None:
            model = configuration.model
            if configuration.encrypted_api_key:
                api_key = self._cipher.decrypt(configuration.encrypted_api_key)
        if not api_key:
            return await self._fallback.classify(message, tenant, customer_phone)

        classifier = OpenAIIntentClassifier(
            api_key=api_key, model=model, prompt_version=self._prompt_version
        )
        try:
            result = await classifier.classify(message, tenant, customer_phone)
        except Exception:
            local = await self._fallback.classify(message, tenant, customer_phone)
            return replace(local, source="rules_fallback", fallback_used=True)
        finally:
            await classifier.close()
        if result.requires_human or result.confidence < self._minimum_confidence:
            return replace(result, intent=Intent.HUMAN_HANDOFF, requires_human=True)
        return result
