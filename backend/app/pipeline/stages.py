"""Pipeline stage implementations.  Each stage reads/writes assessment datasets through a ``Ctx``."""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.analysis import deployment as dep_an
from app.analysis import findings as fnd
from app.analysis import licensing as lic_an
from app.analysis import logsources as ls_an
from app.analysis import notifications as notif_an
from app.analysis import performance as perf_an
from app.analysis import scoring
from app.core.config import get_settings
from app.ingestion.safe_extract import SafeExtractor
from app.parsers import domain
from app.parsers.deployment import parse_deployment_xml
from app.parsers.tables import TableStore
from app.pipeline.collect import FileIndex, collect_host_perf, collect_misc

log = logging.getLogger(__name__)

STAGES: list[tuple[str, str, float]] = [
    ("extract", "Extract archive", 0.30),
    ("deployment", "Parse deployment", 0.06),
    ("database", "Analyze database dumps", 0.20),
    ("performance", "Analyze performance metrics", 0.10),
    ("applications", "Analyze applications", 0.04),
    ("wincollect", "Analyze WinCollect", 0.04),
    ("notifications", "Analyze notifications", 0.05),
    ("licensing", "Analyze licensing & auto update", 0.04),
    ("findings", "Generate AI findings", 0.07),
    ("recommendations", "Generate recommendations & health score", 0.05),
    ("summary", "Generate executive summary", 0.05),
]
STAGE_NAMES = [s[0] for s in STAGES]


class Ctx:
    """Execution context: data store accessors + progress reporting."""

    def __init__(self, assessment_id: str, workdir: Path, source: Path, load: Callable[[str], Any], save: Callable[[str, Any], None],
                 progress: Callable[[float, str | None], None], warn: Callable[[str], None]) -> None:
        self.id, self.workdir, self.source = assessment_id, workdir, source
        self.load, self.save, self.progress, self.warn = load, save, progress, warn
        self.extract_dir = workdir / "extracted"
        self._idx: FileIndex | None = None

    def index(self) -> FileIndex:
        if self._idx is None:
            manifest = self.load("manifest") or {}
            self._idx = FileIndex(self.extract_dir, manifest.get("entries", []))
        return self._idx


# ---------------------------------------------------------------------------
def stage_extract(ctx: Ctx) -> str:
    if ctx.extract_dir.exists():
        shutil.rmtree(ctx.extract_dir)       # idempotent restart
    last = [0.0]

    def prog(members: int, seen: int) -> None:
        now = time.monotonic()
        if now - last[0] > 1.0:
            last[0] = now
            ctx.progress(min(0.95, members / (members + 5000)), f"{members} members scanned")

    res = SafeExtractor(ctx.extract_dir, get_settings(), progress=prog).extract(ctx.source)
    for w in res.warnings:
        ctx.warn(w)
    cats = Counter(e["category"] for e in res.manifest)
    ctx.save("manifest", {"entries": [e for e in res.manifest if e.get("extracted")], "total_members": res.total_members,
                          "bytes_seen": res.total_bytes_seen, "bytes_extracted": res.total_bytes_extracted,
                          "categories": dict(cats), "security_events": res.security_events[:200],
                          "skipped": sum(1 for e in res.manifest if not e.get("extracted") and not e.get("nested"))})
    if res.security_events:
        ctx.warn(f"{len(res.security_events)} archive security event(s) recorded (links/duplicates skipped)")
    if not res.files:
        raise ValueError("No analysable files were found in the archive - is this a QRadar get_logs package?")
    return f"{len(res.files)} files extracted of {res.total_members}"


def stage_deployment(ctx: Ctx) -> str:
    idx = ctx.index()
    cands = [p for p in idx.by_cat.get("deployment", [])]
    dep: dict[str, Any] = {}
    best = None
    for p in cands:
        try:
            parsed = parse_deployment_xml(idx.read(p, 128 * 1024 * 1024))
        except OSError:
            continue
        parsed["file"] = p
        score = len(parsed.get("hosts", [])) + (1000 if "active" in p.lower() else 0) + (500 if "staging" not in p.lower() else 0)
        if best is None or score > best[0]:
            best = (score, parsed)
    if best:
        dep = best[1]
    else:
        ctx.warn("deployment.xml not found")
    ctx.save("deployment_xml", dep)
    misc = collect_misc(idx)
    ctx.save("misc", misc)
    return f"{len(dep.get('hosts', []))} hosts in deployment.xml"


def _load_file(args: tuple[str, str, list[str], int]) -> tuple[dict[str, list], dict[str, list[str]], int]:
    path, rel, wanted, max_rows = args
    store = TableStore(wanted, max_rows)
    n = store.load(Path(path), rel)
    return store.tables, store.sources, n


def stage_database(ctx: Ctx) -> str:
    idx = ctx.index()
    s = get_settings()
    files = [p for p in idx.by_cat.get("db_dump", []) + idx.by_cat.get("application", []) + idx.by_cat.get("wincollect", []) +
             idx.by_cat.get("logsource", []) + idx.by_cat.get("autoupdate", []) if not p.lower().endswith((".xml", ".json", ".conf", ".properties", ".yaml", ".yml"))]
    files = sorted(set(files))
    store_tables: dict[str, list] = {}
    sources: dict[str, list[str]] = {}
    jobs = [(str(ctx.extract_dir / p), p, domain.WANTED_TABLES, s.max_rows_per_table) for p in files]
    total_bytes = sum((ctx.extract_dir / p).stat().st_size for p in files if (ctx.extract_dir / p).exists())
    results = []
    if len(jobs) > 1 and total_bytes > 32 * 1024 * 1024 and s.parse_workers > 1:
        try:
            with ProcessPoolExecutor(max_workers=s.parse_workers) as ex:
                for i, r in enumerate(ex.map(_load_file, jobs, chunksize=1)):
                    results.append(r)
                    ctx.progress((i + 1) / len(jobs), f"parsed {i + 1}/{len(jobs)} dump files")
        except Exception as e:   # pragma: no cover - fallback path
            log.warning("parallel parse failed (%s); falling back to serial", e)
            results = []
    if not results:
        for i, j in enumerate(jobs):
            results.append(_load_file(j))
            if i % 5 == 0:
                ctx.progress((i + 1) / max(len(jobs), 1), f"parsed {i + 1}/{len(jobs)} dump files")
    for tables, srcs, _ in results:
        for t, rows in tables.items():
            store_tables.setdefault(t, []).extend(rows)
        for t, sr in srcs.items():
            sources.setdefault(t, []).extend(sr)
    # write compact raw cache for later stages
    raw = {t: rows[: s.max_rows_per_table] for t, rows in store_tables.items()}
    cache = ctx.workdir / "tables.json"
    cache.write_text(json.dumps(raw, default=str))
    ctx.save("table_index", {t: {"rows": len(r), "files": sources.get(t, [])[:5]} for t, r in raw.items()})
    if not raw:
        ctx.warn("No recognised QRadar database tables found in the bundle; table-driven sections will be empty")
    return f"{len(raw)} tables, {sum(len(r) for r in raw.values())} rows"


def _tables(ctx: Ctx) -> dict[str, list]:
    cache = ctx.workdir / "tables.json"
    return json.loads(cache.read_text()) if cache.exists() else {}


def _first(tbls: dict[str, list], *names: str) -> list:
    for n in names:
        if tbls.get(n):
            return tbls[n]
    return []


def stage_performance(ctx: Ctx) -> str:
    idx = ctx.index()
    perf_map = collect_host_perf(idx)
    all_hosts = perf_map.pop("__all__", {})
    ctx.save("host_perf", {k: _trim_perf(v) for k, v in all_hosts.items()})
    ctx.save("_perf_alias", {k: v.get("key") for k, v in perf_map.items()})
    if not all_hosts:
        ctx.warn("No system/sar data located; performance analysis limited")
    return f"{len(all_hosts)} host(s) with system data"


def _trim_perf(p: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in p.items()}


def stage_applications(ctx: Ctx) -> str:
    t = _tables(ctx)
    apps = domain.parse_applications(_first(t, "installed_application"), _first(t, "installed_application_instance"))
    ctx.save("applications_raw", apps)
    return f"{len(apps)} application records"


def stage_wincollect(ctx: Ctx) -> str:
    t = _tables(ctx)
    agents = domain.parse_wincollect(_first(t, "wincollect_agent", "wincollect_agents", "wincollect"))
    ctx.save("wincollect_raw", agents)
    return f"{len(agents)} agents"


def stage_notifications(ctx: Ctx) -> str:
    t = _tables(ctx)
    notifs = domain.parse_notifications(_first(t, "notification_view", "notification"))
    ctx.save("notifications_raw", notifs)
    types = {str(r.get("id")): r.get("name") or r.get("devicetypename") for r in t.get("sensordevicetype", [])}
    protos = {str(r.get("id")): r.get("name") or r.get("protocolname") for r in t.get("sensorprotocol", [])}
    ls = domain.parse_log_sources(t.get("sensordevice", []), types, protos)
    ctx.save("logsources_raw", ls)
    if not notifs:
        ctx.warn("notification_view not found or empty")
    return f"{len(notifs)} notifications, {len(ls)} log sources"


def stage_licensing(ctx: Ctx) -> str:
    t = _tables(ctx)
    lic_rows = []
    for n in ("license", "licensepool", "license_pool", "license_key", "licensekey", "host_license", "license_usage"):
        lic_rows += t.get(n, [])
    lic = domain.parse_licenses(lic_rows)
    eps_h = domain.parse_usage_history(_first(t, "eps_history", "eps_usage", "device_eps"), "eps")
    fpm_h = domain.parse_usage_history(_first(t, "fpm_history"), "fpm")
    au_text = ""
    for p in ctx.index().by_cat.get("autoupdate", [])[:8]:
        try:
            au_text += ctx.index().read(p, 2 * 1024 * 1024) + "\n"
        except OSError:
            pass
    au = domain.parse_autoupdate(_first(t, "auto_update_history", "autoupdate", "auto_update"), au_text)
    ctx.save("licensing_raw", {"license": lic, "eps_history": eps_h, "fpm_history": fpm_h})
    ctx.save("autoupdate", au)
    return f"EPS licensed={lic.get('eps_licensed')}, {len(eps_h)} usage points"


def stage_findings(ctx: Ctx) -> str:
    """Run all analysers and generate findings."""
    t = _tables(ctx)
    idx = ctx.index()
    dep = ctx.load("deployment_xml") or {}
    misc = ctx.load("misc") or {}
    host_perf = ctx.load("host_perf") or {}
    alias_map = ctx.load("_perf_alias") or {}
    perf_by_alias: dict[str, dict] = {}
    for a, key in alias_map.items():
        perf_by_alias[a] = host_perf.get(key) or {}
    mh_rows = domain.parse_hosts(_first(t, "managedhost", "managed_host"))
    notifs = ctx.load("notifications_raw") or []
    logsrc = ctx.load("logsources_raw") or []

    notif_hosts = Counter()
    for n in notifs:
        if n.get("status") not in ("closed",):
            notif_hosts[n.get("host")] += 1
            notif_hosts[n.get("host_ip")] += 1
    eps_by_host: dict[str, float] = {}
    for s in logsrc:
        if s.get("host"):
            eps_by_host[s["host"]] = eps_by_host.get(s["host"], 0.0) + s["eps"]

    topo = dep_an.build_topology(dep, mh_rows, perf_by_alias, eps_by_host, notif_hosts)
    # include perf-only hosts (no deployment data) so single-host bundles still render
    known_perf = {n.get("perf_key") for n in topo["nodes"]}
    for key, p in host_perf.items():
        if key not in known_perf:
            ident = p.get("identity", {})
            if not topo["nodes"] or ident.get("ip") or ident.get("hostname"):
                hw = p.get("hardware", {})
                topo["nodes"].append({"id": ident.get("ip") or ident.get("hostname") or key, "hostname": ident.get("hostname") or key, "ip": ident.get("ip"),
                                      "role": "Console" if not topo["nodes"] else "Unknown", "components": [], "source": ["system"], "token": False,
                                      "cpu_cores": hw.get("cpus"), "memory_bytes": hw.get("memory_bytes"), "disk_bytes": hw.get("disk_bytes"),
                                      "perf_key": key, "os": hw.get("os"), "status": "unknown", "health": 80, "eps": None, "fpm": None, "notifications": 0})
    checks = dep_an.validate_deployment(dep, topo, mh_rows, misc)

    notif_res = notif_an.analyse_notifications(notifs)
    ls_res = ls_an.analyse_log_sources(logsrc)
    wc_res = ls_an.analyse_wincollect(ctx.load("wincollect_raw") or [], logsrc)
    app_res = ls_an.analyse_applications(ctx.load("applications_raw") or [])

    perf_assess: list[dict] = []
    perf_hosts: dict[str, Any] = {}
    for key, p in host_perf.items():
        ident = p.get("identity", {})
        name = ident.get("hostname") or ident.get("ip") or key
        perf_assess += perf_an.assess_host(name, p)
        perf_hosts[name] = {
            "key": key, "identity": ident, "hardware": p.get("hardware", {}), "df": p.get("df", []), "memory": p.get("memory", {}),
            "sar_summary": (p.get("sar") or {}).get("summary", {}), "series": (p.get("sar") or {}).get("series", {}),
            "disks": {d: {k: v for k, v in dv.items()} for d, dv in (p.get("sar") or {}).get("disks", {}).items()},
            "interfaces": (p.get("sar") or {}).get("interfaces", {}),
            "top_cpu": perf_an.top_processes(p, "cpu"), "top_mem": perf_an.top_processes(p, "mem"),
            "load": (p.get("sar") or {}).get("summary", {}).get("load") or ({"avg1": p["top"]["load"][0], "avg5": p["top"]["load"][1]} if p.get("top", {}).get("load") else None),
            "httpd_count": p.get("httpd_count"), "samples": (p.get("sar") or {}).get("samples", {}),
        }

    # current EPS/FPM: sum of host values else sum of log sources
    cur_eps = sum(n["eps"] for n in topo["nodes"] if n.get("eps")) or ls_res["total_eps"] or None
    cur_fpm = sum(n["fpm"] for n in topo["nodes"] if n.get("fpm")) or None
    lr = ctx.load("licensing_raw") or {}
    lic_res = lic_an.analyse_licensing(lr.get("license", {}), lr.get("eps_history", []), lr.get("fpm_history", []), cur_eps, cur_fpm)

    # environment
    versions = Counter(n["version"] for n in topo["nodes"] if n.get("version"))
    version = misc.get("version") or (versions.most_common(1)[0][0] if versions else dep.get("version"))
    console = next((n for n in topo["nodes"] if n["role"] == "Console"), None)
    n_hosts = len(topo["nodes"])
    env = {
        "version": version, "fix_pack": misc.get("fix_pack"), "build": misc.get("build"),
        "deployment_type": ("All-in-One" if n_hosts == 1 else "Distributed") if n_hosts else None,
        "install_type": misc.get("install_type"), "platform": misc.get("platform"), "manufacturer": misc.get("manufacturer"),
        "software_hardware": ("Hardware appliance" if misc.get("install_type", "").startswith("Physical") else "Virtual appliance" if misc.get("install_type", "").startswith("Virtual") else None),
        "hosts": n_hosts, "console": console["hostname"] if console else None,
        "source_files": ctx.load("manifest").get("bytes_extracted") if ctx.load("manifest") else None,
        "supported_line": bool(version and re.match(r"7\.[45]\.", version)) if version else None,
    }

    au = ctx.load("autoupdate") or {}
    analysis = {
        "environment": env, "topology": topo, "deployment_checks": checks, "notifications": notif_res, "logsources": ls_res,
        "wincollect": wc_res, "applications": app_res, "performance_assessments": perf_assess, "performance_hosts": perf_hosts,
        "licensing": lic_res, "autoupdate": au, "deployment_xml_summary": {k: dep.get(k) for k in ("file", "valid_xml", "root_tag", "version")},
    }
    # persist
    for k, v in analysis.items():
        ctx.save(f"a_{k}", v)
    fs = fnd.build_findings(analysis)
    ctx.save("_findings", fs)
    return f"{len(fs)} findings"


def stage_recommendations(ctx: Ctx) -> str:
    fs = ctx.load("_findings") or []
    analysis = {k: ctx.load(f"a_{k}") for k in ("environment", "topology", "logsources", "wincollect", "applications", "licensing")}
    available = {
        "deployment": bool((analysis["topology"] or {}).get("nodes")),
        "notifications": bool((ctx.load("notifications_raw") or [])),
        "logsources": bool((analysis["logsources"] or {}).get("total")),
        "applications": bool((analysis["applications"] or {}).get("total")),
        "performance": bool(ctx.load("host_perf")),
        "licensing": bool((analysis["licensing"] or {}).get("has_data")),
        "wincollect": bool((analysis["wincollect"] or {}).get("total")),
    }
    cats = scoring.score_categories(fs, available)
    ov = scoring.overall(cats)
    ctx.save("scores", {"categories": cats, "overall": ov, "available": available})
    ctx.save("top_recommendations", fnd.top_recommendations(fs, 10))
    return f"overall {ov['score']}"


def stage_summary(ctx: Ctx) -> str:
    keys = ("environment", "topology", "logsources", "wincollect", "applications", "licensing")
    analysis = {k: ctx.load(f"a_{k}") for k in keys}
    sc = ctx.load("scores")
    fs = ctx.load("_findings") or []
    summary = fnd.executive_summary(analysis, sc["overall"], sc["categories"], fs)
    ctx.save("executive_summary", summary)
    return summary["headline"]


STAGE_FUNCS: dict[str, Callable[[Ctx], str]] = {
    "extract": stage_extract, "deployment": stage_deployment, "database": stage_database, "performance": stage_performance,
    "applications": stage_applications, "wincollect": stage_wincollect, "notifications": stage_notifications,
    "licensing": stage_licensing, "findings": stage_findings, "recommendations": stage_recommendations, "summary": stage_summary,
}
