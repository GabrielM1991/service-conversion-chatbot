from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.bootstrap import build_container
from app.domain.models import IncomingMessage
from app.infrastructure.logging import configure_logging

configure_logging()
logger = logging.getLogger("chatbot")
container = build_container()


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = asyncio.create_task(container.event_bus.consume_forever(container.processor))
    app.state.container = container
    try:
        yield
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await container.close()


app = FastAPI(
    title="Service Conversion Chatbot",
    version="0.2.0",
    description="Webhook multi-tenant con procesamiento asíncrono y arquitectura hexagonal.",
    lifespan=lifespan,
)


class WhatsAppWebhook(BaseModel):
    message_id: str = Field(min_length=1)
    from_phone: str = Field(min_length=5)
    text: str = Field(min_length=1, max_length=4096)


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "storage": request.app.state.container.storage_mode}


@app.post("/webhooks/whatsapp", status_code=status.HTTP_202_ACCEPTED)
async def whatsapp_webhook(
    payload: WhatsAppWebhook,
    request: Request,
    x_tenant_id: str | None = Header(default=None),
) -> dict[str, str]:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Falta el header X-Tenant-ID")
    runtime = request.app.state.container
    tenant = await runtime.tenants.get(x_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    message = IncomingMessage(
        message_id=payload.message_id,
        tenant_id=x_tenant_id,
        customer_phone=payload.from_phone,
        text=payload.text,
        received_at=datetime.now(timezone.utc),
    )
    logger.info(
        'Mensaje entrante de WhatsApp: "%s"',
        payload.text,
        extra={"component": "WhatsAppWebhook", "tenant": x_tenant_id},
    )
    await runtime.event_bus.publish(message)
    return {"status": "accepted", "message_id": payload.message_id}
