"""M01 Auth Foundation — initial user + auth tables.

User, EmailVerificationToken, PasswordResetToken, RefreshTokenFamily,
FailedLoginAttempt, AuthEvent.
"""
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        # ------- User -------
        migrations.CreateModel(
            name="User",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False, verbose_name="superuser status")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.EmailField(db_index=True, max_length=254, unique=True)),
                ("display_name", models.CharField(max_length=64)),
                ("is_active", models.BooleanField(default=True)),
                ("is_verified", models.BooleanField(default=False)),
                ("is_staff", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "groups",
                    models.ManyToManyField(blank=True, related_name="user_set", related_query_name="user", to="auth.group", verbose_name="groups"),
                ),
                (
                    "user_permissions",
                    models.ManyToManyField(blank=True, related_name="user_set", related_query_name="user", to="auth.permission", verbose_name="user permissions"),
                ),
            ],
            options={"db_table": "users_user"},
        ),
        # ------- EmailVerificationToken -------
        migrations.CreateModel(
            name="EmailVerificationToken",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "users_email_verification_token"},
        ),
        # ------- PasswordResetToken -------
        migrations.CreateModel(
            name="PasswordResetToken",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "users_password_reset_token"},
        ),
        # ------- RefreshTokenFamily -------
        migrations.CreateModel(
            name="RefreshTokenFamily",
            fields=[
                ("family_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoke_reason", models.CharField(blank=True, default="", max_length=64)),
                ("current_jti", models.CharField(db_index=True, max_length=64)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="refresh_families", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "users_refresh_token_family",
            },
        ),
        migrations.AddIndex(
            model_name="refreshtokenfamily",
            index=models.Index(fields=["user", "revoked_at"], name="users_refre_user_id_idx"),
        ),
        # ------- FailedLoginAttempt -------
        migrations.CreateModel(
            name="FailedLoginAttempt",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                ("occurred_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={"db_table": "users_failed_login_attempt"},
        ),
        migrations.AddIndex(
            model_name="failedloginattempt",
            index=models.Index(fields=["email", "occurred_at"], name="users_faile_email_idx"),
        ),
        # ------- AuthEvent -------
        migrations.CreateModel(
            name="AuthEvent",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("event_type", models.CharField(
                    choices=[
                        ("register", "Register"),
                        ("verify_email", "Verify Email"),
                        ("login_ok", "Login Ok"),
                        ("login_fail", "Login Fail"),
                        ("logout", "Logout"),
                        ("refresh_ok", "Refresh Ok"),
                        ("refresh_reuse", "Refresh Reuse"),
                        ("family_revoked", "Family Revoked"),
                        ("password_reset_requested", "Password Reset Requested"),
                        ("password_reset_confirmed", "Password Reset Confirmed"),
                        ("account_locked", "Account Locked"),
                        ("resend_verification", "Resend Verification"),
                    ],
                    max_length=32,
                )),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, default="", max_length=512)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="auth_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "users_auth_event"},
        ),
        migrations.AddIndex(
            model_name="authevent",
            index=models.Index(fields=["user", "occurred_at"], name="users_authe_user_id_idx"),
        ),
    ]
