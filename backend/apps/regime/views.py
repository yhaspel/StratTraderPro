"""Regime API (M06 §6.7/§9). All MFA-enforced; returns i18n-neutral enums."""
from __future__ import annotations

from django.conf import settings
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from .models import RegimeObservation
from .services import get_active_model, model_degraded


def _obs_to_wire(obs: RegimeObservation) -> dict:
    return {
        "ts": obs.ts.isoformat() if obs.ts else None,
        "scope": obs.scope,
        "label": obs.label,
        "rule_bucket": obs.rule_bucket,
        "rule_score": obs.rule_score,
        "hmm_state": obs.hmm_state,
        "hmm_probs": obs.hmm_probs,
        "top_features": obs.top_features,
        "model": {"version": obs.model_version, "degraded": obs.model_degraded},
    }


class _Base(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def _disabled(self):
        return fail("FEATURE_DISABLED", "Regime feature is disabled.", status=503)

    def _enabled(self):
        return getattr(settings, "ENABLE_REGIME_UI", True)


class RegimeCurrentView(_Base):
    @extend_schema(operation_id="regime_current", tags=["regime"])
    def get(self, request):
        if not self._enabled():
            return self._disabled()
        obs = RegimeObservation.objects.filter(scope="MARKET").order_by("-ts").first()
        if obs is None:
            return ok(None)
        return ok(_obs_to_wire(obs))


class RegimeHistoryView(_Base):
    @extend_schema(operation_id="regime_history", tags=["regime"])
    def get(self, request):
        if not self._enabled():
            return self._disabled()
        scope = request.query_params.get("scope", "MARKET").upper()
        qs = RegimeObservation.objects.filter(scope=scope).order_by("-ts")
        if request.query_params.get("from") and parse_datetime(request.query_params["from"]):
            qs = qs.filter(ts__gte=parse_datetime(request.query_params["from"]))
        if request.query_params.get("to") and parse_datetime(request.query_params["to"]):
            qs = qs.filter(ts__lte=parse_datetime(request.query_params["to"]))
        return ok([_obs_to_wire(o) for o in qs[:500]])


class RegimeModelView(_Base):
    @extend_schema(operation_id="regime_model", tags=["regime"])
    def get(self, request):
        # `source_configured` is the difference between "the pipeline ran and
        # found nothing" and "the pipeline never ran because FMP_API_KEY /
        # FRED_API_KEY are unset". Without it the dashboard can only say
        # "No regime data yet", which reads as a bug rather than as missing
        # configuration — see apps.regime.tasks.compute_features_daily.
        from .tasks import _daily_source_configured

        source_configured = _daily_source_configured()
        model = get_active_model()
        if model is None:
            return ok({
                "active": None,
                "degraded": True,
                "source_configured": source_configured,
            })
        return ok({
            "version": model.version,
            "n_states": model.n_states,
            "trained_at": model.trained_at.isoformat() if model.trained_at else None,
            "holdout_ll": model.holdout_ll,
            "degraded": model_degraded(model),
            "source_configured": source_configured,
        })


class RegimeSymbolView(_Base):
    @extend_schema(operation_id="regime_symbol", tags=["regime"])
    def get(self, request, sym):
        return fail("NOT_IMPLEMENTED", "Per-symbol regime lands in a later milestone.", status=501)
