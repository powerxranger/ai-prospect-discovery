from __future__ import annotations

import logging

from app.logging_config import SecretRedactionFilter, configure_logging


def test_secret_redaction_filter_hides_configured_secret() -> None:
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "key is super-secret-value-1234", (), None
    )
    assert SecretRedactionFilter(["super-secret-value-1234"]).filter(record) is True
    assert "super-secret-value-1234" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_short_values_are_not_registered() -> None:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "value abc", (), None)
    SecretRedactionFilter(["abc"]).filter(record)
    assert record.getMessage() == "value abc"


def test_configure_logging_is_idempotent(settings) -> None:
    configure_logging(settings)
    before = len(logging.getLogger().handlers)
    configure_logging(settings)
    assert len(logging.getLogger().handlers) == before
