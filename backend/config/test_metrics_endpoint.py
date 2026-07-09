"""/metrics exposition tests (AC-10-12 / §10.6).

Invoked at the WSGI-callable level — the Django test client routes the urlconf
and cannot reach an out-of-urlconf mount, so the exposition app is called
directly.
"""
import base64

from django.test import SimpleTestCase, override_settings

from config.metrics_endpoint import metrics_wsgi_app, wrap_wsgi


def _call(app, environ):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


class MetricsEndpointTests(SimpleTestCase):
    def test_open_when_auth_unconfigured(self):
        status, headers, body = _call(metrics_wsgi_app, {"HTTP_AUTHORIZATION": ""})
        self.assertTrue(status.startswith("200"))
        self.assertIn("text/plain", headers["Content-Type"])

    @override_settings(METRICS_BASIC_AUTH_USERNAME="scrape", METRICS_BASIC_AUTH_PASSWORD="s3cret")
    def test_401_without_credentials(self):
        status, headers, _ = _call(metrics_wsgi_app, {"HTTP_AUTHORIZATION": ""})
        self.assertTrue(status.startswith("401"))
        self.assertIn("WWW-Authenticate", headers)

    @override_settings(METRICS_BASIC_AUTH_USERNAME="scrape", METRICS_BASIC_AUTH_PASSWORD="s3cret")
    def test_200_with_valid_credentials(self):
        token = base64.b64encode(b"scrape:s3cret").decode()
        status, _, body = _call(metrics_wsgi_app, {"HTTP_AUTHORIZATION": f"Basic {token}"})
        self.assertTrue(status.startswith("200"))
        self.assertIn(b"# HELP", body)  # Prometheus exposition payload

    @override_settings(METRICS_BASIC_AUTH_USERNAME="scrape", METRICS_BASIC_AUTH_PASSWORD="s3cret")
    def test_401_with_wrong_credentials(self):
        token = base64.b64encode(b"scrape:wrong").decode()
        status, _, _ = _call(metrics_wsgi_app, {"HTTP_AUTHORIZATION": f"Basic {token}"})
        self.assertTrue(status.startswith("401"))

    def test_dispatcher_passes_non_metrics_to_django(self):
        sentinel = object()

        def fake_django(environ, start_response):
            return sentinel

        app = wrap_wsgi(fake_django)
        self.assertIs(app({"PATH_INFO": "/api/v1/health"}, lambda *a: None), sentinel)
