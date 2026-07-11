"""OTel export wiring tests (AC-10-10).

Two regressions are guarded here, both of which fail *silently* in production —
the exporter reports healthy, no errors are logged, and Tempo simply stays empty:

1. **Entrypoint ordering.** ``DjangoInstrumentor`` activates by inserting its
   middleware into ``settings.MIDDLEWARE``. Django freezes the middleware chain
   when the handler is constructed (``BaseHandler.load_middleware()``), so calling
   ``init_otel()`` *after* ``get_wsgi_application()`` mutates a list nothing reads
   again and the web tier emits zero request spans.

2. **OTLP signal path.** The OTLP/HTTP exporter only appends ``/v1/traces`` when it
   resolves the endpoint from the environment itself; an endpoint passed explicitly
   is used verbatim. Handing it the OTLP *base* URL makes every span POST to
   ``/otlp`` and 404.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

from config.otel import _traces_endpoint

_CONFIG_DIR = Path(__file__).resolve().parent


def _first_call_lineno(source: str, func_name: str) -> int | None:
    """Line of the first call to ``func_name``.

    Parsed via ``ast`` rather than string search so that prose in comments and
    docstrings (which necessarily name these functions) cannot satisfy the guard.
    """
    tree = ast.parse(source)
    linenos = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == func_name
    ]
    return min(linenos) if linenos else None


class TracesEndpointTests(SimpleTestCase):
    """The exporter is handed a signal-specific URL, whatever form the env uses."""

    def test_appends_signal_path_to_base_endpoint(self):
        self.assertEqual(
            _traces_endpoint("https://otlp-gateway-prod-eu-central-0.grafana.net/otlp"),
            "https://otlp-gateway-prod-eu-central-0.grafana.net/otlp/v1/traces",
        )

    def test_tolerates_trailing_slash(self):
        self.assertEqual(
            _traces_endpoint("https://otlp-gateway-prod-eu-central-0.grafana.net/otlp/"),
            "https://otlp-gateway-prod-eu-central-0.grafana.net/otlp/v1/traces",
        )

    def test_is_idempotent_when_already_a_traces_url(self):
        url = "https://otlp-gateway-prod-eu-central-0.grafana.net/otlp/v1/traces"
        self.assertEqual(_traces_endpoint(url), url)


class EntrypointOrderTests(SimpleTestCase):
    """`init_otel()` must run before the Django handler is constructed."""

    def _assert_init_precedes(self, module: str, build_func: str):
        src = (_CONFIG_DIR / module).read_text()
        init_line = _first_call_lineno(src, "init_otel")
        build_line = _first_call_lineno(src, build_func)

        self.assertIsNotNone(init_line, f"config/{module} never calls init_otel()")
        self.assertIsNotNone(build_line, f"config/{module} never calls {build_func}()")
        self.assertLess(
            init_line,
            build_line,
            f"init_otel() must precede {build_func}() in config/{module}: "
            "DjangoInstrumentor activates by inserting its middleware into "
            "settings.MIDDLEWARE, and Django freezes the middleware chain when the "
            "handler is constructed. Initializing afterwards leaves the web tier "
            "untraced (exporter healthy, no errors logged, Tempo empty).",
        )

    def test_wsgi_inits_otel_before_building_app(self):
        self._assert_init_precedes("wsgi.py", "get_wsgi_application")

    def test_asgi_inits_otel_before_building_app(self):
        self._assert_init_precedes("asgi.py", "get_asgi_application")
