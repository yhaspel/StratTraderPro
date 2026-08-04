"""Signals for the users app.

Currently:
- ``post_save`` on User creates a default UserProfile so callers can always
  rely on ``user.profile`` resolving without a 404. M02.
"""
from __future__ import annotations

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
