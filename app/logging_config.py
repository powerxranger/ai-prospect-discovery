from __future__ import annotations

import logging

from .config import Settings


class SecretRedactionFilter(logging.Filter):
    """Replace configured secrets in log records."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [value for value in secrets if len(value) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for secret in self._secrets:
            message = message.replace(secret, "[REDACTED]")
        if message != record.msg:
            record.msg = message
            record.args = ()
        return True


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler: logging.Handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)
    redactor = SecretRedactionFilter(settings.configured_secrets())
    for handler in root.handlers:
        handler.addFilter(redactor)
