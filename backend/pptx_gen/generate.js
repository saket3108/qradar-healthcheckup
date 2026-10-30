/* PowerPoint generator (pptxgenjs).  Usage: node generate.js <input.json> <output.pptx>
 * Input JSON: { model: {...slide-ready data...}, images: { name: <base64 png> } } */
const fs = require("fs");
const PptxGenJS = require("pptxgenjs");

const [, , inPath, outPath] = process.argv;
const { model, images } = JSON.parse(fs.readFileSync(inPath, "utf8"));
const img = (k) => (images[k] ? "image/png;base64," + images[k] : null);

const NAVY = "0F2A4A", BLUE = "0F62FE", GREY = "6F7782", LIGHT = "F2F4F8", WHITE = "FFFFFF";
const SEV = { critical: "DA1E28", high: "FF832B", medium: "D2A106", low: "24A148", info: "0F62FE" };
const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pptx.title = model.title;
pptx.author = model.consultant || "IBM Security";

pptx.defineSlideMaster({
  title: "BODY", background: { color: WHITE },
  objects: [
    { rect: { x: 0, y: 0, w: 13.33, h: 0.9, fill: { color: NAVY } } },
    { rect: { x: 0, y: 0.9, w: 13.33, h: 0.05, fill: { color: BLUE } } },
    { text: { text: `${model.customer}  |  ${model.classification}`, options: { x: 0.4, y: 7.05, w: 8, h: 0.3, fontSize: 9, color: GREY } } },
  ],
  slideNumber: { x: 12.4, y: 7.05, fontSize: 9, color: GREY },
});

function slide(title, notes) {
  const s = pptx.addSlide({ masterName: "BODY" });
  s.addText(title, { x: 0.4, y: 0.12, w: 12.5, h: 0.65, fontSize: 24, bold: true, color: WHITE, fontFace: "Calibri" });
  if (notes) s.addNotes(notes);
  return s;
}
function commentBox(s, text, y = 6.35) {
  if (!text) return;
  s.addShape(pptx.ShapeType.rect, { x: 0.4, y, w: 12.5, h: 0.6, fill: { color: "FFF8E1" }, line: { color: "F1C21B", width: 0.75 } });
  s.addText("Consultant comment: " + text, { x: 0.5, y, w: 12.3, h: 0.6, fontSize: 10, color: "5B4A00", valign: "middle", fit: "shrink" });
}
function kpi(s, x, y, w, label, value, color = NAVY) {
  s.addShape(pptx.ShapeType.rect, { x, y, w, h: 1.1, fill: { color: LIGHT }, line: { color: "DDE1E6", width: 0.5 } });
  s.addText(String(value), { x, y: y + 0.08, w, h: 0.65, align: "center", fontSize: 28, bold: true, color });
  s.addText(label, { x, y: y + 0.72, w, h: 0.32, align: "center", fontSize: 10, color: GREY });
}
function table(s, header, rows, opts) {
  const hdr = header.map((h) => ({ text: h, options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: opts.fontSize || 10 } }));
  const body = rows.map((r, i) => r.map((c) => {
    const txt = String(c ?? "");
    const sevColor = SEV[txt.toLowerCase()];
    return { text: txt, options: { fontSize: opts.fontSize || 10, fill: { color: i % 2 ? LIGHT : WHITE }, color: sevColor || "1F2328", bold: !!sevColor } };
  }));
  s.addTable([hdr, ...body], { x: opts.x ?? 0.4, y: opts.y ?? 1.2, w: opts.w ?? 12.5, colW: opts.colW, border: { type: "solid", color: "DDE1E6", pt: 0.5 }, valign: "middle", margin: 0.05, autoPage: false });
}
const sec = (k) => model.sections.includes(k);
const cm = (k) => model.comments["section:" + k];
const ov = model.overall || {};

/* 1 Cover */
{
  const s = pptx.addSlide();
  s.background = { color: NAVY };
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 4.9, w: 13.33, h: 0.08, fill: { color: BLUE } });
  if (model.logo) s.addImage({ data: model.logo, x: 0.7, y: 0.5, w: 2.2, h: 1.0, sizing: { type: "contain", w: 2.2, h: 1.0 } });
  s.addText(model.title, { x: 0.7, y: 2.0, w: 12, h: 1.1, fontSize: 40, bold: true, color: WHITE });
  s.addText(model.customer, { x: 0.7, y: 3.2, w: 12, h: 0.6, fontSize: 24, color: "C6D4F0" });
  s.addText(`Overall health score ${ov.score ?? "n/a"}/100  |  Risk: ${ov.risk_level ?? "n/a"}`, { x: 0.7, y: 4.1, w: 12, h: 0.5, fontSize: 18, color: WHITE, bold: true });
  s.addText(`Prepared by ${model.consultant || "IBM Security"}  -  ${model.generated}  -  QRadar ${model.version || ""}`, { x: 0.7, y: 5.3, w: 12, h: 0.4, fontSize: 14, color: "C6D4F0" });
  s.addText(model.classification.toUpperCase(), { x: 0.7, y: 6.6, w: 6, h: 0.3, fontSize: 11, color: "C6D4F0" });
}

/* 2 Executive summary */
if (sec("executive_summary")) {
  const s = slide("Executive Summary");
  if (img("gauge")) s.addImage({ data: img("gauge"), x: 0.5, y: 1.2, w: 3.6, h: 2.2 });
  if (img("donut")) s.addImage({ data: img("donut"), x: 0.7, y: 3.6, w: 3.2, h: 2.7 });
  s.addText(model.summary.headline, { x: 4.4, y: 1.15, w: 8.5, h: 0.5, fontSize: 18, bold: true, color: BLUE });
  s.addText(model.summary.paragraphs.map((t) => ({ text: t, options: { breakLine: true, paraSpaceAfter: 8 } })), { x: 4.4, y: 1.7, w: 8.5, h: 3.4, fontSize: 12, color: "1F2328", valign: "top", fit: "shrink" });
  if (model.summary.highlights.length)
    s.addText(model.summary.highlights.slice(0, 4).map((t) => ({ text: t, options: { bullet: true, breakLine: true } })), { x: 4.4, y: 5.1, w: 8.5, h: 1.2, fontSize: 11, color: GREY, valign: "top", fit: "shrink" });
  commentBox(s, cm("executive_summary"));
}

/* 3 Environment */
if (sec("environment")) {
  const s = slide("Environment Overview");
  const e = model.environment;
  kpi(s, 0.4, 1.2, 2.9, "QRadar version", e.version || "n/a");
  kpi(s, 3.5, 1.2, 2.9, "Deployment type", e.deployment_type || "n/a");
  kpi(s, 6.6, 1.2, 2.9, "Hosts", e.hosts ?? "n/a");
  kpi(s, 9.7, 1.2, 3.2, "Install type", e.install_type || "n/a");
  s.addImage({ data: img("category_bars"), x: 0.4, y: 2.55, w: 6.2, h: 3.0, sizing: { type: "contain", w: 6.2, h: 3.0 } });
  table(s, ["Hostname", "Role", "CPU", "RAM", "Disk"], model.nodes.slice(0, 8).map((n) => [n.hostname, n.role, n.cpu ?? "-", n.ram, n.disk]), { x: 6.8, y: 2.6, w: 6.1, fontSize: 9, colW: [2.2, 1.1, 0.7, 1.0, 1.1] });
  commentBox(s, cm("environment"));
}

/* 4 Deployment */
if (sec("deployment")) {
  const s = slide("Deployment Architecture");
  s.addImage({ data: img("deployment"), x: 0.4, y: 1.15, w: 7.6, h: 4.0, sizing: { type: "contain", w: 7.6, h: 4.0 } });
  table(s, ["Check", "Result"], model.checks.slice(0, 9).map((c) => [c.name, c.status]), { x: 8.2, y: 1.2, w: 4.7, fontSize: 9, colW: [3.4, 1.3] });
  s.addText(model.ha_text, { x: 0.4, y: 5.3, w: 12.5, h: 0.8, fontSize: 12, color: "1F2328", fit: "shrink" });
  commentBox(s, cm("deployment"));
}

/* 5 Notifications */
if (sec("notifications")) {
  const s = slide("Notification Analysis");
  const b = model.notif.by_severity;
  ["critical", "high", "medium", "low"].forEach((k, i) => kpi(s, 0.4 + i * 3.15, 1.2, 3.0, k.toUpperCase(), b[k] || 0, SEV[k]));
  table(s, ["Severity", "Notification", "Root cause", "Priority"], model.notif.top.slice(0, 7).map((n) => [n.severity, n.title, n.root_cause.slice(0, 110), n.priority]), { y: 2.55, fontSize: 9, colW: [1.1, 3.6, 7.0, 0.8] });
  commentBox(s, cm("notifications"));
}

/* 6 Log sources */
if (sec("logsources")) {
  const s = slide("Log Source Analysis");
  const l = model.logsources;
  kpi(s, 0.4, 1.2, 2.0, "Total", l.total || 0); kpi(s, 2.5, 1.2, 2.0, "Enabled", l.enabled || 0, "24A148"); kpi(s, 4.6, 1.2, 2.0, "Error", l.error || 0, "DA1E28");
  kpi(s, 6.7, 1.2, 2.0, "Disabled", l.disabled || 0); kpi(s, 8.8, 1.2, 2.0, "Silent", l.silent_count || 0, "FF832B"); kpi(s, 10.9, 1.2, 2.0, "Total EPS", Math.round(l.total_eps || 0));
  if (img("protocols")) s.addImage({ data: img("protocols"), x: 0.4, y: 2.5, w: 6.2, h: 3.6, sizing: { type: "contain", w: 6.2, h: 3.6 } });
  table(s, ["Top EPS source", "Type", "EPS"], (l.top_eps || []).slice(0, 8).map((t) => [t.name, t.type, t.eps.toFixed(1)]), { x: 6.8, y: 2.55, w: 6.1, fontSize: 9, colW: [2.6, 2.6, 0.9] });
  commentBox(s, cm("logsources"));
}

/* 7 WinCollect */
if (sec("wincollect")) {
  const s = slide("WinCollect");
  const w = model.wincollect;
  if (w.total) {
    kpi(s, 0.4, 1.2, 2.0, "Agents", w.total); kpi(s, 2.5, 1.2, 2.0, "Managed", w.managed, "24A148"); kpi(s, 4.6, 1.2, 2.0, "Standalone", w.standalone);
    kpi(s, 6.7, 1.2, 2.0, "Disconnected", w.disconnected, "DA1E28"); kpi(s, 8.8, 1.2, 2.0, "Outdated", w.outdated, "FF832B"); kpi(s, 10.9, 1.2, 2.0, "Errors", w.error, "DA1E28");
    if (img("wc_versions")) s.addImage({ data: img("wc_versions"), x: 0.4, y: 2.5, w: 6.2, h: 3.6, sizing: { type: "contain", w: 6.2, h: 3.6 } });
    table(s, ["Issue", "Agents"], [["Old versions", w.old_versions.length], ["Communication problems", w.communication_problems.length], ["Configuration issues", w.config_issues.length], ["Deployment problems", w.deployment_problems.length]], { x: 6.8, y: 2.6, w: 6.1, fontSize: 11, colW: [4.6, 1.5] });
  } else s.addText("No WinCollect agent data was present in the collected bundle.", { x: 0.5, y: 1.4, w: 12, h: 0.6, fontSize: 16, color: GREY });
  commentBox(s, cm("wincollect"));
}

/* 8 Applications */
if (sec("applications")) {
  const s = slide("Applications");
  const a = model.applications;
  if (a.total) {
    kpi(s, 0.4, 1.2, 3.0, "Running", a.running, "24A148"); kpi(s, 3.55, 1.2, 3.0, "Stopped", a.stopped); kpi(s, 6.7, 1.2, 3.0, "Degraded", a.degraded, "FF832B"); kpi(s, 9.85, 1.2, 3.0, "Error", a.error, "DA1E28");
    table(s, ["Application", "Version", "Host", "Status", "Observation"], model.app_rows.slice(0, 8), { y: 2.55, fontSize: 9, colW: [2.4, 1.0, 1.8, 1.0, 6.3] });
  } else s.addText("No application data was present in the collected bundle.", { x: 0.5, y: 1.4, w: 12, h: 0.6, fontSize: 16, color: GREY });
  commentBox(s, cm("applications"));
}

/* 9 Performance */
if (sec("performance")) {
  const s = slide("Performance");
  if (img("perf_cpu")) s.addImage({ data: img("perf_cpu"), x: 0.4, y: 1.15, w: 6.2, h: 2.5, sizing: { type: "contain", w: 6.2, h: 2.5 } });
  if (img("perf_mem")) s.addImage({ data: img("perf_mem"), x: 6.8, y: 1.15, w: 6.1, h: 2.5, sizing: { type: "contain", w: 6.1, h: 2.5 } });
  table(s, ["Host", "Metric", "Severity", "Finding"], model.perf_rows.slice(0, 6), { y: 3.85, fontSize: 9, colW: [1.8, 2.4, 1.1, 7.2] });
  commentBox(s, cm("performance"));
}

/* 10 Licensing */
if (sec("licensing")) {
  const s = slide("Licensing");
  const L = model.licensing;
  if (L.has_data) {
    if (img("lic_eps")) s.addImage({ data: img("lic_eps"), x: 0.4, y: 1.15, w: 2.8, h: 1.8 });
    if (img("lic_fpm")) s.addImage({ data: img("lic_fpm"), x: 0.4, y: 3.2, w: 2.8, h: 1.8 });
    table(s, ["Metric", "Licensed", "Current", "Peak", "Consumption", "Risk"], L.rows, { x: 3.5, y: 1.2, w: 9.4, fontSize: 11 });
    if (img("lic_chart")) s.addImage({ data: img("lic_chart"), x: 3.5, y: 2.9, w: 9.4, h: 3.2, sizing: { type: "contain", w: 9.4, h: 3.2 } });
  } else s.addText("No licence information was present in the collected bundle.", { x: 0.5, y: 1.4, w: 12, h: 0.6, fontSize: 16, color: GREY });
  commentBox(s, cm("licensing"));
}

/* 11 Recommendations */
if (sec("recommendations")) {
  const s = slide("Top Recommendations");
  table(s, ["#", "Recommendation", "Severity", "Priority", "Key action"], model.recs.slice(0, 8).map((r) => [r.rank, r.title, r.severity, r.priority, r.action]), { fontSize: 9, colW: [0.4, 3.6, 1.0, 0.8, 6.7] });
  commentBox(s, cm("recommendations"));
}

/* 12 Action plan */
if (sec("next_steps")) {
  const s = slide("Action Plan");
  const cols = [["Immediate (0-7 days)", model.plan.immediate, "DA1E28"], ["Short term (30 days)", model.plan.short, "FF832B"], ["Medium term (60-90 days)", model.plan.medium, "0F62FE"]];
  cols.forEach(([h, items, c], i) => {
    const x = 0.4 + i * 4.2;
    s.addShape(pptx.ShapeType.rect, { x, y: 1.2, w: 4.0, h: 0.5, fill: { color: c } });
    s.addText(h, { x, y: 1.2, w: 4.0, h: 0.5, align: "center", fontSize: 13, bold: true, color: WHITE });
    s.addShape(pptx.ShapeType.rect, { x, y: 1.7, w: 4.0, h: 4.4, fill: { color: LIGHT }, line: { color: "DDE1E6", width: 0.5 } });
    s.addText(items.length ? items.map((t) => ({ text: t, options: { bullet: true, breakLine: true, paraSpaceAfter: 6 } })) : "No actions in this window", { x: x + 0.1, y: 1.8, w: 3.8, h: 4.2, fontSize: 10, color: "1F2328", valign: "top", fit: "shrink" });
  });
}

/* 13 Next steps */
if (sec("next_steps")) {
  const s = slide("Next Steps");
  s.addText(model.next_steps.map((t, i) => ({ text: t, options: { bullet: { type: "number" }, breakLine: true, paraSpaceAfter: 10 } })), { x: 0.6, y: 1.3, w: 12, h: 4.8, fontSize: 16, color: "1F2328", valign: "top", fit: "shrink" });
  commentBox(s, cm("next_steps"));
}

pptx.writeFile({ fileName: outPath }).then(() => process.exit(0)).catch((e) => { console.error(e); process.exit(1); });
