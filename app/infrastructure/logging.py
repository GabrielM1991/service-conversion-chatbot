import logging
from datetime import datetime


class CorporateFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        tenant = getattr(record, "tenant", "-")
        component = getattr(record, "component", record.name)
        return f"[{timestamp}] [{record.levelname}] [Tenant: {tenant}] [{component}] {record.getMessage()}"


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(CorporateFormatter())
    logger = logging.getLogger("chatbot")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

