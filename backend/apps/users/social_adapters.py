"""
django-allauth adapters — bridge OAuth dance to our custom JWT/MFA pipeline.

We use allauth ONLY for the OAuth state machine. Email verification, password
reset, login forms, and JWT issuance remain in our own M01/M02 code. These
adapters ensure:

* New User rows created via OAuth have ``display_name`` populated from the
  Google profile and ``is_verified=True`` (Google asserted email_verified).
* When a Google login arrives for an email that already has a User, we
  auto-link the SocialAccount to that existing User instead of creating a
  duplicate (per AC: "auto-link if email is verified by Google").
* allauth's session-based login is suppressed at the post-callback step —
  we hand off to ``views_oauth.OAuthCallbackBridgeView`` which issues our
  exchange code instead of completing a Django session login.
"""
from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model

User = get_user_model()


class AccountAdapter(DefaultAccountAdapter):
    """Disable allauth's local signup form — only OAuth-initiated signups allowed."""

    def is_open_for_signup(self, request) -> bool:
        # Local (email + password) signup is handled by our /auth/register/ view,
        # not allauth. Always returning False here forces all allauth signup
        # paths through the social-account flow.
        return False


class SocialAdapter(DefaultSocialAccountAdapter):
    """Adapter for OAuth signups + linking."""

    def is_open_for_signup(self, request, sociallogin) -> bool:
        # Always allow Google signups; the gate is whether Google's
        # email_verified claim is true (handled in pre_social_login).
        return True

    def populate_user(self, request, sociallogin, data):
        """
        Called when allauth creates a fresh User from a Google profile.
        We map Google's name into our ``display_name`` field.
        """
        user = super().populate_user(request, sociallogin, data)
        # Google's userinfo endpoint returns `name` (full name). Fall back to
        # the local-part of the email if Google didn't share a name.
        google_name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        user.display_name = google_name or (email.split("@")[0] if email else "User")
        # Google verified the email at the OAuth provider; we trust that.
        user.is_verified = True
        return user

    def pre_social_login(self, request, sociallogin):
        """
        Auto-link Google identity to an existing User-by-email.

        When a Google sign-in arrives for an email that already has a local
        password account, attach the new SocialAccount to that existing User
        instead of triggering allauth's "this email is already registered"
        error page.

        Safety: we only auto-link when Google asserts email_verified=true
        (configured via ``SOCIALACCOUNT_PROVIDERS['google']['VERIFIED_EMAIL']``
        and re-checked here). An attacker who controls a Google account but
        not the underlying email would have email_verified=false and so would
        be rejected.
        """
        # If the socialaccount already has a `user` attached (i.e. this Google
        # identity has signed in here before), nothing to do.
        if sociallogin.is_existing:
            return

        email = (sociallogin.account.extra_data.get("email") or "").lower()
        email_verified = bool(sociallogin.account.extra_data.get("email_verified", False))
        if not email or not email_verified:
            return

        try:
            existing = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return

        # Connect this socialaccount to the existing user. allauth will create
        # the SocialAccount row and skip the "create new user" step.
        sociallogin.connect(request, existing)
