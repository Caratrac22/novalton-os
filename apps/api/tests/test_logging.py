import json
import logging

from novalton_api.core.context import reset_correlation_id, set_correlation_id
from novalton_api.core.logging import JsonFormatter


def test_json_formatter_includes_request_context() -> None:
    token = set_correlation_id("request_123")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Request processed",
            args=(),
            exc_info=None,
        )
        record.event = "test.completed"

        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_correlation_id(token)

    assert payload["level"] == "INFO"
    assert payload["service"] == "novalton-api"
    assert payload["request_id"] == "request_123"
    assert payload["correlation_id"] == "request_123"
    assert payload["event"] == "test.completed"
    assert payload["message"] == "Request processed"
    assert payload["timestamp"]


def test_json_formatter_omits_context_that_does_not_exist() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="No request context",
        args=(),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert "request_id" not in payload
    assert "correlation_id" not in payload
    assert "tenant_id" not in payload
