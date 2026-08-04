from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    BackupCode,
    FailedLoginAttempt,
    MFADevice,
    RefreshTokenFamily,
    User,
    UserProfile,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-created_at",)
    list_display = (
        "email",
        "display_name",
        "is_verified",
        "is_active",
        "is_staff",
        "mfa_enabled_display",
        "created_at",
    )
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

    @admin.display(boolean=True, description="MFA enabled")
    def mfa_enabled_display(self, obj):
        return obj.mfa_enabled


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "timezone", "language", "notification_email", "created_at")
    search_fields = ("user__email",)


@admin.register(MFADevice)
class MFADeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "verified", "enrolled_at", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("secret_encrypted", "created_at", "updated_at")
    actions = ["force_disable_mfa"]

    @admin.action(description="Force-disable MFA (audited; emails the user)")
    def force_disable_mfa(self, request, queryset):
        from apps.audit.events import AuthEventType
        from apps.audit.services import emit

        from . import services

        actor = request.user if request.user.is_authenticated else None
        for device in queryset:
            user = device.user
            device.delete()
            user.backup_codes.all().delete()
            services.send_mfa_disabled_email(user)
            emit(
                f"auth.{AuthEventType.MFA_DISABLED}",
                user=user,
                actor=actor,
                request=request,
                data_after={"email": user.email, "actor": "admin"},
            )
        self.message_user(request, f"Disabled MFA on {queryset.count()} user(s).")


@admin.register(BackupCode)
class BackupCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "used_at", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("code_hash", "salt", "used_at", "created_at")


@admin.register(RefreshTokenFamily)
class RefreshTokenFamilyAdmin(admin.ModelAdmin):
    list_display = ("family_id", "user", "created_at", "last_used_at", "revoked_at", "revoke_reason")
    list_filter = ("revoked_at",)
    readonly_fields = (
        "family_id",
        "user",
        "created_at",
        "revoked_at",
        "revoke_reason",
        "current_jti",
        "ip",
        "user_agent",
        "last_used_at",
    )


@admin.register(FailedLoginAttempt)
class FailedLoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("email", "ip", "occurred_at")
    search_fields = ("email",)
    readonly_fields = ("email", "ip", "occurred_at")
