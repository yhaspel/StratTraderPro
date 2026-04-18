from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuthEvent, FailedLoginAttempt, RefreshTokenFamily, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-created_at",)
    list_display = ("email", "display_name", "is_verified", "is_active", "is_staff", "created_at")
    search_fields = ("email", "display_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("display_name",)}),
        ("Status", {"fields": ("is_active", "is_verified", "is_staff", "is_superuser")}),
        ("Groups", {"fields": ("groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "display_name", "password1", "password2")}),
    )


@admin.register(AuthEvent)
class AuthEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "event_type", "email", "ip")
    list_filter = ("event_type",)
    search_fields = ("email",)
    readonly_fields = ("user", "email", "event_type", "ip", "user_agent", "metadata", "occurred_at")


@admin.register(RefreshTokenFamily)
class RefreshTokenFamilyAdmin(admin.ModelAdmin):
    list_display = ("family_id", "user", "created_at", "revoked_at", "revoke_reason")
    list_filter = ("revoked_at",)
    readonly_fields = ("family_id", "user", "created_at", "revoked_at", "revoke_reason", "current_jti")


@admin.register(FailedLoginAttempt)
class FailedLoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("email", "ip", "occurred_at")
    search_fields = ("email",)
    readonly_fields = ("email", "ip", "occurred_at")
