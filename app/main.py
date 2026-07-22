from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.bootstrap import build_container
from app.domain.models import AIConfiguration, AuthenticatedUser, IncomingMessage, KnowledgeSource
from app.infrastructure.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    hash_session_token,
    new_csrf_token,
    new_session_token,
    session_expiration,
)
from app.infrastructure.knowledge import extract_pdf_text, verify_image
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
    version="0.6.0",
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


class AdminSettingsUpdate(BaseModel):
    business_name: str = Field(min_length=2, max_length=160)
    bot_name: str = Field(min_length=2, max_length=120)
    tone: str = Field(min_length=2, max_length=160)
    welcome_message: str = Field(min_length=2, max_length=1000)
    system_instructions: str = Field(default="", max_length=8000)
    provider: str = Field(default="openai", pattern="^openai$")
    model: str = Field(min_length=2, max_length=100)
    api_key: str | None = Field(default=None, min_length=8, max_length=500)


class KnowledgeTextCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    text: str = Field(min_length=3, max_length=100_000)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=256)


async def authenticated_user(request: Request) -> AuthenticatedUser | None:
    cached = getattr(request.state, "authenticated_user", None)
    if cached is not None:
        return cached
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user = await request.app.state.container.auth.get_session(
        hash_session_token(token), datetime.now(timezone.utc)
    )
    if user is not None:
        request.state.authenticated_user = user
    return user


async def require_authenticated_user(request: Request) -> AuthenticatedUser:
    user = await authenticated_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar")
    return user


async def require_tenant_access(
    request: Request, tenant_id: str, *, write: bool = False
) -> tuple[AuthenticatedUser, str]:
    user = await require_authenticated_user(request)
    membership = next(
        (item for item in user.memberships if item.tenant_id == tenant_id), None
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    if write and membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Tu rol es de solo lectura")
    return user, membership.role


def require_csrf(request: Request) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    if not cookie_token or not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="Token de seguridad inválido")


def require_demo_mode(request: Request) -> None:
    if request.app.state.container.app_env != "development":
        raise HTTPException(status_code=404, detail="Demo no disponible")


@app.get("/", include_in_schema=False)
@app.get("/demo", include_in_schema=False)
async def demo_page(request: Request) -> FileResponse:
    require_demo_mode(request)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
async def login_page(request: Request) -> Response:
    if await authenticated_user(request) is not None:
        return RedirectResponse("/admin", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@app.post("/auth/login", include_in_schema=False)
async def login(payload: LoginRequest, request: Request) -> JSONResponse:
    runtime = request.app.state.container
    user = await runtime.auth.get_user_by_email(payload.email.strip().casefold())
    valid_password = runtime.passwords.verify_or_dummy(
        user.password_hash if user else None, payload.password
    )
    if user is None or not valid_password:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    token = new_session_token()
    csrf_token = new_csrf_token()
    expires_at = session_expiration(runtime.session_ttl_hours)
    await runtime.auth.create_session(user.id, hash_session_token(token), expires_at)
    max_age = runtime.session_ttl_hours * 3600
    response = JSONResponse({"status": "authenticated"})
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=runtime.cookie_secure,
        samesite="lax", path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, max_age=max_age, httponly=False,
        secure=runtime.cookie_secure, samesite="strict", path="/",
    )
    return response


@app.get("/auth/me", include_in_schema=False)
async def auth_me(request: Request) -> dict[str, object]:
    user = await require_authenticated_user(request)
    return {
        "id": user.id,
        "email": user.email,
        "memberships": [
            {"tenant_id": membership.tenant_id, "role": membership.role}
            for membership in user.memberships
        ],
    }


@app.post("/auth/logout", include_in_schema=False)
async def logout(request: Request) -> JSONResponse:
    require_csrf(request)
    user = await require_authenticated_user(request)
    await request.app.state.container.auth.delete_session(user.session_id)
    response = JSONResponse({"status": "signed_out"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


@app.get("/admin", include_in_schema=False)
async def admin_page(request: Request) -> Response:
    if await authenticated_user(request) is None:
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/admin/api/tenants", include_in_schema=False)
async def admin_tenants(request: Request) -> list[dict[str, str]]:
    user = await require_authenticated_user(request)
    tenants = []
    for membership in user.memberships:
        tenant = await request.app.state.container.tenants.get(membership.tenant_id)
        if tenant is not None:
            tenants.append({"id": tenant.id, "name": tenant.name, "role": membership.role})
    return tenants


@app.get("/admin/api/tenants/{tenant_id}/settings", include_in_schema=False)
async def admin_settings(tenant_id: str, request: Request) -> dict[str, object]:
    _, role = await require_tenant_access(request, tenant_id)
    runtime = request.app.state.container
    tenant = await runtime.tenants.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    configuration = await runtime.ai_configurations.get(tenant_id)
    return {
        "tenant_id": tenant.id,
        "business_name": tenant.name,
        "bot_name": tenant.bot_name,
        "tone": tenant.tone,
        "welcome_message": tenant.welcome_message,
        "system_instructions": tenant.system_instructions,
        "provider": configuration.provider if configuration else "openai",
        "model": configuration.model if configuration else "gpt-5.6-sol",
        "api_key_configured": bool(configuration and configuration.encrypted_api_key),
        "api_key_hint": f"••••{configuration.key_last_four}" if configuration and configuration.key_last_four else None,
        "encryption_available": runtime.secret_cipher.available,
        "role": role,
    }


@app.put("/admin/api/tenants/{tenant_id}/settings", include_in_schema=False)
async def update_admin_settings(
    tenant_id: str, payload: AdminSettingsUpdate, request: Request
) -> dict[str, str]:
    require_csrf(request)
    await require_tenant_access(request, tenant_id, write=True)
    runtime = request.app.state.container
    tenant = await runtime.tenants.get(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    await runtime.tenants.update_profile(
        replace(
            tenant,
            name=payload.business_name,
            bot_name=payload.bot_name,
            tone=payload.tone,
            welcome_message=payload.welcome_message,
            system_instructions=payload.system_instructions,
        )
    )
    current = await runtime.ai_configurations.get(tenant_id)
    encrypted_key = current.encrypted_api_key if current else None
    key_last_four = current.key_last_four if current else None
    if payload.api_key:
        try:
            encrypted_key = runtime.secret_cipher.encrypt(payload.api_key)
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        key_last_four = payload.api_key[-4:]
    await runtime.ai_configurations.save(
        AIConfiguration(
            tenant_id=tenant_id,
            provider=payload.provider,
            model=payload.model,
            encrypted_api_key=encrypted_key,
            key_last_four=key_last_four,
        )
    )
    return {"status": "saved"}


def knowledge_payload(source: KnowledgeSource) -> dict[str, object]:
    return {
        "id": source.id,
        "title": source.title,
        "kind": source.kind,
        "status": source.status,
        "filename": source.filename,
        "content_type": source.content_type,
        "size_bytes": source.size_bytes,
        "characters": len(source.extracted_text),
        "created_at": source.created_at,
        "has_file": bool(source.storage_key),
    }


@app.get("/admin/api/tenants/{tenant_id}/knowledge", include_in_schema=False)
async def list_admin_knowledge(tenant_id: str, request: Request) -> list[dict[str, object]]:
    await require_tenant_access(request, tenant_id)
    if await request.app.state.container.tenants.get(tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    sources = await request.app.state.container.knowledge.list(tenant_id)
    return [knowledge_payload(source) for source in sources]


@app.post("/admin/api/tenants/{tenant_id}/knowledge/text", include_in_schema=False)
async def create_text_knowledge(
    tenant_id: str, payload: KnowledgeTextCreate, request: Request
) -> dict[str, object]:
    require_csrf(request)
    await require_tenant_access(request, tenant_id, write=True)
    if await request.app.state.container.tenants.get(tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    source = KnowledgeSource(
        id=str(uuid.uuid4()), tenant_id=tenant_id, title=payload.title,
        kind="text", status="ready", created_at=datetime.now(timezone.utc),
        size_bytes=len(payload.text.encode("utf-8")), extracted_text=payload.text,
    )
    await request.app.state.container.knowledge.add(source)
    return knowledge_payload(source)


@app.post("/admin/api/tenants/{tenant_id}/knowledge/file", include_in_schema=False)
async def upload_admin_knowledge(
    tenant_id: str,
    request: Request,
    title: str = Form(min_length=2, max_length=180),
    description: str = Form(default="", max_length=10_000),
    file: UploadFile = File(),
) -> dict[str, object]:
    require_csrf(request)
    await require_tenant_access(request, tenant_id, write=True)
    runtime = request.app.state.container
    if await runtime.tenants.get(tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    content = await file.read(runtime.max_upload_bytes + 1)
    if len(content) > runtime.max_upload_bytes:
        raise HTTPException(status_code=413, detail="El archivo supera el límite permitido")
    content_type = (file.content_type or "").lower()
    filename = file.filename or "archivo"
    try:
        if content_type == "application/pdf":
            kind = "pdf"
            extracted = extract_pdf_text(content)
            status_value = "ready" if extracted else "stored"
        elif content_type in {"image/jpeg", "image/png", "image/webp"}:
            kind = "image"
            verify_image(content)
            extracted = description.strip()
            status_value = "ready" if extracted else "stored"
        else:
            raise ValueError("Solo se admiten PDF, PNG, JPG y WEBP")
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    storage_key = runtime.file_store.save(tenant_id, filename, content)
    source = KnowledgeSource(
        id=str(uuid.uuid4()), tenant_id=tenant_id, title=title, kind=kind,
        status=status_value, created_at=datetime.now(timezone.utc), filename=filename,
        content_type=content_type, size_bytes=len(content), storage_key=storage_key,
        extracted_text=extracted,
    )
    try:
        await runtime.knowledge.add(source)
    except Exception:
        runtime.file_store.delete(storage_key)
        raise
    return knowledge_payload(source)


@app.get("/admin/api/tenants/{tenant_id}/knowledge/{source_id}/content", include_in_schema=False)
async def admin_knowledge_content(
    tenant_id: str, source_id: str, request: Request
) -> FileResponse:
    await require_tenant_access(request, tenant_id)
    source = await request.app.state.container.knowledge.get(tenant_id, source_id)
    if source is None or not source.storage_key:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(
        request.app.state.container.file_store.path(source.storage_key),
        media_type=source.content_type,
        filename=Path(source.filename).name if source.filename else None,
    )


@app.delete("/admin/api/tenants/{tenant_id}/knowledge/{source_id}", include_in_schema=False)
async def delete_admin_knowledge(
    tenant_id: str, source_id: str, request: Request
) -> dict[str, str]:
    require_csrf(request)
    await require_tenant_access(request, tenant_id, write=True)
    runtime = request.app.state.container
    source = await runtime.knowledge.delete(tenant_id, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    if source.storage_key:
        runtime.file_store.delete(source.storage_key)
    return {"status": "deleted"}


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
