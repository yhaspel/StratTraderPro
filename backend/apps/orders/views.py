"""Orders / positions / fills read API (M04 §9 + M05 §6.4).

    GET /api/v1/orders/           paginated list w/ filters (broker/strategy/status/date)
    GET /api/v1/orders/{id}/      detail (order + fills + lifecycle)
    GET /api/v1/orders/export.csv CSV of the filtered set
    GET /api/v1/positions/        live snapshot (open positions)
    GET /api/v1/fills/            list
    GET /api/v1/reconciliation/events/  recon drift/heal events

All MFA-enforced. Responses use the platform ``{"data": ...}`` envelope; lists
carry a ``meta`` page block.
"""
from __future__ import annotations

import csv

from django.http import HttpResponse
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from .models import Fill, Order, Position, ReconEvent
from .serializers import (
    FillSerializer,
    OrderDetailSerializer,
    OrderSerializer,
    PositionSerializer,
    ReconEventSerializer,
)

_PAGE_SIZE = 25
_MAX_EXPORT = 5000


def _filtered_orders(request):
    qs = Order.objects.filter(user=request.user).select_related("strategy", "broker_account").order_by("-created_at")
    p = request.query_params
    if p.get("status"):
        qs = qs.filter(status=p["status"].upper())
    if p.get("strategy"):
        qs = qs.filter(strategy_id=p["strategy"])
    if p.get("broker"):
        qs = qs.filter(broker_account__broker=p["broker"].upper())
    if p.get("symbol"):
        qs = qs.filter(symbol=p["symbol"].upper())
    if p.get("from") and parse_datetime(p["from"]):
        qs = qs.filter(created_at__gte=parse_datetime(p["from"]))
    if p.get("to") and parse_datetime(p["to"]):
        qs = qs.filter(created_at__lte=parse_datetime(p["to"]))
    return qs


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
        qs = _filtered_orders(request)
        total = qs.count()
        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        start = (page - 1) * _PAGE_SIZE
        rows = list(qs[start:start + _PAGE_SIZE])
        num_pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
        return Response(
            {
                "data": OrderSerializer(rows, many=True).data,
                "meta": {"page": page, "page_size": _PAGE_SIZE, "total": total, "num_pages": num_pages},
            }
        )


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="orders_detail", tags=["orders"])
    def get(self, request, pk):
        order = (
            Order.objects.filter(user=request.user, pk=pk)
            .select_related("strategy", "broker_account")
            .prefetch_related("fills")
            .first()
        )
        if order is None:
            return fail("ORDER_NOT_FOUND", "Order not found.", status=404)
        return ok(OrderDetailSerializer(order).data)


class OrderCsvExportView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="orders_export_csv", tags=["orders"])
    def get(self, request):
        qs = _filtered_orders(request)[:_MAX_EXPORT]
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="orders.csv"'
        writer = csv.writer(resp)
        writer.writerow(
            ["created_at", "broker", "strategy", "symbol", "asset_class", "side",
             "qty", "filled_qty", "order_type", "status", "reason"]
        )
        for o in qs:
            writer.writerow([
                o.created_at.isoformat() if o.created_at else "",
                o.broker_account.broker if o.broker_account_id else "",
                o.strategy.slug if o.strategy_id else "",
                o.symbol, o.asset_class, o.side, o.qty, o.filled_qty,
                o.order_type, o.status, o.reason,
            ])
        return resp


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
        qs = Fill.objects.filter(order__user=request.user).select_related("order").order_by("-ts")[:500]
        if request.query_params.get("symbol"):
            qs = Fill.objects.filter(
                order__user=request.user, order__symbol=request.query_params["symbol"].upper()
            ).select_related("order").order_by("-ts")[:500]
        return ok(FillSerializer(qs, many=True).data)


class ReconEventListView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="reconciliation_events", tags=["orders"])
    def get(self, request):
        qs = ReconEvent.objects.filter(user=request.user).order_by("-created_at")[:500]
        return ok(ReconEventSerializer(qs, many=True).data)
