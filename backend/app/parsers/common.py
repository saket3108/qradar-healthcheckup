"""Shared parsing helpers."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from dateutil import parser as dtparser

_SIZE_RE = re.compile(r"^\s*([\d.,]+)\s*([KMGTP]?)(i?B)?\s*$", re.I)
_MULT = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}


def read_text(path: Path, max_bytes: int = 64 * 1024 * 1024) -> str:
    import gzip

    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:  # type: ignore[arg-type]
        data = fh.read(max_bytes)
    return data.decode("utf-8", errors="replace")


def to_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return default


def to_int(v: Any, default: int | None = None) -> int | None:
    f = to_float(v)
    return int(f) if f is not None else default


def to_bool(v: Any) -> bool | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("t", "true", "1", "yes", "y", "enabled"):
        return True
    if s in ("f", "false", "0", "no", "n", "disabled"):
        return False
    return None


def size_to_bytes(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = _SIZE_RE.match(str(v))
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    return int(num * _MULT[m.group(2).upper()])


def parse_ts(v: Any) -> str | None:
    """Return ISO-8601 UTC string or None. Accepts epoch seconds/millis and free-form dates."""
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip()
    try:
        if re.fullmatch(r"\d{10,13}(\.\d+)?", s):
            f = float(s)
            if f > 1e11:
                f /= 1000.0
            return datetime.fromtimestamp(f, tz=timezone.utc).isoformat()
        d = dtparser.parse(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, dtparser.ParserError):
        return None


def pick(row: Mapping[str, Any], *aliases: str, default: Any = None) -> Any:
    for a in aliases:
        if a in row and row[a] not in (None, ""):
            return row[a]
    return default


def downsample(points: list, max_points: int = 288) -> list:
    n = len(points)
    if n <= max_points:
        return points
    step = n / max_points
    return [points[int(i * step)] for i in range(max_points)]


def mean(xs: Iterable[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def percentile(xs: list[float], p: float) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
