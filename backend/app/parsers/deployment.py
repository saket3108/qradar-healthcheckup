"""QRadar deployment.xml parser (tolerant, schema-agnostic) + helper role mapping."""
from __future__ import annotations

import re
from typing import Any

from defusedxml import ElementTree as ET

# role vocabulary → canonical role
_ROLE_ALIASES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"console|master|magistrate|\bmh0?\b|all[-_ ]?in[-_ ]?one|aio", re.I), "Console"),
    (re.compile(r"data[-_ ]?node|\bdn\b|datanode", re.I), "DN"),
    (re.compile(r"app[-_ ]?host|apphost|app[-_ ]?node|docker", re.I), "App Host"),
    (re.compile(r"event[-_ ]?processor|\bep\b|eventprocessor|ariel[-_ ]?proxy|ecs[-_ ]?ep", re.I), "EP"),
    (re.compile(r"event[-_ ]?collector|\bec\b|eventcollector|ecs[-_ ]?ec", re.I), "EC"),
    (re.compile(r"flow[-_ ]?processor|\bfp\b|flowprocessor|qflow|flow[-_ ]?collector|\bfc\b", re.I), "FP"),
    (re.compile(r"extension|\bext\b", re.I), "Extension"),
]
ROLES = ["Console", "EP", "EC", "FP", "DN", "App Host", "Extension", "Unknown"]

_HOST_TAGS = {"host", "managedhost", "managed_host", "managed-host", "appliance", "server", "node", "machine", "system", "deploymenthost"}
_COMPONENT_HINT_TAGS = {"component", "service", "process", "ecs", "ariel", "qflow", "magistrate", "tomcat", "hostcontext", "accumulator"}
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def role_from_text(*texts: str | None) -> str:
    joined = " ".join(t for t in texts if t)
    found: list[str] = []
    for rx, role in _ROLE_ALIASES:
        if rx.search(joined):
            found.append(role)
    for pref in ("Console", "DN", "App Host", "EP", "EC", "FP", "Extension"):
        if pref in found:
            if pref == "EP" and "EC" in found and "Console" not in found:
                return "EP"
            return pref
    return "Unknown"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attrs_lower(el) -> dict[str, str]:
    return {_local(k).lower(): v for k, v in el.attrib.items()}


def _children_text(el) -> dict[str, str]:
    out = {}
    for ch in list(el):
        if len(ch) == 0 and (ch.text or "").strip():
            out[_local(ch.tag).lower()] = ch.text.strip()
    return out


def parse_deployment_xml(text: str) -> dict[str, Any]:
    """Return {hosts, components, ha_pairs, tunnels, validation_facts}."""
    try:
        root = ET.fromstring(text.encode("utf-8", errors="replace") if isinstance(text, str) else text)
    except ET.ParseError as e:
        return {"valid_xml": False, "parse_error": str(e)[:200], "hosts": [], "components": [], "ha_pairs": [], "tunnels": []}

    hosts: dict[str, dict[str, Any]] = {}
    components: list[dict[str, Any]] = []
    ha_pairs: list[dict[str, Any]] = []
    tunnels: list[dict[str, Any]] = []
    refs: list[str] = []

    def host_key(a: dict[str, str]) -> str | None:
        return a.get("id") or a.get("hostid") or a.get("host_id") or a.get("managedhostid") or a.get("name") or a.get("hostname") or a.get("ip") or a.get("ipaddress")

    def walk(el, parent_host: str | None):
        tag = _local(el.tag).lower()
        a = _attrs_lower(el)
        c = _children_text(el)
        merged = {**c, **a}
        ph = parent_host
        if tag in _HOST_TAGS:
            k = host_key(merged)
            if k is not None:
                h = hosts.setdefault(str(k), {"id": str(k)})
                h["hostname"] = merged.get("hostname") or merged.get("name") or h.get("hostname")
                ip = merged.get("ip") or merged.get("ipaddress") or merged.get("ip_address") or merged.get("address")
                if ip and _IP_RE.match(ip):
                    h["ip"] = ip
                h["type_raw"] = merged.get("type") or merged.get("role") or merged.get("applianceType") or merged.get("appliancetype") or h.get("type_raw")
                h["appliance_type"] = merged.get("appliance") or merged.get("appliancetype") or merged.get("model") or h.get("appliance_type")
                h["status"] = merged.get("status") or h.get("status")
                h["version"] = merged.get("version") or h.get("version")
                h["token"] = merged.get("token") or merged.get("encryptiontoken") or h.get("token")
                h["ha_peer"] = merged.get("ha_peer") or merged.get("peer") or merged.get("secondary") or merged.get("primaryhost") or h.get("ha_peer")
                h["ha_role"] = merged.get("ha_role") or merged.get("harole") or h.get("ha_role")
                h["ha_status"] = merged.get("ha_status") or merged.get("hastatus") or h.get("ha_status")
                h["eps"] = merged.get("eps") or h.get("eps")
                h["fpm"] = merged.get("fpm") or h.get("fpm")
                h["encrypted"] = merged.get("encrypted") or h.get("encrypted")
                h.setdefault("components", [])
                ph = str(k)
        if tag in _COMPONENT_HINT_TAGS or "type" in a and tag not in _HOST_TAGS and tag not in ("deployment", "root"):
            ctype = a.get("type") or a.get("name") or tag
            host_ref = a.get("host") or a.get("hostid") or a.get("managedhostid") or ph
            if host_ref:
                components.append({"host": str(host_ref), "type": ctype, "name": a.get("name"), "id": a.get("id"),
                                   "role": role_from_text(ctype, a.get("name"))})
                if host_ref not in hosts and tag != "hostcontext":
                    refs.append(str(host_ref))
                if ph and ph in hosts:
                    hosts[ph]["components"].append(ctype)
        if tag in ("ha", "hacluster", "ha_cluster", "hapair", "ha_pair", "cluster"):
            ha_pairs.append({"primary": merged.get("primary") or merged.get("primaryhost") or merged.get("primary_host"),
                             "secondary": merged.get("secondary") or merged.get("secondaryhost") or merged.get("secondary_host"),
                             "status": merged.get("status"), "vip": merged.get("vip") or merged.get("virtualip") or merged.get("cluster_ip"),
                             "sync": merged.get("sync") or merged.get("syncstatus") or merged.get("sync_status")})
        if tag in ("tunnel", "connection", "link", "encryption"):
            src = merged.get("source") or merged.get("from") or merged.get("src") or merged.get("host")
            dst = merged.get("destination") or merged.get("to") or merged.get("dst") or merged.get("target")
            if src or dst:
                tunnels.append({"source": src, "destination": dst, "port": merged.get("port"), "status": merged.get("status")})
        for ch in el:
            walk(ch, ph)

    walk(root, None)

    for h in hosts.values():
        h["role"] = role_from_text(h.get("type_raw"), h.get("appliance_type"), " ".join(h.get("components", [])),
                                   h.get("hostname"))
        if h["role"] == "Unknown" and h.get("components"):
            roles = {role_from_text(c) for c in h["components"]} - {"Unknown"}
            for pref in ("Console", "DN", "App Host", "EP", "EC", "FP", "Extension"):
                if pref in roles:
                    h["role"] = pref
                    break
    return {
        "valid_xml": True, "root_tag": _local(root.tag), "hosts": list(hosts.values()), "components": components,
        "ha_pairs": ha_pairs, "tunnels": tunnels, "dangling_refs": sorted({r for r in refs if r not in hosts}),
        "version": _attrs_lower(root).get("version"),
    }
