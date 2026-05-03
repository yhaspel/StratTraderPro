"""Admin registrations for the strategies app (M03)."""
from __future__ import annotations

from django.contrib import admin

from .models import Strategy, StrategyFile, WebhookConfig


class StrategyFileInline(admin.TabularInline):
    model = StrategyFile
    extra = 0
    readonly_fields = ("kind", "filename", "sha256", "size_bytes", "uploaded_at")
    can_delete = False


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = (
        "name", "slug", "is_system", "is_enabled",
        "is_community_tested", "owner", "created_at",
    )
    list_filter = ("is_system", "is_enabled", "is_community_tested")
    search_fields = ("name", "slug", "owner__email")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [StrategyFileInline]

    def has_change_permission(self, request, obj=None):
        # System rows: only staff can edit (AC-03-10).
        if obj and obj.is_system and not request.user.is_staff:
            return False
        return super().has_change_permission(request, obj)


@admin.register(StrategyFile)
class StrategyFileAdmin(admin.ModelAdmin):
    list_display = ("strategy", "kind", "filename", "size_bytes", "uploaded_at")
    list_filter = ("kind",)
    readonly_fields = ("id", "sha256", "size_bytes", "uploaded_at")


@admin.register(WebhookConfig)
class WebhookConfigAdmin(admin.ModelAdmin):
    list_display = ("user", "strategy", "version", "rotated_at", "created_at")
    list_filter = ("version",)
    readonly_fields = (
        "id", "user", "strategy", "secret_encrypted",
        "version", "created_at", "rotated_at", "updated_at",
    )

    def has_add_permission(self, request):
        # Configs are created via the API; never via admin.
        return False
