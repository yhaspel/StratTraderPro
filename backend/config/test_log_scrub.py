"""M11 §7.1 V7 — the sensitive-data logging filter is wired and works.

The BUG-009 question applies: a scrubber that is defined but not attached to a
handler redacts nothing. So this asserts BOTH that the filter is wired into the
LOGGING config AND that it actually redacts a secret passed via extra=.
"""
from __future__ import annotations

import io
import logging

from django.conf import settings
from django.test import TestCase

from apps.audit.scrub import REDACTED
from config.log_scrub import SensitiveDataFilter


class LogScrubTests(TestCase):
    def test_filter_is_wired_into_logging_config(self):
        # Defined as a filter...
        self.assertIn("scrub_sensitive", settings.LOGGING["filters"])
        self.assertEqual(
            settings.LOGGING["filters"]["scrub_sensitive"]["()"],
            "config.log_scrub.SensitiveDataFilter",
        )
        # ...AND attached to the console handler (not just declared).
        self.assertIn("scrub_sensitive", settings.LOGGING["handlers"]["console"]["filters"])

    def test_secret_in_extra_is_redacted(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(SensitiveDataFilter())
        handler.setFormatter(logging.Formatter("%(message)s api_key=%(api_key)s password=%(password)s"))
        logger = logging.getLogger("test.scrub")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False

        logger.info("broker connected", extra={"api_key": "PKSECRET123", "password": "hunter2"})

        out = stream.getvalue()
        self.assertNotIn("PKSECRET123", out)
        self.assertNotIn("hunter2", out)
        self.assertEqual(out.count(REDACTED), 2)
