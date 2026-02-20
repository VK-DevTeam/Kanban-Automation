import json
import logging
import sys
from datetime import datetime
from typing import Any, Optional

import httpx
import structlog
from app.config import get_settings


def setup_logging():
    """Configure structlog for JSON output."""
    settings = get_settings()

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )


def get_logger(name: str = __name__):
    """Get a structlog logger instance."""
    return structlog.get_logger(name)


async def alert_dlq(
    reason: str,
    error_code: Optional[str] = None,
    event_id: Optional[str] = None,
    task_gid: Optional[str] = None,
    details: Optional[dict] = None,
):
    """Send alert to DLQ webhook (Slack-compatible)."""
    settings = get_settings()
    logger = get_logger(__name__)

    if not settings.dlq_alert_webhook_url:
        logger.warning("DLQ alert webhook URL not configured, skipping alert")
        return

    message = {
        "text": f"🚨 DLQ Alert: {reason}",
        "attachments": [
            {
                "color": "danger",
                "fields": [
                    {"title": "Reason", "value": reason, "short": False},
                    {"title": "Timestamp", "value": datetime.utcnow().isoformat()},
                ],
            }
        ],
    }

    if error_code:
        message["attachments"][0]["fields"].append(
            {"title": "Error Code", "value": error_code, "short": True}
        )
    if event_id:
        message["attachments"][0]["fields"].append(
            {"title": "Event ID", "value": event_id, "short": True}
        )
    if task_gid:
        message["attachments"][0]["fields"].append(
            {"title": "Task GID", "value": task_gid, "short": True}
        )
    if details:
        message["attachments"][0]["fields"].append(
            {"title": "Details", "value": json.dumps(details), "short": False}
        )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(settings.dlq_alert_webhook_url, json=message)
        logger.info("DLQ alert sent", reason=reason)
    except Exception as e:
        logger.error("Failed to send DLQ alert", error=str(e), reason=reason)
