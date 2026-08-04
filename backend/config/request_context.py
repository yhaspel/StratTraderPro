"""Request/task correlation context (M10 §6.6).

A ``request_id`` (ULID) is minted per inbound HTTP request (or honored from an
inbound ``X-Request-ID``), stored in a ``ContextVar``, echoed on the response,
propagated into Celery task headers, and injected into every log record + Sentry
event. ``task_id`` is set while running inside a Celery task.
"""
from __future__ import annotations

import contextvars
import logging

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)


def new_request_id() -> str:
    from ulid import ULID

    return str(ULID())


def set_request_id(value: str | None):
    return _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def reset_request_id(token) -> None:
    try:
        _request_id.reset(token)
    except (ValueError, LookupError):  # pragma: no cover — token from another context
        _request_id.set(None)


def set_task_id(value: str | None):
    return _task_id.set(value)


def get_task_id() -> str | None:
    return _task_id.get()


class RequestContextFilter(logging.Filter):
    """Inject ``request_id`` + ``task_id`` into every log record (python-json-logger)."""

    def filter(self, record):  # noqa: A003 — logging.Filter API
        record.request_id = get_request_id() or "-"
        record.task_id = get_task_id() or "-"
        return True
