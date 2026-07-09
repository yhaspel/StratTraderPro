"""Admin-portal URL routing (M10 §6.2). Mounted at /api/v1/admin/."""
from django.urls import path

from . import views

urlpatterns = [
    path("users/", views.AdminUserListView.as_view(), name="admin-users"),
    path("users/<uuid:user_id>/", views.AdminUserDetailView.as_view(), name="admin-user-detail"),
    path("users/<uuid:user_id>/disable/", views.AdminUserDisableView.as_view(), name="admin-user-disable"),
    path("users/<uuid:user_id>/enable/", views.AdminUserEnableView.as_view(), name="admin-user-enable"),
    path(
        "users/<uuid:user_id>/impersonate/start/",
        views.AdminImpersonateStartView.as_view(),
        name="admin-impersonate-start",
    ),
    path(
        "impersonation/<uuid:session_id>/stop/",
        views.AdminImpersonationStopView.as_view(),
        name="admin-impersonation-stop",
    ),
    path("audit/", views.AuditSearchView.as_view(), name="admin-audit"),
    path("audit/export.csv", views.AuditExportView.as_view(), name="admin-audit-export"),
    path("platform/status/", views.PlatformStatusView.as_view(), name="admin-platform-status"),
    path("platform/killswitch/", views.PlatformKillswitchView.as_view(), name="admin-platform-killswitch"),
    path("flags/", views.FlagListView.as_view(), name="admin-flags"),
    path("flags/<str:name>/", views.FlagFlipView.as_view(), name="admin-flag-flip"),
    path("health/", views.AdminHealthView.as_view(), name="admin-health"),
]
