"""Normalise raw PostgreSQL table rows into typed domain records.

QRadar's internal schema differs between releases, so every field is resolved through an ordered alias
list.  Anything unresolved stays ``None`` rather than being invented.
"""
from __future__ import annotations

import re
from typing import Any

from app.parsers.common import parse_ts, pick, size_to_bytes, to_bool, to_float, to_int
from app.parsers.tables import Row

WANTED_TABLES = [
    "notification_view", "notification", "managedhost", "managed_host", "sensordevice", "sensordevicetype",
    "sensorprotocol", "sensorprotocolconfig", "installed_application", "installed_application_instance",
    "deployed_component", "license", "licensepool", "license_pool", "license_key", "licensekey", "license_usage",
    "autoupdate", "auto_update", "auto_update_history", "wincollect", "wincollect_agent", "wincollect_agents",
    "wincollect_destination", "host_license", "eps_usage", "eps_history", "fpm_history", "device_eps",
    "log_source_eps", "ha_cluster", "ha_status", "backup_config", "backup_history",
]

SEVERITY_MAP = {"critical": "critical", "emergency": "critical", "alert": "critical", "fatal": "critical",
                "error": "high", "err": "high", "high": "high", "major": "high", "warning": "medium",
                "warn": "medium", "medium": "medium", "minor": "low", "low": "low", "notice": "low",
                "info": "info", "information": "info", "informational": "info", "debug": "info"}


def norm_severity(v: Any) -> str:
    if v is None:
        return "medium"
    s = str(v).strip().lower()
    if s.isdigit():
        n = int(s)
        return "critical" if n >= 9 else "high" if n >= 7 else "medium" if n >= 4 else "low" if n >= 2 else "info"
    return SEVERITY_MAP.get(s, "medium")


# ---------------------------------------------------------------------------
def parse_notifications(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    for i, r in enumerate(rows):
        msg = pick(r, "message", "description", "text", "notification", "notification_text", "payload", default="") or ""
        out.append({
            "id": str(pick(r, "id", "notification_id", "notificationid", default=i)),
            "severity": norm_severity(pick(r, "severity", "sev", "level", "priority", "notification_severity")),
            "severity_raw": pick(r, "severity", "sev", "level", "priority"),
            "timestamp": parse_ts(pick(r, "create_time", "created", "creation_time", "time", "timestamp", "last_time",
                                       "notification_time", "first_time", "creationtime")),
            "last_seen": parse_ts(pick(r, "last_time", "last_occurrence", "lasttime", "updated")),
            "status": ("closed" if to_bool(pick(r, "closed", "is_closed", "dismissed", "resolved")) else
                       (str(pick(r, "status", "state", default="open")).lower())),
            "message": str(msg).strip(),
            "host": pick(r, "host", "hostname", "managed_host", "managedhost", "source_host", "host_name", "qradar_host"),
            "host_ip": pick(r, "ip", "host_ip", "ipaddress", "managed_host_ip"),
            "component": pick(r, "component", "source", "module", "process", "app", "origin"),
            "type": pick(r, "type", "notification_type", "category", "message_id", "msgid", "code"),
            "count": to_int(pick(r, "count", "occurrences", "event_count"), 1) or 1,
        })
    return out


def parse_hosts(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        out.append({
            "id": str(pick(r, "id", "managed_host_id", "managedhostid", "hostid", "host_id", "mhid", default="")),
            "hostname": pick(r, "hostname", "host_name", "name", "managed_host", "host"),
            "ip": pick(r, "ip", "ipaddress", "ip_address", "address", "primary_ip", "managementip"),
            "role_raw": pick(r, "appliance_type", "type", "role", "host_type", "applianceid", "appliance"),
            "status": pick(r, "status", "state", "connection_status"),
            "version": pick(r, "version", "software_version"),
            "cpu_cores": to_int(pick(r, "cpu", "cpus", "cpu_count", "cores", "num_cpus")),
            "memory_bytes": size_to_bytes(pick(r, "memory", "ram", "mem_total", "memory_bytes", "total_memory")),
            "disk_bytes": size_to_bytes(pick(r, "disk", "disk_size", "storage", "disk_total")),
            "eps": to_float(pick(r, "eps", "current_eps", "events_per_second")),
            "fpm": to_float(pick(r, "fpm", "current_fpm", "flows_per_minute")),
            "ha_role": pick(r, "ha_role", "harole"), "ha_peer": pick(r, "ha_peer", "peer", "ha_partner"),
            "ha_status": pick(r, "ha_status", "hastatus", "ha_state"),
            "last_seen": parse_ts(pick(r, "last_seen", "last_contact", "last_checkin", "heartbeat")),
            "compressed": to_bool(pick(r, "compression", "compressed")),
        })
    return out


PROTOCOL_GROUPS = [
    ("WinCollect", re.compile(r"wincollect|win\s*collect", re.I)),
    ("AWS", re.compile(r"aws|amazon|cloudtrail|s3|kinesis|cloudwatch", re.I)),
    ("Azure", re.compile(r"azure|event\s*hub", re.I)),
    ("Office365", re.compile(r"office\s*365|o365|microsoft\s*365", re.I)),
    ("JDBC", re.compile(r"jdbc", re.I)),
    ("SNMP", re.compile(r"snmp", re.I)),
    ("SFTP", re.compile(r"sftp|ftp|scp|log\s*file", re.I)),
    ("OPSEC", re.compile(r"opsec|lea\b|check\s*point", re.I)),
    ("LEEF", re.compile(r"leef", re.I)),
    ("TLS", re.compile(r"tls|ssl", re.I)),
    ("REST API", re.compile(r"rest|http\s*receiver|api|https?", re.I)),
    ("TCP", re.compile(r"tcp", re.I)),
    ("UDP", re.compile(r"udp", re.I)),
    ("Syslog", re.compile(r"syslog", re.I)),
    ("Universal DSM", re.compile(r"universal|udsm", re.I)),
]


def protocol_group(protocol: str | None, dsm: str | None = None) -> str:
    text = f"{protocol or ''} {dsm or ''}"
    if dsm and re.search(r"universal", dsm, re.I):
        return "Universal DSM"
    for name, rx in PROTOCOL_GROUPS:
        if rx.search(protocol or ""):
            return name
    for name, rx in PROTOCOL_GROUPS:
        if rx.search(text):
            return name
    return "Other"


def parse_log_sources(rows: list[Row], types: dict[str, str] | None = None, protocols: dict[str, str] | None = None) -> list[dict[str, Any]]:
    types, protocols = types or {}, protocols or {}
    out = []
    for i, r in enumerate(rows):
        tid = str(pick(r, "devicetypeid", "device_type_id", "typeid", "sensordevicetypeid", default=""))
        pid = str(pick(r, "protocolid", "protocol_id", "sensorprotocolid", default=""))
        dsm = pick(r, "type", "devicetype", "device_type", "dsm", "type_name", "devicetypename") or types.get(tid)
        proto = pick(r, "protocol", "protocol_name", "protocolname", "sensorprotocol") or protocols.get(pid)
        enabled = to_bool(pick(r, "enabled", "is_enabled", "active"))
        raw_status = str(pick(r, "status", "state", "health", default="")).lower()
        deleted = to_bool(pick(r, "deleted", "is_deleted"))
        if deleted:
            continue
        if raw_status in ("error", "failed", "failure", "err", "warn", "warning"):
            status = "error"
        elif enabled is False or raw_status in ("disabled", "inactive"):
            status = "disabled"
        elif enabled is True or raw_status in ("enabled", "active", "ok", "running", "success"):
            status = "enabled"
        else:
            status = "unknown"
        last_evt = parse_ts(pick(r, "last_event", "last_event_time", "lastseen", "last_event_received", "last_seen", "lastevent", "last_event_ts"))
        out.append({
            "id": str(pick(r, "id", "sensordeviceid", "log_source_id", "logsourceid", default=i)),
            "name": pick(r, "devicename", "name", "log_source_name", "logsourcename", "sensordevice_name", default=f"LogSource-{i}"),
            "identifier": pick(r, "deviceid", "identifier", "hostname", "log_source_identifier"),
            "type": dsm or "Unknown", "protocol": proto or "Unknown",
            "protocol_group": protocol_group(proto, dsm),
            "status": status, "status_raw": raw_status or None, "enabled": enabled,
            "eps": to_float(pick(r, "eps", "avg_eps", "average_eps", "current_eps", "events_per_second"), 0.0) or 0.0,
            "last_event": last_evt, "coalesce": to_bool(pick(r, "coalesce_events", "coalesce")),
            "store_payload": to_bool(pick(r, "store_event_payload", "storepayload")),
            "group": pick(r, "groups", "group", "group_name"),
            "wincollect": bool(re.search(r"wincollect", f"{proto} {dsm} {pick(r, 'wincollect_agent', default='')}", re.I)),
            "host": pick(r, "managed_host", "managedhost", "host", "qradar_host", "eventcollector"),
            "creation_date": parse_ts(pick(r, "creationdate", "created", "creation_date")),
            "description": pick(r, "description"),
        })
    return out


def parse_wincollect(rows: list[Row]) -> list[dict[str, Any]]:
    out = []
    for i, r in enumerate(rows):
        status_raw = str(pick(r, "status", "state", "connection_status", default="")).lower()
        mode = str(pick(r, "mode", "type", "management", "management_mode", "agent_type", default="")).lower()
        managed = to_bool(pick(r, "managed", "is_managed"))
        if managed is None and mode:
            managed = "stand" not in mode and "unman" not in mode
        if status_raw in ("connected", "ok", "active", "running", "online", "enabled"):
            status = "connected"
        elif status_raw in ("disconnected", "offline", "lost", "inactive", "stopped", "disabled", "unreachable"):
            status = "disconnected"
        elif status_raw in ("error", "failed", "failure"):
            status = "error"
        else:
            status = "unknown"
        out.append({
            "id": str(pick(r, "id", "agent_id", "agentid", default=i)),
            "name": pick(r, "name", "agent_name", "hostname", "host", "computer", "agent", default=f"Agent-{i}"),
            "ip": pick(r, "ip", "ipaddress", "ip_address"),
            "version": pick(r, "version", "agent_version", "wincollect_version"),
            "managed": managed, "mode": "managed" if managed else ("standalone" if managed is False else "unknown"),
            "status": status, "destination": pick(r, "destination", "event_collector", "managed_host", "target", "ec"),
            "last_checkin": parse_ts(pick(r, "last_checkin", "last_contact", "last_seen", "last_heartbeat", "lastcheckin")),
            "os": pick(r, "os", "operating_system"),
            "config_error": pick(r, "config_error", "last_error", "error", "error_message"),
            "log_sources": to_int(pick(r, "log_sources", "sources", "device_count")),
        })
    return out


def _parse_app_status(raw: Any, restarts: int | None = None) -> str:
    s = str(raw or "").strip().lower()
    if s in ("running", "up", "started", "active", "deployed", "ok"):
        return "running"
    if s in ("stopped", "exited", "down", "inactive", "disabled", "created"):
        return "stopped"
    if s in ("error", "failed", "failure", "crashed", "dead", "install_failed"):
        return "error"
    if s in ("degraded", "unhealthy", "restarting", "warning", "paused", "starting", "installing", "pending"):
        return "degraded"
    return "unknown"


def parse_applications(apps: list[Row], instances: list[Row]) -> list[dict[str, Any]]:
    app_idx: dict[str, Row] = {}
    for a in apps:
        k = str(pick(a, "id", "application_id", "app_id", "installed_application_id", default=""))
        app_idx[k] = a
    out: list[dict[str, Any]] = []
    seen_apps: set[str] = set()
    for i, inst in enumerate(instances):
        aid = str(pick(inst, "installed_application_id", "application_id", "app_id", "installedapplicationid", default=""))
        a = app_idx.get(aid, {})
        seen_apps.add(aid)
        out.append(_app_record(f"{aid}-{i}", a, inst))
    for k, a in app_idx.items():
        if k not in seen_apps:
            out.append(_app_record(k, a, {}))
    return out


def _app_record(rid: str, a: Row, inst: Row) -> dict[str, Any]:
    restarts = to_int(pick(inst, "restart_count", "restarts", "restartcount", "restart"), 0) or 0
    status_raw = pick(inst, "status", "state", "container_state", "health") or pick(a, "status", "state")
    mem_limit = size_to_bytes(pick(inst, "memory_limit", "mem_limit", "memory_limit_bytes", "memory"))
    mem_used = size_to_bytes(pick(inst, "memory_usage", "mem_usage", "memory_used", "mem_used"))
    mem_pct = to_float(pick(inst, "memory_percent", "mem_percent", "mem_pct"))
    if mem_pct is None and mem_limit and mem_used:
        mem_pct = 100.0 * mem_used / mem_limit
    return {
        "id": rid,
        "name": pick(a, "name", "application_name", "app_name", "title") or pick(inst, "name", "application_name", "app_name", default="Unknown App"),
        "version": pick(a, "version", "app_version", "application_version") or pick(inst, "version"),
        "latest_version": pick(a, "latest_version", "available_version", "update_version"),
        "host": pick(inst, "managed_host", "host", "hostname", "managedhost", "host_ip", "managed_host_id", "managed_host_name"),
        "status": _parse_app_status(status_raw),
        "status_raw": status_raw,
        "cpu_pct": to_float(pick(inst, "cpu_usage", "cpu_percent", "cpu", "cpu_pct")),
        "memory_pct": mem_pct, "memory_used_bytes": mem_used, "memory_limit_bytes": mem_limit,
        "restart_count": restarts,
        "uptime": pick(inst, "uptime", "running_for"),
        "last_error": pick(inst, "error", "last_error", "error_message", "status_message", "message"),
        "disk_used_bytes": size_to_bytes(pick(inst, "disk_usage", "storage_used", "volume_usage")),
        "disk_limit_bytes": size_to_bytes(pick(inst, "disk_limit", "storage_limit", "volume_size")),
        "app_id": pick(a, "application_id", "app_id", "id"),
        "created": parse_ts(pick(inst, "created", "create_time", "creation_date", "started_at")),
    }


def parse_licenses(rows: list[Row]) -> dict[str, Any]:
    """Aggregate license rows into EPS / FPM / App Framework entitlement."""
    lic: dict[str, Any] = {"eps_licensed": None, "fpm_licensed": None, "apps_licensed": None, "expiry": None,
                           "type": None, "rows": len(rows), "hosts": []}
    for r in rows:
        txt = " ".join(str(v) for v in r.values() if v is not None).lower()
        val = to_float(pick(r, "value", "limit", "licensed", "max", "capacity", "allowed", "entitlement"))
        kind = str(pick(r, "type", "name", "key", "metric", "license_type", "resource", default="")).lower()
        if val is None:
            for key, aliases in (("eps_licensed", ("eps", "events_per_second", "max_eps", "licensed_eps")),
                                 ("fpm_licensed", ("fpm", "flows_per_minute", "max_fpm", "licensed_fpm"))):
                for a in aliases:
                    v = to_float(r.get(a))
                    if v is not None:
                        lic[key] = (lic[key] or 0) + v
            continue
        if re.search(r"\beps\b|events?[_ ]per[_ ]sec", kind) or kind == "eps":
            lic["eps_licensed"] = (lic["eps_licensed"] or 0) + val
        elif re.search(r"\bfpm\b|flows?[_ ]per[_ ]min", kind) or kind == "fpm":
            lic["fpm_licensed"] = (lic["fpm_licensed"] or 0) + val
        elif re.search(r"app|framework|container", kind):
            lic["apps_licensed"] = val
        exp = pick(r, "expiry", "expires", "expiration", "expiration_date", "expire_date", "valid_until")
        if exp and not lic["expiry"]:
            lic["expiry"] = parse_ts(exp)
        t = pick(r, "license_type", "edition", "product")
        if t and not lic["type"]:
            lic["type"] = t
        _ = txt
    return lic


def parse_usage_history(rows: list[Row], metric: str) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        ts = parse_ts(pick(r, "ts", "time", "timestamp", "date", "day", "created", "period"))
        val = to_float(pick(r, metric, "value", "avg", "average", "current", "count"))
        peak = to_float(pick(r, f"peak_{metric}", f"max_{metric}", "peak", "max", "maximum"))
        if ts and val is not None:
            out.append({"ts": ts, "value": val, "peak": peak if peak is not None else val})
    out.sort(key=lambda x: x["ts"])
    return out


def parse_autoupdate(rows: list[Row], text: str = "") -> dict[str, Any]:
    info: dict[str, Any] = {"current_version": None, "latest_version": None, "pending_updates": 0, "repo_reachable": None,
                            "last_run": None, "last_status": None, "history": [], "errors": []}
    for r in rows:
        status = str(pick(r, "status", "result", "state", default="")).lower()
        entry = {"ts": parse_ts(pick(r, "time", "timestamp", "date", "run_time", "created", "last_run")),
                 "type": pick(r, "type", "update_type", "name", "package"), "status": status,
                 "version": pick(r, "version", "update_version", "new_version", "package_version"),
                 "message": pick(r, "message", "error", "detail")}
        info["history"].append(entry)
        if any(w in status for w in ("fail", "error")):
            info["errors"].append(entry)
        if any(w in status for w in ("pending", "available", "downloaded", "ready")):
            info["pending_updates"] += 1
        v = pick(r, "installed_version", "current_version")
        if v:
            info["current_version"] = v
        v = pick(r, "latest_version", "available_version")
        if v:
            info["latest_version"] = v
    info["history"].sort(key=lambda x: x["ts"] or "", reverse=True)
    if info["history"]:
        info["last_run"] = info["history"][0]["ts"]
        info["last_status"] = info["history"][0]["status"]
    if text:
        low = text.lower()
        if re.search(r"(unable to|cannot|could not|failed to)\s+(connect|reach|resolve|download)|connection (refused|timed out)|"
                     r"could not resolve host|ssl (error|certificate)|proxy", low):
            info["repo_reachable"] = False
            m = re.search(r"((?:unable to|cannot|could not|failed to)[^\n]{0,160})", text, re.I)
            if m:
                info["errors"].append({"ts": None, "type": "connectivity", "status": "failed", "message": m.group(1).strip(), "version": None})
        elif re.search(r"connect(ed|ion) (ok|success)|downloaded|up to date|no updates", low):
            info["repo_reachable"] = True
        m = re.search(r"(?:current|installed)\s+(?:version|level)[^\d]{0,10}(\d+\.\d+[\w.\-]*)", text, re.I)
        if m and not info["current_version"]:
            info["current_version"] = m.group(1)
        m = re.search(r"(?:latest|available)\s+(?:version|level)[^\d]{0,10}(\d+\.\d+[\w.\-]*)", text, re.I)
        if m and not info["latest_version"]:
            info["latest_version"] = m.group(1)
    if info["repo_reachable"] is None and info["history"]:
        info["repo_reachable"] = not any("connect" in (e.get("message") or "").lower() or "resolve" in (e.get("message") or "").lower()
                                         for e in info["errors"])
    return info
