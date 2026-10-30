"""Deployment topology assembly, HA analysis and deployment validation checks."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.parsers.deployment import ROLES, role_from_text

PASS, WARN, CRIT = "PASS", "WARNING", "CRITICAL"
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def build_topology(dep: dict[str, Any], mh_rows: list[dict[str, Any]], host_perf: dict[str, Any],
                   sources_by_host: dict[str, float] | None = None, notif_hosts: Counter | None = None) -> dict[str, Any]:
    """Merge deployment.xml hosts with managedhost table rows and per-host metrics into node cards."""
    nodes: dict[str, dict[str, Any]] = {}

    def key_for(rec: dict[str, Any]) -> str:
        for k in (rec.get("ip"), rec.get("hostname"), rec.get("id")):
            if k and _norm(k) in nodes_alias:
                return nodes_alias[_norm(k)]
        return str(rec.get("id") or rec.get("ip") or rec.get("hostname"))

    nodes_alias: dict[str, str] = {}
    for h in dep.get("hosts", []):
        nid = h["id"]
        nodes[nid] = {"id": nid, "hostname": h.get("hostname") or nid, "ip": h.get("ip"), "role": h.get("role", "Unknown"),
                      "status_raw": h.get("status"), "version": h.get("version"), "components": sorted(set(h.get("components", []))),
                      "ha_role": h.get("ha_role"), "ha_peer": h.get("ha_peer"), "ha_status": h.get("ha_status"),
                      "eps": _f(h.get("eps")), "fpm": _f(h.get("fpm")), "token": bool(h.get("token")), "source": ["deployment.xml"]}
        for a in (nid, h.get("hostname"), h.get("ip")):
            if a:
                nodes_alias[_norm(a)] = nid
    for r in mh_rows:
        nid = key_for(r)
        n = nodes.setdefault(nid, {"id": nid, "hostname": r.get("hostname") or nid, "ip": r.get("ip"), "role": "Unknown",
                                   "components": [], "source": [], "token": False})
        n["source"].append("managedhost")
        n["hostname"] = n.get("hostname") or r.get("hostname")
        n["ip"] = n.get("ip") or r.get("ip")
        n["status_raw"] = n.get("status_raw") or r.get("status")
        n["version"] = n.get("version") or r.get("version")
        n["eps"] = n.get("eps") if n.get("eps") is not None else r.get("eps")
        n["fpm"] = n.get("fpm") if n.get("fpm") is not None else r.get("fpm")
        n["ha_role"] = n.get("ha_role") or r.get("ha_role")
        n["ha_peer"] = n.get("ha_peer") or r.get("ha_peer")
        n["ha_status"] = n.get("ha_status") or r.get("ha_status")
        if n.get("role") in (None, "Unknown"):
            n["role"] = role_from_text(r.get("role_raw"), r.get("hostname"))
        n["cpu_cores"] = r.get("cpu_cores")
        n["memory_bytes"] = r.get("memory_bytes")
        n["disk_bytes"] = r.get("disk_bytes")
        n["last_seen"] = r.get("last_seen")
        for a in (nid, r.get("hostname"), r.get("ip"), r.get("id")):
            if a:
                nodes_alias[_norm(a)] = nid
    # overlay metrics gathered from host directories
    for nid, n in nodes.items():
        perf = None
        for a in (n.get("ip"), n.get("hostname"), nid):
            if a and _norm(a) in host_perf:
                perf = host_perf[_norm(a)]
                break
        if perf:
            hw = perf.get("hardware", {})
            n["cpu_cores"] = n.get("cpu_cores") or hw.get("cpus")
            n["memory_bytes"] = n.get("memory_bytes") or hw.get("memory_bytes")
            n["disk_bytes"] = n.get("disk_bytes") or hw.get("disk_bytes")
            n["perf_key"] = perf.get("key")
            n["os"] = hw.get("os")
            n["version"] = n.get("version") or perf.get("version")
        if sources_by_host and n.get("eps") is None:
            for a in (n.get("hostname"), n.get("ip"), nid):
                if a and a in sources_by_host:
                    n["eps"] = sources_by_host[a]
        n["notifications"] = (notif_hosts or Counter()).get(n.get("hostname"), 0) + (notif_hosts or Counter()).get(n.get("ip"), 0)
        n["status"], n["health"] = _node_health(n)
    # ensure there is exactly one console label when only one host exists
    if nodes and not any(n["role"] == "Console" for n in nodes.values()) and len(nodes) == 1:
        next(iter(nodes.values()))["role"] = "Console"
    ha = analyse_ha(dep, list(nodes.values()), nodes_alias)
    edges = build_edges(list(nodes.values()), dep, ha)
    return {"nodes": list(nodes.values()), "edges": edges, "ha": ha, "role_counts": dict(Counter(n["role"] for n in nodes.values())),
            "alias": nodes_alias}


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _node_health(n: dict[str, Any]) -> tuple[str, int]:
    raw = _norm(n.get("status_raw"))
    score = 100
    if raw in ("error", "failed", "down", "inactive", "unreachable", "lost", "disconnected", "offline"):
        status, score = "error", 20
    elif raw in ("warning", "degraded", "warn"):
        status, score = "warning", 65
    elif raw in ("", "unknown"):
        status = "unknown"
        score = 80
    else:
        status = "healthy"
    score -= min(25, 5 * (n.get("notifications") or 0))
    return status, max(score, 0)


def analyse_ha(dep: dict[str, Any], nodes: list[dict[str, Any]], alias: dict[str, str]) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()
    by_id = {n["id"]: n for n in nodes}
    for p in dep.get("ha_pairs", []):
        a, b = alias.get(_norm(p.get("primary")), p.get("primary")), alias.get(_norm(p.get("secondary")), p.get("secondary"))
        if a or b:
            seen.add(frozenset(x for x in (a, b) if x))
            pairs.append({"primary": a, "secondary": b, "status": p.get("status"), "sync": p.get("sync"), "vip": p.get("vip")})
    for n in nodes:
        peer = alias.get(_norm(n.get("ha_peer")))
        if peer and peer in by_id:
            fs = frozenset((n["id"], peer))
            if fs in seen:
                continue
            seen.add(fs)
            role = _norm(n.get("ha_role"))
            primary, secondary = (n["id"], peer) if "second" not in role and "stand" not in role else (peer, n["id"])
            pairs.append({"primary": primary, "secondary": secondary, "status": n.get("ha_status"), "sync": n.get("ha_status"), "vip": None})
    result = []
    paired = set()
    for p in pairs:
        st, sy = _norm(p["status"]), _norm(p["sync"])
        synced = any(w in f"{st} {sy}" for w in ("sync", "uptodate", "up-to-date", "active", "ok", "healthy", "connected")) and \
            not any(w in f"{st} {sy}" for w in ("unsync", "not sync", "out of sync", "inconsist", "split", "fail", "down", "standalone", "degrad"))
        failed = any(w in f"{st} {sy}" for w in ("fail", "down", "split", "standalone", "degrad", "inconsist", "unsync", "out of sync"))
        readiness = "ready" if synced else "not_ready" if failed else "unknown"
        result.append({**p, "synchronised": synced, "failover_readiness": readiness})
        paired.update(x for x in (p["primary"], p["secondary"]) if x)
    unprotected = [n for n in nodes if n["id"] not in paired and n["role"] in ("Console", "EP", "DN")]
    return {"pairs": result, "protected_hosts": sorted(paired), "unprotected": [{"id": n["id"], "hostname": n["hostname"], "role": n["role"]} for n in unprotected],
            "configured": bool(result)}


def build_edges(nodes: list[dict[str, Any]], dep: dict[str, Any], ha: dict[str, Any]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    console = next((n for n in nodes if n["role"] == "Console"), None)
    ids = {n["id"] for n in nodes}
    for t in dep.get("tunnels", []):
        a = next((n["id"] for n in nodes if _norm(t.get("source")) in (_norm(n["id"]), _norm(n["ip"]), _norm(n["hostname"]))), None)
        b = next((n["id"] for n in nodes if _norm(t.get("destination")) in (_norm(n["id"]), _norm(n["ip"]), _norm(n["hostname"]))), None)
        if a and b and a != b:
            edges.append({"source": a, "target": b, "kind": "tunnel", "label": t.get("port") or "tunnel"})
    linked = {frozenset((e["source"], e["target"])) for e in edges}
    if console:
        for n in nodes:
            if n["id"] != console["id"] and frozenset((console["id"], n["id"])) not in linked:
                edges.append({"source": console["id"], "target": n["id"], "kind": "managed"})
    for p in ha["pairs"]:
        if p["primary"] in ids and p["secondary"] in ids:
            edges.append({"source": p["primary"], "target": p["secondary"], "kind": "ha", "label": "HA",
                          "ok": p["synchronised"]})
    return edges


def validate_deployment(dep: dict[str, Any], topology: dict[str, Any], mh_rows: list[dict[str, Any]],
                        extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return list of checks: {id,name,status,detail,recommendation}."""
    extra = extra or {}
    checks: list[dict[str, Any]] = []
    nodes = topology["nodes"]

    def add(cid, name, status, detail, reco=""):
        checks.append({"id": cid, "name": name, "status": status, "detail": detail, "recommendation": reco})

    # 1. deployment XML
    if not dep:
        add("xml", "Deployment XML Validation", WARN, "deployment.xml was not found in the bundle.", "Re-collect get_logs from the Console ensuring /store/configservices/staging/globalconfig is included.")
    elif not dep.get("valid_xml", True):
        add("xml", "Deployment XML Validation", CRIT, f"deployment.xml is not well-formed: {dep.get('parse_error')}", "Contact QRadar Support - the staged deployment may be corrupt; restore from the last known good backup.")
    elif not dep.get("hosts"):
        add("xml", "Deployment XML Validation", WARN, "deployment.xml parsed but no host entries were recognised.", "Verify the file is the full staged/active deployment.xml.")
    else:
        add("xml", "Deployment XML Validation", PASS, f"Well-formed XML with {len(dep['hosts'])} host(s) and {len(dep.get('components', []))} component(s).")

    # 2. managed host connectivity
    bad = [n for n in nodes if n.get("status") == "error"]
    unknown = [n for n in nodes if n.get("status") == "unknown"]
    if bad:
        add("connectivity", "Managed Host Connectivity", CRIT, "Hosts in error/unreachable state: " + ", ".join(f"{n['hostname']} ({n.get('ip') or 'n/a'})" for n in bad),
            "Verify SSH/encryption tunnel (TCP 22/4333), hostcontext service and time sync on these hosts.")
    elif nodes and len(unknown) == len(nodes):
        add("connectivity", "Managed Host Connectivity", WARN, "Managed host status was not present in the collected data.", "Confirm host status in Admin > System and License Management.")
    elif nodes:
        add("connectivity", "Managed Host Connectivity", PASS, f"All {len(nodes)} managed host(s) report a healthy state.")
    else:
        add("connectivity", "Managed Host Connectivity", WARN, "No managed hosts could be identified.", "Check that the get_logs package is complete.")

    # 3. host references
    dangling = dep.get("dangling_refs", []) if dep else []
    if dangling:
        add("refs", "Host References", CRIT if len(dangling) > 2 else WARN, f"{len(dangling)} component(s) reference hosts that are not defined: " + ", ".join(dangling[:6]),
            "Remove orphaned components via the Deployment Editor or restore the missing managed hosts, then Deploy Changes.")
    else:
        add("refs", "Host References", PASS, "All component host references resolve to defined managed hosts.")

    # 4. consistency (duplicate ids/ips, MH rows vs xml)
    ips = Counter(n["ip"] for n in nodes if n.get("ip"))
    dups = [ip for ip, c in ips.items() if c > 1]
    xml_ids = {h["id"] for h in dep.get("hosts", [])} if dep else set()
    mh_only = [r for r in mh_rows if (r.get("id") and r["id"] not in xml_ids) and xml_ids and r.get("hostname") not in {h.get("hostname") for h in dep.get("hosts", [])}]
    xml_only = [h for h in (dep.get("hosts", []) if dep else []) if mh_rows and h["id"] not in {r["id"] for r in mh_rows} and h.get("hostname") not in {r.get("hostname") for r in mh_rows}]
    if dups:
        add("consistency", "Deployment Consistency", CRIT, "Duplicate IP addresses across hosts: " + ", ".join(dups), "Remove duplicate host definitions.")
    elif mh_only or xml_only:
        add("consistency", "Deployment Consistency", WARN,
            f"managedhost table and deployment.xml disagree ({len(mh_only)} DB-only, {len(xml_only)} XML-only host entries).", "Deploy Full Configuration and re-verify; unexpected mismatches should be raised with Support.")
    else:
        add("consistency", "Deployment Consistency", PASS, "Host inventory is consistent between deployment.xml and the managedhost table." if mh_rows and dep else "No inconsistencies detected in available data.")

    # 5. token validity
    no_tok = [n for n in nodes if n["role"] != "Console" and "deployment.xml" in n.get("source", []) and not n.get("token")]
    if dep and dep.get("hosts") and any(h.get("token") for h in dep["hosts"]):
        add("token", "Token Validity", WARN if no_tok else PASS,
            ("Managed hosts without an encryption/auth token: " + ", ".join(n["hostname"] for n in no_tok)) if no_tok else "All remote hosts have a registration token.",
            "Re-add the host (generate new token) and redeploy." if no_tok else "")
    else:
        add("token", "Token Validity", WARN, "Token attributes were not present in the collected deployment data; token validity could not be confirmed.", "Verify with 'qradar_hostcontext_status' and certificate expiry in the Admin tab.")

    # 6. masterlist
    ml = extra.get("masterlist")
    if ml is None:
        add("masterlist", "Masterlist Validation", WARN, "No masterlist/host list file found in the bundle.", "Ensure /opt/qradar/conf/masterlist (or equivalent) is collected.")
    else:
        missing = [n["hostname"] for n in nodes if n.get("ip") and n["ip"] not in ml and n["role"] != "Console"]
        add("masterlist", "Masterlist Validation", WARN if missing else PASS,
            ("Hosts missing from masterlist: " + ", ".join(missing[:8])) if missing else f"Masterlist lists {len(ml)} IP address(es), consistent with deployment hosts.",
            "Re-run deployment to regenerate the masterlist." if missing else "")

    # 7. tunnels
    tunnels = dep.get("tunnels", []) if dep else []
    bad_t = [t for t in tunnels if _norm(t.get("status")) in ("down", "error", "failed", "disconnected")]
    if bad_t:
        add("tunnel", "Tunnel Validation", CRIT, f"{len(bad_t)} encryption tunnel(s) are down.", "Verify TCP 4333 (and 7777) between hosts and restart autossh/tunnel services.")
    elif tunnels:
        add("tunnel", "Tunnel Validation", PASS, f"{len(tunnels)} tunnel definition(s), none reported as down.")
    else:
        tun_info = extra.get("tunnel_errors") or 0
        add("tunnel", "Tunnel Validation", WARN if tun_info else PASS, f"{tun_info} tunnel/SSH error line(s) found in logs." if tun_info else "No tunnel failures detected in available data." if len(nodes) > 1 else "Single-host deployment - no tunnels required.")

    # 8. versions
    vers = {n["version"] for n in nodes if n.get("version")}
    if len(vers) > 1:
        add("version", "Software Version Alignment", CRIT, "Multiple software versions: " + ", ".join(sorted(str(v) for v in vers)), "Upgrade lagging hosts so every host runs the same version/fix pack.")
    elif vers:
        add("version", "Software Version Alignment", PASS, f"All hosts report version {next(iter(vers))}.")

    # 9. HA
    ha = topology["ha"]
    if ha["pairs"]:
        notready = [p for p in ha["pairs"] if p["failover_readiness"] == "not_ready"]
        if notready:
            add("ha", "HA Validation", CRIT, f"{len(notready)} HA pair(s) not synchronised / not failover-ready.", "Check DRBD state, heartbeat network and resolve split-brain before the next failure.")
        elif ha["unprotected"]:
            add("ha", "HA Validation", WARN, f"{len(ha['pairs'])} HA pair(s) healthy; unprotected critical hosts: " + ", ".join(u["hostname"] for u in ha["unprotected"]), "Extend HA to remaining Console/Event Processors.")
        else:
            add("ha", "HA Validation", PASS, f"{len(ha['pairs'])} HA pair(s) synchronised and ready for failover.")
    else:
        add("ha", "HA Validation", WARN, "No High Availability configuration detected for any host.", "Deploy HA for the Console and critical processors.")
    return checks
