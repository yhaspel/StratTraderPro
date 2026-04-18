"""Standard response envelope: { data?, error? }.

Codes (M01): USER_EXISTS, INVALID_CREDENTIALS, EMAIL_NOT_VERIFIED,
ACCOUNT_LOCKED, RATE_LIMITED, TOKEN_INVALID, TOKEN_EXPIRED, PASSWORD_WEAK.
"""
from rest_framework.response import Response


def ok(data=None, status=200, **headers):
    resp = Response({"data": data}, status=status)
    for k, v in headers.items():
        resp[k] = v
    return resp


def fail(code, message, *, status=400, details=None, **headers):
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    resp = Response(body, status=status)
    for k, v in headers.items():
        resp[k] = v
    return resp
