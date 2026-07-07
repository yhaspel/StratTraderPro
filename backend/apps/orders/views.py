"""Orders / positions / fills read API (M04 §9).

    GET /api/v1/orders/      list with filters (status, strategy, symbol, date)
    GET /api/v1/positions/   live snapshot (open positions)
    GET /api/v1/fills/       list

All MFA-enforced. Responses use the platform ``{"data": [...]}`` envelope for
consistency with M01–M03. M04 volume is low (paper); proper pagination + CSV
lands with the M05 Orders page. Lists are capped defensively.
"""
from __future__ import annotations

from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import ok

from .models import Fill, Order, Position
from .serializers import FillSerializer, OrderSerializer, PositionSerializer

_LIST_CAP = 500


# Kept from the M02 scaffold.
class OrdersPingView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def get(self, request):
        return Response({"data": {"app": "orders", "status": "ok"}})


class OrderListView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="orders_list", tags=["orders"])
    def get(self, request):
        qs = Order.objects.filter(user=request.user).select_related("strategy").order_by("-created_at")
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"].upper())
        if p.get("strategy"):
            qs = qs.filter(strategy_id=p["strategy"])
        if p.get("symbol"):
            qs = qs.filter(symbol=p["symbol"].upper())
        if p.get("date_from") and parse_datetime(p["date_from"]):
            qs = qs.filter(created_at__gte=parse_datetime(p["date_from"]))
        if p.get("date_to") and parse_datetime(p["date_to"]):
            qs = qs.filter(created_at__lte=parse_datetime(p["date_to"]))
        return ok(OrderSerializer(qs[:_LIST_CAP], many=True).data)


class PositionListView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="positions_list", tags=["orders"])
    def get(self, request):
        qs = Position.objects.filter(user=request.user).order_by("symbol")
        if request.query_params.get("include_flat") != "true":
            qs = qs.exclude(qty=0)
        return ok(PositionSerializer(qs, many=True).data)


class FillListView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="fills_list", tags=["orders"])
    def get(self, request):
        qs = Fill.objects.filter(order__user=request.user).select_related("order").order_by("-ts")
        if request.query_params.get("symbol"):
            qs = qs.filter(order__symbol=request.query_params["symbol"].upper())
        return ok(FillSerializer(qs[:_LIST_CAP], many=True).data)
