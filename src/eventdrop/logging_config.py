"""Application-wide logging configuration.

EventDrop logs to stdout through a single handler on the root logger. Uvicorn's own
loggers are stripped of their handlers and left to propagate, so every line — access
logs included — goes through the same formatter.

Two output modes, selected by EVENTDROP_LOG_AS_JSON:
  - text (default): human-readable, timestamped
  - json: one JSON object per line, with structured fields for web requests
"""

import json
import logging
import sys
from datetime import datetime, timezone

from eventdrop.config import settings

# Attributes present on every LogRecord. Anything outside this set was supplied by a
# caller via `extra={...}` and is merged into the JSON output.
_STANDARD_RECORD_ATTRS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "module", "msecs", "msg", "name", "pathname",
        "process", "processName", "relativeCreated", "stack_info", "taskName",
        "thread", "threadName",
    }
)

TEXT_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-8s [%(name)s] %(message)s"
TEXT_DATEFMT = "%Y-%m-%dT%H:%M:%S"

UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class JsonFormatter(logging.Formatter):
    """Render each log record as a single JSON object on one line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": self._safe_message(record),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        access_fields = self._access_fields(record)
        if access_fields:
            payload.update(access_fields)

        # Caller-supplied extras (extra={...}) become top-level fields.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exc"] = record.exc_text
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str)

    @staticmethod
    def _safe_message(record: logging.LogRecord) -> str:
        """Render the message, tolerating a msg/args mismatch.

        getMessage() raises if the two disagree. A malformed log call should surface
        the raw message rather than take down the caller from inside a log handler.
        """
        try:
            return record.getMessage()
        except (TypeError, ValueError):
            return f"{record.msg!s} args={record.args!r}"

    @staticmethod
    def _access_fields(record: logging.LogRecord) -> dict | None:
        """Destructure a uvicorn access record into structured request fields.

        Uvicorn logs access lines with args of the shape
        (client_addr, method, full_path, http_version, status_code) — see
        uvicorn.logging.AccessFormatter. If a future uvicorn changes that shape we
        fall back to the plain message rather than raising inside a log handler.
        """
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
            return None
        if len(record.args) != 5:
            return None

        try:
            client_addr, method, full_path, http_version, status_code = record.args
            path, _, query = str(full_path).partition("?")
            return {
                "client_ip": str(client_addr).rsplit(":", 1)[0] if client_addr else None,
                "method": str(method),
                "path": path,
                "query": query,
                "http_version": str(http_version),
                "status": int(status_code),
            }
        except (TypeError, ValueError):
            return None


def _build_formatter() -> logging.Formatter:
    if settings.log_as_json:
        return JsonFormatter()
    return logging.Formatter(TEXT_FORMAT, datefmt=TEXT_DATEFMT)


def setup_logging() -> None:
    """Install EventDrop's log handler on the root logger.

    Called at import time of eventdrop.main. Uvicorn applies its own dictConfig before
    importing the app, so this runs afterwards and deliberately overrides it.
    Idempotent, so re-imports under --reload do not stack handlers.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_build_formatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        # Must stay True: uvicorn gates access logging on
        # `uvicorn.access.hasHandlers()`, which walks ancestors. Clearing the handlers
        # *and* disabling propagation would silently switch access logs off entirely.
        uvicorn_logger.propagate = True
