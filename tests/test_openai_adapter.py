from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.models import Intent, Tenant
from app.infrastructure.adapters import KeywordIntentClassifier, ResilientIntentClassifier
from app.infrastructure.openai_adapter import IntentDecision, OpenAIIntentClassifier


TENANT = Tenant(
    id="ClinicaDental_01",
    name="Clínica Dental Sonrisa",
    tone="cercano y profesional",
    services={"limpieza dental": 45, "ortodoncia": 60},
    knowledge={"precio": "La limpieza cuesta desde 50 USD."},
)


class FakeResponses:
    def __init__(self, decision: IntentDecision) -> None:
        self.decision = decision
        self.kwargs = {}

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            output_parsed=self.decision,
            usage=SimpleNamespace(input_tokens=120, output_tokens=18),
        )


@pytest.mark.asyncio
async def test_openai_classifier_uses_dynamic_prompt_and_structured_output() -> None:
    responses = FakeResponses(
        IntentDecision(
            intent="agendar_cita",
            service="LIMPIEZA DENTAL",
            confidence=0.94,
        )
    )
    classifier = OpenAIIntentClassifier(
        api_key="test-key",
        client=SimpleNamespace(responses=responses),
        model="gpt-test",
        prompt_version="router-test-v2",
    )

    result = await classifier.classify(
        "Quiero reservar una limpieza", TENANT, "+584121234567"
    )

    assert result.intent is Intent.BOOK_APPOINTMENT
    assert result.service == "limpieza dental"
    assert result.source == "openai"
    assert result.model == "gpt-test"
    assert result.prompt_version == "router-test-v2"
    assert result.input_tokens == 120
    assert result.output_tokens == 18
    system_prompt = responses.kwargs["input"][0]["content"]
    assert TENANT.name in system_prompt
    assert "limpieza dental" in system_prompt
    assert responses.kwargs["store"] is False
    safety_id = responses.kwargs["safety_identifier"]
    assert len(safety_id) == 64
    assert "+584121234567" not in safety_id
    user_content = responses.kwargs["input"][1]["content"]
    assert user_content.endswith(
        "<mensaje_cliente>Quiero reservar una limpieza</mensaje_cliente>"
    )


@pytest.mark.asyncio
async def test_unknown_model_service_is_discarded() -> None:
    responses = FakeResponses(
        IntentDecision(intent="agendar_cita", service="servicio inventado", confidence=0.9)
    )
    classifier = OpenAIIntentClassifier(
        api_key="test-key", client=SimpleNamespace(responses=responses)
    )

    result = await classifier.classify("Necesito una cita", TENANT)

    assert result.service is None


@pytest.mark.asyncio
async def test_low_confidence_is_guarded_with_human_handoff() -> None:
    class LowConfidenceClassifier:
        async def classify(self, message, tenant, customer_phone=None):
            from app.domain.models import IntentResult

            return IntentResult(Intent.UNKNOWN, confidence=0.41, source="openai")

    classifier = ResilientIntentClassifier(
        LowConfidenceClassifier(), KeywordIntentClassifier(), minimum_confidence=0.72
    )

    result = await classifier.classify("No sé cómo explicarlo", TENANT)

    assert result.intent is Intent.HUMAN_HANDOFF
    assert result.requires_human is True


@pytest.mark.asyncio
async def test_provider_failure_uses_deterministic_fallback() -> None:
    class FailingClassifier:
        async def classify(self, message, tenant, customer_phone=None):
            raise TimeoutError("provider timeout")

    classifier = ResilientIntentClassifier(FailingClassifier(), KeywordIntentClassifier())

    result = await classifier.classify("Quiero una cita para ortodoncia", TENANT)

    assert result.intent is Intent.BOOK_APPOINTMENT
    assert result.service == "ortodoncia"
    assert result.source == "rules_fallback"
    assert result.fallback_used is True
