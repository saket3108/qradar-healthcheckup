"""Customer-ready PDF report (reportlab) – consulting-style layout."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents
from xml.sax.saxutils import escape

from app.reports import charts
from app.reports.model import SECTION_LABELS

NAVY, BLUE = colors.HexColor("#0f2a4a"), colors.HexColor("#0f62fe")
LIGHT, GREYC = colors.HexColor("#f2f4f8"), colors.HexColor("#6f7782")
SEV = {"critical": colors.HexColor("#da1e28"), "high": colors.HexColor("#ff832b"), "medium": colors.HexColor("#d2a106"), "low": colors.HexColor("#24a148"), "info": BLUE}
W, H = A4
M = 18 * mm


def esc(s: Any) -> str:
    return escape(str(s if s is not None else ""))


class Doc(BaseDocTemplate):
    def __init__(self, buf, meta: dict[str, Any], **kw):
        super().__init__(buf, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=24 * mm, bottomMargin=20 * mm,
                         title=meta["title"], author=meta.get("consultant") or "IBM", **kw)
        self.meta = meta
        self._toc_n = 0
        body = Frame(M, 20 * mm, W - 2 * M, H - 44 * mm, id="body")
        cover = Frame(0, 0, W, H, id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="cover", frames=[cover], onPage=self._cover_bg), PageTemplate(id="body", frames=[body], onPage=self._decor)])

    def _cover_bg(self, c, doc):
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(BLUE)
        c.rect(0, H * 0.34, W, 3 * mm, fill=1, stroke=0)
        c.restoreState()

    def _decor(self, c, doc):
        c.saveState()
        c.setStrokeColor(colors.HexColor("#dde1e6"))
        c.line(M, H - 18 * mm, W - M, H - 18 * mm)
        c.setFont("Helvetica", 8)
        c.setFillColor(GREYC)
        c.drawString(M, H - 14 * mm, f"{self.meta['title']}  |  {self.meta['customer']}")
        c.drawRightString(W - M, H - 14 * mm, self.meta["classification"])
        c.line(M, 16 * mm, W - M, 16 * mm)
        c.drawString(M, 11 * mm, f"Prepared by {self.meta.get('consultant') or 'IBM Security'}  -  {self.meta['generated']}")
        c.drawRightString(W - M, 11 * mm, f"Page {doc.page}")
        c.restoreState()

    def beforeDocument(self):
        self._toc_n = 0   # deterministic bookmark keys on every multiBuild pass

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name in ("H1", "H2"):
            lvl = 0 if f.style.name == "H1" else 1
            self._toc_n += 1
            key = f"toc{self._toc_n}"
            self.canv.bookmarkPage(key)
            self.notify("TOCEntry", (lvl, f.getPlainText(), self.page, key))


def styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("B", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=colors.HexColor("#1f2328"))
    return {
        "B": base,
        "Small": ParagraphStyle("Small", parent=base, fontSize=8, leading=11, textColor=GREYC),
        "H1": ParagraphStyle("H1", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY, spaceBefore=4, spaceAfter=10),
        "H2": ParagraphStyle("H2", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=BLUE, spaceBefore=12, spaceAfter=5),
        "H3": ParagraphStyle("H3", parent=base, fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=NAVY, spaceBefore=6, spaceAfter=2),
        "Cell": ParagraphStyle("Cell", parent=base, fontSize=8, leading=10),
        "CellB": ParagraphStyle("CellB", parent=base, fontSize=8, leading=10, fontName="Helvetica-Bold"),
        "Bullet": ParagraphStyle("Bullet", parent=base, leftIndent=12, bulletIndent=2, spaceAfter=2),
        "Comment": ParagraphStyle("Comment", parent=base, backColor=colors.HexColor("#fff8e1"), borderPadding=5, leftIndent=4, fontSize=9, textColor=colors.HexColor("#5b4a00")),
    }


def tbl(rows: list[list[Any]], widths: list[float], st: dict, header: bool = True, zebra: bool = True) -> Table:
    hdr_style = ParagraphStyle("hd", parent=st["CellB"], textColor=colors.white)
    data = []
    for ri, r in enumerate(rows):
        style = hdr_style if (header and ri == 0) else st["Cell"]
        data.append([c if not isinstance(c, (str, int, float)) else Paragraph(esc(c), style) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dde1e6")),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    if zebra:
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(style))
    return t


def img(png: bytes, width_mm: float) -> Image:
    from PIL import Image as PI

    w, h = PI.open(io.BytesIO(png)).size
    wd = width_mm * mm
    return Image(io.BytesIO(png), width=wd, height=wd * h / w)


def sev_pill(sev: str, st: dict) -> Paragraph:
    return Paragraph(f'<font color="{SEV.get(sev, BLUE).hexval().replace("0x", "#")}"><b>{esc(sev.upper())}</b></font>', st["Cell"])


def build_pdf(model: dict[str, Any]) -> bytes:
    st = styles()
    a, cfg = model["assessment"], model["config"]
    meta = {"title": cfg["title"], "customer": a["customer"], "consultant": a["consultant"], "generated": a["generated"], "classification": cfg["classification"]}
    buf = io.BytesIO()
    doc = Doc(buf, meta)
    secs = [s for s in cfg["sections"]]
    story: list[Any] = []
    comments = model["comments"]

    def section_comment(key: str):
        c = comments.get(f"section:{key}")
        if c:
            story.append(Spacer(1, 4))
            story.append(Paragraph("<b>Consultant comment:</b> " + esc(c).replace("\n", "<br/>"), st["Comment"]))

    # ---- cover ---------------------------------------------------------------
    from reportlab.platypus import NextPageTemplate

    story.append(NextPageTemplate("cover"))
    if "cover" in secs:
        logo = cfg.get("logo_path")
        cov = ParagraphStyle("cov", fontName="Helvetica-Bold", fontSize=32, leading=38, textColor=colors.white, leftIndent=M)
        sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=14, leading=20, textColor=colors.HexColor("#c6d4f0"), leftIndent=M)
        small = ParagraphStyle("sm", fontName="Helvetica", fontSize=10, leading=15, textColor=colors.HexColor("#c6d4f0"), leftIndent=M)
        story.append(Spacer(1, 70 * mm))
        if logo and Path(logo).exists():
            try:
                from PIL import Image as PI
                lw, lh = PI.open(logo).size
                im = Image(logo, width=45 * mm, height=45 * mm * lh / lw)
                im.hAlign = "LEFT"
                t = Table([[im]], colWidths=[W])
                t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), M), ("BACKGROUND", (0, 0), (-1, -1), colors.white), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
                story += [t, Spacer(1, 10 * mm)]
            except Exception:  # noqa: BLE001
                pass
        story += [Paragraph(esc(cfg["title"]), cov), Spacer(1, 6 * mm), Paragraph(esc(a["customer"]), sub), Spacer(1, 40 * mm)]
        score = (model["scores"].get("overall") or {})
        story += [Paragraph(f"Overall health score: <b>{score.get('score', 'n/a')}/100</b> &nbsp; Risk: <b>{esc(score.get('risk_level', 'n/a'))}</b>", sub), Spacer(1, 12 * mm),
                  Paragraph(f"QRadar version: {esc(a.get('version') or model['environment'].get('version') or 'n/a')}", small),
                  Paragraph(f"Prepared by: {esc(a['consultant'] or 'IBM Security')}", small), Paragraph(f"Date: {esc(a['generated'])}", small),
                  Paragraph(esc(cfg["classification"]).upper(), small)]
    story.append(NextPageTemplate("body"))
    story.append(PageBreak())

    # ---- toc -----------------------------------------------------------------
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("t1", fontName="Helvetica-Bold", fontSize=10.5, leading=18, leftIndent=0), ParagraphStyle("t2", fontName="Helvetica", fontSize=9, leading=14, leftIndent=14)]
    story += [Paragraph("Contents", st["H1"]), toc, PageBreak()]

    S = model["scores"]
    cats, ov = S.get("categories") or {}, S.get("overall") or {}

    if "executive_summary" in secs:
        story.append(Paragraph("Executive Summary", st["H1"]))
        story.append(Paragraph(esc(model["summary"].get("headline", "")), st["H2"]))
        for p in model["summary"].get("paragraphs", []):
            story += [Paragraph(esc(p), st["B"]), Spacer(1, 5)]
        if model["summary"].get("highlights"):
            story.append(Paragraph("Key facts", st["H3"]))
            story += [Paragraph(esc(h), st["Bullet"], bulletText="\u2022") for h in model["summary"]["highlights"]]
        if cfg.get("notes"):
            story += [Paragraph("Consultant notes", st["H3"]), Paragraph(esc(cfg["notes"]).replace("\n", "<br/>"), st["Comment"])]
        section_comment("executive_summary")
        story.append(PageBreak())

    if "health_score" in secs and ov:
        story.append(Paragraph("Health Score", st["H1"]))
        row = [[img(charts.gauge(ov["score"], f"Grade {ov['grade']}"), 62), img(charts.severity_donut(ov.get("severity_totals", {})), 55)]]
        t = Table(row, colWidths=[85 * mm, 85 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        story += [t, Spacer(1, 4)]
        story.append(tbl([["Overall", "Risk score", "Risk level", "Maturity"], [f"{ov['score']}/100 ({ov['grade']})", f"{ov['risk_score']}/100", ov["risk_level"], f"{ov['maturity_level']} ({ov['maturity_index']}/5)"]], [42 * mm] * 4, st))
        story += [Spacer(1, 6), img(charts.category_bars(cats), 165)]
        rows = [["Category", "Score", "Critical", "High", "Medium", "Low"]]
        for c in cats.values():
            f = c["findings"]
            rows.append([c["label"] + ("" if c["data_available"] else " (no data)"), c["score"], f["critical"], f["high"], f["medium"], f["low"]])
        story += [Spacer(1, 6), tbl(rows, [58 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm], st)]
        section_comment("health_score")
        story.append(PageBreak())

    if "environment" in secs:
        e = model["environment"]
        story.append(Paragraph("Environment Overview", st["H1"]))
        rows = [["Attribute", "Value"], ["QRadar version", e.get("version") or "Not determined"], ["Fix pack", e.get("fix_pack") or "Not determined"], ["Build", e.get("build") or "Not determined"],
                ["Deployment type", e.get("deployment_type") or "Not determined"], ["Installation type", e.get("install_type") or "Not determined"],
                ["Software / hardware", e.get("software_hardware") or "Not determined"], ["Hosts", e.get("hosts")], ["Console", e.get("console") or "n/a"]]
        story.append(tbl(rows, [55 * mm, 115 * mm], st))
        nodes = model["topology"].get("nodes", [])
        if nodes:
            story.append(Paragraph("Appliance inventory", st["H2"]))
            rows = [["Hostname", "IP", "Role", "CPU", "RAM", "Disk"]]
            for n in nodes:
                rows.append([n.get("hostname"), n.get("ip") or "-", n.get("role"), n.get("cpu_cores") or "-", _gb(n.get("memory_bytes")), _gb(n.get("disk_bytes"))])
            story.append(tbl(rows, [45 * mm, 30 * mm, 24 * mm, 16 * mm, 26 * mm, 29 * mm], st))
        au = model["autoupdate"]
        if au:
            story += [Paragraph("Auto Update", st["H2"]), tbl([["Current version", "Latest version", "Pending updates", "Repository connectivity"],
                                                             [au.get("current_version") or "n/a", au.get("latest_version") or "n/a", au.get("pending_updates", 0),
                                                              {True: "Reachable", False: "Unreachable", None: "Unknown"}[au.get("repo_reachable")]]], [42 * mm] * 4, st)]
        section_comment("environment")
        story.append(PageBreak())

    if "deployment" in secs:
        story.append(Paragraph("Deployment", st["H1"]))
        story += [img(charts.deployment_diagram(model["topology"]), 168), Spacer(1, 6)]
        ha = model["topology"].get("ha", {})
        story.append(Paragraph("High availability: " + (f"{len(ha.get('pairs', []))} pair(s) configured." if ha.get("pairs") else "<b>not configured</b>."), st["B"]))
        story.append(Paragraph("Deployment validation", st["H2"]))
        rows = [["Check", "Result", "Detail"]]
        for c in model["deployment_checks"]:
            rows.append([c["name"], c["status"], c["detail"]])
        t = tbl(rows, [45 * mm, 24 * mm, 101 * mm], st)
        story.append(t)
        section_comment("deployment")
        story.append(PageBreak())

    if "notifications" in secs:
        n = model["notifications"]
        story.append(Paragraph("Notification Analysis", st["H1"]))
        bs = n.get("by_severity", {})
        story += [tbl([["Critical", "High", "Medium", "Low", "Info", "Open"], [bs.get("critical", 0), bs.get("high", 0), bs.get("medium", 0), bs.get("low", 0), bs.get("info", 0), n.get("open", 0)]], [28 * mm] * 6, st), Spacer(1, 6)]
        shown = [i for i in n.get("items", []) if i["effective_severity"] in ("critical", "high", "medium")][:40]
        for i in shown:
            block = [Paragraph(f"{esc(i['title'])} <font color='#6f7782' size=8>- {esc(i['effective_severity'].upper())} / {esc(i['priority'])}</font>", st["H3"]),
                     Paragraph(f"<i>{esc(i['message'][:300])}</i>", st["Small"]),
                     Paragraph(f"<b>Root cause:</b> {esc(i['root_cause'])}", st["B"]), Paragraph(f"<b>Business impact:</b> {esc(i['business_impact'])}", st["B"]),
                     Paragraph("<b>Recommendation:</b>", st["B"])] + [Paragraph(esc(r), st["Bullet"], bulletText="\u2022") for r in i["recommendation"][:4]] + \
                    [Paragraph(f"<b>IBM best practice:</b> {esc(i['best_practice'])}", st["Small"])]
            if i.get("comment"):
                block.append(Paragraph("<b>Consultant comment:</b> " + esc(i["comment"]), st["Comment"]))
            story.append(KeepTogether(block))
        if len(n.get("items", [])) > len(shown):
            story.append(Paragraph(f"{len(n['items']) - len(shown)} lower-severity notification(s) are listed in the appendix.", st["Small"]))
        section_comment("notifications")
        story.append(PageBreak())

    if "logsources" in secs:
        l = model["logsources"]
        story.append(Paragraph("Log Source Analysis", st["H1"]))
        if l.get("total"):
            story.append(tbl([["Total", "Enabled", "Disabled", "Error", "Unknown", "Total EPS", "Avg EPS"], [l["total"], l["enabled"], l["disabled"], l["error"], l["unknown"], f"{l['total_eps']:.0f}", f"{l['average_eps']:.1f}"]], [24 * mm] * 7, st))
            pr = l.get("protocols", [])
            row = [[img(charts.bar([p["name"] for p in pr], [p["count"] for p in pr], "Log sources by protocol"), 85), img(charts.pie([p["name"] for p in pr], [p["eps"] for p in pr], "EPS by protocol"), 80)]]
            story += [Spacer(1, 6), Table(row, colWidths=[88 * mm, 82 * mm])]
            story += [Paragraph("Top EPS sources", st["H2"]), tbl([["Name", "Type", "Protocol", "EPS"]] + [[s["name"], s["type"], s["protocol"], f"{s['eps']:.1f}"] for s in l["top_eps"][:10]], [55 * mm, 55 * mm, 40 * mm, 20 * mm], st)]
            if l.get("problematic"):
                story += [Paragraph("Problematic log sources", st["H2"]),
                          tbl([["Name", "Type", "Status", "EPS", "Last event", "Reason"]] + [[p["name"], p["type"], p["status"], f"{p['eps']:.1f}", (p.get("last_event") or "-")[:10], "; ".join(p["reasons"])] for p in l["problematic"][:30]],
                              [34 * mm, 30 * mm, 16 * mm, 14 * mm, 20 * mm, 56 * mm], st)]
        else:
            story.append(Paragraph("No log source data was present in the collected bundle.", st["B"]))
        story.append(Paragraph("Log source recommendations", st["H2"]))
        for f in [f for f in model["findings"] if f["category"] == "logsources"][:8]:
            story += _finding_block(f, st)
        section_comment("logsources")
        story.append(PageBreak())

    if "wincollect" in secs:
        w = model["wincollect"]
        story.append(Paragraph("WinCollect Analysis", st["H1"]))
        if w.get("total"):
            story.append(tbl([["Total", "Managed", "Standalone", "Unmanaged", "Disconnected", "Outdated"], [w["total"], w["managed"], w["standalone"], w["unmanaged"], w["disconnected"], w["outdated"]]], [28 * mm] * 6, st))
            v = w.get("versions", [])
            story += [Spacer(1, 6), img(charts.bar([x["version"] for x in v][:12], [x["count"] for x in v][:12], "Agent version distribution", color=charts.TEAL, horizontal=False), 120)]
            for title, key in (("Old versions", "old_versions"), ("Communication problems", "communication_problems"), ("Configuration issues", "config_issues"), ("Deployment problems", "deployment_problems")):
                if w.get(key):
                    story += [Paragraph(title, st["H2"]), tbl([["Agent", "Version", "Status", "Detail"]] + [[x["name"], x.get("version") or "-", x["status"], x.get("reason") or ""] for x in w[key][:15]], [45 * mm, 24 * mm, 28 * mm, 73 * mm], st)]
        else:
            story.append(Paragraph("No WinCollect agent data was present in the collected bundle.", st["B"]))
        for f in [f for f in model["findings"] if f["category"] == "wincollect"][:5]:
            story += _finding_block(f, st)
        section_comment("wincollect")
        story.append(PageBreak())

    if "applications" in secs:
        ap = model["applications"]
        story.append(Paragraph("Application Analysis", st["H1"]))
        if ap.get("total"):
            story.append(tbl([["Running", "Stopped", "Degraded", "Error"], [ap["running"], ap["stopped"], ap["degraded"], ap["error"]]], [42 * mm] * 4, st))
            story.append(Spacer(1, 6))
            story.append(tbl([["Application", "Version", "Host", "Status", "CPU", "Memory", "Restarts"]] + [[i["name"], i.get("version") or "-", i.get("host") or "-", i["status"],
                         f"{i['cpu_pct']:.0f}%" if i.get("cpu_pct") is not None else "-", f"{i['memory_pct']:.0f}%" if i.get("memory_pct") is not None else "-", i.get("restart_count", 0)] for i in ap["items"][:40]],
                        [40 * mm, 20 * mm, 30 * mm, 20 * mm, 16 * mm, 20 * mm, 24 * mm], st))
            for i in [x for x in ap["items"] if x["issues"]][:12]:
                block = [Paragraph(f"{esc(i['name'])} - {esc(i['status'])}", st["H3"]), Paragraph(f"<b>Observation:</b> {esc(i['observation'])}", st["B"]), Paragraph(f"<b>Impact:</b> {esc(i['impact'])}", st["B"]),
                         Paragraph(f"<b>Priority:</b> {esc(i['priority'])}", st["B"])] + [Paragraph(esc(r), st["Bullet"], bulletText="\u2022") for r in i["recommendation"][:3]]
                if i.get("comment"):
                    block.append(Paragraph("<b>Consultant comment:</b> " + esc(i["comment"]), st["Comment"]))
                story.append(KeepTogether(block))
        else:
            story.append(Paragraph("No application data was present in the collected bundle.", st["B"]))
        section_comment("applications")
        story.append(PageBreak())

    if "performance" in secs:
        story.append(Paragraph("Performance Analysis", st["H1"]))
        hosts = model["performance_hosts"]
        for name, h in list(hosts.items())[:6]:
            story.append(Paragraph(esc(name), st["H2"]))
            ser = h.get("series", {})
            if ser.get("cpu"):
                story.append(img(charts.line(ser["cpu"], [("used", "CPU used %", charts.BLUE), ("iowait", "I/O wait %", "#ff832b")], "CPU utilisation", "%", (0, 100), hline=90), 165))
            if ser.get("memory"):
                story.append(img(charts.line(ser["memory"], [("used_pct", "Memory used %", charts.PURPLE)], "Memory utilisation (excl. cache)", "%", (0, 100), hline=90), 165))
            if ser.get("disk"):
                story.append(img(charts.line(ser["disk"], [("await", "await (ms)", "#da1e28"), ("util", "%util", charts.TEAL)], "Disk latency & utilisation"), 165))
            if h.get("df"):
                story.append(tbl([["Mount", "Size", "Used", "Use %"]] + [[f["mount"], _gb(f["size_bytes"]), _gb(f["used_bytes"]), f"{f['use_pct']:.0f}%"] for f in h["df"] if f.get("size_bytes")][:14], [60 * mm, 36 * mm, 36 * mm, 30 * mm], st))
        story.append(Paragraph("Performance findings", st["H2"]))
        rows = [["Host", "Metric", "Severity", "Finding", "Priority"]]
        for p in [x for x in model["performance_assessments"] if x["severity"] not in ("ok", "info")][:40]:
            rows.append([p["host"], p["label"], p["severity"].upper(), p["finding"], p["priority"]])
        if len(rows) > 1:
            story.append(tbl(rows, [26 * mm, 32 * mm, 18 * mm, 80 * mm, 14 * mm], st))
        else:
            story.append(Paragraph("No performance risks were identified.", st["B"]))
        section_comment("performance")
        story.append(PageBreak())

    if "licensing" in secs:
        lic = model["licensing"]
        story.append(Paragraph("Licensing", st["H1"]))
        if lic.get("has_data"):
            rows = [["Metric", "Licensed", "Current", "Peak", "Consumption", "Risk"]]
            for m in (lic.get("eps"), lic.get("fpm")):
                if m:
                    rows.append([m["name"], _n(m.get("licensed")), _n(m.get("current")), _n(m.get("peak")), f"{m['consumption_pct']:.0f}%" if m.get("consumption_pct") is not None else "n/a", m["risk"]])
            story.append(tbl(rows, [26 * mm, 28 * mm, 28 * mm, 28 * mm, 30 * mm, 30 * mm], st))
            for m in (lic.get("eps"), lic.get("fpm")):
                if m and m.get("series"):
                    story.append(img(charts.licence_chart(m), 160))
                if m and m.get("forecast"):
                    story.append(Paragraph(f"{m['name']} forecast: " + ", ".join(f"{f['months']} months: {f['pct']:.0f}%" for f in m["forecast"] if f.get("pct") is not None), st["B"]))
        else:
            story.append(Paragraph("No licence information was present in the collected bundle.", st["B"]))
        section_comment("licensing")
        story.append(PageBreak())

    if "recommendations" in secs:
        story.append(Paragraph("Recommendations", st["H1"]))
        for t in model["top_recommendations"]:
            block = [Paragraph(f"{t['rank']}. {esc(t['title'])} <font color='#6f7782' size=8>- {esc(t['severity'].upper())} / {esc(t['priority'])} / {t['count']} finding(s)</font>", st["H3"]),
                     Paragraph(f"<b>Impact:</b> {esc(t['impact'])}", st["B"])] + [Paragraph(esc(r), st["Bullet"], bulletText="\u2022") for r in t["recommendation"][:5]] + [Paragraph(f"<b>IBM best practice:</b> {esc(t['best_practice'])}", st["Small"])]
            story.append(KeepTogether(block))
        section_comment("recommendations")
        story.append(PageBreak())

    if "next_steps" in secs:
        story.append(Paragraph("Next Steps", st["H1"]))
        story += [Paragraph(esc(s), st["Bullet"], bulletText=f"{i}.") for i, s in enumerate(cfg["next_steps"], 1)]
        section_comment("next_steps")
        story.append(PageBreak())

    if "appendix" in secs:
        story.append(Paragraph("Appendix", st["H1"]))
        story.append(Paragraph("A. Complete findings register", st["H2"]))
        rows = [["#", "Severity", "Priority", "Category", "Finding"]]
        for i, f in enumerate(model["findings"], 1):
            rows.append([i, f["severity"].upper(), f["priority"], f["category"], f["title"]])
        story.append(tbl(rows, [10 * mm, 20 * mm, 16 * mm, 28 * mm, 96 * mm], st))
        low = [i for i in model["notifications"].get("items", []) if i["effective_severity"] in ("low", "info")][:60]
        if low:
            story += [Paragraph("B. Low-severity notifications", st["H2"]), tbl([["Severity", "Timestamp", "Message"]] + [[i["effective_severity"], (i.get("timestamp") or "-")[:16], i["message"][:200]] for i in low], [20 * mm, 30 * mm, 120 * mm], st)]
        m = model["manifest"]
        story += [Paragraph("C. Data collection", st["H2"]), Paragraph(f"Source package: {esc(a['source_filename'])}. Archive members scanned: {m.get('total_members', 'n/a')}. "
                                                                         f"Analysis is based exclusively on the data present in the supplied get_logs package; metrics not present in the package are reported as unavailable.", st["B"])]
    doc.multiBuild(story)
    return buf.getvalue()


def _finding_block(f: dict[str, Any], st: dict) -> list[Any]:
    block = [Paragraph(f"{esc(f['title'])} <font color='#6f7782' size=8>- {esc(f['severity'].upper())} / {esc(f['priority'])}</font>", st["H3"]),
             Paragraph(esc(f["observation"]), st["B"])] + [Paragraph(esc(r), st["Bullet"], bulletText="\u2022") for r in f["recommendation"][:4]]
    if f.get("comment"):
        block.append(Paragraph("<b>Consultant comment:</b> " + esc(f["comment"]), st["Comment"]))
    return [KeepTogether(block)]


def _gb(b: Any) -> str:
    return f"{b / 1024**3:.0f} GB" if b else "-"


def _n(v: Any) -> str:
    return f"{v:,.0f}" if v is not None else "n/a"
