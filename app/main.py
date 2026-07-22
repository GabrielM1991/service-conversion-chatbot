from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.bootstrap import build_container
from app.domain.models import IncomingMessage
from app.infrastructure.logging import configure_logging

configure_logging()
logger = logging.getLogger("chatbot")
container = build_container()


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = (
        asyncio.create_task(container.event_bus.consume_forever(container.processor))
        if container.embedded_worker
        else None
    )
    app.state.container = container
    try:
        yield
    finally:
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        await container.close()


app = FastAPI(
    title="Service Conversion Chatbot",
    version="0.4.1",
    description="Webhook multi-tenant con procesamiento asíncrono y arquitectura hexagonal.",
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


class WhatsAppWebhook(BaseModel):
    message_id: str = Field(min_length=1)
    from_phone: str = Field(min_length=5)
    text: str = Field(min_length=1, max_length=4096)


class DemoTenant(BaseModel):
    id: str
    name: str
    tone: str


class DemoMessage(BaseModel):
    id: str
    direction: str
    text: str
    created_at: datetime
    intent: str | None = None
    confidence: float | None = None
    ai_source: str | None = None
    requires_human: bool = False


def require_demo_mode(request: Request) -> None:
    if request.app.state.container.app_env != "development":
        raise HTTPException(status_code=404, detail="Demo no disponible")


@app.get("/", include_in_schema=False)
@app.get("/demo", include_in_schema=False)
async def demo_page(request: Request) -> FileResponse:
    require_demo_mode(request)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/demo/tenants", response_model=list[DemoTenant], include_in_schema=False)
async def demo_tenants(request: Request) -> list[DemoTenant]:
    require_demo_mode(request)
    tenants = await request.app.state.container.tenants.list_active()
    return [DemoTenant(id=tenant.id, name=tenant.name, tone=tenant.tone) for tenant in tenants]


@app.get("/demo/messages", response_model=list[DemoMessage], include_in_schema=False)
async def demo_messages(
    request: Request,
    phone: str = Query(min_length=5, max_length=32),
    x_tenant_id: str | None = Header(default=None),
) -> list[DemoMessage]:
    require_demo_mode(request)
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Falta el header X-Tenant-ID")
    tenant = await request.app.state.container.tenants.get(x_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    entries = await request.app.state.container.conversations.list_recent(
        x_tenant_id, phone, limit=80
    )
    return [
        DemoMessage(
            id=entry.id,
            direction=entry.direction,
            text=entry.text,
            created_at=entry.created_at,
            intent=entry.intent,
            confidence=entry.confidence,
            ai_source=entry.ai_source,
            requires_human=entry.requires_human,
        )
        for entry in entries
    ]


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    runtime = request.app.state.container
    return {
        "status": "ok",
        "storage": runtime.storage_mode,
        "broker": runtime.broker_mode,
        "ai": runtime.ai_mode,
    }


@app.get("/ready")
async def ready(request: Request) -> dict[str, str]:
    runtime = request.app.state.container
    try:
        if runtime.database_engine is not None:
            async with runtime.database_engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        if runtime.redis_client is not None:
            await runtime.redis_client.ping()
    except Exception as error:
        logger.exception(
            "Dependencia no disponible durante readiness",
            extra={"component": "Readiness", "tenant": "-"},
        )
        raise HTTPException(status_code=503, detail="Dependencia no disponible") from error
    return {"status": "ready"}


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
    if not runtime.embedded_worker:
        is_new = await runtime.deduplication.mark_if_new(x_tenant_id, payload.message_id)
        if not is_new:
            logger.info(
                "Webhook duplicado aceptado sin reencolar: %s",
                payload.message_id,
                extra={"component": "RedisDeduplication", "tenant": x_tenant_id},
            )
            return {"status": "accepted", "message_id": payload.message_id}
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
