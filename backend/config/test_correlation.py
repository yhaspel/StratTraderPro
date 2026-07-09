"""Request-id correlation tests (AC-10-10 [CI] / §10.1): middleware, logging
filter, Celery header propagation (eager round-trip), Sentry tagging helper."""
import logging

from django.test import SimpleTestCase, TestCase

from config import celery as celery_mod
from config.middleware import RequestIdMiddleware
from config.request_context import (
    RequestContextFilter,
    get_request_id,
    set_request_id,
    set_task_id,
)


class _FakeRequest:
    def __init__(self, meta=None):
        self.META = meta or {}


class RequestIdMiddlewareTests(SimpleTestCase):
    def _mw(self, captured):
        def get_response(request):
            captured["rid_during"] = get_request_id()
            return {}

        return RequestIdMiddleware(get_response)

    def test_mints_ulid_and_echoes_header(self):
        captured = {}
        resp = self._mw(captured)(_FakeRequest())
        self.assertIsNotNone(captured["rid_during"])
        self.assertEqual(resp["X-Request-ID"], captured["rid_during"])
        # Reset after the request.
        self.assertIsNone(get_request_id())

    def test_honors_inbound_request_id(self):
        captured = {}
        resp = self._mw(captured)(_FakeRequest({"HTTP_X_REQUEST_ID": "abc-123"}))
        self.assertEqual(captured["rid_during"], "abc-123")
        self.assertEqual(resp["X-Request-ID"], "abc-123")


class LoggingFilterTests(SimpleTestCase):
    def test_injects_request_and_task_id(self):
        token = set_request_id("rid-9")
        try:
            set_task_id("task-9")
            record = logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None)
            RequestContextFilter().filter(record)
            self.assertEqual(record.request_id, "rid-9")
            self.assertEqual(record.task_id, "task-9")
        finally:
            from config.request_context import reset_request_id

            reset_request_id(token)
            set_task_id(None)


class CeleryPropagationTests(TestCase):
    def test_before_publish_sets_header_from_contextvar(self):
        token = set_request_id("rid-pub")
        try:
            headers = {}
            celery_mod._propagate_request_id(headers=headers)
            self.assertEqual(headers["request_id"], "rid-pub")
        finally:
            from config.request_context import reset_request_id

            reset_request_id(token)

    def test_eager_roundtrip_preserves_ambient_request_id(self):
        from celery import shared_task

        @shared_task(name="tests.echo_request_id")
        def echo_request_id():
            return get_request_id()

        token = set_request_id("rid-eager")
        try:
            result = echo_request_id.delay().get()
            self.assertEqual(result, "rid-eager")
            # Ambient survives the eager task (postrun restored it).
            self.assertEqual(get_request_id(), "rid-eager")
        finally:
            from config.request_context import reset_request_id

            reset_request_id(token)


class SentryTaggingHelperTests(SimpleTestCase):
    def test_tag_sentry_correlation_returns_request_id(self):
        from config.otel import tag_sentry_correlation

        token = set_request_id("rid-sentry")
        try:
            tags = tag_sentry_correlation()
            self.assertEqual(tags.get("request_id"), "rid-sentry")
        finally:
            from config.request_context import reset_request_id

            reset_request_id(token)
