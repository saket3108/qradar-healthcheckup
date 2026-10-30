"""Alembic migrations must build the same schema as the ORM models."""
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(db_url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "QHC_DATABASE_URL": db_url}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)


def test_upgrade_check_downgrade(tmp_path):
    url = f"sqlite:///{tmp_path}/m.db"
    up = _alembic(url, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    chk = _alembic(url, "check")
    assert chk.returncode == 0, chk.stdout + chk.stderr          # no model/migration drift
    down = _alembic(url, "downgrade", "base")
    assert down.returncode == 0, down.stderr
