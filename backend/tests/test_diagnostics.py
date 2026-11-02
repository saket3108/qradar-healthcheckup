"""Archive detection / diagnostics: valid, nested, partial and unsupported archives (+ the reported hotfix-bundle regression)."""
import gzip
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.ingestion.detect import UNSUPPORTED_MESSAGE, build_diagnostics, find_indicators
from app.ingestion.safe_extract import SafeExtractor, sniff

DEPLOYMENT = b"<?xml version='1.0'?><deployment><hosts/></deployment>"


def mk_tar(path: Path, members: dict, gz: bool = True) -> Path:
    with tarfile.open(path, "w:gz" if gz else "w") as tf:
        for n, d in members.items():
            ti = tarfile.TarInfo(n)
            ti.size = len(d)
            tf.addfile(ti, io.BytesIO(d))
    return path


def diagnose(archive: Path, out: Path):
    res = SafeExtractor(out, Settings()).extract(archive)
    d = build_diagnostics(res.manifest, source_name=archive.name, archive_type=sniff(archive), total_members=res.total_members,
                          bytes_seen=res.total_bytes_seen)
    return res, d


GET_LOGS = {
    "get_logs/10.0.0.1/deployment.xml": DEPLOYMENT,
    "get_logs/10.0.0.1/VERSION": b"7.5.0 build 2024\n",
    "get_logs/10.0.0.1/hostcontext.log": b"x\n",
    "get_logs/10.0.0.1/df": b"Filesystem Size Used\n",
    "get_logs/10.0.0.1/postgres/notification_view.copy": b"id\tseverity\n",
    "get_logs/10.0.0.1/var/log/qradar.error": b"error\n",
}

HOTFIX = {
    "QRADAR-36266-hotfix-non-QIF/QRADAR-36266.sh": b"#!/bin/bash\necho patch\n",
    "QRADAR-36266-hotfix-non-QIF/install.sh": b"#!/bin/bash\n",
    "QRADAR-36266-hotfix-non-QIF/install_on_all_hosts.sh": b"#!/bin/bash\n",
    "QRADAR-36266-hotfix-non-QIF/signed-rpms.tar.gz": b"",     # replaced with a real nested tarball in fixtures
}


def hotfix_bundle(tmp_path: Path) -> Path:
    inner = mk_tar(tmp_path / "signed-rpms.tar.gz", {"signed-rpms/php82-php-8.2.1.x86_64.rpm": b"\xed\xab\xee\xdb" + b"0" * 50,
                                                      "signed-rpms/php82-php-8.2.1.x86_64.rpm.sha256": b"abc\n",
                                                      "signed-rpms/libaom-3.1.rpm": b"\xed\xab\xee\xdb" + b"1" * 50})
    members = dict(HOTFIX)
    members["QRADAR-36266-hotfix-non-QIF/signed-rpms.tar.gz"] = inner.read_bytes()
    return mk_tar(tmp_path / "QRADAR-QRSIEM-202610221930INT-HF.tgz", members)


# ---------------------------------------------------------------- 1. valid get_logs
def test_valid_get_logs_is_supported_and_standard(tmp_path):
    res, d = diagnose(mk_tar(tmp_path / "g.tar.gz", GET_LOGS), tmp_path / "o")
    assert d["supported"] and d["layout"] == "standard" and d["message"] is None
    assert {"deployment_xml", "version_file", "hostcontext", "postgres_dump", "qradar_logs"} <= set(d["indicators"])
    assert d["detected_kind"] == "QRadar get_logs package" and res.files


# ---------------------------------------------------------------- 2. nested get_logs
def test_nested_tgz_inside_tgz_is_extracted_and_detected(tmp_path):
    inner = mk_tar(tmp_path / "inner.tgz", GET_LOGS)
    outer = mk_tar(tmp_path / "outer.tar.gz", {"support/get_logs_host1.tgz": inner.read_bytes(), "support/readme.txt": b"hi"})
    res, d = diagnose(outer, tmp_path / "o")
    assert d["supported"] and d["layout"] == "standard"
    assert d["nested_archives"] == ["support/get_logs_host1.tgz"]
    assert any(f.rel_path.endswith("deployment.xml") for f in res.files)


def test_nested_plain_tar_and_zip_are_followed(tmp_path):
    t = mk_tar(tmp_path / "i.tar", {"a/deployment.xml": DEPLOYMENT}, gz=False)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("b/VERSION", "7.4.3\n")
        z.writestr("b/hostcontext.xml", "<x/>")
    outer = mk_tar(tmp_path / "o.tar.gz", {"in.tar": t.read_bytes(), "in.zip": buf.getvalue()})
    _, d = diagnose(outer, tmp_path / "out")
    assert d["supported"] and sorted(d["nested_archives"]) == ["in.tar", "in.zip"]


# ---------------------------------------------------------------- 3. partial QRadar archive
def test_partial_archive_continues_with_warning_layout(tmp_path):
    arch = mk_tar(tmp_path / "p.tar.gz", {"misc/VERSION": b"7.5.0\n", "misc/notes.txt": b"x"})
    _, d = diagnose(arch, tmp_path / "o")
    assert d["supported"] is True          # indicators found -> analysis continues instead of failing
    assert d["layout"] == "partial" and d["message"] is None
    assert "version_file" in d["indicators"]


def test_single_hostcontext_file_is_enough(tmp_path):
    _, d = diagnose(mk_tar(tmp_path / "p.tar.gz", {"x/hostcontext.log": b"x"}), tmp_path / "o")
    assert d["supported"] and d["layout"] == "partial"


# ---------------------------------------------------------------- 4. unsupported archive
def test_unsupported_archive_returns_diagnostics_not_an_exception(tmp_path):
    arch = mk_tar(tmp_path / "u.tar.gz", {"photos/a.jpg": b"\xff\xd8", "docs/readme.txt": b"hello", "top.bin": b"1"})
    res, d = diagnose(arch, tmp_path / "o")
    assert d["supported"] is False and d["layout"] == "unsupported"
    assert d["message"] == UNSUPPORTED_MESSAGE
    assert d["total_members"] == 3 and d["indicators"] == {}
    assert {r["name"] for r in d["root_folders"]} == {"photos", "docs"} and d["top_level_files"] == ["top.bin"]
    assert len(d["sample_files"]) == 3 and d["guidance"]


# ---------------------------------------------------------------- regression: the reported file
def test_hotfix_bundle_is_reported_as_patch_not_get_logs(tmp_path):
    res, d = diagnose(hotfix_bundle(tmp_path), tmp_path / "o")
    assert d["supported"] is False, d["indicators"]
    assert d["identifier"] == "QRADAR-36266"
    assert "hotfix" in d["detected_kind"].lower()
    assert d["nested_archives"] == ["QRADAR-36266-hotfix-non-QIF/signed-rpms.tar.gz"]
    assert d["extensions"].get(".sh") == 3 and d["extensions"].get(".rpm") == 2
    assert d["root_folders"][0]["name"] == "QRADAR-36266-hotfix-non-QIF"


# ---------------------------------------------------------------- helpers
def test_sample_files_capped_at_100(tmp_path):
    arch = mk_tar(tmp_path / "big.tar.gz", {f"d/f{i}.bin": b"x" for i in range(150)})
    _, d = diagnose(arch, tmp_path / "o")
    assert len(d["sample_files"]) == 100 and d["total_members"] == 150


def test_find_indicators_caps_hits_and_matches_variants():
    paths = [f"h/tomcat/catalina.out.{i}" for i in range(9)] + ["x/ariel/db", "opt/qradar/conf/x.conf", "sar/sa12.gz", "a/WinCollect/agent.txt"]
    f = find_indicators(paths)
    assert len(f["tomcat_logs"]) == 5
    assert {"ariel_data", "qradar_config", "sar_data", "wincollect"} <= set(f)


def test_rpm_only_and_script_only_kinds(tmp_path):
    _, d = diagnose(mk_tar(tmp_path / "r.tar.gz", {"x/a.rpm": b"1"}), tmp_path / "o1")
    assert d["detected_kind"] == "RPM package bundle"
    _, d = diagnose(mk_tar(tmp_path / "s.tar.gz", {"x/a.sh": b"1"}), tmp_path / "o2")
    assert d["detected_kind"] == "Script bundle"
    _, d = diagnose(mk_tar(tmp_path / "t.tar.gz", {"x/a.dat": b"1"}), tmp_path / "o3")
    assert d["detected_kind"] == "Unrecognised archive"


def test_plain_gz_of_non_qradar_text_is_unsupported(tmp_path):
    p = tmp_path / "notes.txt.gz"
    p.write_bytes(gzip.compress(b"just some text"))
    res, d = diagnose(p, tmp_path / "o")
    assert d["archive_type"] == "gz" and d["supported"] is False


def test_no_hard_fail_message_left_in_codebase():
    root = Path(__file__).resolve().parents[1] / "app"
    offenders = [str(f) for f in root.rglob("*.py") if "No analysable files were found" in f.read_text()]
    assert offenders == []


# ---------------------------------------------------------------- end-to-end through the API / pipeline
def _upload_and_run(client, headers, path: Path, name: str):
    from app.pipeline import dispatch
    with open(path, "rb") as fh:
        up = client.post("/api/uploads/direct", files={"file": (name, fh, "application/gzip")}, headers=headers)
    assert up.status_code == 201, up.text
    a = client.post("/api/assessments", json={"upload_id": up.json()["upload_id"], "customer_name": "Diag"}, headers=headers).json()
    dispatch.wait_idle(120)
    return a["id"], client.get(f"/api/assessments/{a['id']}", headers=headers).json()


def test_api_hotfix_upload_ends_unsupported_with_diagnostics(client, admin_headers, tmp_path):
    aid, d = _upload_and_run(client, admin_headers, hotfix_bundle(tmp_path), "QRADAR-QRSIEM-202610221930INT-HF.tgz")
    assert d["status"] == "unsupported" and d["error"] == UNSUPPORTED_MESSAGE
    assert d["overall_score"] is None and d["summary"] is None            # never a fabricated score
    by = {s["name"]: s for s in d["stages"]}
    assert by["extract"]["status"] == "done" and by["deployment"]["status"] == "skipped" and by["summary"]["status"] == "skipped"
    diag = client.get(f"/api/assessments/{aid}/diagnostics", headers=admin_headers).json()
    assert diag["supported"] is False and diag["identifier"] == "QRADAR-36266" and diag["sample_files"]
    assert client.get(f"/api/assessments/{aid}/overview", headers=admin_headers).status_code == 409
    # resume re-evaluates and lands in the same state (idempotent, no crash)
    from app.pipeline import dispatch
    assert client.post(f"/api/assessments/{aid}/resume", headers=admin_headers).status_code == 200
    dispatch.wait_idle(120)
    assert client.get(f"/api/assessments/{aid}", headers=admin_headers).json()["status"] == "unsupported"
    assert client.delete(f"/api/assessments/{aid}", headers=admin_headers).status_code == 204


def test_api_partial_archive_continues_through_pipeline(client, admin_headers, tmp_path):
    arch = mk_tar(tmp_path / "partial.tar.gz", {"misc/VERSION": b"7.5.0\n", "misc/hostcontext.log": b"x\n"})
    aid, d = _upload_and_run(client, admin_headers, arch, "partial.tar.gz")
    assert d["status"] in ("completed", "partial"), d
    diag = client.get(f"/api/assessments/{aid}/diagnostics", headers=admin_headers).json()
    assert diag["supported"] and diag["layout"] == "partial"
    assert client.delete(f"/api/assessments/{aid}", headers=admin_headers).status_code == 204


def test_api_valid_and_nested_get_logs_still_complete(client, admin_headers, sample_bundle, tmp_path):
    aid, d = _upload_and_run(client, admin_headers, sample_bundle, "troubled.tar.gz")
    assert d["status"] in ("completed", "partial") and d["overall_score"] is not None
    assert client.get(f"/api/assessments/{aid}/diagnostics", headers=admin_headers).json()["layout"] == "standard"
    outer = mk_tar(tmp_path / "outer.tgz", {"wrapper/inner.tgz": sample_bundle.read_bytes()})
    aid2, d2 = _upload_and_run(client, admin_headers, outer, "wrapped.tgz")
    assert d2["status"] in ("completed", "partial") and d2["overall_score"] is not None


def test_diagnostics_endpoint_requires_auth_and_404(client, admin_headers):
    assert client.get("/api/assessments/nope/diagnostics", headers=admin_headers).status_code == 404
    assert client.get("/api/assessments/nope/diagnostics").status_code in (401, 403)


# ---------------------------------------------------------------- corrupt / fake nested archives must not abort the job
def test_fake_nested_archive_is_kept_as_plain_file(tmp_path):
    """macOS AppleDouble stubs (._x.tgz) and truncated copies look like archives by name only."""
    arch = mk_tar(tmp_path / "o.tar.gz", {"pkg/._signed-rpms.tar.gz": b"\x00\x05\x16\x07 apple double", "pkg/bad.zip": b"not a zip",
                                          "pkg/trunc.tgz": gzip.compress(b"x" * 600)[:12], "pkg/install.sh": b"#!/bin/sh\n"})
    res, d = diagnose(arch, tmp_path / "o")
    assert d["total_members"] == 4 and d["nested_archives"] == [] and d["supported"] is False
    assert sum("could not be opened" in w for w in res.warnings) == 3


def test_security_errors_in_nested_archives_still_abort(tmp_path):
    from app.ingestion.safe_extract import ArchiveSecurityError
    evil = mk_tar(tmp_path / "evil.tgz", {"../../x.xml": b"x"})
    outer = mk_tar(tmp_path / "outer.tgz", {"a/evil.tgz": evil.read_bytes()})
    with pytest.raises(ArchiveSecurityError):
        SafeExtractor(tmp_path / "o", Settings()).extract(outer)
