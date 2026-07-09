"""OTel span-attribute test for the webhook→order path (AC-10-10 [CI]).

Captures spans with an in-memory exporter and asserts the ``webhook.place_order``
span carries ``alert_id``/``strategy_id``/``broker``/``user_id_hash`` and that the
raw user id never reaches the trace backend.
"""
from unittest import mock

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from apps.m04_testutils import create_broker_account, fake_factory, valid_alert

from .test_webhooks import _Base

_EXPORTER = InMemorySpanExporter()


class OtelSpanTests(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))

    def setUp(self):
        super().setUp()
        _EXPORTER.clear()

    def test_place_order_span_has_non_pii_attributes(self):
        create_broker_account(self.user)
        with mock.patch("apps.brokers.services.build_adapter", side_effect=fake_factory()):
            self.post(valid_alert(symbol="AAPL", qty=1))

        spans = [s for s in _EXPORTER.get_finished_spans() if s.name == "webhook.place_order"]
        self.assertEqual(len(spans), 1, "expected exactly one webhook.place_order span")
        attrs = dict(spans[0].attributes)
        self.assertIn("alert_id", attrs)
        self.assertEqual(attrs["broker"], "ALPACA")
        self.assertEqual(attrs["strategy_id"], str(self.strategy.id))
        self.assertEqual(len(attrs["user_id_hash"]), 16)
        # The raw user id must never appear anywhere in the span attributes.
        self.assertNotIn(str(self.user.id), str(attrs))
