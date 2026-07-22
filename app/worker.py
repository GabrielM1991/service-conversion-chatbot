from __future__ import annotations

import asyncio
import logging

from app.bootstrap import build_container
from app.infrastructure.logging import configure_logging


async def run_worker() -> None:
    configure_logging()
    logger = logging.getLogger("chatbot")
    container = build_container()
    if container.embedded_worker:
        raise RuntimeError("El worker durable requiere REDIS_URL")
    logger.info(
        "Iniciando worker de eventos",
        extra={"component": "MessageWorker", "tenant": "-"},
    )
    try:
        await container.event_bus.consume_forever(container.processor)
    finally:
        await container.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
