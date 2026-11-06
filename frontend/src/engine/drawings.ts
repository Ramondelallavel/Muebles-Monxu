// @ts-nocheck
// Planos de fabricación en PDF generados en el navegador (port de monxu/docs/plans.py + drawing_kit.py):
// A3 horizontal, primer diedro, cuadro de rotulación ISO 7200, líneas ISO 128-2, acotación ISO 129-1,
// símbolos de soldadura ISO 2553. Las vistas se obtienen de los sólidos facetados (hlr.ts).
import * as C from "./catalog";
import { explodeOf, instanceBBox, instanceCentroid, modelBBox, partGeometry } from "./geometry";
import { project, projectPoint } from "./hlr";
import { mmul, translation } from "./model";
import { PDF, textWidth } from "./pdf";

const FRAME = [20, 10, 410, 287];
const TB_W = 180, TB_H = 58;
const LW_THICK = 0.5, LW_THIN = 0.25, LW_DIM = 0.18;
const SCALES = [[1, 1], [1, 2], [1, 5], [1, 10], [1, 20], [1, 50], [1, 100]];
const RED = [0.78, 0.1, 0.1], GREY = [0.45, 0.45, 0.45], BLACK = [0, 0, 0];
const TB_RESERVED = [226, 6, 412, 80];

export const fmt = (v, dec = 1) => (Math.abs(v - Math.round(v)) < 0.05 ? String(Math.round(v)) : v.toFixed(dec).replace(".", ","));
const scaleLabel = (s) => (s ? `${s[0]}:${s[1]}` : "S/E");
function fitText(s, width, h) {
  s = String(s);
  if (textWidth(s, h) <= width) return s;
  while (s && textWidth(s + "…", h) > width) s = s.slice(0, -1);
  return s + "…";
}

// ============================================================================ kit de dibujo
export class Drawing {
  constructor(info) {
    this.pdf = new PDF({ title: info.title ?? "Planos", author: info.designer ?? "", subject: `${info.project_code ?? ""} Rev.${info.revision ?? ""}` });
    this.info = info; this.pages = [];
  }
  get page() { return this.pages.at(-1); }
  recordDim(name, value, source) { this.page.dims.push({ name, value: Math.round(value * 1000) / 1000, source }); }
  newSheet(number, title, scale, material = "Ver lista") {
    this.pdf.page(420, 297);
    this.pages.push({ number, title, scale, dims: [] });
    this.frame();
    this.titleBlock(number, title, scale, material);
  }
  async finish() { return this.pdf.save(); }
  text(x, y, s, h = 3.5, align = "l", angle = 0, bold = false, color = BLACK) { this.pdf.text(x, y, s, h, { align, angle, bold, color }); }
  label(x, y, s) { this.text(x, y, s, 1.8, "l", 0, false, GREY); }
  field(x, y, w, h, label, value, bold = false) { this.label(x + 1.5, y + h - 2.5, label); this.text(x + 2, y + 2, fitText(value ?? "", w - 3, h >= 10 ? 3.0 : 2.8), h >= 10 ? 3.0 : 2.8, "l", 0, bold); }
  line(p, q, lw = LW_THIN, dash = null, color = BLACK) { this.pdf.lw(lw).dash(dash).stroke(color).line(p[0], p[1], q[0], q[1]); this.pdf.dash(null).stroke(BLACK); }
  polyline(pts, lw = LW_THICK, dash = null, color = BLACK, close = false) { this.pdf.lw(lw).dash(dash).stroke(color).poly(pts, close); this.pdf.dash(null).stroke(BLACK); }
  rect(x, y, w, h, lw = LW_THIN, fill = null) {
    this.pdf.lw(lw);
    if (fill) { this.pdf.fill(fill).rect(x, y, w, h, "B"); this.pdf.fill(BLACK); } else this.pdf.rect(x, y, w, h);
  }
  circle(cx, cy, r, lw = LW_THIN, fill = null) { this.pdf.lw(lw); if (fill) { this.pdf.fill(fill).circle(cx, cy, r, "B"); this.pdf.fill(BLACK); } else this.pdf.circle(cx, cy, r); }
  arrow(tip, dir, size = 3.0) {
    const n = Math.hypot(dir[0], dir[1]) || 1, dx = dir[0] / n, dy = dir[1] / n;
    const w = size * Math.tan((10 * Math.PI) / 180), bx = tip[0] - dx * size, by = tip[1] - dy * size;
    this.pdf.fill(BLACK).poly([tip, [bx - dy * w, by + dx * w], [bx + dy * w, by - dx * w]], true, "f");
  }
  frame() {
    const [x0, y0, x1, y1] = FRAME;
    this.pdf.lw(0.7).rect(x0, y0, x1 - x0, y1 - y0);
    for (let i = 0; i < 8; i++) this.text(x0 + ((x1 - x0) * (i + 0.5)) / 8, y1 + 2.5, String(i + 1), 2.5, "c");
    "ABCDEF".split("").forEach((ch, j) => this.text(x0 - 3, y1 - ((y1 - y0) * (j + 0.5)) / 6, ch, 2.5, "c"));
    this.line([210, y1], [210, y1 + 4]); this.line([210, y0], [210, y0 - 4]);
  }
  titleBlock(number, title, scale, material) {
    const I = this.info, x1 = FRAME[2], y0 = FRAME[1], x0 = x1 - TB_W, y1 = y0 + TB_H;
    this.pdf.lw(0.5).rect(x0, y0, TB_W, TB_H);
    for (const y of [y0 + 10, y0 + 20, y0 + 30, y0 + 46]) this.line([x0, y], [x1, y]);
    for (const x of [x0 + 45, x0 + 90, x0 + 135]) this.line([x, y0 + 46], [x, y1]);
    this.field(x0, y0 + 46, 45, 12, "Diseñado", I.designer ?? "");
    this.field(x0 + 45, y0 + 46, 45, 12, "Comprobado", I.checked ?? "—");
    this.field(x0 + 90, y0 + 46, 45, 12, "Aprobado", I.approved ?? "—");
    this.field(x0 + 135, y0 + 46, 45, 12, "Fecha", I.date ?? "");
    this.label(x0 + 1.5, y0 + 43.5, "Título");
    this.text(x0 + 3, y0 + 37.5, fitText(I.product_name ?? "", TB_W - 6, 4.2), 4.2, "l", 0, true);
    this.text(x0 + 3, y0 + 32, fitText(title, TB_W - 6, 3.2), 3.2, "l");
    for (const x of [x0 + 40, x0 + 75, x0 + 100, x0 + 125, x0 + 150]) this.line([x, y0 + 20], [x, y0 + 30]);
    this.field(x0, y0 + 20, 40, 10, "Nº de plano", number, true);
    this.field(x0 + 40, y0 + 20, 35, 10, "Código proyecto", I.project_code ?? "");
    this.field(x0 + 75, y0 + 20, 25, 10, "Revisión", String(I.revision ?? ""), true);
    this.field(x0 + 100, y0 + 20, 25, 10, "Escala", scale);
    this.field(x0 + 125, y0 + 20, 25, 10, "Unidades", "mm");
    this.field(x0 + 150, y0 + 20, 30, 10, "Hoja", `${this.pages.length}/${I.total_sheets ?? "?"}`);
    for (const x of [x0 + 70, x0 + 125, x0 + 155]) this.line([x, y0 + 10], [x, y0 + 20]);
    this.field(x0, y0 + 10, 70, 10, "Material", material);
    this.field(x0 + 70, y0 + 10, 55, 10, "Ref. conjunto", I.assembly_ref ?? "");
    this.field(x0 + 125, y0 + 10, 30, 10, "Cliente", I.client ?? "");
    this.label(x0 + 156.5, y0 + 17.5, "Proyección");
    this.firstAngle(x0 + 167.5, y0 + 13.5);
    this.line([x0 + 120, y0], [x0 + 120, y0 + 10]);
    this.label(x0 + 1.5, y0 + 7.5, "Tolerancias generales");
    this.text(x0 + 3, y0 + 2.5, `${I.tolerances ?? "ISO 2768-mK"} · soldadura EN ISO 13920-BF`, 2.6, "l");
    this.text(x0 + 121.5, y0 + 6, I.company ?? "MUEBLES MONXU", 3.2, "l", 0, true);
    this.text(x0 + 121.5, y0 + 2, "Documento generado del modelo paramétrico", 1.9, "l");
    if (I.status_stamp) {
      const col = I.status_level === "error" ? RED : GREY;
      this.pdf.lw(0.4).stroke(col).rect(x0, y1 + 2, TB_W, 7);
      this.pdf.stroke(BLACK);
      this.text(x0 + TB_W / 2, y1 + 4, fitText(I.status_stamp, TB_W - 4, 2.6), 2.6, "c", 0, true, col);
    }
  }
  firstAngle(cx, cy) {
    this.line([cx - 9, cy - 1.5], [cx - 9, cy + 1.5]); this.line([cx - 3, cy - 3], [cx - 3, cy + 3]);
    this.line([cx - 9, cy + 1.5], [cx - 3, cy + 3]); this.line([cx - 9, cy - 1.5], [cx - 3, cy - 3]);
    this.circle(cx + 4, cy, 3); this.circle(cx + 4, cy, 1.5);
  }
  dimH(x1, x2, yf1, yf2, yd, value, name = null, source = "geometria", prefix = "") {
    if (Math.abs(x2 - x1) < 0.5) return;
    if (x1 > x2) { [x1, x2] = [x2, x1]; [yf1, yf2] = [yf2, yf1]; }
    const sgn = yd >= Math.max(yf1, yf2) ? 1 : -1;
    for (const [x, yf] of [[x1, yf1], [x2, yf2]]) this.line([x, yf + sgn], [x, yd + sgn * 2], LW_DIM);
    this.line([x1, yd], [x2, yd], LW_DIM);
    if (x2 - x1 > 9) { this.arrow([x1, yd], [-1, 0]); this.arrow([x2, yd], [1, 0]); }
    else { this.line([x1 - 5, yd], [x2 + 5, yd], LW_DIM); this.arrow([x1, yd], [1, 0]); this.arrow([x2, yd], [-1, 0]); }
    const txt = prefix + fmt(value);
    this.text((x1 + x2) / 2, yd + (x2 - x1 > txt.length * 2.2 + 2 || sgn > 0 ? 1.0 : -4.2), txt, 3.0, "c");
    if (name) this.recordDim(name, value, source);
  }
  dimV(y1, y2, xf1, xf2, xd, value, name = null, source = "geometria", prefix = "") {
    if (Math.abs(y2 - y1) < 0.5) return;
    if (y1 > y2) { [y1, y2] = [y2, y1]; [xf1, xf2] = [xf2, xf1]; }
    const sgn = xd >= Math.max(xf1, xf2) ? 1 : -1;
    for (const [y, xf] of [[y1, xf1], [y2, xf2]]) this.line([xf + sgn, y], [xd + sgn * 2, y], LW_DIM);
    this.line([xd, y1], [xd, y2], LW_DIM);
    if (y2 - y1 > 9) { this.arrow([xd, y1], [0, -1]); this.arrow([xd, y2], [0, 1]); }
    else { this.line([xd, y1 - 5], [xd, y2 + 5], LW_DIM); this.arrow([xd, y1], [0, 1]); this.arrow([xd, y2], [0, -1]); }
    const txt = prefix + fmt(value);
    if (y2 - y1 > txt.length * 2.2 + 2) this.text(xd - 1.0, (y1 + y2) / 2, txt, 3.0, "c", 90);
    else this.text(xd - 4.6 * sgn, (y1 + y2) / 2, txt, 3.0, "c", 90);
    if (name) this.recordDim(name, value, source);
  }
  balloon(c, target, label, r = 4) {
    const dx = target[0] - c[0], dy = target[1] - c[1], d = Math.hypot(dx, dy) || 1;
    this.line([c[0] + (dx / d) * r, c[1] + (dy / d) * r], target, LW_THIN);
    this.pdf.fill(BLACK).circle(target[0], target[1], 0.5, "f");
    this.circle(c[0], c[1], r, LW_THIN, [1, 1, 1]);
    this.text(c[0], c[1] - 1.2, String(label), 3.2, "c", 0, true);
  }
  weldSymbol(target, base, a, allAround = true, process = "135", length = null, side = 1) {
    const [bx, by] = base;
    this.line(base, target, LW_THIN);
    this.arrow(target, [target[0] - bx, target[1] - by], 2.5);
    const Lr = 22 * side;
    this.line([bx, by], [bx + Lr, by]);
    this.line([bx, by - 1.2], [bx + Lr, by - 1.2], LW_THIN, [1.2, 0.8]);
    const tx = bx + 9 * side;
    this.pdf.lw(LW_THIN).poly([[tx - 2.2, by], [tx + 2.2, by], [tx - 2.2, by + 4.0]], true);
    this.text(tx - 3.2, by + 0.8, `a${fmt(a)}`, 2.6, "r");
    if (length) this.text(tx + 3.0, by + 0.8, fmt(length), 2.6, "l");
    if (allAround) this.circle(bx, by, 1.6);
    const ex = bx + Lr;
    this.line([ex, by], [ex + 2.5 * side, by + 2.5]); this.line([ex, by], [ex + 2.5 * side, by - 2.5]);
    this.text(ex + 3.5 * side, by - 1.0, process, 2.4, side > 0 ? "l" : "r");
  }
  table(x, yTop, cols, rows, rowH = 5.0, headH = 6.0, textH = 2.4) {
    const W = cols.reduce((s, c) => s + c[1], 0), H = headH + rowH * rows.length;
    this.pdf.lw(0.35).rect(x, yTop - H, W, H);
    this.line([x, yTop - headH], [x + W, yTop - headH]);
    let xx = x;
    cols.forEach(([t, w], k) => { if (k) this.line([xx, yTop], [xx, yTop - H]); this.text(xx + w / 2, yTop - headH + 1.8, t, 2.4, "c", 0, true); xx += w; });
    rows.forEach((row, ri) => {
      const yy = yTop - headH - rowH * (ri + 1);
      if (ri) this.line([x, yy + rowH], [x + W, yy + rowH], 0.1);
      let x2 = x;
      cols.forEach(([, w, al], k) => {
        const v = row[k];
        let s = v === null || v === undefined ? "" : typeof v === "number" && !Number.isInteger(v) ? fmt(v, 2) : String(v);
        s = fitText(s, w - 2.4, textH);
        if (al === "c") this.text(x2 + w / 2, yy + 1.4, s, textH, "c"); else if (al === "r") this.text(x2 + w - 1.2, yy + 1.4, s, textH, "r"); else this.text(x2 + 1.2, yy + 1.4, s, textH, "l");
        x2 += w;
      });
    });
    return yTop - H;
  }
  notes(x, yTop, lines, h = 2.6, width = 180, boldFirst = false) {
    let y = yTop;
    lines.forEach((ln, n) => {
      if (!ln) { y -= h * 0.8; return; }
      while (ln) {
        const words = ln.split(" ");
        let part = "";
        for (const w of words) { const cand = (part + " " + w).trim(); if (textWidth(cand, h) > width && part) break; part = cand; }
        this.text(x, y, part, h, "l", 0, boldFirst && n === 0);
        ln = ln.slice(part.length).trimStart();
        y -= h * 1.55;
      }
    });
    return y;
  }
  drawView(v, hidden = true, lw = LW_THICK) {
    const segs = (list) => list.map(([a, b, c, d]) => [...v.P(a, b), ...v.P(c, d)]);
    this.pdf.lw(lw).dash(null).stroke(BLACK).segments(segs(v.proj.visible));
    if (hidden && v.proj.hidden.length) { this.pdf.lw(LW_THIN * 0.8).dash([2.0, 1.0]).stroke(GREY).segments(segs(v.proj.hidden)); this.pdf.dash(null).stroke(BLACK); }
    if (v.label) this.text(v.ox + v.w / 2, v.oy - (v.labelOffset ?? 20), v.label, 3.0, "c", 0, true);
  }
}

class View {
  constructor(proj, scale, ox, oy, name) { Object.assign(this, { proj, scale, ox, oy, name, u0: proj.bbox[0], v0: proj.bbox[1], label: "" }); }
  P(u, v) { return [this.ox + (u - this.u0) * this.scale, this.oy + (v - this.v0) * this.scale]; }
  get w() { return (this.proj.bbox[2] - this.proj.bbox[0]) * this.scale; }
  get h() { return (this.proj.bbox[3] - this.proj.bbox[1]) * this.scale; }
  at(p) { return this.P(...projectPoint(p, this.name)); }
}
const size = (proj) => [proj.bbox[2] - proj.bbox[0], proj.bbox[3] - proj.bbox[1]];
const intersects = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];

function layoutOrtho(projs, region, reserved = [], gap = 24, pad = 16) {
  const [wf, hf] = size(projs.alzado), ws = size(projs.perfil)[0], ht = size(projs.planta)[1];
  for (const s of SCALES) {
    const k = s[0] / s[1], ox = region[0] + pad, top = region[3] - pad;
    const fr = [ox, top - hf * k, ox + wf * k, top];
    const rects = { alzado: fr, perfil: [fr[2] + gap, fr[1], fr[2] + gap + ws * k, top], planta: [ox, fr[1] - gap - ht * k, ox + wf * k, fr[1] - gap] };
    let ok = true;
    for (const r of Object.values(rects)) {
      const p = [r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad];
      if (r[0] < region[0] || r[1] - pad < region[1] || r[2] > region[2] || r[3] > region[3]) ok = false;
      if (reserved.some((z) => intersects(p, z))) ok = false;
    }
    if (ok) return [s, Object.fromEntries(Object.entries(rects).map(([n, r]) => [n, new View(projs[n], k, r[0], r[1], n)]))];
  }
  // sin escala normalizada: ajuste libre
  const k = Math.min((region[2] - region[0] - 2 * pad - gap - 40) / (wf + ws), (region[3] - region[1] - 2 * pad - gap - 30) / (hf + ht));
  const ox = region[0] + pad, top = region[3] - pad;
  const fr = [ox, top - hf * k, ox + wf * k, top];
  return [null, { alzado: new View(projs.alzado, k, fr[0], fr[1], "alzado"), perfil: new View(projs.perfil, k, fr[2] + gap, fr[1], "perfil"),
    planta: new View(projs.planta, k, ox, fr[1] - gap - ht * k, "planta") }];
}
function fitView(proj, name, rect, scales = SCALES, free = false) {
  let [w, h] = size(proj);
  w = Math.max(w, 1e-3); h = Math.max(h, 1e-3);
  if (!free) for (const s of scales) {
    const k = s[0] / s[1];
    if (w * k <= rect[2] - rect[0] && h * k <= rect[3] - rect[1])
      return [s, new View(proj, k, rect[0] + (rect[2] - rect[0] - w * k) / 2, rect[1] + (rect[3] - rect[1] - h * k) / 2, name)];
  }
  const k = Math.min((rect[2] - rect[0]) / w, (rect[3] - rect[1]) / h);
  return [null, new View(proj, k, rect[0] + (rect[2] - rect[0] - w * k) / 2, rect[1] + (rect[3] - rect[1] - h * k) / 2, name)];
}
function balloons(d, v, targets, above = true, spacing = 10, yOff = 14) {
  const pts = targets.map(([l, p]) => [l, v.at(p)]).sort((a, b) => a[1][0] - b[1][0]);
  if (!pts.length) return;
  const xs = [];
  for (const [, t] of pts) xs.push(xs.length ? Math.max(t[0], xs.at(-1) + spacing) : t[0]);
  const over = xs.at(-1) - (v.ox + v.w + 5);
  if (over > 0) { for (let i = 0; i < xs.length; i++) xs[i] -= over; for (let i = xs.length - 2; i >= 0; i--) xs[i] = Math.min(xs[i], xs[i + 1] - spacing); }
  const y = above ? v.oy + v.h + yOff : v.oy - yOff;
  pts.forEach(([l, t], i) => d.balloon([xs[i], y], t, l));
}

// ============================================================================ contexto
class Ctx {
  constructor(model, summary, info, onProgress) {
    Object.assign(this, { m: model, s: summary, plan: summary.manufacturing, bom: summary.bom, eng: summary.engineering, info, onProgress });
    this.cache = new Map();
  }
  items(insts, explode = false) { return insts.map((i) => ({ part: i.part, T: explode ? mmul(translation(...explodeOf(this.m, i)), i.T) : i.T })); }
  proj(key, insts, view, hidden = true, explode = false) {
    const k = `${key}|${view}|${explode}`;
    if (!this.cache.has(k)) { this.onProgress?.(`Planos: proyección ${view} (${key})`); this.cache.set(k, project(this.items(insts, explode), view, { hidden: true })); }
    const p = this.cache.get(k);
    return hidden ? p : { ...p, hidden: [] };
  }
  group(...g) { return this.m.instances.filter((i) => g.includes(i.group)); }
  inst(id) { return this.m.instance(id); }
}
const LABEL = { alzado: "ALZADO", perfil: "PERFIL IZQUIERDO", planta: "PLANTA" };

// ============================================================================ hojas
function planGeneral(d, X) {
  const m = X.m, insts = m.instances;
  const projs = Object.fromEntries(["alzado", "perfil", "planta"].map((v) => [v, X.proj("all", insts, v, false)]));
  const [s, V] = layoutOrtho(projs, [28, 18, 405, 272], [TB_RESERVED]);
  const env = m.dims.envelope;
  const envI = env.ids ? env.ids.map((i) => X.inst(i)) : insts.filter((i) => env.groups.includes(i.group));
  const [lo, hi] = modelBBox(m, envI);
  const [nx, ny] = env.names ?? ["LONGITUD", "ANCHURA"];
  d.newSheet("01", "Conjunto general", scaleLabel(s), "Ver despiece (plano 08)");
  for (const [n, v] of Object.entries(V)) { v.label = LABEL[n]; d.drawView(v, false); }
  const a = V.alzado, p = V.perfil, pl = V.planta;
  const [x0, ztop] = a.at([lo[0], 0, hi[2]]), [x1] = a.at([hi[0], 0, hi[2]]);
  d.dimH(x0, x1, ztop, ztop, ztop + 9, hi[0] - lo[0], nx);
  const [, yfloor] = a.at([0, 0, 0]);
  const xl = a.ox;
  const levels = (m.dims.levels ?? []).map(([name, iid]) => [name, instanceBBox(X.inst(iid))[1][2]]);
  if (levels.length <= 1) {
    d.dimV(yfloor, ztop, xl, xl, xl - 9, hi[2], "ALTURA");
    for (const [name, z] of levels) { const [, ys] = a.at([0, 0, z]); d.dimV(yfloor, ys, xl, xl, xl - 17, z, name); }
  } else {
    d.dimV(yfloor, ztop, xl, xl, xl - 17, hi[2], "ALTURA");
    const zs = [0, ...levels.map((l) => l[1]).sort((u, w) => u - w)];
    for (let k = 0; k < zs.length - 1; k++) { const ya = a.at([0, 0, zs[k]])[1], yb = a.at([0, 0, zs[k + 1]])[1]; d.dimV(ya, yb, xl, xl, xl - 9, zs[k + 1] - zs[k], `DIST_NIVEL_${k + 1}`); }
  }
  const [u0, zt] = p.at([0, hi[1], hi[2]]), [u1] = p.at([0, lo[1], hi[2]]);
  d.dimH(u0, u1, zt, zt, zt + 9, hi[1] - lo[1], ny);
  const [xa, ya] = pl.at([lo[0], lo[1], 0]), [xb, yb] = pl.at([hi[0], hi[1], 0]);
  d.dimH(xa, xb, ya, ya, pl.oy - 9, hi[0] - lo[0]);
  d.dimV(ya, yb, pl.ox, pl.ox, pl.ox - 9, hi[1] - lo[1]);
  const iso = X.proj("all", insts, "iso", false);
  let best = null;
  for (const r of [[p.ox + p.w + 18, 86, 405, 270], [pl.ox + pl.w + 22, 86, 405, p.oy - 14]]) {
    if (r[2] - r[0] < 40 || r[3] - r[1] < 40) continue;
    const [sc, vi] = fitView(iso, "iso", r, [...SCALES, [1, 200]]);
    if (!best || vi.scale > best[1].scale) best = [sc, vi];
  }
  if (best) { best[1].label = "PERSPECTIVA ISOMÉTRICA" + (best[0] ? ` (E ${scaleLabel(best[0])})` : " (sin escala)"); d.drawView(best[1], false, 0.35); }
  const ps = m.params.values;
  const lines = [`Producto: ${m.family_name} ${m.product_code}`, `Masa total calculada desde la geometría: ${X.bom.totals.total_mass.toFixed(1)} kg`, m.dims.load_text ?? "",
    `Estado de verificación: ${X.eng.status_label}`, `Altura con pies niveladores en posición nominal (regulación ±${fmt(C.component(ps.PIE_NIVELADOR).adjust / 2)} mm).`,
    `Acabado: ${C.finish(ps.ACABADO).name}`];
  if (pl.oy - 30 > 52) d.notes(32, pl.oy - 30, lines, 2.6, 190);
  else d.notes(pl.ox + pl.w + 24, Math.min(pl.oy + pl.h, 140), lines, 2.6, Math.max(60, 222 - pl.ox - pl.w - 24));
}

function planStructure(d, X) {
  const m = X.m, est = X.group("EST");
  const projs = Object.fromEntries(["alzado", "perfil", "planta"].map((v) => [v, X.proj("est", est, v, true)]));
  const [s, V] = layoutOrtho(projs, [28, 18, 405, 272], [TB_RESERVED, [300, 80, 412, 272]]);
  d.newSheet("02", "Estructura soldada: vistas y cotas", scaleLabel(s), m.params.values.MATERIAL_ESTRUCTURAL);
  for (const [n, v] of Object.entries(V)) { v.label = LABEL[n]; d.drawView(v, true); }
  const a = V.alzado, p = V.perfil, pl = V.planta;
  const lv = m.structure.levels, legs = m.structure.leg_ids.map((i) => X.inst(i));
  const [lo, hi] = modelBBox(m, est);
  const [x0, yz] = a.at([lo[0], 0, hi[2]]), [x1] = a.at([hi[0], 0, hi[2]]);
  d.dimH(x0, x1, yz, yz, yz + 9, hi[0] - lo[0], "EST_LONGITUD");
  const [, yb] = a.at([0, 0, lo[2]]);
  d.dimV(yb, yz, a.ox, a.ox, a.ox - 9, hi[2] - lo[2], "EST_ALTURA");
  const lower = Object.keys(lv).filter((k) => k !== "SUP").map((k) => [instanceBBox(X.inst(lv[k].long[0]))[1][2], k]).sort((u, w) => u[0] - w[0]);
  if (lower.length === 1) { const [z, k] = lower[0]; const [, yr] = a.at([0, 0, z]); d.dimV(yb, yr, a.ox, a.ox, a.ox - 17, z - lo[2], `COTA_BASTIDOR_${k}`); }
  else if (lower.length) {
    const zs = [lo[2], ...lower.map((l) => l[0])];
    for (let k = 0; k < zs.length - 1; k++) d.dimV(a.at([0, 0, zs[k]])[1], a.at([0, 0, zs[k + 1]])[1], a.ox, a.ox, a.ox - 17, zs[k + 1] - zs[k]);
  }
  const top = lv.SUP, ids = [top.end[0], ...top.int, top.end[1]];
  const xs = ids.map((i) => { const [l, h] = instanceBBox(X.inst(i)); return (l[0] + h[0]) / 2; });
  for (let k = 0; k < xs.length - 1; k++) {
    const [xa2, ya2] = pl.at([xs[k], lo[1], 0]), [xb2] = pl.at([xs[k + 1], lo[1], 0]);
    d.dimH(xa2, xb2, ya2, ya2, pl.oy - 9, xs[k + 1] - xs[k], `PASO_TRAVESANO_${k + 1}`);
  }
  d.dimV(pl.at([0, lo[1], 0])[1], pl.at([0, hi[1], 0])[1], pl.ox, pl.ox, pl.ox - 9, hi[1] - lo[1], "EST_ANCHURA");
  const yL2 = instanceBBox(legs[2])[1][1], yL0 = instanceBBox(legs[0])[0][1];
  const [pu0, pzt] = p.at([0, yL2, hi[2]]), [pu1] = p.at([0, yL0, hi[2]]);
  d.dimH(pu0, pu1, pzt, pzt, pzt + 9, yL2 - yL0);
  const reps = new Map();
  for (const i of est) if (i.part.kind === "perfil" && !reps.has(i.part.key)) reps.set(i.part.key, i);
  balloons(d, a, [...reps.values()].map((i) => [String(i.part.pos), instanceCentroid(i)]), true, 10, 20);
  d.notes(305, 268, ["Estructura soldada (subconjunto EST).", `Clase de ejecución ${m.params.values.CLASE_EJECUCION} según EN 1090-2.`, "Cotas a caras exteriores de perfil.",
    "Planitud del plano de apoyo de encimera: EN ISO 13920 clase F.", "Detalle de uniones soldadas: plano 05.", "Longitudes de corte y mecanizados: plano 02B."], 2.6, 100);
}

function planProfiles(d, X) {
  const m = X.m;
  const profs = Object.values(m.parts).filter((p) => p.kind === "perfil").sort((a, b) => a.pos - b.pos);
  const counts = {};
  for (const i of m.instances) counts[i.part.key] = (counts[i.part.key] ?? 0) + 1;
  d.newSheet("02B", "Perfiles: longitudes de corte, mecanizados y plan de corte", "Sin escala", m.params.values.MATERIAL_ESTRUCTURAL);
  let y = 262;
  const maxL = Math.max(...profs.map((p) => p.length));
  for (const p of profs) {
    const w = (150 * p.length) / maxL + 20, x0 = 40, hg = 7;
    d.text(x0 - 6, y + 2, String(p.pos), 3.2, "r", 0, true);
    d.polyline([[x0, y], [x0 + w, y], [x0 + w, y + hg], [x0, y + hg]], LW_THICK, null, BLACK, true);
    d.line([x0 - 3, y + hg / 2], [x0 + w + 3, y + hg / 2], LW_THIN, [6, 1, 1, 1], GREY);
    for (const [, z] of p.holes) d.circle(x0 + (w * z) / p.length, y + hg / 2, 1.2);
    d.dimH(x0, x0 + w, y + hg, y + hg, y + hg + 4, p.length, `L_${p.ref}`, "geometria_pieza");
    let desc = `${p.ref}  ${p.profile.code}  ${p.material}  L=${fmt(p.length)}  90°/90°  ×${counts[p.key]}`;
    if (p.holes.length) desc += `  Taladros Ø${String(p.holes[0][3]).replace(".", ",")} en cara exterior a: ` + p.holes.map((h) => fmt(h[1])).join(", ");
    d.text(x0 + w + 6, y + 2, fitText(desc, 400 - x0 - w - 6, 2.4), 2.4, "l");
    y -= 17;
    if (y < 95) break;
  }
  y -= 2;
  d.text(32, y, "PLAN DE CORTE DE BARRAS", 3.2, "l", 0, true);
  y -= 7;
  for (const c of X.plan.cutting) {
    d.text(32, y, `${c.profile} ${c.material} — barras de ${fmt(c.bar_length)} mm: ${c.n_bars} (cota inferior ${c.lower_bound}, aprovechamiento ${(c.utilization * 100).toFixed(1)} %, sierra ${fmt(c.kerf)} mm)`, 2.6);
    y -= 5;
    for (const b of c.bars) {
      const x = 40, W = 180, k = W / c.bar_length;
      d.polyline([[x, y], [x + W, y], [x + W, y + 3.5], [x, y + 3.5]], LW_THIN, null, BLACK, true);
      let xx = x + c.trim * k;
      for (const cut of b.cuts) {
        const ww = cut.length * k;
        d.rect(xx, y, ww, 3.5, LW_THIN, [0.82, 0.86, 0.9]);
        if (ww > 9) d.text(xx + ww / 2, y + 0.9, cut.ref.split("-").at(-1), 2.0, "c");
        xx += ww + c.kerf * k;
      }
      d.text(x + W + 3, y + 0.6, `Barra ${b.bar}: retal ${fmt(b.remnant)} mm${b.remnant_reusable ? " (aprovechable)" : ""}`, 2.2);
      y -= 5.5;
      if (y < 22) return;
    }
    y -= 2;
  }
}

function planSheetPart(d, X, part, number) {
  const it = [{ part, T: [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]] }];
  X.onProgress?.(`Planos: pieza de chapa ${part.ref}`);
  const projs = Object.fromEntries(["alzado", "perfil", "planta"].map((v) => [v, project(it, v, { hidden: true, res: 2000 })]));
  const [s, V] = layoutOrtho(projs, [28, 18, 405, 272], [TB_RESERVED, [290, 80, 412, 272]]);
  const spec = part.spec;
  d.newSheet(number, `Pieza de chapa: ${part.name}`, scaleLabel(s), `${part.material} e=${fmt(spec.t)}`);
  for (const [n, v] of Object.entries(V)) { v.label = LABEL[n]; d.drawView(v, true); }
  const [lo, hi] = partGeometry(part).bbox;
  const a = V.alzado, pl = V.planta;
  const [xa, ya] = pl.at([lo[0], lo[1], 0]), [xb, yb] = pl.at([hi[0], hi[1], 0]);
  d.dimH(xa, xb, ya, ya, pl.oy - 9, hi[0] - lo[0], `${part.ref}_LX`);
  d.dimV(ya, yb, pl.ox, pl.ox, pl.ox - 9, hi[1] - lo[1], `${part.ref}_LY`);
  const [, z0] = a.at([0, 0, lo[2]]), [, z1] = a.at([0, 0, hi[2]]);
  d.dimV(z0, z1, a.ox + a.w, a.ox + a.w, a.ox + a.w + 9, hi[2] - lo[2], `${part.ref}_ALA`);
  if (spec.notch[0]) { const [x1] = pl.at([spec.notch[0], lo[1], 0]); d.dimH(xa, x1, yb, yb, pl.oy + pl.h + 7, spec.notch[0], `${part.ref}_ESCOTADURA`); }
  // sección A-A del ala (geometría exacta del pliegue)
  const f0 = spec.flanges.find((f) => f.edge === "y0") ?? spec.flanges[0];
  if (f0) {
    const { t, r, R } = spec, hf = f0.height;
    const rect = [296, 176, 404, 262];
    const sc = [[5, 1], [2, 1], [1, 1]].find(([k]) => (hf + 15) * k <= rect[2] - rect[0] - 14 && (hf + 6) * k <= rect[3] - rect[1] - 6) ?? [1, 1];
    const k = sc[0] / sc[1], ox = rect[0] + 12, oy = rect[1] + 3 + hf * k;
    const Q = (y, z) => [ox + y * k, oy + z * k];       // y: desde la cara exterior del ala, z: desde la cara superior
    const arcPts = (rr, a0, a1) => Array.from({ length: 13 }, (_, i) => { const an = a0 + ((a1 - a0) * i) / 12; return Q(R + rr * Math.cos(an), -R + rr * Math.sin(an)); });
    const prof = [Q(R + 15, 0), ...arcPts(R, Math.PI / 2, Math.PI), Q(0, -hf), Q(t, -hf), ...arcPts(r, Math.PI, Math.PI / 2), Q(R + 15, -t)];
    d.polyline(prof, LW_THICK);
    d.line(Q(R + 15, 0), Q(R + 15, -t), LW_THIN, [1.5, 1]);
    d.dimV(Q(0, -hf)[1], Q(0, 0)[1], Q(0, 0)[0], Q(0, 0)[0], Q(0, 0)[0] - 7, hf, `${part.ref}_ALA_SECCION`, "seccion");
    d.dimH(Q(0, -hf)[0], Q(t, -hf)[0], Q(0, -hf)[1], Q(0, -hf)[1], Q(0, -hf)[1] - 4, t, `${part.ref}_ESPESOR`, "seccion");
    d.text(Q(R, -R)[0] + 3, Q(R, -R)[1] + 2, `Ri ${fmt(r)}`, 2.6, "l");
    d.text((rect[0] + rect[2]) / 2, rect[1] - 6, `SECCIÓN A-A (E ${scaleLabel(sc)})`, 3.0, "c", 0, true);
    d.notes(rect[0], rect[1] - 12, [`Espesor t = ${fmt(t)} mm · Ri = ${fmt(r)} mm · K = ${spec.K.toFixed(3)}`, `Pliegues a 90° hacia ${f0.direction === "up" ? "arriba" : "abajo"} · BD = ${fmt(spec.BD, 3)} mm`], 2.6, 105);
  }
  const holes = spec.flanges.reduce((s2, f) => s2 + f.holes.length, 0) + (spec.holes?.length ?? 0);
  d.notes(296, 150, [`Referencia: ${part.ref}`, `Material: ${C.material(part.material).name}`, `Masa (desde sólido): ${part.mass.toFixed(2)} kg`,
    `Taladros: ${holes} uds — posiciones en desarrollo (plano 04) y DXF`, `Acabado: ${part.finish ? C.finish(part.finish).name : "—"}`, "Rebabas eliminadas. Aristas vivas matadas 0,5 mm."], 2.6, 105);
}

function planFlat(d, X, part, number) {
  const fp = part.flat.normalized();
  const w = fp.width, h = fp.height, rect = [52, 100, 400, 238];
  const s = SCALES.find(([a, b]) => (w * a) / b <= rect[2] - rect[0] && (h * a) / b <= rect[3] - rect[1]) ?? SCALES.at(-1);
  const k = s[0] / s[1];
  d.newSheet(number, `Desarrollo: ${part.name}`, scaleLabel(s), `${part.material} e=${fmt(part.spec.t)}`);
  const ox = rect[0] + (rect[2] - rect[0] - w * k) / 2, oy = rect[1] + (rect[3] - rect[1] - h * k) / 2 + 4;
  const P = (x, y) => [ox + x * k, oy + y * k];
  d.polyline(fp.outline.map(([x, y]) => P(x, y)), LW_THICK, null, BLACK, true);
  for (const ho of fp.holes) {
    if (ho.kind === "round") { const [cx, cy] = P(ho.x, ho.y); d.circle(cx, cy, Math.max(0.4, (ho.d / 2) * k)); }
    else { const [x0, y0] = P(ho.x - ho.w / 2, ho.y - ho.h / 2); d.rect(x0, y0, ho.w * k, ho.h * k); }
  }
  const xs = [], ys = [];
  for (const b of fp.bends) {
    const p0 = P(...b.p0), p1 = P(...b.p1);
    d.line(p0, p1, LW_THIN, [6, 1.5, 1, 1.5]);
    const mid = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2], horiz = Math.abs(p1[1] - p0[1]) < 1e-6;
    d.text(mid[0] + (horiz ? 0 : -1.5), mid[1] + (horiz ? 1.2 : 0), `${b.direction} 90° Ri${fmt(b.radius)}`, 2.2, "c", horiz ? 0 : 90, false, GREY);
    if (horiz) ys.push(b.p0[1]); else xs.push(b.p0[0]);
  }
  d.dimH(P(0, 0)[0], P(w, 0)[0], oy, oy, oy - 14, w, `${part.ref}_DESARROLLO_X`, "desarrollo");
  d.dimV(P(0, 0)[1], P(0, h)[1], ox, ox, ox - 14, h, `${part.ref}_DESARROLLO_Y`, "desarrollo");
  let chain = [0, ...xs.sort((a, b) => a - b), w];
  for (let i = 0; i < chain.length - 1; i++) d.dimH(P(chain[i], 0)[0], P(chain[i + 1], 0)[0], oy, oy, oy - 7, chain[i + 1] - chain[i]);
  chain = [0, ...ys.sort((a, b) => a - b), h];
  for (let i = 0; i < chain.length - 1; i++) d.dimV(P(0, chain[i])[1], P(0, chain[i + 1])[1], ox, ox, ox - 7, chain[i + 1] - chain[i]);
  const spec = part.spec;
  const rows = fp.holes.slice(0, 48).map((ho, n) => [n + 1, Math.round(ho.x * 100) / 100, Math.round(ho.y * 100) / 100, ho.kind === "round" ? `Ø${fmt(ho.d)}` : `□${fmt(ho.w)}x${fmt(ho.h)}`]);
  const cols = [["Nº", 10, "c"], ["X", 22, "r"], ["Y", 22, "r"], ["Forma", 22, "c"]];
  for (let c = 0; c < 4 && rows.length > c * 12; c++) d.table(40 + c * 82, 86, cols, rows.slice(c * 12, c * 12 + 12), 4.4, 6, 2.2);
  d.notes(32, 268, [`Desarrollo plano de ${part.ref} — origen en la esquina inferior izquierda · espesor ${fmt(spec.t)} mm · Ri ${fmt(spec.r)} mm · K ${spec.K.toFixed(3)} (DIN 6935) · `
    + `BA = π/2·(Ri+K·t) = ${fmt(spec.BA, 3)} mm · BD = ${fmt(spec.BD, 3)} mm.`,
  `Contorno neto ${fmt(fp.netArea / 1e6, 4)} m² · longitud de corte ${fmt(fp.cutLength / 1000, 2)} m · fichero de corte 03_DXF_CORTE/${part.ref}.dxf (escala 1:1, mm) · tolerancias EN ISO 9013 clase 2.`], 2.6, 370);
}

function planPlates(d, X, number) {
  const plates = Object.values(X.m.parts).filter((p) => p.kind === "pletina").sort((a, b) => a.pos - b.pos);
  if (!plates.length) return;
  d.newSheet(number, "Pletinas cortadas por láser", "2:1", [...new Set(plates.map((p) => p.material))].sort().join(", "));
  let x = 50;
  for (const p of plates) {
    const k = 2, y = 170, r = p.corner_r;
    const pts = [];
    for (const [cx, cy, a0] of [[p.w - r, r, -90], [p.w - r, p.h - r, 0], [r, p.h - r, 90], [r, r, 180]])
      for (let i = 0; i <= 8; i++) { const an = ((a0 + (90 * i) / 8) * Math.PI) / 180; pts.push([x + (cx + r * Math.cos(an)) * k, y + (cy + r * Math.sin(an)) * k]); }
    d.polyline(pts, LW_THICK, null, BLACK, true);
    for (const [hx, hy, hd] of p.holes) {
      const cx = x + hx * k, cy = y + hy * k;
      d.circle(cx, cy, (hd / 2) * k);
      d.line([cx - hd * k, cy], [cx + hd * k, cy], LW_THIN, [3, 1, 1, 1]); d.line([cx, cy - hd * k], [cx, cy + hd * k], LW_THIN, [3, 1, 1, 1]);
      d.text(cx + (hd * k) / 2 + 2, cy + (hd * k) / 2 + 2, `Ø${fmt(hd)}`, 2.8);
    }
    d.dimH(x, x + p.w * k, y, y, y - 9, p.w, `${p.ref}_W`, "geometria_pieza");
    d.dimV(y, y + p.h * k, x, x, x - 9, p.h, `${p.ref}_H`, "geometria_pieza");
    d.text(x, y + p.h * k + 12, `Pos. ${p.pos} — ${p.ref}`, 3.0, "l", 0, true);
    d.text(x, y + p.h * k + 7, `${p.name} · ${p.material} e=${fmt(p.t)} · R${fmt(p.corner_r)}`, 2.6);
    x += p.w * k + 70;
  }
}

function detail(d, X, joint, members, rect, title, half = 60) {
  const insts = members.map((id) => { try { return X.inst(id); } catch { return null; } }).filter(Boolean);
  if (!insts.length) return;
  const proj = project(X.items(insts), "iso", { hidden: false, res: 1600 });
  const c = projectPoint(joint.location, "iso");
  const win = [c[0] - half, c[1] - half, c[0] + half, c[1] + half];
  const clip = (s) => {            // recorte de segmento a la ventana (Liang-Barsky)
    let [x0, y0, x1, y1] = s, t0 = 0, t1 = 1;
    const dx = x1 - x0, dy = y1 - y0;
    for (const [p, q] of [[-dx, x0 - win[0]], [dx, win[2] - x0], [-dy, y0 - win[1]], [dy, win[3] - y0]]) {
      if (p === 0) { if (q < 0) return null; continue; }
      const r = q / p;
      if (p < 0) { if (r > t1) return null; if (r > t0) t0 = r; } else { if (r < t0) return null; if (r < t1) t1 = r; }
    }
    return [x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy];
  };
  const vis = proj.visible.map(clip).filter(Boolean);
  const sub = { visible: vis, hidden: [], bbox: win };
  const [sc, v] = fitView(sub, "iso", [rect[0] + 4, rect[1] + 10, rect[2] - 30, rect[3] - 8], [[1, 1], [1, 2], [1, 5]]);
  d.drawView(v, false, 0.35);
  d.rect(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1], 0.3);
  d.text(rect[0] + 3, rect[3] - 5, `${title} (E ${scaleLabel(sc)})`, 2.8, "l", 0, true);
  const tgt = v.P(...c);
  d.weldSymbol(tgt, [Math.min(rect[2] - 28, tgt[0] + 14), Math.min(rect[3] - 10, tgt[1] + 14)], joint.weld.a, joint.weld.all_around ?? true, "135");
}

function planWelds(d, X) {
  const m = X.m, est = X.group("EST");
  const proj = X.proj("est", est, "alzado", false);
  const [s, v] = fitView(proj, "alzado", [35, 152, 290, 248]);
  d.newSheet("05", "Uniones soldadas: símbolos, detalles y secuencia", scaleLabel(s), m.params.values.MATERIAL_ESTRUCTURAL);
  v.label = "ALZADO DE LA ESTRUCTURA"; v.labelOffset = 8;
  d.drawView(v, false);
  const groups = new Map();
  for (const j of m.joints) if (j.kind === "soldadura") { if (!groups.has(j.description)) groups.set(j.description, []); groups.get(j.description).push(j); }
  const rows = [], placed = [];
  [...groups.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).forEach(([desc, js], n0) => {
    const n = n0 + 1, j = js[0];
    const tgt = v.at(j.location), left = tgt[0] < v.ox + v.w / 2, side = left ? -1 : 1;
    let y = v.oy + v.h + 6;
    while (placed.some(([px, py]) => Math.abs(y - py) < 6.5 && (px < v.ox + v.w / 2) === left)) y += 6.5;
    const bx = left ? v.ox - 4 : v.ox + v.w + 4;
    if (y < 268) { d.weldSymbol(tgt, [bx, y], j.weld.a, j.weld.all_around ?? true, "135", null, side); d.text(bx + 24 * side + (side > 0 ? 3 : -3), y + 1.2, `(${n})`, 2.4, side > 0 ? "l" : "r"); placed.push([bx, y]); }
    const L = j.weld.length;
    rows.push([n, desc, `a${fmt(j.weld.a)}`, j.weld.all_around ? "perimetral" : "3 cordones", fmt(L), js.length, fmt(L * js.length), j.weld.process ?? "135"]);
  });
  d.table(32, 140, [["Nº", 8, "c"], ["Unión", 80, "l"], ["Garganta", 15, "c"], ["Tipo", 19, "c"], ["L unit. mm", 18, "r"], ["Uds", 9, "c"], ["L total mm", 19, "r"], ["Proceso", 22, "c"]], rows, 4.4, 6, 2.2);
  const topLong = m.structure.levels.SUP.long[0];
  const jl = m.joints.find((j) => j.id === `J.${topLong}.0`), jp = m.joints.find((j) => j.id.startsWith("J.PLACA."));
  if (jl) detail(d, X, jl, jl.members, [300, 205, 405, 268], "DETALLE A: LARGUERO–PATA", 70);
  if (jp) detail(d, X, jp, [...jp.members, jp.id.replace("J.PLACA", "EST.TUERCA")], [300, 140, 405, 203], "DETALLE B: PLACA BASE", 45);
  const w = X.plan.welding;
  d.notes(300, 134, ["NOTAS DE SOLDADURA", "Representación simbólica EN ISO 2553. Proceso 135 (MAG, hilo macizo G3Si1).",
    `Cordón total ${fmt(w.total_length_mm / 1000, 2)} m · depositado ${fmt(w.deposit_kg, 3)} kg · hilo ${fmt(w.wire_kg, 3)} kg · gas ${fmt(w.gas_l, 0)} l.`,
    `Calidad EN ISO 5817-C · ${m.params.values.CLASE_EJECUCION} (EN 1090-2).`,
    "Secuencia: 1) puntear bastidor superior en mesa plana con escuadras; 2) puntear patas y verificar diagonales; 3) bastidores inferiores; 4) soldar alternando esquinas opuestas; "
    + "5) placas base y tuercas; 6) enderezar, amolar caras enrasadas y verificar planitud.",
    "Pared delgada: cordones cortos alternos para limitar la distorsión.",
    m.joints.some((j) => j.kind === "soldadura" && j.weld.a < 3) ? "Garganta a < 3 mm: requiere WPS cualificada (EN ISO 15614-1)." : ""], 2.2, 104, true);
}

function partTargets(X, insts, explode) {
  const t = new Map();
  for (const i of insts) if (!t.has(i.part.key)) {
    const [lo, hi] = instanceBBox(i), ex = explode ? explodeOf(X.m, i) : [0, 0, 0];
    t.set(i.part.key, [String(i.part.pos), lo.map((v, k) => (v + hi[k]) / 2 + ex[k])]);
  }
  return [...t.values()];
}

function planExploded(d, X) {
  const m = X.m;
  const proj = X.proj("all", m.instances, "iso", false, true);
  const [s, v] = fitView(proj, "iso", [35, 30, 295, 248], [...SCALES, [1, 200]]);
  d.newSheet("06", "Vista explosionada", scaleLabel(s), "Ver despiece");
  v.label = "PERSPECTIVA ISOMÉTRICA EXPLOSIONADA";
  d.drawView(v, false, 0.3);
  balloons(d, v, partTargets(X, m.instances, true), true, 9, 8);
  d.table(300, 262, [["Pos", 9, "c"], ["Ref", 10, "c"], ["Descripción", 70, "l"], ["Cant", 11, "c"]],
    X.bom.rows.map((r) => [r.pos, r.kind !== "normalizado" ? r.ref.split("-").at(-1) : "N", r.description, r.qty]), 4.6, 6, 2.2);
}

export const ASSEMBLY_TEXTS = {
  EST: "Recepción de la estructura soldada y pintada. Insertar las tuercas remachables M6 en los taladros Ø9,1 de largueros y travesaños con remachadora manual.",
  APO: "Roscar los pies niveladores en las tuercas soldadas de las placas base. Nivelar la mesa en su emplazamiento (nivel de burbuja sobre encimera al final).",
  BAL: "Colocar la balda sobre el bastidor inferior, con las escotaduras alrededor de las patas. Fijar con tornillos ISO 7380 M6x12 (par 8 N·m, llave Allen 4 mm).",
  ENC: "Colocar la encimera sobre el bastidor superior y fijarla con tornillos ISO 7380 M6x12 por las pestañas (par 8 N·m). Apretar en cruz desde el centro.",
};
const TOOLS = ["HERRAMIENTAS:", "· Remachadora para tuercas M6", "· Llave Allen 4 mm (dinamométrica)", "· Llave fija 17/19 para contratuerca de pies", "· Nivel de burbuja", "",
  "PARES DE APRIETE:", "· ISO 7380 M6 8.8 en remachable de acero: 8 N·m", "", "DESMONTAJE:", "Chapas desmontables (uniones atornilladas). La estructura es un subconjunto soldado no desmontable.", "",
  "SEGURIDAD:", "Manipular las chapas entre dos personas; usar guantes (cantos de chapa)."];

function planAssembly(d, X) {
  const m = X.m;
  const order = Object.values(m.subassemblies).sort((a, b) => a.step - b.step);
  d.newSheet("07", "Instrucciones de montaje", "S/E", "—");
  const cells = [[28, 178, 152, 270], [156, 178, 280, 270], [284, 178, 408, 270], [28, 84, 152, 174], [156, 84, 280, 174]];
  const texts = { ...ASSEMBLY_TEXTS, ...(m.structure.assembly_texts ?? {}) };
  const shown = [];
  order.slice(0, 4).forEach((sa, n) => {
    shown.push(...m.instances.filter((i) => i.group === sa.id));
    const proj = X.proj(`paso${n}`, [...shown], "iso", false);
    const cell = cells[n];
    const [, v] = fitView(proj, "iso", [cell[0] + 2, cell[1] + 18, cell[2] - 2, cell[3] - 9], [], true);
    d.drawView(v, false, 0.25);
    d.rect(cell[0], cell[1], cell[2] - cell[0], cell[3] - cell[1], 0.3);
    d.text(cell[0] + 3, cell[3] - 6, `PASO ${n + 1}: ${sa.name.toUpperCase()}`, 3.0, "l", 0, true);
    d.notes(cell[0] + 3, cell[1] + 14, [texts[sa.id] ?? ""], 2.1, 118);
  });
  d.rect(284, 84, 124, 90, 0.3);
  d.notes(287, 170, TOOLS, 2.2, 118);
}

function planBom(d, X) {
  const rows = X.bom.rows.map((r) => [r.pos, r.ref, r.description, r.material ?? "", r.thickness, r.length, r.width, r.qty, r.unit_mass, r.total_mass]);
  d.newSheet("08", "Despiece y lista de materiales", "—", "Ver lista");
  const y = d.table(30, 268, [["Pos", 10, "c"], ["Referencia", 42, "l"], ["Descripción", 105, "l"], ["Material", 42, "l"], ["Espesor", 16, "r"], ["Largo", 20, "r"], ["Ancho", 18, "r"],
    ["Cant.", 13, "c"], ["Peso unit. kg", 22, "r"], ["Peso total kg", 22, "r"]], rows, 5.2, 6, 2.4);
  const t = X.bom.totals;
  d.notes(30, y - 6, [`Componentes: ${t.components} (${t.manufactured_parts} fabricados, ${t.standard_parts} normalizados) · Referencias distintas: ${t.distinct_parts} · Masa total: ${t.total_mass.toFixed(2)} kg (calculada desde los sólidos).`,
    "Metros de perfil: " + Object.entries(t.profile_meters).map(([k, v]) => `${k}: ${v.toFixed(3)} m`).join("; "),
    "Superficie de chapa: " + Object.entries(t.sheet_area_m2).map(([k, v]) => `${k}: ${v.toFixed(4)} m²`).join("; ")], 2.6, 360);
}

/** Juego completo de planos. Devuelve { pdf: Uint8Array, sheets, total }. */
export async function drawingSet(model, summary, info, onProgress = null) {
  const X = new Ctx(model, summary, info, onProgress);
  const sheets = Object.values(model.parts).filter((p) => p.kind === "chapa").sort((a, b) => a.pos - b.pos);
  const plates = Object.values(model.parts).filter((p) => p.kind === "pletina");
  const total = 3 + sheets.length * 2 + (plates.length ? 1 : 0) + 4;
  const d = new Drawing({ ...info, total_sheets: total, title: `Planos ${model.product_code}`, assembly_ref: model.product_code });
  planGeneral(d, X);
  planStructure(d, X);
  planProfiles(d, X);
  sheets.forEach((p, n) => planSheetPart(d, X, p, `03.${n + 1}`));
  sheets.forEach((p, n) => planFlat(d, X, p, `04.${n + 1}`));
  if (plates.length) planPlates(d, X, `04.${sheets.length + 1}`);
  planWelds(d, X);
  planExploded(d, X);
  planAssembly(d, X);
  planBom(d, X);
  onProgress?.("Planos: compresión del PDF");
  return { pdf: await d.finish(), sheets: d.pages, total: d.pages.length, ctx: X };
}

/** Instrucciones de montaje (documento independiente): portada + una hoja por paso con vista explosionada del paso. */
export async function assemblyInstructions(model, summary, info, X = null, onProgress = null) {
  X = X ?? new Ctx(model, summary, info, onProgress);
  const m = model;
  const order = Object.values(m.subassemblies).sort((a, b) => a.step - b.step);
  const d = new Drawing({ ...info, total_sheets: order.length + 1, title: `Instrucciones de montaje ${m.product_code}`, assembly_ref: m.product_code });
  const texts = { ...ASSEMBLY_TEXTS, ...(m.structure.assembly_texts ?? {}) };
  d.newSheet("M0", "Instrucciones de montaje: conjunto y herramientas", "S/E", "—");
  const all = X.proj("all", m.instances, "iso", false, true);
  const [, v0] = fitView(all, "iso", [30, 90, 270, 270], [], true);
  v0.label = "CONJUNTO EXPLOSIONADO"; v0.labelOffset = 6;
  d.drawView(v0, false, 0.3);
  balloons(d, v0, partTargets(X, m.instances, true), true, 9, 4);
  d.rect(284, 84, 124, 190, 0.3);
  let y = d.notes(287, 268, [`${m.family_name} ${m.product_code}`, `Masa total ${summary.bom.totals.total_mass.toFixed(1)} kg · ${summary.bom.totals.components} componentes`, "",
    "ORDEN DE MONTAJE:", ...order.map((s, n) => `${n + 1}. ${s.name}`), "", ...TOOLS], 2.4, 118, true);
  void y;
  const shown = [];
  order.forEach((sa, n) => {
    const now = m.instances.filter((i) => i.group === sa.id);
    d.newSheet(`M${n + 1}`, `Paso ${n + 1}: ${sa.name}`, "S/E", "—");
    const prev = project(X.items(shown), "iso", { hidden: false, res: 1800 });
    const cur = project(now.map((i) => ({ part: i.part, T: mmul(translation(...explodeOf(m, i).map((e) => e * 0.6)), i.T) })), "iso", { hidden: false, res: 1800 });
    const bb = [Math.min(prev.bbox[0], cur.bbox[0]), Math.min(prev.bbox[1], cur.bbox[1]), Math.max(prev.bbox[2], cur.bbox[2]), Math.max(prev.bbox[3], cur.bbox[3])];
    const both = { visible: [], hidden: [], bbox: shown.length ? bb : cur.bbox };
    const [, v] = fitView(both, "iso", [30, 86, 270, 270], [], true);
    const vp = new View(prev, v.scale, v.ox + (prev.bbox[0] - both.bbox[0]) * v.scale, v.oy + (prev.bbox[1] - both.bbox[1]) * v.scale, "iso");
    const vc = new View(cur, v.scale, v.ox + (cur.bbox[0] - both.bbox[0]) * v.scale, v.oy + (cur.bbox[1] - both.bbox[1]) * v.scale, "iso");
    if (shown.length) { d.pdf.lw(0.18).stroke(GREY).segments(prev.visible.map(([a, b, c, e]) => [...vp.P(a, b), ...vp.P(c, e)])); d.pdf.stroke(BLACK); }
    d.drawView(vc, false, 0.4);
    const cnt = new Map();
    for (const i of now) cnt.set(i.part.key, (cnt.get(i.part.key) ?? 0) + 1);
    const rows = [...cnt.entries()].map(([k, q]) => { const p = m.parts[k]; return [p.pos, p.ref, p.name, q]; }).sort((a, b) => a[0] - b[0]);
    d.text(30, 80, `PASO ${n + 1}: ${sa.name.toUpperCase()}`, 3.6, "l", 0, true);
    d.notes(30, 72, [texts[sa.id] ?? ""], 2.8, 190);
    d.table(284, 268, [["Pos", 10, "c"], ["Ref", 34, "l"], ["Pieza", 66, "l"], ["Uds", 12, "c"]], rows.slice(0, 30), 5.2, 6, 2.3);
    shown.push(...now);
  });
  return { pdf: await d.finish(), sheets: d.pages, total: d.pages.length };
}

/** Coherencia de las cotas registradas al dibujar frente a parámetros y geometría (port de qa.drawing_consistency). */
export function drawingConsistency(model, sheets) {
  const env = model.dims.envelope ?? {};
  const names = env.names ?? ["LONGITUD", "ANCHURA"];
  const exp = {};
  if (env.dx != null) exp[names[0]] = env.dx;
  if (env.dy != null) exp[names[1]] = env.dy;
  if (env.zmax != null) exp.ALTURA = env.zmax;
  for (const [name] of model.dims.levels ?? []) if (model.dims[name] != null) exp[name] = model.dims[name];
  Object.assign(exp, model.dims.drawing_expected ?? {});
  for (const p of Object.values(model.parts)) {
    if (p.kind === "chapa") {
      exp[`${p.ref}_DESARROLLO_X`] = p.flat.width; exp[`${p.ref}_DESARROLLO_Y`] = p.flat.height;
      exp[`${p.ref}_LX`] = p.spec.Lx; exp[`${p.ref}_LY`] = p.spec.Ly; exp[`${p.ref}_ESPESOR`] = p.spec.t;
    }
    if (p.kind === "perfil") exp[`L_${p.ref}`] = p.length;
  }
  const mism = [];
  let checked = 0;
  for (const sh of sheets) for (const dm of sh.dims) if (dm.name in exp) {
    checked++;
    if (Math.abs(dm.value - exp[dm.name]) > 0.05) mism.push({ sheet: sh.number, dim: dm.name, drawn: dm.value, expected: Math.round(exp[dm.name] * 1000) / 1000 });
  }
  return { checked_dims: checked, mismatches: mism };
}
