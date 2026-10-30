"""Chart rendering (matplotlib, headless) for report exports.  All functions return PNG bytes."""
from __future__ import annotations

import io
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Wedge  # noqa: E402

NAVY, BLUE, TEAL, PURPLE = "#0f2a4a", "#0f62fe", "#009d9a", "#8a3ffc"
SEV_COLORS = {"critical": "#da1e28", "high": "#ff832b", "medium": "#f1c21b", "low": "#42be65", "info": "#78a9ff"}
GREY = "#6f7782"


def _score_color(v: float) -> str:
    return "#24a148" if v >= 85 else "#8bc34a" if v >= 70 else "#f1c21b" if v >= 55 else "#ff832b" if v >= 40 else "#da1e28"


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c6c6c6")
    ax.tick_params(colors=GREY, labelsize=8)


def gauge(value: float, label: str = "", vmax: float = 100, size: float = 3.2) -> bytes:
    fig, ax = plt.subplots(figsize=(size, size * 0.62))
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-0.15, 1.15)
    ax.axis("off")
    ax.add_patch(Wedge((0, 0), 1.0, 0, 180, width=0.22, facecolor="#e8eaed"))
    frac = max(0.0, min(1.0, value / vmax))
    ax.add_patch(Wedge((0, 0), 1.0, 180 - 180 * frac, 180, width=0.22, facecolor=_score_color(value)))
    ax.text(0, 0.28, f"{value:.0f}", ha="center", va="center", fontsize=26, fontweight="bold", color=NAVY)
    if label:
        ax.text(0, -0.02, label, ha="center", va="center", fontsize=9, color=GREY)
    return _png(fig)


def usage_gauge(pct: float | None, label: str) -> bytes:
    p = pct or 0
    fig, ax = plt.subplots(figsize=(2.8, 1.8))
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-0.15, 1.15)
    ax.axis("off")
    ax.add_patch(Wedge((0, 0), 1.0, 0, 180, width=0.22, facecolor="#e8eaed"))
    color = "#24a148" if p < 70 else "#f1c21b" if p < 85 else "#ff832b" if p < 100 else "#da1e28"
    ax.add_patch(Wedge((0, 0), 1.0, 180 - 180 * min(p, 100) / 100, 180, width=0.22, facecolor=color))
    ax.text(0, 0.28, f"{p:.0f}%" if pct is not None else "n/a", ha="center", va="center", fontsize=20, fontweight="bold", color=NAVY)
    ax.text(0, -0.02, label, ha="center", fontsize=9, color=GREY)
    return _png(fig)


def category_bars(cats: dict[str, Any]) -> bytes:
    items = list(cats.values())
    fig, ax = plt.subplots(figsize=(7, 0.42 * len(items) + 0.6))
    names = [c["label"] for c in items][::-1]
    vals = [c["score"] for c in items][::-1]
    bars = ax.barh(names, vals, color=[_score_color(v) for v in vals], height=0.62)
    ax.set_xlim(0, 100)
    for b, v in zip(bars, vals):
        ax.text(v + 1.5, b.get_y() + b.get_height() / 2, f"{v}", va="center", fontsize=9, color=NAVY, fontweight="bold")
    _style(ax)
    ax.grid(axis="x", color="#eceff1")
    ax.set_axisbelow(True)
    return _png(fig)


def radar(cats: dict[str, Any]) -> bytes:
    import numpy as np

    items = list(cats.values())
    labels = [c["label"] for c in items]
    vals = [c["score"] for c in items]
    ang = np.linspace(0, 2 * np.pi, len(vals), endpoint=False).tolist()
    vals2, ang2 = vals + vals[:1], ang + ang[:1]
    fig, ax = plt.subplots(figsize=(4.2, 4.2), subplot_kw={"polar": True})
    ax.plot(ang2, vals2, color=BLUE, linewidth=2)
    ax.fill(ang2, vals2, color=BLUE, alpha=0.2)
    ax.set_xticks(ang)
    ax.set_xticklabels(labels, fontsize=8, color=NAVY)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels([], fontsize=6)
    ax.grid(color="#dde1e6")
    return _png(fig)


def severity_donut(totals: dict[str, int]) -> bytes:
    keys = [k for k in ("critical", "high", "medium", "low") if totals.get(k)]
    fig, ax = plt.subplots(figsize=(3.4, 3.4))
    if not keys:
        ax.text(0.5, 0.5, "No findings", ha="center", va="center", fontsize=12, color=GREY)
        ax.axis("off")
        return _png(fig)
    ax.pie([totals[k] for k in keys], colors=[SEV_COLORS[k] for k in keys], startangle=90, counterclock=False,
           wedgeprops={"width": 0.38, "edgecolor": "white"}, labels=[f"{k.title()} ({totals[k]})" for k in keys], textprops={"fontsize": 8, "color": NAVY})
    ax.text(0, 0, str(sum(totals.get(k, 0) for k in keys)), ha="center", va="center", fontsize=20, fontweight="bold", color=NAVY)
    return _png(fig)


def bar(labels: list[str], values: list[float], title: str = "", color: str = BLUE, horizontal: bool = True, size=(6.5, 3.2), fmt="{:.0f}") -> bytes:
    fig, ax = plt.subplots(figsize=size)
    if not labels:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", color=GREY)
        ax.axis("off")
        return _png(fig)
    if horizontal:
        b = ax.barh(labels[::-1], values[::-1], color=color, height=0.62)
        for r, v in zip(b, values[::-1]):
            ax.text(r.get_width(), r.get_y() + r.get_height() / 2, " " + fmt.format(v), va="center", fontsize=8, color=NAVY)
    else:
        b = ax.bar(labels, values, color=color, width=0.62)
        for r, v in zip(b, values):
            ax.text(r.get_x() + r.get_width() / 2, r.get_height(), fmt.format(v), ha="center", va="bottom", fontsize=8, color=NAVY)
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    if title:
        ax.set_title(title, fontsize=10, color=NAVY, loc="left", fontweight="bold")
    _style(ax)
    return _png(fig)


def pie(labels: list[str], values: list[float], title: str = "") -> bytes:
    pal = [BLUE, TEAL, PURPLE, "#ff832b", "#f1c21b", "#42be65", "#da1e28", "#78a9ff", "#9f1853", "#6f7782"]
    fig, ax = plt.subplots(figsize=(4.2, 3.4))
    if not values or sum(values) == 0:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", color=GREY)
        ax.axis("off")
        return _png(fig)
    ax.pie(values, labels=labels, colors=pal[: len(values)], startangle=90, counterclock=False, wedgeprops={"width": 0.45, "edgecolor": "white"},
           textprops={"fontsize": 7, "color": NAVY})
    if title:
        ax.set_title(title, fontsize=10, color=NAVY, fontweight="bold")
    return _png(fig)


def line(series: list[dict[str, Any]], keys: list[tuple[str, str, str]], title: str = "", ylabel: str = "", ylim: tuple | None = None, size=(6.8, 2.8),
         hline: float | None = None) -> bytes:
    """series: [{ts, ...}], keys: [(field, label, color)]"""
    from datetime import datetime

    fig, ax = plt.subplots(figsize=size)
    if not series:
        ax.text(0.5, 0.5, "No data collected", ha="center", va="center", color=GREY)
        ax.axis("off")
        return _png(fig)
    xs = [datetime.fromisoformat(p["ts"]) for p in series]
    for field, label, color in keys:
        ys = [p.get(field) for p in series]
        if any(y is not None for y in ys):
            ax.plot(xs, [y if y is not None else float("nan") for y in ys], label=label, color=color, linewidth=1.5)
    if hline is not None:
        ax.axhline(hline, color="#da1e28", linestyle="--", linewidth=1)
    if ylim:
        ax.set_ylim(*ylim)
    ax.set_ylabel(ylabel, fontsize=8, color=GREY)
    if title:
        ax.set_title(title, fontsize=10, color=NAVY, loc="left", fontweight="bold")
    ax.legend(fontsize=7, frameon=False, loc="upper right", ncol=len(keys))
    ax.grid(color="#eceff1")
    _style(ax)
    fig.autofmt_xdate()
    return _png(fig)


def licence_chart(m: dict[str, Any]) -> bytes:
    series = m.get("series") or []
    fig, ax = plt.subplots(figsize=(6.8, 2.8))
    if not series:
        ax.text(0.5, 0.5, "No usage history in bundle", ha="center", va="center", color=GREY)
        ax.axis("off")
        return _png(fig)
    from datetime import datetime

    xs = [datetime.fromisoformat(p["ts"]) for p in series]
    ax.plot(xs, [p["value"] for p in series], color=BLUE, label="Average", linewidth=1.6)
    ax.plot(xs, [p.get("peak") or p["value"] for p in series], color=PURPLE, label="Peak", linewidth=1, alpha=0.7)
    if m.get("licensed"):
        ax.axhline(m["licensed"], color="#da1e28", linestyle="--", linewidth=1.2, label=f"Licensed ({m['licensed']:.0f})")
    ax.set_title(f"{m['name']} usage", fontsize=10, color=NAVY, loc="left", fontweight="bold")
    ax.legend(fontsize=7, frameon=False)
    ax.grid(color="#eceff1")
    _style(ax)
    fig.autofmt_xdate()
    return _png(fig)


def deployment_diagram(topo: dict[str, Any]) -> bytes:
    nodes, edges = topo.get("nodes", []), topo.get("edges", [])
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.axis("off")
    if not nodes:
        ax.text(0.5, 0.5, "No deployment information", ha="center", va="center", color=GREY)
        return _png(fig)
    order = ["Console", "EP", "EC", "FP", "DN", "App Host", "Extension", "Unknown"]
    tiers: dict[str, list[dict]] = {}
    for n in nodes:
        tiers.setdefault(n["role"], []).append(n)
    rows = [r for r in order if r in tiers]
    pos: dict[str, tuple[float, float]] = {}
    ymax = len(rows)
    for ri, role in enumerate(rows):
        lst = tiers[role]
        for i, n in enumerate(lst):
            pos[n["id"]] = ((i + 1) / (len(lst) + 1) * 10, (ymax - ri) * 2.0)
    for e in edges:
        if e["source"] in pos and e["target"] in pos:
            (x1, y1), (x2, y2) = pos[e["source"]], pos[e["target"]]
            ax.plot([x1, x2], [y1, y2], color=("#24a148" if e.get("ok", True) else "#da1e28") if e["kind"] == "ha" else "#b0b7c3",
                    linewidth=2 if e["kind"] == "ha" else 1, linestyle="--" if e["kind"] == "ha" else "-", zorder=1)
    role_colors = {"Console": NAVY, "EP": BLUE, "EC": TEAL, "FP": PURPLE, "DN": "#9f1853", "App Host": "#ff832b", "Extension": "#6f7782", "Unknown": "#a8a8a8"}
    for n in nodes:
        x, y = pos[n["id"]]
        st = n.get("status")
        edge = "#da1e28" if st == "error" else "#f1c21b" if st == "warning" else "white"
        ax.add_patch(plt.Rectangle((x - 0.95, y - 0.6), 1.9, 1.2, facecolor=role_colors.get(n["role"], "#a8a8a8"), edgecolor=edge, linewidth=2.2, zorder=2))
        ax.text(x, y + 0.28, f"{n['role']}", ha="center", color="white", fontsize=8, fontweight="bold", zorder=3)
        ax.text(x, y, (n.get("hostname") or "")[:20], ha="center", color="white", fontsize=7, zorder=3)
        ax.text(x, y - 0.28, n.get("ip") or "", ha="center", color="#dbe6ff", fontsize=6.5, zorder=3)
    ax.set_xlim(0, 10)
    ax.set_ylim(0.3, ymax * 2 + 1)
    return _png(fig)
