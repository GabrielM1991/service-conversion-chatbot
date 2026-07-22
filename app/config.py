from __future__ import annotations

import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str = "development"
    database_url: str | None = None
    redis_url: str | None = None
    event_stream: str = "whatsapp_messages"
    event_dlq_stream: str = "whatsapp_messages_dlq"
    consumer_group: str = "chatbot_workers"
    consumer_name: str = "local-worker"
    max_event_retries: int = 3
    deduplication_ttl_seconds: int = 86400
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-sol"
    openai_prompt_version: str = "intent-router-v1"
    llm_minimum_confidence: float = 0.72
    tenant_secret_key: str | None = None
    upload_dir: str = "/tmp/chatbot_uploads"
    max_upload_bytes: int = 10 * 1024 * 1024
    bootstrap_admin_email: str = "admin@serviceflow.local"
    bootstrap_admin_password: str = "ServiceFlow-local-2026!"
    session_ttl_hours: int = 12

    @property
    def uses_postgres(self) -> bool:
        return bool(self.database_url)

    @property
    def uses_redis(self) -> bool:
        return bool(self.redis_url)


def load_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development")
    default_email = "admin@serviceflow.local" if app_env == "development" else ""
    default_password = "ServiceFlow-local-2026!" if app_env == "development" else ""
    return Settings(
        app_env=app_env,
        database_url=os.getenv("DATABASE_URL") or None,
        redis_url=os.getenv("REDIS_URL") or None,
        event_stream=os.getenv("EVENT_STREAM", "whatsapp_messages"),
        event_dlq_stream=os.getenv("EVENT_DLQ_STREAM", "whatsapp_messages_dlq"),
        consumer_group=os.getenv("CONSUMER_GROUP", "chatbot_workers"),
        consumer_name=os.getenv("CONSUMER_NAME", socket.gethostname()),
        max_event_retries=int(os.getenv("MAX_EVENT_RETRIES", "3")),
        deduplication_ttl_seconds=int(os.getenv("DEDUPLICATION_TTL_SECONDS", "86400")),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-sol"),
        openai_prompt_version=os.getenv("OPENAI_PROMPT_VERSION", "intent-router-v1"),
        llm_minimum_confidence=float(os.getenv("LLM_MINIMUM_CONFIDENCE", "0.72")),
        tenant_secret_key=os.getenv("TENANT_SECRET_KEY") or None,
        upload_dir=os.getenv("UPLOAD_DIR", "/tmp/chatbot_uploads"),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        bootstrap_admin_email=os.getenv("BOOTSTRAP_ADMIN_EMAIL", default_email),
        bootstrap_admin_password=os.getenv("BOOTSTRAP_ADMIN_PASSWORD", default_password),
        session_ttl_hours=int(os.getenv("SESSION_TTL_HOURS", "12")),
    )
