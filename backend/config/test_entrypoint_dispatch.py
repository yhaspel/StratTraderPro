"""M11 §7.0 / AC-11-14 — SERVICE_ROLE entrypoint-dispatch tests.

A pure subprocess test (no docker-in-docker): it drives docker/entrypoint.sh
under STP_ENTRYPOINT_DRY_RUN=1 and asserts each role resolves to its **pinned
command literal** in docker/entrypoint.expected — string equality, not merely
exit 0 (an exit-0 check passes for any dispatcher that prints anything; that is
the worthless self-report BUG-009 is made of).

The unset / bogus / web-dev-misconfig cases must exit NON-ZERO and never resolve
to `web` (or any role) — BUG-011's silent web-server substitution is exactly what
this dispatcher exists to convert into a loud crash.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.sh"
EXPECTED = REPO_ROOT / "docker" / "entrypoint.expected"

# The command literals contain no shell metacharacters that a container needs
# resolved at dry-run time; the dispatcher must print ${PORT} literally.
UNEXPANDED_PORT = "${PORT}"


def _expected_rows():
    """Parse entrypoint.expected: skip `#` comment lines and blank lines."""
    rows = []
    for line in EXPECTED.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        role, _, command = line.partition("|")
        rows.append((role, command))
    return rows


def _run(env_overrides, *, unset=()):
    env = {**os.environ}
    for key in ("SERVICE_ROLE", "STP_ENTRYPOINT_DRY_RUN", "RAILWAY_ENVIRONMENT_NAME", *unset):
        env.pop(key, None)
    env.update(env_overrides)
    return subprocess.run(  # noqa: S603 — fixed, trusted path (the repo's own entrypoint)
        [str(ENTRYPOINT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_expected_file_has_seven_data_rows():
    rows = _expected_rows()
    assert len(rows) == 7, f"expected exactly 7 pinned roles, got {len(rows)}: {[r[0] for r in rows]}"
    assert {r[0] for r in rows} == {
        "web", "web-dev", "worker", "worker-backtest", "beat", "streams", "ws",
    }


def test_expected_file_ends_with_newline():
    # A `while read` loop silently drops a final unterminated line (would skip ws).
    assert EXPECTED.read_bytes().endswith(b"\n")


@pytest.mark.parametrize("role,expected", _expected_rows(), ids=[r[0] for r in _expected_rows()])
def test_role_resolves_to_pinned_literal(role, expected):
    result = _run({
        "STP_ENTRYPOINT_DRY_RUN": "1",
        "SERVICE_ROLE": role,
        "DJANGO_SETTINGS_MODULE": "config.settings.dev",
    })
    assert result.returncode == 0, f"role {role} exited {result.returncode}: {result.stderr}"
    assert result.stdout.strip() == expected, (
        f"role {role} resolved-command mismatch\n want: {expected!r}\n got : {result.stdout.strip()!r}"
    )


def test_ws_dry_run_keeps_port_unexpanded():
    # BUG-guard: an expanding dry-run would differ on host (PORT unset) vs
    # container (PORT=8777) and someone would "fix" it by weakening the assert.
    result = _run({
        "STP_ENTRYPOINT_DRY_RUN": "1",
        "SERVICE_ROLE": "ws",
        "DJANGO_SETTINGS_MODULE": "config.settings.dev",
        "PORT": "9999",
    })
    assert "${PORT:-8788}" in result.stdout
    assert "9999" not in result.stdout


def test_unset_role_exits_nonzero_and_never_defaults_to_web():
    result = _run({"STP_ENTRYPOINT_DRY_RUN": "1"})
    assert result.returncode != 0
    assert "gunicorn" not in result.stdout  # did NOT fall back to web
    assert "SERVICE_ROLE" in result.stderr


def test_bogus_role_exits_nonzero_and_never_defaults_to_web():
    result = _run({"STP_ENTRYPOINT_DRY_RUN": "1", "SERVICE_ROLE": "nonsense"})
    assert result.returncode != 0
    assert "gunicorn" not in result.stdout
    assert "nonsense" in result.stderr


def test_web_dev_refuses_non_dev_settings():
    result = _run({
        "STP_ENTRYPOINT_DRY_RUN": "1",
        "SERVICE_ROLE": "web-dev",
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    })
    assert result.returncode != 0
    assert "runserver" not in result.stdout


def test_web_dev_refuses_deployed_env():
    result = _run({
        "STP_ENTRYPOINT_DRY_RUN": "1",
        "SERVICE_ROLE": "web-dev",
        "DJANGO_SETTINGS_MODULE": "config.settings.dev",
        "RAILWAY_ENVIRONMENT_NAME": "production",
    })
    assert result.returncode != 0
    assert "runserver" not in result.stdout


def test_entrypoint_is_committed_executable():
    """The image CMD is exec-form; a non-exec entrypoint dies 'permission denied'."""
    git = shutil.which("git")
    if git:
        out = subprocess.run(  # noqa: S603 — fixed argv, git resolved via shutil.which
            [git, "ls-files", "-s", "docker/entrypoint.sh"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False,
        ).stdout.strip()
        if out:  # tracked — assert the committed mode
            assert out.split()[0] == "100755", f"entrypoint.sh committed mode is {out.split()[0]!r}, want 100755"
            return
    # Fallback (pre-commit / no git): filesystem exec bit.
    assert os.access(ENTRYPOINT, os.X_OK), "docker/entrypoint.sh is not executable"
