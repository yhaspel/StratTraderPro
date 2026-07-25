"""Refresh-token cookie helpers (P1-4).

The refresh token is delivered to browsers as an HttpOnly cookie and stripped
from the JSON body, so no XSS can read it (localStorage was exfiltratable). The
refresh/logout endpoints still accept the token in the request body as a
fallback for non-browser clients — the browser SPA never sees the value, so
this cannot reintroduce the exfiltration vector.

SameSite=Strict is the CSRF control: the cookie is never attached to cross-site
requests, so a hostile origin cannot trigger a rotation with the victim's cookie.
"""
from __future__ import annotations

from django.conf import settings

from .responses import ok


def _name() -> str:
    return getattr(settings, "REFRESH_COOKIE_NAME", "stp_refresh")


def _path() -> str:
    return getattr(settings, "REFRESH_COOKIE_PATH", "/api/v1/auth/")


def set_refresh_cookie(response, refresh: str) -> None:
    lifetime = settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
    response.set_cookie(
        _name(),
        refresh,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        secure=getattr(settings, "REFRESH_COOKIE_SECURE", False),
        samesite="Strict",
        path=_path(),
    )


def clear_refresh_cookie(response) -> None:
    response.delete_cookie(_name(), path=_path())


def read_refresh(request) -> str | None:
    """The refresh token for a rotation/logout: request body wins (non-browser /
    API clients), else the HttpOnly cookie (browser SPA)."""
    body = None
    try:
        body = request.data.get("refresh")
    except Exception:  # noqa: BLE001 — non-DRF request or unparsable body
        body = None
    return body or request.COOKIES.get(_name())


def token_pair_response(pair: dict, *, status: int = 200):
    """Return an ok() response with the access token + user in the body and the
    refresh token moved into the HttpOnly cookie (stripped from the body)."""
    data = dict(pair)
    refresh = data.pop("refresh", None)
    resp = ok(data, status=status)
    if refresh:
        set_refresh_cookie(resp, refresh)
    return resp
