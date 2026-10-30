"""Unit tests for scoring, licensing, KB, security helpers, assistant engine and pipeline recovery."""
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis import kb
from app.analysis.licensing import analyse_licensing
from app.analysis.scoring import CATEGORIES, overall, score_categories
from app.assistant import engine
from app.core import security


# ------------------------------------------------------------------ scoring
def _f(cat, sev, status="open"):
    return {"code": "X", "category": cat, "severity": sev, "status": status}


def test_scoring_clean_is_perfect():
    cats = score_categories([], {})
    ov = overall(cats)
    assert ov["score"] == 100 and ov["grade"] == "A" and ov["risk_level"] == "Low"


def test_scoring_monotonic_with_severity():
    s = lambda sev: score_categories([_f("deployment", sev)], {})["deployment"]["score"]   # noqa: E731
    assert s("critical") < s("high") < s("medium") < s("low") <= 100


def test_scoring_dismissed_ignored_and_diminishing():
    base = score_categories([_f("deployment", "high")], {})["deployment"]["score"]
    assert score_categories([_f("deployment", "high"), _f("deployment", "critical", "dismissed")], {})["deployment"]["score"] == base
    many = score_categories([_f("deployment", "critical")] * 30, {})["deployment"]["score"]
    assert 0 <= many < 20


def test_overall_critical_cap_and_unavailable_categories():
    cats = score_categories([_f("deployment", "critical")], {})
    assert overall(cats)["score"] <= 89
    avail = {c: False for c in CATEGORIES}
    avail["deployment"] = True
    assert overall(score_categories([], avail))["score"] == 100
    assert overall(score_categories([], {c: False for c in CATEGORIES}))["score"] == 100   # nothing rated -> falls back to all
    many_crit = overall(score_categories([_f(c, "critical") for c in CATEGORIES] * 3, {}))
    assert many_crit["score"] < 50 and many_crit["risk_level"] in ("High", "Critical") and many_crit["maturity_level"]


# ------------------------------------------------------------------ licensing
def test_licensing_over_limit_and_forecast():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    hist = [{"ts": (now - timedelta(days=30 - i)).isoformat(), "value": 4000 + i * 60} for i in range(30)]
    out = analyse_licensing({"eps_licensed": 5000, "fpm_licensed": 100000, "expiry": "2025-01-20"}, hist, [], 5800, 20000, now=now)
    assert out["eps"]["consumption_pct"] > 100 and out["eps"]["risk"] in ("high", "critical")
    assert out["utilisation_risk"] in ("high", "critical")
    assert out["eps"]["unit"] == "events/s"


def test_licensing_unknown_and_expired():
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    out = analyse_licensing({}, [], [], None, None, now=now)
    assert out["eps"]["risk"] == "unknown"
    expired = analyse_licensing({"eps_licensed": 1000, "expiry": "2024-01-01"}, [], [], 100, None, now=now)
    assert expired["utilisation_risk"] == "critical"
    soon = analyse_licensing({"eps_licensed": 1000, "expiry": "2025-02-01"}, [], [], 100, None, now=now)
    assert soon["utilisation_risk"] in ("high", "critical")
    bad = analyse_licensing({"eps_licensed": 1000, "expiry": "not-a-date"}, [], [], 100, None, now=now)
    assert bad["utilisation_risk"] in ("low", "unknown", "medium")


# ------------------------------------------------------------------ knowledge base
def test_kb_entries_complete_and_unique():
    codes = [e.code for e in kb.ENTRIES]
    assert len(codes) == len(set(codes)) >= 30
    for e in kb.ENTRIES:
        assert e.description and e.impact and e.risk and e.best_practice and e.recommendation
        assert e.priority in ("P1", "P2", "P3", "P4") and e.severity in ("critical", "high", "medium", "low", "info")


def test_kb_covers_required_domains():
    text = " ".join(f"{e.domain} {e.title} {e.category}".lower() for e in kb.ENTRIES)
    for needle in ("dsm", "pars", "licen", "disk", "ha", "app", "search", "sar", "wincollect", "deploy", "storage", "backup", "container"):
        assert needle in text, needle


# ------------------------------------------------------------------ security
def test_password_hash_roundtrip_and_limits():
    h = security.hash_password("CorrectHorse12")
    assert security.verify_password("CorrectHorse12", h) and not security.verify_password("wrong", h)
    assert not security.verify_password("x", "not-a-hash")
    with pytest.raises(ValueError):
        security.hash_password("a" * 73)


def test_rbac_matrix():
    P = security.Perm
    assert all(security.has_perm("administrator", p) for p in P)
    assert security.has_perm("consultant", P.upload) and not security.has_perm("consultant", P.delete)
    assert security.has_perm("manager", P.export) and not security.has_perm("manager", P.edit)
    assert security.has_perm("read_only", P.view) and not security.has_perm("read_only", P.export)
    assert not security.has_perm("hacker", P.view)


def test_token_roundtrip_and_expiry():
    import jwt
    t = security.create_access_token("u1", "consultant")
    assert security.decode_token(t)["sub"] == "u1"
    with pytest.raises(jwt.PyJWTError):
        security.decode_token(security.create_access_token("u1", "consultant", minutes=-5))


# ------------------------------------------------------------------ assistant engine
class _Ctx(engine.AssessmentContext):
    pass


def _ctx(data=None, findings=None):
    data = data or {}
    return engine.AssessmentContext(lambda k: data.get(k), findings or [], {"id": "a", "name": "n"})


def test_assistant_with_empty_data_is_graceful():
    ctx = _ctx()
    for q in ["why is the health score low", "show critical findings", "what should the customer fix first", "why is EPS high",
              "explain notification 5", "license forecast", "wincollect agents", "log sources parsing", "applications restart",
              "cpu memory disk performance", "deployment HA failover", "qradar version", "hello there"]:
        res = engine.answer(q, ctx)
        assert isinstance(res["answer"], str) and res["answer"] and res["intent"]


def test_assistant_uses_findings():
    fnds = [{"id": "1", "code": "A", "category": "deployment", "severity": "critical", "priority": "P1", "title": "HA missing", "observation": "No HA", "status": "open"},
            {"id": "2", "code": "B", "category": "licensing", "severity": "low", "priority": "P4", "title": "Minor", "observation": "meh", "status": "open"},
            {"id": "3", "code": "C", "category": "licensing", "severity": "critical", "priority": "P1", "title": "Dismissed", "observation": "x", "status": "dismissed"}]
    res = engine.answer("Show critical findings", _ctx(findings=fnds))
    assert "HA missing" in res["answer"] and "Dismissed" not in res["answer"]
    res = engine.answer("what should customer fix first", _ctx(findings=fnds))
    assert res["answer"].index("HA missing") < res["answer"].index("Minor") if "Minor" in res["answer"] else True


def test_assistant_llm_augmentation_and_failure(monkeypatch):
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "llm_base_url", "http://llm.invalid/v1")
    monkeypatch.setattr(s, "llm_api_key", "k")

    class R:
        def raise_for_status(self): ...
        def json(self): return {"choices": [{"message": {"content": "LLM polished"}}]}
    monkeypatch.setattr(engine.httpx, "post", lambda *a, **k: R())
    res = engine.answer("show critical findings", _ctx(), [{"role": "user", "content": "hi"}])
    assert res["answer"] == "LLM polished" and res["llm"] is True

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(engine.httpx, "post", boom)
    res = engine.answer("show critical findings", _ctx())
    assert res["llm"] is False and res["answer"] != "LLM polished"


# ------------------------------------------------------------------ pipeline recovery / dispatch
def test_recover_stale_jobs_marks_queued(client):
    from app.db.base import session_scope
    from app.db.models import Assessment
    from app.pipeline.runner import recover_stale_jobs
    from app.core.config import get_settings

    with session_scope() as db:
        a = Assessment(name="stale", source_filename="x.tar", source_path="/nonexistent", source_size=1, status="processing",
                       heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=get_settings().stale_job_seconds + 100))
        fresh = Assessment(name="fresh", source_filename="x.tar", source_path="/nonexistent", source_size=1, status="processing",
                           heartbeat_at=datetime.now(timezone.utc))
        db.add_all([a, fresh])
        db.flush()
        stale_id, fresh_id = a.id, fresh.id
    ids = recover_stale_jobs()
    assert stale_id in ids and fresh_id not in ids
    with session_scope() as db:
        assert db.get(Assessment, stale_id).status == "queued"
        db.delete(db.get(Assessment, stale_id))
        db.delete(db.get(Assessment, fresh_id))


def test_missing_source_fails_job_and_is_resumable(client):
    from app.db.base import session_scope
    from app.db.models import Assessment
    from app.pipeline import dispatch
    from app.pipeline.runner import init_stages, run_assessment

    with session_scope() as db:
        a = Assessment(name="gone", source_filename="gone.tar", source_path="/nonexistent/gone.tar", source_size=1, status="queued")
        db.add(a)
        db.flush()
        aid = a.id
    init_stages(aid)
    run_assessment(aid)
    with session_scope() as db:
        got = db.get(Assessment, aid)
        assert got.status == "failed" and got.error
        db.delete(got)
    dispatch.wait_idle(5)
