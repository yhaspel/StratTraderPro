"""M11 §7.4 — auto-activate the FakeBrokerAdapter seam on a DEDICATED load stack.

Python imports ``sitecustomize`` automatically at interpreter startup if it is on
``sys.path``. On a dedicated load-test compose stack, add this directory to the
path and flip the flag on the backend/worker/streams services:

    environment:
      STP_LOADTEST_FAKE_BROKER: "1"
      PYTHONPATH: "/app/loadtest"

Because it runs BEFORE Django is configured, we cannot patch
``apps.brokers.services`` here directly. Instead we wrap ``Apps.populate`` so the
patch runs the instant the app registry is ready — in every process that calls
``django.setup()`` (gunicorn/daphne/celery/manage.py). This keeps the whole seam
inside ``backend/loadtest/`` with zero edits to tracked app or config code.

Do NOT set the flag on the shared dev stack.
"""
from __future__ import annotations

import os

if os.environ.get("STP_LOADTEST_FAKE_BROKER") == "1":  # pragma: no cover - infra glue
    try:
        from django.apps.registry import Apps

        _orig_populate = Apps.populate

        def _populate(self, installed_apps=None):
            result = _orig_populate(self, installed_apps)
            if self.ready and not getattr(self, "_stp_fake_patched", False):
                try:
                    from fake_broker_patch import patch_build_adapter

                    if patch_build_adapter():
                        self._stp_fake_patched = True
                except Exception:  # noqa: BLE001 — never break app boot over a load hook
                    import logging

                    logging.getLogger("loadtest.fake_broker").exception(
                        "sitecustomize failed to patch build_adapter"
                    )
            return result

        Apps.populate = _populate  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 — Django not importable yet; nothing to do
        pass
