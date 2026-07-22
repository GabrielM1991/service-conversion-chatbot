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

    @property
    def uses_postgres(self) -> bool:
        return bool(self.database_url)

    @property
    def uses_redis(self) -> bool:
        return bool(self.redis_url)


def load_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL") or None,
        redis_url=os.getenv("REDIS_URL") or None,
        event_stream=os.getenv("EVENT_STREAM", "whatsapp_messages"),
        event_dlq_stream=os.getenv("EVENT_DLQ_STREAM", "whatsapp_messages_dlq"),
        consumer_group=os.getenv("CONSUMER_GROUP", "chatbot_workers"),
        consumer_name=os.getenv("CONSUMER_NAME", socket.gethostname()),
        max_event_retries=int(os.getenv("MAX_EVENT_RETRIES", "3")),
        deduplication_ttl_seconds=int(os.getenv("DEDUPLICATION_TTL_SECONDS", "86400")),
    )
