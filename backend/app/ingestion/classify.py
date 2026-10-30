"""Classify get_logs members into analysis categories (path/name driven)."""
from __future__ import annotations

import re

CATEGORIES = ("deployment", "hostcontext", "autoupdate", "db_dump", "sar", "system", "config",
              "application", "wincollect", "logsource", "log", "other")

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("deployment", re.compile(r"(^|/)deployment[^/]*\.xml(\.gz)?$|(^|/)(globalconfig|staging)/[^/]*deployment[^/]*\.xml$", re.I)),
    ("hostcontext", re.compile(r"hostcontext", re.I)),
    ("autoupdate", re.compile(r"auto[_-]?update|autoupdate", re.I)),
    ("wincollect", re.compile(r"wincollect|win_collect", re.I)),
    ("application", re.compile(r"installed_application|app_framework|appframework|(^|/)apps?(/|_)|docker[_-]?(ps|inspect)|\bapp[_-]?instance", re.I)),
    ("logsource", re.compile(r"sensordevice|log_?sources?|logsource", re.I)),
    ("db_dump", re.compile(r"(\.sql|\.dump|\.pgdump|\.pg_dump|\.copy|_view|\.tsv|\.csv)(\.gz)?$|postgres|pg_dump|notification_view|managedhost", re.I)),
    ("sar", re.compile(r"(^|/)(sar|sa)[^/]*$|(^|/)sa\d{2}(\.gz)?$|sysstat|iostat|(^|/)sar_", re.I)),
    ("system", re.compile(r"(^|/)(df|free|top|ps|uptime|lsblk|lscpu|ifconfig|dmesg|vmstat|mount|hostname|uname|cpuinfo|meminfo|"
                          r"os-release|redhat-release|ip[_-]?addr|netstat|ss|fdisk|pvs|vgs|lvs|rpm[_-]?qa|systemctl)[^/]*$|"
                          r"system[_-]?(info|output)|/proc/|hardware|dmidecode", re.I)),
    ("config", re.compile(r"\.(conf|cfg|properties|ini|yaml|yml|json|xml)(\.gz)?$|(^|/)VERSION[^/]*$|/opt/qradar/conf", re.I)),
    ("log", re.compile(r"\.log(\.\d+)?(\.gz)?$|qradar\.(error|log)|/var/log/|messages(-\d+)?(\.gz)?$", re.I)),
]

# Hard ceiling for non-interesting members (bytes)
OTHER_MAX_BYTES = 5 * 1024 * 1024
LOG_MAX_BYTES = 64 * 1024 * 1024
CONFIG_MAX_BYTES = 128 * 1024 * 1024

ARCHIVE_RE = re.compile(r"\.(tar|tar\.gz|tgz|zip|gz)$", re.I)


def classify(path: str) -> str:
    p = path.replace("\\", "/")
    for cat, rx in _RULES:
        if rx.search(p):
            return cat
    return "other"


def member_cap(category: str, global_cap: int, text_cap: int) -> int:
    """Max bytes to extract for a member of this category."""
    if category == "other":
        return OTHER_MAX_BYTES
    if category == "log":
        return min(LOG_MAX_BYTES, text_cap)
    if category in ("db_dump",):
        return global_cap
    if category in ("sar", "system", "config", "deployment", "hostcontext", "autoupdate", "application",
                    "wincollect", "logsource"):
        return min(text_cap, CONFIG_MAX_BYTES) if category != "sar" else text_cap
    return OTHER_MAX_BYTES
