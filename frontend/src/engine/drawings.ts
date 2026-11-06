// @ts-nocheck
// Planos de fabricación en PDF generados en el navegador (port de monxu/docs/plans.py + drawing_kit.py):
// A3 horizontal, primer diedro, cuadro de rotulación ISO 7200, líneas ISO 128-2, acotación ISO 129-1,
// símbolos de soldadura ISO 2553. Las vistas se obtienen de los sólidos facetados (hlr.ts).
import * as C from "./catalog";
import { explodeOf, instanceBBox, instanceCentroid, modelBBox, partGeometry } from "./geometry";
import { project, projectPoint } from "./hlr";
import { mmul, translation } from "./model";
import { PDF, textWidth } from "./pdf";
import { Occupancy, auditPage, boxesOverlap, segHitsBox, segsCross, summarize, textBox } from "./layout";

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
const TB_BOX = [228, 8, 412, 80];               // cuadro de rotulación + sello de estado
const AREA = [FRAME[0] + 1.5, FRAME[1] + 1.5, FRAME[2] - 1.5, FRAME[3] - 1.5];

/** Partición en líneas de ancho máximo `width` (mm): [{ s, para }] (s = null para una línea en blanco). */
function wrap(lines, h, width, bold = false) {
  const out = [];
  lines.forEach((ln0, para) => {
    let ln = ln0;
    if (!ln) { out.push({ s: null, para }); return; }
    while (ln) {
      const words = ln.split(" ");
      let part = "";
      for (const w of words) { const cand = (part + " " + w).trim(); if (textWidth(cand, h, bold) > width && part) break; part = cand; }
      if (!part) part = ln;
      out.push({ s: part, para });
      ln = ln.slice(part.length).trimStart();
    }
  });
  return out;
}
/** Caja de un bloque de notas con la primera línea base en yTop. */
function notesBox(x, yTop, lines, h, width, boldFirst) {
  let y = yTop, w = 0, last = yTop;
  for (const l of wrap(lines, h, width)) {
    if (l.s === null) { y -= h * 0.8; continue; }
    w = Math.max(w, textWidth(l.s, h, boldFirst && l.para === 0));
    last = y; y -= h * 1.55;
  }
  return [x, last - 0.22 * h, x + w, yTop + 1.18 * h];
}

export class Drawing {
  constructor(info) {
    this.pdf = new PDF({ title: info.title ?? "Planos", author: info.designer ?? "", subject: `${info.project_code ?? ""} Rev.${info.revision ?? ""}` });
    this.info = info; this.pages = []; this.gidSeq = 0; this.pendingLabels = []; this.pendingDimTexts = [];
  }
  get page() { return this.pages.at(-1); }
  get occ() { return this.page.occ; }
  recordDim(name, value, source) { this.page.dims.push({ name, value: Math.round(value * 1000) / 1000, source }); }
  /** Ejecuta fn con una categoría y un identificador de grupo para todo lo que dibuje. */
  group(cat, fn) {
    const pc = this.pdf.cat, pg = this.pdf.gid;
    this.pdf.cat = cat; this.pdf.gid = ++this.gidSeq;
    try { return fn(this.pdf.gid); } finally { this.pdf.cat = pc; this.pdf.gid = pg; }
  }
  newSheet(number, title, scale, material = "Ver lista") {
    this.flushLabels();
    this.pdf.page(420, 297);
    const occ = new Occupancy();
    this.pdf.rec = occ;
    this.pages.push({ number, title, scale, dims: [], occ, forbid: [TB_BOX] });
    this.group("frame", () => this.frame());
    this.group("tb", () => this.titleBlock(number, title, scale, material));
  }
  /** Reserva zonas en las que no deben colocarse textos ni globos automáticos (p. ej. una tabla que se dibujará después). */
  reserve(box) { this.page.forbid.push(box); }
  async finish() { this.flushLabels(); this.pdf.rec = null; return this.pdf.save(); }
  /** Coste de colocar una caja: conflictos con lo ya dibujado, zonas reservadas y salida del área útil. */
  boxCost(box, opts = {}) {
    let n = this.occ.cost(box, { region: opts.region ?? AREA, ignoreGid: opts.ignoreGid ?? null, cats: opts.cats ?? null });
    for (const f of this.page.forbid) if (boxesOverlap(box, f, 0)) n += 50;
    return n;
  }
  /** Elige entre posiciones candidatas la de menor coste ([x, y, align, angle]) y dibuja el texto. */
  placeText(s, h, cands, opts = {}) {
    const bold = !!opts.bold, w = textWidth(s, h, bold);
    let best = null;
    cands.forEach(([x, y, align = "l", angle = 0], k) => {
      const dx = align === "c" ? -w / 2 : align === "r" ? -w : 0;
      const a = (angle * Math.PI) / 180;
      const box = textBox(x + dx * Math.cos(a), y + dx * Math.sin(a), w, h, angle);
      const c = this.boxCost(box, opts) * 10 + k * (opts.orderWeight ?? 0.01);
      if (!best || c < best.c) best = { c, x, y, align, angle, box };
    });
    if (best) this.text(best.x, best.y, s, h, best.align, best.angle, bold, opts.color ?? BLACK);
    return best;
  }
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
    this.firstAngle(x0 + 168.5, y0 + 13.2);
    this.line([x0 + 120, y0], [x0 + 120, y0 + 10]);
    this.label(x0 + 1.5, y0 + 7.5, "Tolerancias generales");
    this.text(x0 + 3, y0 + 2.5, `${I.tolerances ?? "ISO 2768-mK"} · soldadura EN ISO 13920-BF`, 2.6, "l");
    this.text(x0 + 121.5, y0 + 5.6, fitText(I.company ?? "MUEBLES MONXU", 57, 3.2), 3.2, "l", 0, true);
    this.text(x0 + 121.5, y0 + 1.6, "Documento generado del modelo paramétrico", 1.9, "l");
    if (I.status_stamp) {
      const col = I.status_level === "error" ? RED : GREY;
      this.pdf.lw(0.4).stroke(col).rect(x0, y1 + 2, TB_W, 7);
      this.pdf.stroke(BLACK);
      this.text(x0 + TB_W / 2, y1 + 4, fitText(I.status_stamp, TB_W - 4, 2.6), 2.6, "c", 0, true, col);
    }
  }
  firstAngle(cx, cy) {
    this.line([cx - 9, cy - 1.3], [cx - 9, cy + 1.3]); this.line([cx - 3, cy - 2.6], [cx - 3, cy + 2.6]);
    this.line([cx - 9, cy + 1.3], [cx - 3, cy + 2.6]); this.line([cx - 9, cy - 1.3], [cx - 3, cy - 2.6]);
    this.circle(cx + 4, cy, 2.6); this.circle(cx + 4, cy, 1.3);
  }
  /** Desplaza la línea de cota hacia fuera mientras se superponga a la línea de otra cota (cotas apiladas). */
  _lane(lo, hi, pos, sgn, horizontal) {
    for (let k = 0; k < 5; k++) {
      const band = horizontal ? [lo + 0.8, pos - 0.6, hi - 0.8, pos + 0.6] : [pos - 0.6, lo + 0.8, pos + 0.6, hi - 0.8];
      // las prolongaciones colineales de cotas cortas vecinas (≤ 5 mm) no cuentan como choque
      // (flechas y prolongaciones de cotas cortas vecinas en la misma línea, a menos de 6 mm de los extremos)
      const clash = this.occ.segsIn(band, ["dim"]).some((q) => {
        const g = q.seg, a0 = Math.min(horizontal ? g[0] : g[1], horizontal ? g[2] : g[3]), a1 = Math.max(horizontal ? g[0] : g[1], horizontal ? g[2] : g[3]);
        const c0 = horizontal ? g[1] : g[0], c1 = horizontal ? g[3] : g[2];
        const onLine = Math.abs(c0 - pos) < 0.7 && Math.abs(c1 - pos) < 0.7;
        return !(onLine && Math.min(a1, hi) - Math.max(a0, lo) <= 6);
      });
      if (!clash) return pos;
      const nxt = pos + sgn * 7;
      if (horizontal ? nxt < AREA[1] + 4 || nxt > AREA[3] - 4 : nxt < AREA[0] + 4 || nxt > AREA[2] - 4) return pos;
      pos = nxt;
    }
    return pos;
  }
  /** Los textos de cota se colocan al final (cuando ya están todas las líneas de cota de la hoja). */
  _dimText(fn) { this.pendingDimTexts.push(fn); }
  flushDimTexts() { const q = this.pendingDimTexts; this.pendingDimTexts = []; for (const f of q) f(); }
  dimH(x1, x2, yf1, yf2, yd, value, name = null, source = "geometria", prefix = "", lane = true) {
    if (Math.abs(x2 - x1) < 0.5) return;
    if (x1 > x2) { [x1, x2] = [x2, x1]; [yf1, yf2] = [yf2, yf1]; }
    const sgn = yd >= Math.max(yf1, yf2) ? 1 : -1, h = 3.0, txt = prefix + fmt(value), w = textWidth(txt, h);
    if (lane) yd = this._lane(x1, x2, yd, sgn, true);
    this.group("dim", () => {
      for (const [x, yf] of [[x1, yf1], [x2, yf2]]) this.line([x, yf + sgn], [x, yd + sgn * 2], LW_DIM);
      this.line([x1, yd], [x2, yd], LW_DIM);
      const inner = x2 - x1 > 9;
      if (inner) { this.arrow([x1, yd], [-1, 0]); this.arrow([x2, yd], [1, 0]); }
      else { this.line([x1 - 5, yd], [x2 + 5, yd], LW_DIM); this.arrow([x1, yd], [1, 0]); this.arrow([x2, yd], [-1, 0]); }
    });
    this._dimText(() => this.group("dim", () => {
      const inner = x2 - x1 > 9;
      const up = yd + 1.0, dn = yd - 1.0 - h, mid = (x1 + x2) / 2, fits = x2 - x1 > w + 3;
      const c = [];
      if (fits) { c.push([mid, up, "c"]); for (const f of [0.3, 0.7, 0.15, 0.85]) c.push([x1 + 1.5 + w / 2 + f * (x2 - x1 - 3 - w), up, "c"]); }
      const xr = x2 + (inner ? 2.5 : 6), xl = x1 - (inner ? 2.5 : 6);
      c.push([xr, up, "l"], [xl, up, "r"]);
      if (fits) c.push([mid, dn, "c"]);
      c.push([xr, dn, "l"], [xl, dn, "r"]);
      // filas escalonadas más allá del extremo de las líneas de referencia (cadenas de cotas apretadas)
      const far = sgn > 0 ? [yd + 3.2, yd + 7.6, yd + 12] : [yd - 3.2 - 1.18 * h, yd - 7.6 - 1.18 * h, yd - 12 - 1.18 * h];
      for (const yy of far) c.push([mid, yy, "c"], [x1, yy, "c"], [x2, yy, "c"]);
      const b = this.placeText(txt, h, c, { orderWeight: 0.6 });
      if (b && b.align !== "c") {          // texto fuera de las líneas de referencia: prolongar la línea de cota bajo él
        const e = b.align === "l" ? [x2, b.x + w + 0.5] : [b.x - w - 0.5, x1];
        this.line([e[0], yd], [e[1], yd], LW_DIM);
      }
    }));
    if (name) this.recordDim(name, value, source);
  }
  dimV(y1, y2, xf1, xf2, xd, value, name = null, source = "geometria", prefix = "", lane = true) {
    if (Math.abs(y2 - y1) < 0.5) return;
    if (y1 > y2) { [y1, y2] = [y2, y1]; [xf1, xf2] = [xf2, xf1]; }
    const sgn = xd >= Math.max(xf1, xf2) ? 1 : -1, h = 3.0, txt = prefix + fmt(value), w = textWidth(txt, h);
    if (lane) xd = this._lane(y1, y2, xd, sgn, false);
    this.group("dim", () => {
      for (const [y, xf] of [[y1, xf1], [y2, xf2]]) this.line([xf + sgn, y], [xd + sgn * 2, y], LW_DIM);
      this.line([xd, y1], [xd, y2], LW_DIM);
      const inner = y2 - y1 > 9;
      if (inner) { this.arrow([xd, y1], [0, -1]); this.arrow([xd, y2], [0, 1]); }
      else { this.line([xd, y1 - 5], [xd, y2 + 5], LW_DIM); this.arrow([xd, y1], [0, 1]); this.arrow([xd, y2], [0, -1]); }
    });
    this._dimText(() => this.group("dim", () => {
      const inner = y2 - y1 > 9;
      // texto girado 90°: la caja ocupa x ∈ [x − 1,18·h, x + 0,22·h]
      const lf = xd - 1.0, rt = xd + 1.0 + 1.18 * h, mid = (y1 + y2) / 2, fits = y2 - y1 > w + 3;
      const c = [];
      if (fits) { c.push([lf, mid, "c", 90]); for (const f of [0.3, 0.7, 0.15, 0.85]) c.push([lf, y1 + 1.5 + w / 2 + f * (y2 - y1 - 3 - w), "c", 90]); }
      const yu = y2 + (inner ? 2.5 : 6), yl = y1 - (inner ? 2.5 : 6);
      c.push([lf, yu, "l", 90], [lf, yl, "r", 90]);
      if (fits) c.push([rt, mid, "c", 90]);
      c.push([rt, yu, "l", 90], [rt, yl, "r", 90]);
      const far = sgn > 0 ? [xd + 3.2 + 1.18 * h, xd + 7.6 + 1.18 * h, xd + 12 + 1.18 * h] : [xd - 3.2, xd - 7.6, xd - 12];
      for (const xx of far) c.push([xx, mid, "c", 90], [xx, y1, "c", 90], [xx, y2, "c", 90]);
      const b = this.placeText(txt, h, c, { orderWeight: 0.6 });
      if (b && b.align !== "c") {
        const e = b.align === "l" ? [y2, b.y + w + 0.5] : [b.y - w - 0.5, y1];
        this.line([xd, e[0]], [xd, e[1]], LW_DIM);
      }
    }));
    if (name) this.recordDim(name, value, source);
  }
  /**
   * Cadena de cotas a lo largo de un eje (coordenadas dibujadas `pts`, valores reales `vals`). Los tramos iguales
   * consecutivos demasiado cortos para su texto se acotan juntos con la notación «n×paso» (cada tramo se registra).
   */
  dimChain(horizontal, pts, vals, f, pos, names = [], source = "geometria") {
    let i = 0;
    while (i < vals.length) {
      let j = i;
      while (j + 1 < vals.length && Math.abs(vals[j + 1] - vals[i]) < 0.05) j++;
      const seg = Math.abs(pts[i + 1] - pts[i]), w = textWidth(fmt(vals[i]), 3.0);
      const draw = (a, b, v, name, prefix = "") => horizontal ? this.dimH(pts[a], pts[b], f, f, pos, v, name, source, prefix) : this.dimV(pts[a], pts[b], f, f, pos, v, name, source, prefix);
      if (j > i && seg < w + 3) {
        draw(i, j + 1, vals[i], null, `${j - i + 1}×`);
        for (let k = i; k <= j; k++) if (names[k]) this.recordDim(names[k], vals[k], source);
      } else for (let k = i; k <= j; k++) draw(k, k + 1, vals[k], names[k] ?? null);
      i = j + 1;
    }
  }
  balloon(c, target, label, r = 4) {
    this.group("balloon", () => {
      const dx = target[0] - c[0], dy = target[1] - c[1], d = Math.hypot(dx, dy) || 1;
      this.pdf.cat = "leader";
      this.line([c[0] + (dx / d) * r, c[1] + (dy / d) * r], target, LW_THIN);
      this.pdf.fill(BLACK).circle(target[0], target[1], 0.5, "f");
      this.pdf.cat = "balloon";
      this.circle(c[0], c[1], r, LW_THIN, [1, 1, 1]);
      this.text(c[0], c[1] - 1.2, String(label), 3.2, "c", 0, true);
    });
  }
  /** Caja que ocupa un símbolo de soldadura con su base en `base` (para colocarlo sin solapes). */
  weldBox(base, a, length, process, side, tag) {
    const [bx, by] = base, Lr = 22 * side, ex = bx + Lr;
    const tw = textWidth(process + (tag ? `  ${tag}` : ""), 2.4) + 4;
    const xs = [bx - 2 * side, bx + 9 * side - 3.2 * side - (side > 0 ? textWidth(`a${fmt(a)}`, 2.6) : -textWidth(`a${fmt(a)}`, 2.6)), ex + (3.5 + tw) * side];
    if (length) xs.push(bx + 12 * side + textWidth(fmt(length), 2.6) * side);
    return [Math.min(...xs), by - 2.8, Math.max(...xs), by + 4.6];
  }
  weldSymbol(target, base, a, allAround = true, process = "135", length = null, side = 1, tag = null) {
    this.group("weld", () => {
      const [bx, by] = base;
      this.pdf.cat = "leader";
      this.line(base, target, LW_THIN);
      this.arrow(target, [target[0] - bx, target[1] - by], 2.5);
      this.pdf.cat = "sym";
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
      this.text(ex + 3.5 * side, by - 1.0, process + (tag ? `  ${tag}` : ""), 2.4, side > 0 ? "l" : "r");
    });
  }
  table(x, yTop, cols, rows, rowH = 5.0, headH = 6.0, textH = 2.4) {
    return this.group("table", () => {
      const W = cols.reduce((s, c) => s + c[1], 0), H = headH + rowH * rows.length;
      this.pdf.lw(0.35).rect(x, yTop - H, W, H);
      this.line([x, yTop - headH], [x + W, yTop - headH]);
      let xx = x;
      cols.forEach(([t, w], k) => { if (k) this.line([xx, yTop], [xx, yTop - H]); this.text(xx + w / 2, yTop - headH + 1.8, fitText(t, w - 1.2, 2.4), 2.4, "c", 0, true); xx += w; });
      rows.forEach((row, ri) => {
        const yy = yTop - headH - rowH * (ri + 1);
        if (ri) this.line([x, yy + rowH], [x + W, yy + rowH], 0.1);
        let x2 = x;
        cols.forEach(([, w, al], k) => {
          const v = row[k];
          let s = v === null || v === undefined ? "" : typeof v === "number" && !Number.isInteger(v) ? fmt(v, 2) : String(v);
          s = fitText(s, w - 2.4, textH);
          const ty = yy + (rowH - textH) / 2 + 0.15;
          if (al === "c") this.text(x2 + w / 2, ty, s, textH, "c"); else if (al === "r") this.text(x2 + w - 1.2, ty, s, textH, "r"); else this.text(x2 + 1.2, ty, s, textH, "l");
          x2 += w;
        });
      });
      return yTop - H;
    });
  }
  notes(x, yTop, lines, h = 2.6, width = 180, boldFirst = false) {
    return this.group("note", () => {
      let y = yTop;
      for (const l of wrap(lines, h, width)) {
        if (l.s === null) { y -= h * 0.8; continue; }
        this.text(x, y, l.s, h, "l", 0, boldFirst && l.para === 0);
        y -= h * 1.55;
      }
      return y;
    });
  }
  /** Coloca un bloque de notas en la posición candidata [x, yTop] de menor coste (sin conflictos si la hay). */
  placeNotes(lines, cands, h = 2.6, width = 180, boldFirst = false) {
    let best = null;
    cands.forEach(([x, yTop, wd = width], k) => {
      const c = this.boxCost(notesBox(x, yTop, lines, h, wd, boldFirst)) + k * 0.01;
      if (!best || c < best.c) best = { c, x, yTop, wd };
    });
    if (best && best.c >= 1) {
      // sin hueco en las posiciones previstas: búsqueda en toda la hoja, cerca de la primera posición pedida
      const [ax, ay] = cands[0] ?? [30, 270];
      for (const wd of [width, width * 0.75, width * 0.55]) for (let x = AREA[0] + 4; x < AREA[2] - 30; x += 8) for (let y = AREA[3] - 4; y > AREA[1] + 8; y -= 4) {
        const c = this.boxCost(notesBox(x, y, lines, h, wd, boldFirst)) + Math.hypot(x - ax, y - ay) * 0.002 + (width - wd) * 0.001;
        if (c < best.c) best = { c, x, yTop: y, wd };
      }
    }
    return best ? this.notes(best.x, best.yTop, lines, h, best.wd, boldFirst) : null;
  }
  drawView(v, hidden = true, lw = LW_THICK) {
    const segs = (list) => list.map(([a, b, c, d]) => [...v.P(a, b), ...v.P(c, d)]);
    this.group("geom", () => {
      this.pdf.lw(lw).dash(null).stroke(BLACK).segments(segs(v.proj.visible));
      if (hidden && v.proj.hidden.length) { this.pdf.cat = "hidden"; this.pdf.lw(LW_THIN * 0.8).dash([2.0, 1.0]).stroke(GREY).segments(segs(v.proj.hidden)); this.pdf.dash(null).stroke(BLACK); }
    });
    if (v.label) this.viewLabel(v, v.label);
  }
  /** Rótulo de vista: se coloca al terminar la hoja, bajo la vista y fuera de sus cotas (o encima si no cabe). */
  viewLabel(v, s, h = 3.0) { this.pendingLabels.push({ v, s, h }); }
  flushLabels() {
    if (!this.pages.length) { this.pendingLabels = []; this.pendingDimTexts = []; return; }
    this.flushDimTexts();
    for (const { v, s, h } of this.pendingLabels) {
      const cx = v.ox + v.w / 2, c = [];
      for (let k = 0; k <= 26; k++) c.push([cx, v.oy - 5 - h - k * 1.5, "c"]);
      for (let k = 0; k <= 12; k++) c.push([cx, v.oy + v.h + 4 + k * 1.5, "c"]);
      for (const dx of [-0.25, 0.25]) for (let k = 0; k <= 10; k++) c.push([cx + dx * v.w, v.oy - 5 - h - k * 2, "c"]);
      this.group("label", () => this.placeText(s, h, c, { bold: true, orderWeight: 0.05 }));
    }
    this.pendingLabels = [];
  }
}

class View {
  constructor(proj, scale, ox, oy, name) { Object.assign(this, { proj, scale, ox, oy, name, u0: proj.bbox[0], v0: proj.bbox[1], label: "" }); }
  P(u, v) { return [this.ox + (u - this.u0) * this.scale, this.oy + (v - this.v0) * this.scale]; }
  get w() { return (this.proj.bbox[2] - this.proj.bbox[0]) * this.scale; }
  get h() { return (this.proj.bbox[3] - this.proj.bbox[1]) * this.scale; }
  get box() { return [this.ox, this.oy, this.ox + this.w, this.oy + this.h]; }
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

/** Desenreda referencias: intercambia posiciones de dos elementos mientras sus líneas se crucen y el cambio reduzca cruces. */
function untangle(items, leadOf, canSwap = () => true) {
  const crosses = (i, j) => segsCross(leadOf(items[i]), leadOf(items[j]));
  const count = (i) => items.reduce((n, _, j) => n + (j !== i && crosses(i, j) ? 1 : 0), 0);
  for (let it = 0; it < 60; it++) {
    let changed = false;
    for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
      if (!crosses(i, j) || !canSwap(items[i], items[j])) continue;
      const before = count(i) + count(j);
      [items[i].pos, items[j].pos] = [items[j].pos, items[i].pos];
      if (count(i) + count(j) < before) changed = true; else [items[i].pos, items[j].pos] = [items[j].pos, items[i].pos];
    }
    if (!changed) break;
  }
}
const segCircleHit = (sg, c, r) => {
  const [x0, y0, x1, y1] = sg, dx = x1 - x0, dy = y1 - y0, L2 = dx * dx + dy * dy;
  const t = L2 ? Math.max(0, Math.min(1, ((c[0] - x0) * dx + (c[1] - y0) * dy) / L2)) : 0;
  return Math.hypot(x0 + t * dx - c[0], y0 + t * dy - c[1]) < r;
};

/**
 * Globos de posición alrededor de una vista. Cada globo se coloca de forma voraz en la posición candidata de
 * menor coste: sin pisar textos, cotas, otros globos ni la geometría, con la línea de referencia sin cruzar
 * textos ni otras referencias y lo más corta posible. Los candidatos están en anillos alrededor de la vista,
 * con preferencia por los lados indicados. Al final se intercambian globos cuyas referencias se crucen.
 */
function balloons(d, v, targets, opts = {}) {
  const r = opts.r ?? 4, sides = opts.sides ?? ["top", "right", "left", "bottom"], region = opts.region ?? AREA;
  const pts = targets.map(([l, p]) => [l, v.at(p)]);
  if (!pts.length) return;
  const [bx0, by0, bx1, by1] = v.box, cx = (bx0 + bx1) / 2, cy = (by0 + by1) / 2;
  const ang = (p) => { const a = Math.atan2(p[1] - cy, p[0] - cx); return (Math.PI * 2.75 - a) % (Math.PI * 2); };
  pts.sort((a, b) => ang(a[1]) - ang(b[1]));
  const ring0 = opts.ring0 ?? 10, step = 2 * r + 1.6;
  const leadOf = (c, t) => { const dx = t[0] - c[0], dy = t[1] - c[1], L = Math.hypot(dx, dy) || 1; return [c[0] + (dx / L) * r, c[1] + (dy / L) * r, t[0], t[1]]; };
  const placed = [];
  for (const [l, t] of pts) {
    let best = null;
    const cands = [];
    sides.forEach((side, si) => {
      for (let o = 0; o < 6; o++) {
        const off = ring0 + o * (2 * r + 2);
        for (let k = -12; k <= 12; k++) {
          let c;
          if (side === "top") c = [Math.min(bx1 + off, Math.max(bx0 - off, t[0])) + k * step, by1 + off];
          else if (side === "bottom") c = [Math.min(bx1 + off, Math.max(bx0 - off, t[0])) + k * step, by0 - off];
          else if (side === "right") c = [bx1 + off, Math.min(by1 + off, Math.max(by0 - off, t[1])) + k * step];
          else c = [bx0 - off, Math.min(by1 + off, Math.max(by0 - off, t[1])) + k * step];
          cands.push([c, o * 0.6 + si * 1.5 + Math.abs(k) * 0.08]);
        }
      }
    });
    // huecos libres cerca de la propia pieza (dentro del contorno de la vista si no pisan geometría)
    if (opts.near !== false) for (const dist of [10, 13, 17, 22, 28]) for (let q = 0; q < 16; q++) {
      const a = (q * Math.PI) / 8 + 0.2;
      cands.push([[t[0] + dist * Math.cos(a), t[1] + dist * Math.sin(a)], 0.3]);
    }
    {
      for (const [c, pref] of cands) {
        {
          const lead = leadOf(c, t), dist = Math.hypot(t[0] - c[0], t[1] - c[1]);
          let cost = d.occ.circleCost(c, r, { region }) * 10 + d.occ.leaderCost(lead) * 6;
          const bb = [c[0] - r, c[1] - r, c[0] + r, c[1] + r];
          for (const f of d.page.forbid) if (boxesOverlap(bb, f, -1)) cost += 500;
          for (const [, t2] of pts) if (t2 !== t && Math.hypot(t2[0] - c[0], t2[1] - c[1]) < r + 1.5) cost += 300;   // no tapar puntos señalados
          for (const q of placed) {
            if (Math.hypot(q.pos[0] - c[0], q.pos[1] - c[1]) < 2 * r + 1.4) cost += 1000;
            const ql = leadOf(q.pos, q.t);
            if (segsCross(lead, ql)) cost += 30;
            if (segCircleHit(lead, q.pos, r + 0.5) || segCircleHit(ql, c, r + 0.5)) cost += 300;
          }
          cost += dist * 0.05 + pref;
          if (!best || cost < best.cost) best = { cost, c };
        }
      }
    }
    placed.push({ l, t, pos: best.c });
  }
  untangle(placed, (q) => leadOf(q.pos, q.t), (a, b) => {
    // el intercambio no debe hacer que una referencia atraviese textos o globos
    const la = leadOf(b.pos, a.t), lb = leadOf(a.pos, b.t);
    return d.occ.leaderCost(la) <= d.occ.leaderCost(leadOf(a.pos, a.t)) + 1 && d.occ.leaderCost(lb) <= d.occ.leaderCost(leadOf(b.pos, b.t)) + 1
      && !segCircleHit(la, a.pos, r + 0.5) && !segCircleHit(lb, b.pos, r + 0.5)
      && !placed.some((q) => q !== a && q !== b && (segCircleHit(la, q.pos, r + 0.5) || segCircleHit(lb, q.pos, r + 0.5)));
  });
  for (const q of placed) d.balloon(q.pos, q.t, q.l, r);
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
/** Nota de altura según el tipo de apoyo (pies niveladores regulables o ruedas). */
function supportLine(m) {
  const sup = m.structure.supports?.[0];
  if (!sup) return "";
  const c = C.component(sup.component);
  if (c.category.startsWith("ruedas")) return `Altura sobre ruedas Ø${fmt(c.wheel_d)} mm (altura de rueda ${fmt(c.nominal_height)} mm, sin regulación).`;
  return `Altura con pies niveladores en posición nominal (regulación ±${fmt(c.adjust / 2)} mm).`;
}

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
    d.dimChain(false, zs.map((z) => a.at([0, 0, z])[1]), zs.slice(1).map((z, k) => z - zs[k]), xl, xl - 9, zs.slice(1).map((_, k) => `DIST_NIVEL_${k + 1}`));
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
    `Estado de verificación: ${X.eng.status_label}`, supportLine(m),
    `Acabado: ${C.finish(ps.ACABADO).name}`];
  d.flushLabels();
  const cands = [];
  for (let k = 0; k < 40; k++) cands.push([32, pl.oy - 14 - k * 2, 190]);
  const xr = pl.ox + pl.w + 24, wr = Math.max(60, 222 - pl.ox - pl.w - 24);
  for (let k = 0; k < 40; k++) cands.push([xr, Math.min(pl.oy + pl.h, 140) - k * 2, wr]);
  d.placeNotes(lines, cands, 2.6, 190);
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
  const lower = Object.keys(lv).filter((k) => k !== "SUP").map((k) => [instanceBBox(X.inst(lv[k].long[0]))[1][2], k]).sort((u, w) => u[0] - w[0]);
  d.dimV(yb, yz, a.ox, a.ox, a.ox - (lower.length ? 17 : 9), hi[2] - lo[2], "EST_ALTURA");
  if (lower.length === 1) { const [z, k] = lower[0]; const [, yr] = a.at([0, 0, z]); d.dimV(yb, yr, a.ox, a.ox, a.ox - 9, z - lo[2], `COTA_BASTIDOR_${k}`); }
  else if (lower.length) {
    const zs = [lo[2], ...lower.map((l) => l[0])];
    d.dimChain(false, zs.map((z) => a.at([0, 0, z])[1]), zs.slice(1).map((z, k) => z - zs[k]), a.ox, a.ox - 9);
  }
  const top = lv.SUP, ids = [top.end[0], ...top.int, top.end[1]];
  const xs = ids.map((i) => { const [l, h] = instanceBBox(X.inst(i)); return (l[0] + h[0]) / 2; });
  d.dimChain(true, xs.map((x) => pl.at([x, lo[1], 0])[0]), xs.slice(1).map((x, k) => x - xs[k]), pl.at([0, lo[1], 0])[1], pl.oy - 9,
    xs.slice(1).map((_, k) => `PASO_TRAVESANO_${k + 1}`));
  d.dimV(pl.at([0, lo[1], 0])[1], pl.at([0, hi[1], 0])[1], pl.ox, pl.ox, pl.ox - 9, hi[1] - lo[1], "EST_ANCHURA");
  const yL2 = instanceBBox(legs[2])[1][1], yL0 = instanceBBox(legs[0])[0][1];
  const [pu0, pzt] = p.at([0, yL2, hi[2]]), [pu1] = p.at([0, yL0, hi[2]]);
  d.dimH(pu0, pu1, pzt, pzt, pzt + 9, yL2 - yL0);
  d.flushLabels();
  const nl = ["Estructura soldada (subconjunto EST).", `Clase de ejecución ${m.params.values.CLASE_EJECUCION} según EN 1090-2.`, "Cotas a caras exteriores de perfil.",
    "Planitud del plano de apoyo de encimera: EN ISO 13920 clase F.", "Detalle de uniones soldadas: plano 05.", "Longitudes de corte y mecanizados: plano 02B."];
  const nc = [];
  for (let k = 0; k < 30; k++) nc.push([305, 268 - k * 3, 100]);
  for (let k = 0; k < 30; k++) nc.push([Math.max(p.ox + p.w + 14, 230), 268 - k * 3, 400 - Math.max(p.ox + p.w + 14, 230)]);
  d.placeNotes(nl, nc, 2.6, 100);
  const reps = new Map();
  for (const i of est) if (i.part.kind === "perfil" && !reps.has(i.part.key)) reps.set(i.part.key, i);
  balloons(d, a, [...reps.values()].map((i) => [String(i.part.pos), instanceCentroid(i)]), { sides: ["top", "left", "right", "bottom"] });
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
      const x = 40, W = y < 86 ? 110 : 180, k = W / c.bar_length;
      d.polyline([[x, y], [x + W, y], [x + W, y + 3.5], [x, y + 3.5]], LW_THIN, null, BLACK, true);
      let xx = x + c.trim * k;
      for (const cut of b.cuts) {
        const ww = cut.length * k;
        d.rect(xx, y, ww, 3.5, LW_THIN, [0.82, 0.86, 0.9]);
        if (ww > 9) d.text(xx + ww / 2, y + 0.9, cut.ref.split("-").at(-1), 2.0, "c");
        xx += ww + c.kerf * k;
      }
      d.text(x + W + 3, y + 0.6, fitText(`Barra ${b.bar}: retal ${fmt(b.remnant)} mm${b.remnant_reusable ? " (aprovechable)" : ""}`, (y < 86 ? 224 : 400) - x - W - 3, 2.2), 2.2);
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
    d.group("geom", () => { d.polyline(prof, LW_THICK); d.line(Q(R + 15, 0), Q(R + 15, -t), LW_THIN, [1.5, 1]); });
    d.dimV(Q(0, -hf)[1], Q(0, 0)[1], Q(0, 0)[0], Q(0, 0)[0], Q(0, 0)[0] - 7, hf, `${part.ref}_ALA_SECCION`, "seccion");
    d.dimH(Q(0, -hf)[0], Q(t, -hf)[0], Q(0, -hf)[1], Q(0, -hf)[1], Q(0, -hf)[1] - 4, t, `${part.ref}_ESPESOR`, "seccion");
    // radio interior: texto en el hueco interior del pliegue con línea de referencia al arco interior
    const c45 = Math.SQRT1_2, arcP = Q(R - r * c45, -R + r * c45), ri = `Ri ${fmt(r)}`;
    const rc = [];
    for (const dy of [5, 8, 11, 14, 18]) for (const dx of [5, 9, 14, 20]) rc.push([arcP[0] + dx, arcP[1] - dy, "l"]);
    const rb = d.group("dim", () => d.placeText(ri, 2.6, rc));
    if (rb) d.group("leader", () => { d.line([rb.box[0] - 0.6, rb.box[3] - 0.6], arcP, LW_DIM); d.arrow(arcP, [arcP[0] - rb.box[0], arcP[1] - rb.box[3]], 2.0); });
    const tc = [];
    for (let k = 0; k < 10; k++) tc.push([(rect[0] + rect[2]) / 2, rect[1] - 6 - k * 2, "c"]);
    const tb = d.group("label", () => d.placeText(`SECCIÓN A-A (E ${scaleLabel(sc)})`, 3.0, tc, { bold: true }));
    const y0n = (tb ? tb.box[1] : rect[1] - 8) - 5;
    const sl = [`Espesor t = ${fmt(t)} mm · Ri = ${fmt(r)} mm · K = ${spec.K.toFixed(3)}`, `Pliegues a 90° hacia ${f0.direction === "up" ? "arriba" : "abajo"} · BD = ${fmt(spec.BD, 3)} mm`];
    d.placeNotes(sl, Array.from({ length: 8 }, (_, k) => [rect[0], y0n - k * 2, 105]), 2.6, 105);
  }
  const holes = spec.flanges.reduce((s2, f) => s2 + f.holes.length, 0) + (spec.holes?.length ?? 0);
  d.flushLabels();
  d.placeNotes([`Referencia: ${part.ref}`, `Material: ${C.material(part.material).name}`, `Masa (desde sólido): ${part.mass.toFixed(2)} kg`,
    `Taladros: ${holes} uds — posiciones en desarrollo (plano 04) y DXF`, `Acabado: ${part.finish ? C.finish(part.finish).name : "—"}`, "Rebabas eliminadas. Aristas vivas matadas 0,5 mm."],
    Array.from({ length: 40 }, (_, k) => [296, 150 - k * 1.5, 105]), 2.6, 105);
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
    const horiz = Math.abs(p1[1] - p0[1]) < 1e-6, bc = [];
    for (const f of [0.5, 0.35, 0.65, 0.2, 0.8]) {
      const q = [p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f];
      if (horiz) bc.push([q[0], q[1] + 1.0, "c", 0], [q[0], q[1] - 3.6, "c", 0]); else bc.push([q[0] - 1.0, q[1], "c", 90], [q[0] + 3.6, q[1], "c", 90]);
    }
    // a continuación de los extremos de la línea de plegado (fuera de la chapa) cuando no cabe junto a ella
    if (horiz) for (const gx of [3, 8, 14]) bc.push([ox + w * k + gx, p0[1] - 1.1, "l", 0], [ox - gx, p0[1] - 1.1, "r", 0]);
    else for (const gy of [3, 8, 14]) bc.push([p0[0] + 1.1, oy + h * k + gy, "l", 90], [p0[0] + 1.1, oy - gy, "r", 90]);
    d.group("note", () => d.placeText(`${b.direction} 90° Ri${fmt(b.radius)}`, 2.2, bc, { color: GREY }));
    if (horiz) ys.push(b.p0[1]); else xs.push(b.p0[0]);
  }
  d.dimH(P(0, 0)[0], P(w, 0)[0], oy, oy, oy - 14, w, `${part.ref}_DESARROLLO_X`, "desarrollo");
  d.dimV(P(0, 0)[1], P(0, h)[1], ox, ox, ox - 14, h, `${part.ref}_DESARROLLO_Y`, "desarrollo");
  let chain = [0, ...xs.sort((a, b) => a - b), w];
  d.dimChain(true, chain.map((c) => P(c, 0)[0]), chain.slice(1).map((c, i) => c - chain[i]), oy, oy - 7);
  chain = [0, ...ys.sort((a, b) => a - b), h];
  d.dimChain(false, chain.map((c) => P(0, c)[1]), chain.slice(1).map((c, i) => c - chain[i]), ox, ox - 7);
  const spec = part.spec;
  // perforaciones regulares (paneles): se acotan como patrón; en la tabla sólo los taladros sueltos
  const rects = fp.holes.filter((h) => h.kind === "rect");
  let listed = fp.holes, grid = null;
  if (rects.length > 24) {
    listed = fp.holes.filter((h) => h.kind !== "rect");
    const xs = [...new Set(rects.map((h) => Math.round(h.x * 1000) / 1000))].sort((a, b) => a - b);
    const ys = [...new Set(rects.map((h) => Math.round(h.y * 1000) / 1000))].sort((a, b) => a - b);
    grid = `Perforación □${fmt(rects[0].w)}x${fmt(rects[0].h)}: ${xs.length} × ${ys.length} = ${rects.length} agujeros a paso ${fmt(xs[1] - xs[0], 1)} × ${fmt(ys[1] - ys[0], 1)} mm; `
      + `primer agujero (centro) en X ${fmt(xs[0], 2)} · Y ${fmt(ys[0], 2)} desde el origen del desarrollo.`;
  }
  const rows = listed.slice(0, 24).map((ho, n) => [n + 1, Math.round(ho.x * 100) / 100, Math.round(ho.y * 100) / 100, ho.kind === "round" ? `Ø${fmt(ho.d)}` : `□${fmt(ho.w)}x${fmt(ho.h)}`]);
  const cols = [["Nº", 10, "c"], ["X", 22, "r"], ["Y", 22, "r"], ["Forma", 22, "c"]];
  for (let c = 0; c < 2 && rows.length > c * 12; c++) d.table(40 + c * 82, 86, cols, rows.slice(c * 12, c * 12 + 12), 4.4, 6, 2.2);
  const more = listed.length > 24 ? [`Taladros 25 a ${listed.length}: posiciones en el fichero DXF de corte.`] : [];
  d.placeNotes([`Desarrollo plano de ${part.ref} — origen en la esquina inferior izquierda · espesor ${fmt(spec.t)} mm · Ri ${fmt(spec.r)} mm · K ${spec.K.toFixed(3)} (DIN 6935) · `
    + `BA = π/2·(Ri+K·t) = ${fmt(spec.BA, 3)} mm · BD = ${fmt(spec.BD, 3)} mm.`,
  `Contorno neto ${fmt(fp.netArea / 1e6, 4)} m² · longitud de corte ${fmt(fp.cutLength / 1000, 2)} m · fichero de corte 03_DXF_CORTE/${part.ref}.dxf (escala 1:1, mm) · tolerancias EN ISO 9013 clase 2.`,
  ...(grid ? [grid] : []), ...more], [[32, 268, 370], [32, 280, 370]], 2.6, 370);
}

function planPlates(d, X, number) {
  const plates = Object.values(X.m.parts).filter((p) => p.kind === "pletina").sort((a, b) => a.pos - b.pos);
  if (!plates.length) return;
  // escala y disposición en filas: la mayor escala normalizada con la que caben todas (con hueco para cotas y rótulos)
  const region = [44, 92, 400, 266];
  const layout = (k) => {
    const pos = [];
    let x = region[0], yTop = region[3], rowH = 0;
    for (const p of plates) {
      const w = p.w * k, h = p.h * k;
      if (x + w > region[2] && x > region[0]) { x = region[0]; yTop -= rowH + 34; rowH = 0; }
      pos.push([x, yTop - 16 - h]);
      x += Math.max(w, 70) + 40; rowH = Math.max(rowH, h + 16);
    }
    return pos.every(([px, py], i) => py - 16 >= region[1] && px + plates[i].w * k <= region[2]) ? pos : null;
  };
  let sc = SCALES.at(-1), pos = null;
  for (const s2 of [[2, 1], ...SCALES]) { const q = layout(s2[0] / s2[1]); if (q) { sc = s2; pos = q; break; } }
  if (!pos) pos = layout(sc[0] / sc[1]) ?? plates.map((_, i) => [region[0] + i * 60, 150]);
  const k = sc[0] / sc[1];
  d.newSheet(number, "Pletinas cortadas por láser", scaleLabel(sc), [...new Set(plates.map((p) => p.material))].sort().join(", "));
  plates.forEach((p, i) => {
    const [x, y] = pos[i], r = p.corner_r;
    const pts = [];
    for (const [cx, cy, a0] of [[p.w - r, r, -90], [p.w - r, p.h - r, 0], [r, p.h - r, 90], [r, r, 180]])
      for (let j = 0; j <= 8; j++) { const an = ((a0 + (90 * j) / 8) * Math.PI) / 180; pts.push([x + (cx + r * Math.cos(an)) * k, y + (cy + r * Math.sin(an)) * k]); }
    d.group("geom", () => d.polyline(pts, LW_THICK, null, BLACK, true));
    for (const [hx, hy, hd] of p.holes) {
      const cx = x + hx * k, cy = y + hy * k;
      d.group("geom", () => {
        d.circle(cx, cy, (hd / 2) * k);
        // ejes del taladro: sobresalen 2 mm del círculo (sin invadir rótulos ni piezas vecinas)
        const ext = (hd * k) / 2 + 2;
        d.line([cx - ext, cy], [cx + ext, cy], LW_THIN, [3, 1, 1, 1]); d.line([cx, cy - ext], [cx, cy + ext], LW_THIN, [3, 1, 1, 1]);
      });
      const rr = (hd * k) / 2, hc = [];
      for (const g of [2, 5, 9]) hc.push([cx + rr + g, cy + rr + g * 0.6], [cx + rr + g, cy - rr - 3.6 - g * 0.6], [cx - rr - g, cy + rr + g * 0.6, "r"], [cx - rr - g, cy - rr - 3.6 - g * 0.6, "r"]);
      d.group("note", () => d.placeText(`Ø${fmt(hd)}`, 2.8, hc));
    }
    d.dimH(x, x + p.w * k, y, y, y - 9, p.w, `${p.ref}_W`, "geometria_pieza");
    d.dimV(y, y + p.h * k, x, x, x - 9, p.h, `${p.ref}_H`, "geometria_pieza");
    d.group("label", () => {
      d.text(x, y + p.h * k + 11, `Pos. ${p.pos} — ${p.ref}`, 3.0, "l", 0, true);
      d.text(x, y + p.h * k + 6, fitText(`${p.name} · ${p.material} e=${fmt(p.t)} · R${fmt(p.corner_r)}`, 100, 2.6), 2.6);
    });
  });
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
  d.group("frame", () => d.rect(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1], 0.3));
  d.group("label", () => d.text(rect[0] + 3, rect[3] - 5, `${title} (E ${scaleLabel(sc)})`, 2.8, "l", 0, true));
  placeWeld(d, v.P(...c), joint.weld, [rect[0] + 1, rect[1] + 1, rect[2] - 1, rect[3] - 7], null);
}

/** Coloca símbolos de soldadura [{ tgt, weld, tag }] en posiciones libres de `region`, sin cruces entre sus flechas. */
function placeWelds(d, items, region, opts = {}) {
  const placed = [];
  for (const it of items) {
    const { tgt, weld, tag } = it;
    let best = null;
    const tryBase = (base, side, pref) => {
      const box = d.weldBox(base, weld.a, null, "135", side, tag);
      const lead = [base[0], base[1], tgt[0], tgt[1]], L = Math.hypot(tgt[0] - base[0], tgt[1] - base[1]);
      if (L < 6) return;
      let cost = d.boxCost(box, { region }) * 10 + d.occ.leaderCost(lead) * 6 + L * 0.05 + pref
        + (opts.view && boxesOverlap(box, opts.view, 0) ? 2 : 0)
        + d.occ.segsIn([Math.min(lead[0], lead[2]), Math.min(lead[1], lead[3]), Math.max(lead[0], lead[2]), Math.max(lead[1], lead[3])], ["geom"]).filter((q) => segsCross(lead, q.seg)).length * 0.4;
      for (const q of placed) {
        if (boxesOverlap(box, q.box, -0.8)) cost += 1000;
        if (segsCross(lead, [q.pos[0], q.pos[1], q.tgt[0], q.tgt[1]])) cost += 80;
        if (segHitsBox(lead, q.box) || segHitsBox([q.pos[0], q.pos[1], q.tgt[0], q.tgt[1]], box)) cost += 300;
      }
      if (!best || cost < best.cost) best = { cost, base, side, box };
    };
    const cols = opts.cols ?? [[region[0] + 8, -1], [region[2] - 8, 1]];
    for (let y = region[1] + 4; y <= region[3] - 5; y += 3.25) {
      for (const [x, side] of cols) tryBase([x, y], side, 0);
      for (const dx of [10, 16, 24, 32]) for (const side of [1, -1]) tryBase([tgt[0] + dx * side, y], side, 2);
    }
    if (best) placed.push({ ...it, pos: best.base, side: best.side, box: best.box });
  }
  for (const q of placed) q.pos = { p: q.pos, side: q.side };
  const boxOf = (q) => d.weldBox(q.pos.p, q.weld.a, null, "135", q.pos.side, q.tag);
  untangle(placed, (q) => [q.pos.p[0], q.pos.p[1], q.tgt[0], q.tgt[1]], (a, b) => {
    const la = [b.pos.p[0], b.pos.p[1], a.tgt[0], a.tgt[1]], lb = [a.pos.p[0], a.pos.p[1], b.tgt[0], b.tgt[1]];
    const ba = d.weldBox(b.pos.p, a.weld.a, null, "135", b.pos.side, a.tag), bb = d.weldBox(a.pos.p, b.weld.a, null, "135", a.pos.side, b.tag);
    return d.occ.leaderCost(la) + d.occ.leaderCost(lb) <= d.occ.leaderCost([a.pos.p[0], a.pos.p[1], a.tgt[0], a.tgt[1]]) + d.occ.leaderCost([b.pos.p[0], b.pos.p[1], b.tgt[0], b.tgt[1]])
      && d.boxCost(ba, { region }) + d.boxCost(bb, { region }) <= d.boxCost(boxOf(a), { region }) + d.boxCost(boxOf(b), { region })
      && !placed.some((q) => q !== a && q !== b && (segHitsBox(la, boxOf(q)) || segHitsBox(lb, boxOf(q))));
  });
  for (const q of placed) d.weldSymbol(q.tgt, q.pos.p, q.weld.a, q.weld.all_around ?? true, "135", null, q.pos.side, q.tag);
}
function placeWeld(d, tgt, weld, region, tag, opts = {}) { placeWelds(d, [{ tgt, weld, tag }], region, opts); }

function planWelds(d, X) {
  const m = X.m, est = X.group("EST");
  const proj = X.proj("est", est, "alzado", false);
  const [s, v] = fitView(proj, "alzado", [80, 152, 250, 278]);
  d.newSheet("05", "Uniones soldadas: símbolos, detalles y secuencia", scaleLabel(s), m.params.values.MATERIAL_ESTRUCTURAL);
  v.label = "ALZADO DE LA ESTRUCTURA"; v.labelOffset = 8;
  d.drawView(v, false);
  const groups = new Map();
  for (const j of m.joints) if (j.kind === "soldadura") { if (!groups.has(j.description)) groups.set(j.description, []); groups.get(j.description).push(j); }
  const rows = [];
  const region = [24, 146, 296, 284];
  const cols = [[Math.max(region[0] + 44, v.ox - 5), -1], [Math.min(region[2] - 44, v.ox + v.w + 5), 1]];
  const items = [], used = [];
  const edge = (p) => Math.min(p[0] - v.ox, v.ox + v.w - p[0]);
  [...groups.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1)).forEach(([desc, js], n0) => {
    const n = n0 + 1, j = js[0];
    // unión representativa: la más cercana al contorno de la vista cuyo punto no esté ya señalado por otro símbolo
    const near = (p) => used.some((u) => Math.hypot(u[0] - p[0], u[1] - p[1]) < 3);
    const cand = js.map((q) => v.at(q.location)).sort((a, b) => (near(a) - near(b)) || edge(a) - edge(b));
    let tgt = cand[0];
    for (let k = 1; near(tgt) && k < 8; k++) tgt = [cand[0][0], cand[0][1] + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 3];
    used.push(tgt);
    items.push({ tgt, weld: j.weld, tag: `(${n})` });
    const L = j.weld.length;
    rows.push([n, desc, `a${fmt(j.weld.a)}`, j.weld.all_around ? "perimetral" : "3 cordones", fmt(L), js.length, fmt(L * js.length), j.weld.process ?? "135"]);
  });
  placeWelds(d, items, region, { cols, view: v.box });
  d.flushLabels();
  d.table(32, 140, [["Nº", 8, "c"], ["Unión", 76, "l"], ["Garganta", 19, "c"], ["Tipo", 19, "c"], ["L unit. mm", 18, "r"], ["Uds", 9, "c"], ["L total mm", 19, "r"], ["Proceso", 22, "c"]], rows, 4.4, 6, 2.2);
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
  // dos zonas posibles fuera de la tabla de piezas y del cuadro de rotulación: se elige la de mayor escala
  let s = null, v = null;
  for (const r of [[40, 92, 292, 262], [40, 30, 220, 262]]) {
    const [s2, v2] = fitView(proj, "iso", r, [...SCALES, [1, 200]]);
    if (!v || v2.scale > v.scale) [s, v] = [s2, v2];
  }
  d.newSheet("06", "Vista explosionada", scaleLabel(s), "Ver despiece");
  v.label = "PERSPECTIVA ISOMÉTRICA EXPLOSIONADA";
  d.drawView(v, false, 0.3);
  d.flushLabels();
  const ty = d.table(300, 262, [["Pos", 9, "c"], ["Ref", 10, "c"], ["Descripción", 70, "l"], ["Cant", 11, "c"]],
    X.bom.rows.map((r) => [r.pos, r.kind !== "normalizado" ? r.ref.split("-").at(-1) : "N", r.description, r.qty]), 4.6, 6, 2.2);
  d.reserve([298, ty - 2, 402, 264]);
  balloons(d, v, partTargets(X, m.instances, true), { region: [24, 12, 296, 285] });
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

/** Auditoría de legibilidad de todas las hojas (después de terminar el documento). Libera el registro de ocupación. */
function layoutReport(d) {
  const sheets = d.pages.map((p) => ({ number: p.number, title: p.title, conflicts: auditPage(p.occ, { titleBlock: TB_BOX }) }));
  for (const p of d.pages) delete p.occ;
  const all = sheets.flatMap((s) => s.conflicts);
  return { total: all.length, by: summarize(all),
    sheets: sheets.filter((s) => s.conflicts.length).map((s) => ({ number: s.number, title: s.title, by: summarize(s.conflicts), sample: s.conflicts.slice(0, 10) })) };
}

/** Juego completo de planos. Devuelve { pdf: Uint8Array, sheets, total, layout }. */
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
  const pdf = await d.finish();
  const layout = layoutReport(d);
  return { pdf, sheets: d.pages, total: d.pages.length, ctx: X, layout };
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
  d.flushLabels();
  d.group("frame", () => d.rect(284, 84, 124, 190, 0.3));
  d.reserve([283, 83, 409, 275]);
  balloons(d, v0, partTargets(X, m.instances, true), { region: [24, 84, 280, 285] });
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
  const pdf = await d.finish();
  return { pdf, sheets: d.pages, total: d.pages.length, layout: layoutReport(d) };
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
