"""M00 backend tests — health endpoints, schema, logging scrubber, sentry init."""
import json

from django.test import RequestFactory, TestCase, override_settings

from config.urls import healthz


class HealthzTest(TestCase):
    def test_healthz_returns_ok(self):
        factory = RequestFactory()
        request = factory.get("/healthz")
        response = healthz(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["status"], "ok")
        self.assertIn("version", data)


class ReadyzTest(TestCase):
    def test_readyz_reports_db_and_redis(self):
        response = self.client.get("/readyz")
        data = json.loads(response.content)
        self.assertIn("checks", data)
        self.assertIn("db", data["checks"])
        self.assertIn("redis", data["checks"])


class OpenAPISchemaTest(TestCase):
    def test_openapi_schema_parses_as_json(self):
        response = self.client.get("/api/schema/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn("openapi", data)
        self.assertIn("info", data)


class LoggingScrubberTest(TestCase):
    def test_logging_scrubber_strips_authorization(self):
        from apps.audit.scrub import _scrub_sensitive

        event = {"authorization": "Bearer secret123", "user": "test@example.com"}
        result = _scrub_sensitive(None, None, event)
        self.assertEqual(result["authorization"], "***REDACTED***")
        self.assertEqual(result["user"], "test@example.com")

    def test_logging_scrubber_strips_multiple_keys(self):
        from apps.audit.scrub import _scrub_sensitive

        event = {"password": "hunter2", "token": "abc", "name": "safe"}
        result = _scrub_sensitive(None, None, event)
        self.assertEqual(result["password"], "***REDACTED***")
        self.assertEqual(result["token"], "***REDACTED***")
        self.assertEqual(result["name"], "safe")


class SentryInitTest(TestCase):
    @override_settings(SENTRY_DSN="")
    def test_sentry_init_does_not_raise(self):
        """Sentry should not raise when DSN is empty."""
        try:
            import sentry_sdk
            # Re-initializing with empty DSN should be a no-op
            sentry_sdk.init(dsn="")
        except Exception as exc:
            self.fail(f"Sentry init raised: {exc}")
