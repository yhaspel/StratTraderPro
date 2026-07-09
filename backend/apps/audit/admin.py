"""Audit admin — strictly read-only (the table is append-only; edits/deletes are
blocked by DB triggers on Postgres regardless)."""
from django.contrib import admin

from .models import AuditLog, AuditVerifierState


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("id", "occurred_at", "event_type", "user", "actor", "entity_type", "entity_id")
    list_filter = ("event_type",)
    search_fields = ("entity_id", "event_type")
    readonly_fields = (
        "occurred_at", "event_type", "user", "actor", "entity_type", "entity_id",
        "data_before", "data_after", "ip", "ua", "prev_hash", "self_hash",
    )
    ordering = ("-id",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditVerifierState)
class AuditVerifierStateAdmin(admin.ModelAdmin):
    list_display = ("id", "last_verified_id", "run_at", "result")
    readonly_fields = ("last_verified_id", "last_verified_hash", "run_at", "result")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
