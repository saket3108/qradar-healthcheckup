"""API tests: auth, RBAC, uploads, assessments, comments, findings, report config, exports, assistant, audit."""
import io
import zipfile

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# ------------------------------------------------------------------ health + auth
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_login_ok_and_me(client, admin_headers):
    r = client.get("/api/auth/me", headers=admin_headers)
    assert r.status_code == 200 and r.json()["role"] == "administrator"


def test_login_bad_password_and_unknown(client):
    assert client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password"}).status_code == 401


def test_login_lockout(client):
    from app.core.security import login_throttle
    for _ in range(10):
        client.post("/api/auth/login", json={"email": "lock@example.com", "password": "nope-nope-nope"})
    r = client.post("/api/auth/login", json={"email": "lock@example.com", "password": "nope-nope-nope"})
    assert r.status_code == 429
    login_throttle.reset("lock@example.com")


def test_unauthenticated_and_bad_token(client):
    assert client.get("/api/assessments").status_code == 401
    assert client.get("/api/assessments", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_query_token_auth(client, admin_headers):
    tok = admin_headers["Authorization"].split()[1]
    assert client.get(f"/api/auth/me?token={tok}").status_code == 200


def test_user_management_rbac(client, admin_headers, role_headers):
    assert client.get("/api/users", headers=role_headers["consultant"]).status_code == 403
    assert client.get("/api/users", headers=admin_headers).status_code == 200
    dup = client.post("/api/users", json={"email": "consultant@example.com", "password": "Password12345", "role": "consultant"}, headers=admin_headers)
    assert dup.status_code == 409
    weak = client.post("/api/users", json={"email": "weak@example.com", "password": "short", "role": "consultant"}, headers=admin_headers)
    assert weak.status_code == 422


def test_user_update_and_self_protection(client, admin_headers, role_headers):
    users = client.get("/api/users", headers=admin_headers).json()
    me = next(u for u in users if u["email"] == "admin@example.com")
    other = next(u for u in users if u["email"] == "read_only@example.com")
    assert client.patch(f"/api/users/{me['id']}", json={"is_active": False}, headers=admin_headers).status_code == 400
    assert client.patch(f"/api/users/{me['id']}", json={"role": "read_only"}, headers=admin_headers).status_code == 400
    r = client.patch(f"/api/users/{other['id']}", json={"full_name": "RO User", "password": "NewPassword12345"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["full_name"] == "RO User"
    assert client.patch("/api/users/does-not-exist", json={"full_name": "x"}, headers=admin_headers).status_code == 404
    # password change took effect
    assert client.post("/api/auth/login", json={"email": "read_only@example.com", "password": "NewPassword12345"}).status_code == 200


def test_disabled_user_rejected(client, admin_headers):
    r = client.post("/api/users", json={"email": "gone@example.com", "password": "Password12345", "role": "read_only"}, headers=admin_headers)
    uid = r.json()["id"]
    tok = client.post("/api/auth/login", json={"email": "gone@example.com", "password": "Password12345"}).json()["access_token"]
    client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=admin_headers)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "gone@example.com", "password": "Password12345"}).status_code == 401


# ------------------------------------------------------------------ uploads
def test_upload_rbac_and_validation(client, role_headers, admin_headers):
    body = {"filename": "x.tar.gz", "size": 10}
    assert client.post("/api/uploads", json=body, headers=role_headers["read_only"]).status_code == 403
    assert client.post("/api/uploads", json=body, headers=role_headers["manager"]).status_code == 403
    assert client.post("/api/uploads", json={"filename": "evil.exe", "size": 10}, headers=admin_headers).status_code == 400
    assert client.post("/api/uploads", json={"filename": "x.tar", "size": 0}, headers=admin_headers).status_code == 413
    assert client.post("/api/uploads", json={"filename": "x.tar", "size": 10**15}, headers=admin_headers).status_code == 413


def test_upload_filename_sanitised(client, admin_headers):
    r = client.post("/api/uploads", json={"filename": "../../etc/passwd.tar.gz", "size": 5}, headers=admin_headers)
    assert r.status_code == 201
    st = client.get(f"/api/uploads/{r.json()['upload_id']}", headers=admin_headers).json()
    assert "/" not in st["filename"] and ".." not in st["filename"]


def test_chunked_upload_flow_and_resume(client, admin_headers, sample_bundle):
    data = sample_bundle.read_bytes()
    init = client.post("/api/uploads", json={"filename": "chunked.tar.gz", "size": len(data)}, headers=admin_headers).json()
    uid = init["upload_id"]
    half = len(data) // 2
    r = client.put(f"/api/uploads/{uid}?offset=0", content=data[:half], headers=admin_headers)
    assert r.status_code == 200 and r.json()["received"] == half and not r.json()["complete"]
    # incomplete cannot be completed
    assert client.post(f"/api/uploads/{uid}/complete", headers=admin_headers).status_code == 409
    # wrong offset -> 409 with server-side progress for resume
    bad = client.put(f"/api/uploads/{uid}?offset=5", content=b"abc", headers=admin_headers)
    assert bad.status_code == 409 and bad.json()["detail"]["received"] == half
    st = client.get(f"/api/uploads/{uid}", headers=admin_headers).json()
    assert st["received"] == half
    r = client.put(f"/api/uploads/{uid}?offset={st['received']}", content=data[half:], headers=admin_headers)
    assert r.json()["complete"]
    done = client.post(f"/api/uploads/{uid}/complete", headers=admin_headers)
    assert done.status_code == 200 and len(done.json()["sha256"]) == 64
    # cannot write to a completed upload
    assert client.put(f"/api/uploads/{uid}?offset=0", content=b"x", headers=admin_headers).status_code == 404


def test_chunk_exceeding_declared_size(client, admin_headers):
    uid = client.post("/api/uploads", json={"filename": "s.tar", "size": 4}, headers=admin_headers).json()["upload_id"]
    assert client.put(f"/api/uploads/{uid}?offset=0", content=b"too long", headers=admin_headers).status_code == 413


def test_upload_not_found_and_foreign(client, admin_headers, role_headers):
    assert client.get("/api/uploads/nope", headers=admin_headers).status_code == 404
    assert client.post("/api/uploads/nope/complete", headers=admin_headers).status_code == 404
    uid = client.post("/api/uploads", json={"filename": "s.tar", "size": 4}, headers=admin_headers).json()["upload_id"]
    assert client.put(f"/api/uploads/{uid}?offset=0", content=b"abcd", headers=role_headers["consultant"]).status_code == 403


def test_direct_upload_rejects_bad_type(client, admin_headers):
    r = client.post("/api/uploads/direct", files={"file": ("a.txt", b"hello", "text/plain")}, headers=admin_headers)
    assert r.status_code == 400


def test_create_assessment_requires_complete_upload(client, admin_headers):
    assert client.post("/api/assessments", json={"upload_id": "nope"}, headers=admin_headers).status_code == 400
    uid = client.post("/api/uploads", json={"filename": "s.tar", "size": 4}, headers=admin_headers).json()["upload_id"]
    assert client.post("/api/assessments", json={"upload_id": uid}, headers=admin_headers).status_code == 400


def test_malicious_zip_slip_fails_job(client, admin_headers):
    from app.pipeline import dispatch
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../evil.txt", "pwned")
    up = client.post("/api/uploads/direct", files={"file": ("evil.zip", buf.getvalue(), "application/zip")}, headers=admin_headers).json()
    a = client.post("/api/assessments", json={"upload_id": up["upload_id"], "customer_name": "Evil"}, headers=admin_headers).json()
    dispatch.wait_idle(60)
    d = client.get(f"/api/assessments/{a['id']}", headers=admin_headers).json()
    assert d["status"] == "failed" and d["error"]
    # results not accessible, and retry is allowed
    assert client.get(f"/api/assessments/{a['id']}/overview", headers=admin_headers).status_code == 409
    assert client.post(f"/api/assessments/{a['id']}/resume?from_stage=bogus", headers=admin_headers).status_code == 400
    assert client.delete(f"/api/assessments/{a['id']}", headers=admin_headers).status_code == 204


# ------------------------------------------------------------------ assessments + data endpoints
def test_assessment_listing_and_detail(client, admin_headers, completed_assessment):
    lst = client.get("/api/assessments", headers=admin_headers).json()
    assert any(a["id"] == completed_assessment for a in lst)
    assert client.get("/api/assessments?q=ACME", headers=admin_headers).json()
    assert client.get("/api/assessments?q=zzzzzz", headers=admin_headers).json() == []
    assert all(a["status"] == "completed" for a in client.get("/api/assessments?status=completed", headers=admin_headers).json())
    d = client.get(f"/api/assessments/{completed_assessment}", headers=admin_headers).json()
    assert d["overall_score"] is not None and d["stages"]
    assert client.get("/api/assessments/nope", headers=admin_headers).status_code == 404


@pytest.mark.parametrize("path,keys", [
    ("overview", ["environment", "topology", "logsources", "wincollect", "applications", "licensing", "autoupdate", "scores"]),
    ("deployment", ["topology", "checks", "environment"]),
    ("logsources-analysis", ["logsources", "wincollect"]),
    ("licensing", ["licensing"]),
    ("performance", ["hosts", "assessments"]),
    ("health", ["scores", "summary", "top_recommendations"]),
])
def test_data_endpoints(client, admin_headers, completed_assessment, path, keys):
    r = client.get(f"/api/assessments/{completed_assessment}/{path}", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in keys:
        assert k in body
    assert any(body[k] for k in keys)


def test_health_content(client, admin_headers, completed_assessment):
    h = client.get(f"/api/assessments/{completed_assessment}/health", headers=admin_headers).json()
    assert 0 <= h["scores"]["overall"]["score"] <= 100
    assert len(h["top_recommendations"]) == 10
    assert set(h["scores"]["categories"]) >= {"deployment", "notifications", "logsources", "applications", "performance", "licensing", "wincollect"}


def test_notifications_endpoint_filters(client, admin_headers, completed_assessment):
    base = f"/api/assessments/{completed_assessment}/notifications"
    allr = client.get(base, headers=admin_headers).json()
    assert allr["items"]
    sev = allr["items"][0]["effective_severity"]
    only = client.get(f"{base}?severity={sev}", headers=admin_headers).json()["items"]
    assert only and all(i["effective_severity"] == sev for i in only)
    assert client.get(f"{base}?q=zzzzqqq", headers=admin_headers).json()["items"] == []
    item = allr["items"][0]
    for k in ("root_cause", "recommendation", "best_practice", "business_impact", "risk"):
        assert k in item


def test_applications_endpoint(client, admin_headers, completed_assessment):
    r = client.get(f"/api/assessments/{completed_assessment}/applications", headers=admin_headers).json()
    assert r["items"] and "comment" in r["items"][0]


# ------------------------------------------------------------------ comments + findings
def test_comments_roundtrip_with_rbac(client, admin_headers, role_headers, completed_assessment):
    aid = completed_assessment
    nid = client.get(f"/api/assessments/{aid}/notifications", headers=admin_headers).json()["items"][0]["id"]
    url = f"/api/assessments/{aid}/comments/notification/{nid}"
    assert client.put(url, json={"text": "nope"}, headers=role_headers["read_only"]).status_code == 403
    assert client.put(url, json={"text": "Customer is aware"}, headers=role_headers["consultant"]).status_code == 200
    assert client.put(url, json={"text": "Customer is aware - ticket raised"}, headers=admin_headers).status_code == 200
    items = client.get(f"/api/assessments/{aid}/notifications", headers=admin_headers).json()["items"]
    assert next(i for i in items if i["id"] == nid)["comment"] == "Customer is aware - ticket raised"
    lst = client.get(f"/api/assessments/{aid}/comments?target_type=notification", headers=admin_headers).json()
    assert any(c["target_key"] == str(nid) for c in lst)
    assert client.put(f"/api/assessments/{aid}/comments/bogus/1", json={"text": "x"}, headers=admin_headers).status_code == 400
    assert client.put(f"/api/assessments/nope/comments/notification/1", json={"text": "x"}, headers=admin_headers).status_code == 404
    # comments with slashes in key
    assert client.put(f"/api/assessments/{aid}/comments/logsource/Syslog/Windows/1", json={"text": "slash"}, headers=admin_headers).status_code == 200


def test_findings_list_filter_and_update_rescores(client, admin_headers, role_headers, completed_assessment):
    aid = completed_assessment
    fl = client.get(f"/api/assessments/{aid}/findings", headers=admin_headers).json()
    assert fl and fl[0]["severity"] == "critical"
    crit = client.get(f"/api/assessments/{aid}/findings?severity=critical", headers=admin_headers).json()
    assert crit and all(f["severity"] == "critical" for f in crit)
    cat = fl[0]["category"]
    assert all(f["category"] == cat for f in client.get(f"/api/assessments/{aid}/findings?category={cat}", headers=admin_headers).json())

    before = client.get(f"/api/assessments/{aid}/health", headers=admin_headers).json()["scores"]["overall"]["score"]
    fid = crit[0]["id"]
    assert client.patch(f"/api/assessments/{aid}/findings/{fid}", json={"status": "accepted"}, headers=role_headers["read_only"]).status_code == 403
    assert client.patch(f"/api/assessments/{aid}/findings/nope", json={"status": "accepted"}, headers=admin_headers).status_code == 404
    for f in crit:   # dismiss all criticals -> score must improve
        assert client.patch(f"/api/assessments/{aid}/findings/{f['id']}", json={"status": "dismissed"}, headers=admin_headers).status_code == 200
    after = client.get(f"/api/assessments/{aid}/health", headers=admin_headers).json()["scores"]["overall"]["score"]
    assert after > before
    # restore for downstream tests
    for f in crit:
        client.patch(f"/api/assessments/{aid}/findings/{f['id']}", json={"status": "open"}, headers=admin_headers)
    restored = client.get(f"/api/assessments/{aid}/health", headers=admin_headers).json()["scores"]["overall"]["score"]
    assert restored == before


def test_update_assessment_metadata(client, admin_headers, role_headers, completed_assessment):
    aid = completed_assessment
    assert client.patch(f"/api/assessments/{aid}", json={"customer_name": "X"}, headers=role_headers["read_only"]).status_code == 403
    r = client.patch(f"/api/assessments/{aid}", json={"customer_name": "ACME Corp"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["customer_name"] == "ACME Corp"


# ------------------------------------------------------------------ report config + logo
def test_report_config_roundtrip(client, admin_headers, role_headers, completed_assessment):
    aid = completed_assessment
    cfg = client.get(f"/api/assessments/{aid}/report-config", headers=admin_headers).json()
    assert len(cfg["available_sections"]) >= 10 and cfg["config"]["sections"]
    secs = ["cover", "executive_summary", "health_score"]
    r = client.put(f"/api/assessments/{aid}/report-config", json={"sections": secs, "notes": "Prepared for QBR", "customer_name": "ACME Corp", "consultant_name": "Jane Doe"}, headers=admin_headers)
    assert r.status_code == 200
    cfg = client.get(f"/api/assessments/{aid}/report-config", headers=admin_headers).json()["config"]
    assert cfg["sections"] == secs and cfg["notes"] == "Prepared for QBR"
    assert client.put(f"/api/assessments/{aid}/report-config", json={"sections": ["bogus"]}, headers=admin_headers).status_code == 422
    assert client.put(f"/api/assessments/{aid}/report-config", json={"notes": "x"}, headers=role_headers["read_only"]).status_code == 403
    client.put(f"/api/assessments/{aid}/report-config", json={"sections": cfg_all(client, admin_headers, aid)}, headers=admin_headers)


def cfg_all(client, headers, aid):
    return [s["key"] for s in client.get(f"/api/assessments/{aid}/report-config", headers=headers).json()["available_sections"]]


def test_logo_upload_validation(client, admin_headers, role_headers, completed_assessment):
    aid = completed_assessment
    assert client.get(f"/api/assessments/{aid}/logo", headers=admin_headers).status_code == 404
    bad = client.post(f"/api/assessments/{aid}/logo", files={"file": ("logo.png", b"<svg onload=alert(1)>", "image/png")}, headers=admin_headers)
    assert bad.status_code == 400
    big = client.post(f"/api/assessments/{aid}/logo", files={"file": ("logo.png", PNG + b"0" * (2 * 1024 * 1024), "image/png")}, headers=admin_headers)
    assert big.status_code == 413
    assert client.post(f"/api/assessments/{aid}/logo", files={"file": ("logo.png", PNG, "image/png")}, headers=role_headers["read_only"]).status_code == 403
    ok = client.post(f"/api/assessments/{aid}/logo", files={"file": ("logo.png", PNG, "image/png")}, headers=admin_headers)
    assert ok.status_code == 200
    got = client.get(f"/api/assessments/{aid}/logo", headers=admin_headers)
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert client.get(f"/api/assessments/{aid}/report-config", headers=admin_headers).json()["has_logo"] is True


def test_knowledge_base_endpoint(client, admin_headers):
    kb = client.get("/api/knowledge-base", headers=admin_headers).json()
    assert len(kb) >= 30
    for e in kb:
        for k in ("description", "impact", "risk", "recommendation", "best_practice", "priority"):
            assert e[k]


# ------------------------------------------------------------------ assistant
@pytest.mark.parametrize("q,intent", [
    ("Why is health score low?", "why_score_low"),
    ("Show critical findings.", "critical"),
    ("Why is EPS high?", "eps_high"),
    ("What should customer fix first?", "fix_first"),
    ("Explain this notification.", "explain_notification"),
])
def test_assistant_intents(client, admin_headers, completed_assessment, q, intent):
    r = client.post(f"/api/assessments/{completed_assessment}/assistant", json={"message": q}, headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == intent and len(body["answer"]) > 40


def test_assistant_history_and_clear(client, admin_headers, role_headers, completed_assessment):
    aid = completed_assessment
    assert len(client.get(f"/api/assessments/{aid}/assistant", headers=admin_headers).json()) >= 2
    assert client.get(f"/api/assessments/{aid}/assistant", headers=role_headers["manager"]).json() == []
    assert client.delete(f"/api/assessments/{aid}/assistant", headers=admin_headers).status_code == 204
    assert client.get(f"/api/assessments/{aid}/assistant", headers=admin_headers).json() == []
    assert client.post(f"/api/assessments/{aid}/assistant", json={"message": ""}, headers=admin_headers).status_code == 422


# ------------------------------------------------------------------ exports
@pytest.mark.parametrize("fmt,magic", [("pdf", b"%PDF"), ("docx", b"PK"), ("pptx", b"PK")])
def test_exports(client, admin_headers, role_headers, completed_assessment, fmt, magic):
    aid = completed_assessment
    assert client.post(f"/api/assessments/{aid}/exports/{fmt}", headers=role_headers["read_only"]).status_code == 403
    r = client.post(f"/api/assessments/{aid}/exports/{fmt}", headers=role_headers["manager"])
    assert r.status_code == 200, r.text
    dl = client.get(r.json()["download"], headers=admin_headers)
    assert dl.status_code == 200 and dl.content.startswith(magic) and len(dl.content) > 5_000
    assert fmt in dl.headers["content-disposition"]
    lst = client.get(f"/api/assessments/{aid}/exports", headers=admin_headers).json()
    assert any(e["format"] == fmt for e in lst)


def test_export_bad_format_and_missing(client, admin_headers, completed_assessment):
    assert client.post(f"/api/assessments/{completed_assessment}/exports/xls", headers=admin_headers).status_code == 400
    assert client.post("/api/assessments/nope/exports/pdf", headers=admin_headers).status_code == 404
    assert client.get("/api/exports/nope/download", headers=admin_headers).status_code == 404


def test_export_respects_selected_sections(client, admin_headers, completed_assessment):
    aid = completed_assessment
    client.put(f"/api/assessments/{aid}/report-config", json={"sections": ["cover", "executive_summary"]}, headers=admin_headers)
    small = client.post(f"/api/assessments/{aid}/exports/pdf", headers=admin_headers).json()["size"]
    client.put(f"/api/assessments/{aid}/report-config", json={"sections": cfg_all(client, admin_headers, aid)}, headers=admin_headers)
    full = client.post(f"/api/assessments/{aid}/exports/pdf", headers=admin_headers).json()["size"]
    assert small < full


# ------------------------------------------------------------------ audit + delete
def test_audit_log(client, admin_headers, role_headers, completed_assessment):
    aid = completed_assessment
    assert client.get("/api/audit", headers=role_headers["consultant"]).status_code == 403
    rows = client.get(f"/api/audit?assessment_id={aid}", headers=role_headers["manager"]).json()
    actions = {r["action"] for r in rows}
    assert {"report_created", "report_modified", "comment_updated", "export_generated"} <= actions
    only = client.get("/api/audit?action=login", headers=admin_headers).json()
    assert only and all(r["action"] == "login" for r in only)


def test_resume_and_delete(client, admin_headers, role_headers, completed_assessment):
    from app.pipeline import dispatch
    aid = completed_assessment
    assert client.delete(f"/api/assessments/{aid}", headers=role_headers["consultant"]).status_code == 403
    r = client.post(f"/api/assessments/{aid}/resume?from_stage=findings", headers=role_headers["consultant"])
    assert r.status_code in (200, 409)
    dispatch.wait_idle(120)
    assert client.get(f"/api/assessments/{aid}", headers=admin_headers).json()["status"] in ("completed", "partial")
    assert client.delete(f"/api/assessments/{aid}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/assessments/{aid}", headers=admin_headers).status_code == 404
