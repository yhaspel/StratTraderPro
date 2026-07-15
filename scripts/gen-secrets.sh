#!/usr/bin/env bash
#
# gen-secrets.sh — generate the secrets a StratTraderPro instance needs.
#
# Emits two `KEY=value` lines on stdout, ready to paste into backend/.env:
#
#   SECRET_KEY   — Django secret key (64 hex chars). Signs sessions + JWTs.
#   FERNET_KEK   — Fernet key-encryption key (url-safe base64 of 32 bytes).
#                  Encrypts stored broker credentials + TOTP secrets at rest.
#                  MANDATORY in production (config.settings.prod hard-crashes
#                  without a real one).
#
# Both are read by `config/settings/prod.py`, which rejects the insecure dev
# defaults. `make setup` calls this for you; run it directly to rotate a key.
#
set -euo pipefail

if ! command -v openssl >/dev/null 2>&1; then
  echo "error: openssl not found — install it, or generate the keys manually:" >&2
  echo "  SECRET_KEY  = 64 random hex chars" >&2
  echo "  FERNET_KEK  = python -c \"import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())\"" >&2
  exit 1
fi

# 64 hex chars — no shell/dotenv-special characters to escape.
SECRET_KEY="$(openssl rand -hex 32)"

# A valid Fernet key: url-safe base64 of exactly 32 random bytes.
# openssl emits standard base64 (+/); translate to url-safe (-_) for Fernet.
FERNET_KEK="$(openssl rand -base64 32 | tr '+/' '-_')"

printf 'SECRET_KEY=%s\n' "$SECRET_KEY"
printf 'FERNET_KEK=%s\n' "$FERNET_KEK"
