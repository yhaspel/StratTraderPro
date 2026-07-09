from django.contrib import admin

from .models import FeatureFlag, ImpersonationSession


@admin.register(ImpersonationSession)
class ImpersonationSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "actor", "target", "started_at", "expires_at", "ended_at")
    readonly_fields = ("id", "actor", "target", "reason", "started_at", "expires_at", "ended_at", "ip", "ua")
    search_fields = ("actor__email", "target__email")

    def has_add_permission(self, request):
        return False


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled", "updated_by", "updated_at")
    readonly_fields = ("updated_at",)
    search_fields = ("name",)
