"""Structured JSON logging with correlation ids and secret redaction."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_REDACT = re.compile(r"(?i)(token|password|secret|api[_-]?key|authorization)(\"?\s*[:=]\s*\"?)([^\s\",]+)")


def redact(text: str) -> str:
    return _REDACT.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": round(time.time(), 3), "level": record.levelname, "logger": record.name,
                   "request_id": request_id_var.get(), "msg": redact(record.getMessage())}
        for k in ("path", "method", "status", "ms", "workspace"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload)


def configure(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
