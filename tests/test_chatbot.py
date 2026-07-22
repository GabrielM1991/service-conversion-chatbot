from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase

from app.application.pipeline import PipelineStatus
from app.bootstrap import build_container
from app.domain.models import IncomingMessage


def message(message_id: str, text: str, tenant: str = "ClinicaDental_01") -> IncomingMessage:
    return IncomingMessage(message_id, tenant, "+584121234567", text, datetime.now(timezone.utc))


class ChatbotTests(IsolatedAsyncioTestCase):
    async def test_booking_uses_tenant_service_and_returns_slots(self) -> None:
        container = build_container()

        result = await container.processor.execute(
            message("wamid-1", "Quiero una cita para limpieza dental")
        )

        self.assertIs(result, PipelineStatus.CONTINUE)
        self.assertEqual(len(container.chat.sent), 1)
        self.assertIn("disponible", container.chat.sent[0].text)
        self.assertEqual(container.chat.sent[0].tenant_id, "ClinicaDental_01")

    async def test_duplicate_message_is_not_sent_twice(self) -> None:
        container = build_container()
        incoming = message("wamid-duplicate", "Quiero agendar una cita")

        await container.processor.execute(incoming)
        result = await container.processor.execute(incoming)

        self.assertIs(result, PipelineStatus.DUPLICATE)
        self.assertEqual(len(container.chat.sent), 1)

    async def test_opt_out_blocks_future_messages(self) -> None:
        container = build_container()

        first = await container.processor.execute(message("wamid-stop", "STOP"))
        second = await container.processor.execute(message("wamid-after", "Quiero una cita"))

        self.assertIs(first, PipelineStatus.OPTED_OUT)
        self.assertIs(second, PipelineStatus.OPTED_OUT)
        self.assertEqual(container.chat.sent, [])

    async def test_unknown_tenant_is_isolated(self) -> None:
        container = build_container()

        with self.assertRaisesRegex(LookupError, "Tenant no encontrado"):
            await container.processor.execute(message("wamid-2", "Hola", "tenant-inexistente"))

    async def test_customer_can_request_a_human_advisor(self) -> None:
        container = build_container()

        await container.processor.execute(message("wamid-human", "Quiero hablar con una persona"))

        self.assertEqual(len(container.chat.sent), 1)
        self.assertIn("asesor humano", container.chat.sent[0].text)

    async def test_conversation_history_is_available_for_local_demo(self) -> None:
        container = build_container()

        await container.processor.execute(
            message("wamid-history", "Quiero una cita para limpieza dental")
        )
        history = await container.conversations.list_recent(
            "ClinicaDental_01", "+584121234567"
        )

        self.assertEqual([entry.direction for entry in history], ["inbound", "outbound"])
        self.assertEqual(history[0].id, "wamid-history")
        self.assertEqual(history[1].intent, "agendar_cita")
