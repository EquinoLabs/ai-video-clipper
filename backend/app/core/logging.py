"""Structured logging configuration with sensitive data redaction."""

import logging
import re
import sys
from typing import Any, Dict


# Regex patterns to detect and mask sensitive information in log streams
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token|authorization)\s*[:=]\s*['\"]?([^'\"\s&]+)"),
    re.compile(r"(https?://[^\s?]+)(\?[^\s]+)"),  # Potential signed URL with query params
]


class SensitiveDataFilter(logging.Filter):
    """Filter that masks tokens, passwords, and signed query strings from logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(v) if isinstance(v, str) else v for v in record.args)
        return True

    @staticmethod
    def _redact(text: str) -> str:
        # Redact keys/tokens
        text = SECRET_PATTERNS[0].sub(r"\1=***REDACTED***", text)
        # Redact signed URL query params
        text = SECRET_PATTERNS[1].sub(r"\1?***REDACTED_PARAMS***", text)
        return text


def setup_logging(level: str = "INFO") -> None:
    """Configure root and application loggers."""
    log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(SensitiveDataFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())
    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
