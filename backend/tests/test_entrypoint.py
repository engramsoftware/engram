"""docker-entrypoint.sh secrets handling, run against temp dirs.

ENGRAM_APP_DIR / ENGRAM_DATA_DIR point the script at tmp_path, and a `python`
shim on PATH stands in for the server (`python main.py` just prints STARTED);
`python -c ...` still runs the real interpreter, so secrets are really generated.
The privilege drop only runs when an "engram" user exists, so it is skipped here.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docker-entrypoint.sh"
EXAMPLE = REPO / "backend" / ".env.example"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


@pytest.fixture
def box(tmp_path):
    app, data, bin_dir = tmp_path / "app", tmp_path / "data", tmp_path / "bin"
    for d in (app, data, bin_dir):
        d.mkdir()
    shutil.copy(EXAMPLE, app / ".env.example")
    shim = bin_dir / "python"
    shim.write_text(f'#!/bin/sh\n[ "$1" = main.py ] && {{ echo STARTED; exit 0; }}\nexec {sys.executable} "$@"\n')
    shim.chmod(0o755)
    return tmp_path


def run(box, **env):
    full = {
        **{k: v for k, v in os.environ.items() if k not in ("JWT_SECRET_KEY", "ENCRYPTION_KEY")},
        "ENGRAM_APP_DIR": str(box / "app"),
        "ENGRAM_DATA_DIR": str(box / "data"),
        "PATH": f"{box / 'bin'}:{os.environ['PATH']}",
        "HOME": str(box),
        **env,
    }
    return subprocess.run(["bash", str(SCRIPT)], env=full, capture_output=True, text=True)


def values(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, val = line.partition("=")
            out[key] = val
    return out


def secrets(box, where="data/secrets.env"):
    v = values(box / where)
    return v.get("JWT_SECRET_KEY"), v.get("ENCRYPTION_KEY")


def test_fresh_install_generates_and_recreate_keeps(box):
    r = run(box)
    assert r.returncode == 0 and "STARTED" in r.stdout, r.stderr
    jwt, enc = secrets(box)
    assert len(jwt) == 64 and len(enc) == 32
    assert secrets(box, "app/.env") == (jwt, enc)
    assert oct((box / "data/secrets.env").stat().st_mode)[-3:] == "600"

    (box / "app/.env").unlink()  # new container, same /data
    assert run(box).returncode == 0
    assert secrets(box, "app/.env") == (jwt, enc)


def test_restart_leaves_env_file_alone(box):
    run(box)
    before = (box / "app/.env").stat().st_mtime_ns
    assert run(box).returncode == 0
    assert (box / "app/.env").stat().st_mtime_ns == before


def test_old_container_secrets_are_kept_verbatim(box):
    # An image from before secrets.env, still in the same container
    (box / "app/.env").write_text("JWT_SECRET_KEY=a&b|c\\d\nENCRYPTION_KEY=old-enc\n")
    assert run(box).returncode == 0
    assert secrets(box) == ("a&b|c\\d", "old-enc")


def test_prerelease_engram_env_is_migrated(box):
    # The pre-release layout: secrets and settings in data/.engram.env (CRLF here)
    (box / "data/.engram.env").write_bytes(
        b"JWT_SECRET_KEY=legacy-jwt\r\nENCRYPTION_KEY=legacy-enc\r\nOPENAI_API_KEY=sk-kept\r\n")
    assert run(box).returncode == 0
    assert secrets(box) == ("legacy-jwt", "legacy-enc")
    assert values(box / "app/.env")["OPENAI_API_KEY"] == "sk-kept"


def test_secrets_file_wins_over_legacy(box):
    (box / "data/secrets.env").write_text("JWT_SECRET_KEY=new-jwt\nENCRYPTION_KEY=new-enc\n")
    (box / "data/.engram.env").write_text("JWT_SECRET_KEY=legacy-jwt\nENCRYPTION_KEY=legacy-enc\n")
    assert run(box).returncode == 0
    assert secrets(box, "app/.env") == ("new-jwt", "new-enc")


def test_environment_wins_and_is_not_persisted(box):
    r = run(box, JWT_SECRET_KEY="from-env", ENCRYPTION_KEY="from-env-2")
    assert r.returncode == 0 and "Generated" not in r.stdout
    assert secrets(box) == (None, None)


@pytest.mark.parametrize("crlf", [False, True])
def test_placeholders_are_never_used(box, crlf):
    example = (box / "app/.env.example").read_text()
    if crlf:
        (box / "app/.env.example").write_text(example.replace("\n", "\r\n"))
    (box / "data/secrets.env").write_text(
        "JWT_SECRET_KEY=change-me-to-a-random-secret-key\nENCRYPTION_KEY=change-me-to-a-random-32-char-key\n")
    assert run(box).returncode == 0
    for value in secrets(box) + secrets(box, "app/.env"):
        assert value and not value.startswith("change-me")


def test_symlinked_secrets_file_is_refused(box):
    target = box / "precious"
    target.write_text("do not touch\n")
    (box / "data/secrets.env").symlink_to(target)
    r = run(box)
    assert r.returncode == 1 and "symlink" in r.stderr
    assert target.read_text() == "do not touch\n"
