"""Append-only + chain-linkage enforcement triggers (M10 §6.1, ADR-100).

Postgres-only. Vendor-guarded via ``RunPython`` — SQLite (tests/dev) skips
entirely; the Python verifier is what catches tampering there. On Postgres these
triggers are the PRIMARY enforcement on Railway's single-role database (they fire
for every role, including the table owner):

- ``audit_log_block_mutation``  BEFORE UPDATE OR DELETE → always RAISE.
- ``audit_log_check_link``       BEFORE INSERT → advisory-lock, reject a malformed
                                 self_hash and a prev_hash that doesn't match the
                                 current chain head (genesis = 64 zeros).

Reverse drops the triggers + functions with a loud notice — post-launch trigger
removal is runbook-gated, never casual.
"""
from django.db import migrations

_FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION audit_log_block_mutation_fn() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only; update/delete is blocked for every role';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION audit_log_check_link_fn() RETURNS trigger AS $$
DECLARE
    head_hash text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('audit_log'));
    IF NEW.self_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'audit_log.self_hash is malformed (expected 64 lowercase hex chars)';
    END IF;
    SELECT self_hash INTO head_hash FROM audit_log ORDER BY id DESC LIMIT 1;
    IF head_hash IS NULL THEN
        IF NEW.prev_hash <> repeat('0', 64) THEN
            RAISE EXCEPTION 'audit_log genesis prev_hash must be 64 zeros';
        END IF;
    ELSIF NEW.prev_hash <> head_hash THEN
        RAISE EXCEPTION 'audit_log chain linkage mismatch (prev_hash does not match head)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_block_mutation ON audit_log;
CREATE TRIGGER audit_log_block_mutation
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation_fn();

DROP TRIGGER IF EXISTS audit_log_check_link ON audit_log;
CREATE TRIGGER audit_log_check_link
    BEFORE INSERT ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_check_link_fn();
"""

_REVERSE_SQL = r"""
-- WARNING: dropping these triggers removes append-only enforcement on the audit
-- log. Runbook-gated only (docs/runbooks/audit-integrity-failure.md). Never casual.
DROP TRIGGER IF EXISTS audit_log_check_link ON audit_log;
DROP TRIGGER IF EXISTS audit_log_block_mutation ON audit_log;
DROP FUNCTION IF EXISTS audit_log_check_link_fn();
DROP FUNCTION IF EXISTS audit_log_block_mutation_fn();
"""


def _apply(sql):
    def _run(apps, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return
        # params=None → skip mogrify. The DDL contains dollar-quoted plpgsql with
        # ``%`` format specifiers (RAISE) that must not be treated as bind params.
        schema_editor.execute(sql, params=None)

    return _run


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_apply(_FORWARD_SQL), _apply(_REVERSE_SQL)),
    ]
