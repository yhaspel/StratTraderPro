from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
    verbose_name = "Users"

    def ready(self):
        # Wire signals: auto-create UserProfile when a User is created.
        from . import signals  # noqa: F401
