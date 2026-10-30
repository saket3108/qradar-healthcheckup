import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_tmp = tempfile.mkdtemp(prefix="qhc_test_")
os.environ.update({"QHC_DATABASE_URL": f"sqlite:///{_tmp}/test.db", "QHC_STORAGE_DIR": f"{_tmp}/storage", "QHC_ADMIN_EMAIL": "admin@example.com",
                   "QHC_ADMIN_PASSWORD": "AdminPass12345", "QHC_RUN_MODE": "inline", "QHC_SECRET_KEY": "test-secret-key-test-secret-key-12345", "QHC_PARSE_WORKERS": "1"})


@pytest.fixture(scope="session")
def sample_bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bundle") / "troubled.tar.gz"
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample_getlogs.py"), str(out), "--profile", "troubled"], check=True, capture_output=True)
    return out


@pytest.fixture(scope="session")
def healthy_bundle(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bundle2") / "healthy.tar.gz"
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample_getlogs.py"), str(out), "--profile", "healthy"], check=True, capture_output=True)
    return out


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "AdminPass12345"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def role_headers(client, admin_headers):
    out = {}
    for role in ("consultant", "manager", "read_only"):
        email = f"{role}@example.com"
        r = client.post("/api/users", json={"email": email, "password": "Password12345", "role": role, "full_name": role.title()}, headers=admin_headers)
        assert r.status_code == 201, r.text
        tok = client.post("/api/auth/login", json={"email": email, "password": "Password12345"}).json()["access_token"]
        out[role] = {"Authorization": f"Bearer {tok}"}
    return out


@pytest.fixture(scope="session")
def completed_assessment(client, admin_headers, sample_bundle):
    from app.pipeline import dispatch

    with open(sample_bundle, "rb") as fh:
        up = client.post("/api/uploads/direct", files={"file": ("troubled.tar.gz", fh, "application/gzip")}, headers=admin_headers)
    assert up.status_code == 201, up.text
    r = client.post("/api/assessments", json={"upload_id": up.json()["upload_id"], "customer_name": "ACME Corp", "consultant_name": "Jane Doe"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    dispatch.wait_idle(180)
    a = client.get(f"/api/assessments/{aid}", headers=admin_headers).json()
    assert a["status"] in ("completed", "partial"), a
    return aid
