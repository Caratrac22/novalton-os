"""Structured logging configuration for the API."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from novalton_api.core.context import get_correlation_id

_OPTIONAL_CONTEXT_FIELDS = (
    "tenant_id",
    "workspace_id",
    "workflow_run_id",
    "agent_run_id",
    "provider_id",
    "model_id",
    "outcome_class",
    "duration_ms",
)


class JsonFormatter(logging.Formatter):
    """Format standard log records as one-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        correlation_id = get_correlation_id()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "novalton-api",
            "event": getattr(record, "event", "application.log"),
            "message": record.getMessage(),
        }
        if correlation_id:
            payload["request_id"] = correlation_id
            payload["correlation_id"] = correlation_id
        for field in _OPTIONAL_CONTEXT_FIELDS:
            if value := getattr(record, field, None):
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Configure the root logger without logging sensitive application data."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
