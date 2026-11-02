"""Archive diagnostics: QRadar artifact indicator detection and fallback inventory.

Works on the *manifest* (every member seen, extracted or not), so a package is recognised even when its
interesting files were catalogued rather than extracted.  Nothing here raises: an unrecognised archive
produces an inventory + diagnostics instead of aborting the job.
"""
from __future__ import annotations

import posixpath
import re
from collections import Counter
from typing import Any

UNSUPPORTED_MESSAGE = "Archive extracted successfully but no supported QRadar artifacts were detected. See diagnostics."

SAMPLE_LIMIT = 100

# indicator name -> path regex (matched against the full, '/'-normalised member path)
INDICATORS: dict[str, re.Pattern[str]] = {
    "deployment_xml": re.compile(r"(^|/)deployment(_info)?[^/]*\.xml(\.gz)?$", re.I),
    "version_file": re.compile(r"(^|/)(version(\.txt)?|VERSION[^/]*)$", re.I),
    "hostcontext": re.compile(r"hostcontext", re.I),
    "tomcat_logs": re.compile(r"(^|/)(tomcat[^/]*|catalina[^/]*)(/|\.log|\.out)", re.I),
    "postgres_dump": re.compile(r"postgres|pg_dump|(^|/)[^/]*\.(sql|pgdump|dump|copy)(\.gz)?$|notification_view|managedhost", re.I),
    "ariel_data": re.compile(r"(^|/)ariel([_/]|$)|/store/ariel", re.I),
    "qradar_config": re.compile(r"/opt/qradar/(conf|bin|support)|(^|/)(opt/)?qradar/conf|qradar\.(conf|properties)", re.I),
    "qradar_logs": re.compile(r"qradar\.(error|log)(\.\d+)?(\.gz)?$", re.I),
    "autoupdate": re.compile(r"auto[_-]?update", re.I),
    "wincollect": re.compile(r"wincollect|win_collect", re.I),
    "app_framework": re.compile(r"installed_application|app_framework|appframework", re.I),
    "log_sources": re.compile(r"sensordevice|log_?sources?(_|\.|/)|logsource", re.I),
    "sar_data": re.compile(r"(^|/)(sar\d*|sa\d{2})(\.gz)?$|(^|/)sar_[^/]*$|sysstat", re.I),
    "get_logs_artifact": re.compile(r"get_?logs|support[_-]?(info|bundle)|system[_-]?(info|output)", re.I),
}

# categories (assigned by ingestion.classify) that on their own prove the archive is QRadar support data
# (deliberately excludes the loose 'sar' / 'db_dump' categories; those are covered by the tighter indicators above)
CORE_CATEGORIES = {"deployment", "hostcontext", "autoupdate", "wincollect", "application", "logsource"}

_HOTFIX_ID = re.compile(r"(QRADAR-\d+|APAR[-_ ]?\w+|IJ\d{5})", re.I)
_PATCH_WORDS = re.compile(r"hotfix|patch|fixpack|fix[_-]?pack|install_on_all_hosts|signed-rpms", re.I)


def find_indicators(paths: list[str]) -> dict[str, list[str]]:
    """Return {indicator: [up to 5 matching paths]} for every indicator present."""
    found: dict[str, list[str]] = {}
    for p in paths:
        n = p.replace("\\", "/")
        for name, rx in INDICATORS.items():
            if rx.search(n):
                hits = found.setdefault(name, [])
                if len(hits) < 5:
                    hits.append(p)
    return found


def _detect_kind(paths: list[str], by_ext: Counter, source_name: str) -> tuple[str, str | None]:
    """Best-effort label for a non-get_logs archive.  Returns (kind, identifier)."""
    blob = " ".join(paths[:2000]) + " " + source_name
    ident = None
    m = _HOTFIX_ID.search(blob)
    if m:
        ident = m.group(1).upper()
    has_sh = by_ext.get(".sh", 0) > 0
    has_rpm = by_ext.get(".rpm", 0) > 0 or any(p.lower().endswith(".rpm") or "signed-rpms" in p.lower() for p in paths)
    if _PATCH_WORDS.search(blob) or (has_sh and has_rpm):
        return "QRadar hotfix / patch bundle (installable update, not a get_logs support export)", ident
    if has_rpm:
        return "RPM package bundle", ident
    if has_sh:
        return "Script bundle", ident
    return "Unrecognised archive", ident


def build_diagnostics(manifest: list[dict[str, Any]], *, source_name: str, archive_type: str, total_members: int,
                      bytes_seen: int, security_events: int = 0) -> dict[str, Any]:
    """Inventory + indicator report for an extracted archive.  ``supported`` tells the pipeline whether to analyse it."""
    paths = [e["path"] for e in manifest]
    cats = Counter(e.get("category", "other") for e in manifest)
    by_ext: Counter = Counter()
    for p in paths:
        base = posixpath.basename(p).lower()
        ext = ".tar.gz" if base.endswith(".tar.gz") else posixpath.splitext(base)[1] or "(none)"
        by_ext[ext] += 1
    roots = Counter(p.split("/", 1)[0] for p in paths if "/" in p)
    top_level_files = [p for p in paths if "/" not in p]
    nested = [e["path"] for e in manifest if e.get("nested")]
    indicators = find_indicators(paths)
    core = {c: n for c, n in cats.items() if c in CORE_CATEGORIES}
    supported = bool(indicators) or bool(core)
    kind, ident = ("QRadar get_logs package", None) if supported else _detect_kind(paths, by_ext, source_name)
    if supported and len(indicators) < 3:
        layout = "partial"
    elif supported:
        layout = "standard"
    else:
        layout = "unsupported"
    big = sorted(manifest, key=lambda e: -(e.get("size") or 0))[:10]
    return {
        "supported": supported,
        "layout": layout,
        "message": None if supported else UNSUPPORTED_MESSAGE,
        "source_filename": source_name,
        "archive_type": archive_type,
        "detected_kind": kind,
        "identifier": ident,
        "total_members": total_members,
        "total_bytes": bytes_seen,
        "security_events": security_events,
        "root_folders": [{"name": n, "files": c} for n, c in roots.most_common(25)],
        "top_level_files": top_level_files[:25],
        "categories": dict(cats),
        "extensions": dict(by_ext.most_common(20)),
        "nested_archives": nested[:50],
        "indicators": indicators,
        "largest_files": [{"path": e["path"], "size": e.get("size") or 0} for e in big],
        "sample_files": paths[:SAMPLE_LIMIT],
        "guidance": [
            "Collect a support export on the QRadar Console with: /opt/qradar/support/get_logs.sh",
            "Upload the resulting .tar / .tar.gz (nested archives are extracted automatically).",
            "A hotfix, fix pack or RPM bundle is an installer, not diagnostic data, and cannot be health-checked.",
        ],
    }
