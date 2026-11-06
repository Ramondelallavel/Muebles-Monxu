// @ts-nocheck
// Ocupación de la hoja y auditoría de legibilidad de los planos.
//
// Cada primitiva que se dibuja (texto, segmento, círculo) queda registrada con su categoría:
//   geom / hidden  geometría de las vistas (líneas vistas / ocultas)
//   dim            líneas de cota, de referencia de cota y flechas
//   leader         líneas de referencia de globos y de símbolos de soldadura
//   sym            círculos de globos y trazos de símbolos
//   table, tb, frame  tablas, cuadro de rotulación y marco
// Los textos guardan su caja (mm) calculada con las métricas reales de Helvetica.
// El mismo registro sirve para colocar textos y globos en huecos libres mientras se dibuja
// y para auditar después la hoja completa (solapes texto-texto, texto-línea, globos, márgenes).

const CELL = 8;

/** Caja de un texto con altura de mayúsculas h: incluye descendentes (0,22·h) y acentos (0,18·h). */
export function textBox(x, y, w, h, angle = 0) {
  const lo = -0.22 * h, hi = 1.18 * h;
  if (Math.abs(angle) < 1e-9) return [x, y + lo, x + w, y + hi];
  const a = (angle * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  const pts = [[0, lo], [w, lo], [w, hi], [0, hi]].map(([u, v]) => [x + u * c - v * s, y + u * s + v * c]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
export const boxesOverlap = (a, b, pad = 0) => a[0] + pad < b[2] - pad && b[0] + pad < a[2] - pad && a[1] + pad < b[3] - pad && b[1] + pad < a[3] - pad;
const grow = (b, p) => [b[0] - p, b[1] - p, b[2] + p, b[3] + p];

/** ¿El segmento atraviesa la caja? (Liang-Barsky) */
export function segHitsBox(s, b) {
  let [x0, y0, x1, y1] = s, t0 = 0, t1 = 1;
  const dx = x1 - x0, dy = y1 - y0;
  for (const [p, q] of [[-dx, x0 - b[0]], [dx, b[2] - x0], [-dy, y0 - b[1]], [dy, b[3] - y0]]) {
    if (Math.abs(p) < 1e-12) { if (q < 0) return false; continue; }
    const r = q / p;
    if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r; } else { if (r < t0) return false; if (r < t1) t1 = r; }
  }
  return t1 - t0 > 1e-9;
}
/** ¿El círculo (borde o interior) toca la caja? */
export function circleHitsBox(c, r, b) {
  const qx = Math.max(b[0], Math.min(c[0], b[2])), qy = Math.max(b[1], Math.min(c[1], b[3]));
  return Math.hypot(qx - c[0], qy - c[1]) < r;
}
/** Cruce propio entre dos segmentos (sin contar extremos compartidos). */
export function segsCross(a, b) {
  const d = (p, q, r) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const p1 = [a[0], a[1]], p2 = [a[2], a[3]], p3 = [b[0], b[1]], p4 = [b[2], b[3]];
  const d1 = d(p3, p4, p1), d2 = d(p3, p4, p2), d3 = d(p1, p2, p3), d4 = d(p1, p2, p4);
  const eps = 1e-6;
  return ((d1 > eps && d2 < -eps) || (d1 < -eps && d2 > eps)) && ((d3 > eps && d4 < -eps) || (d3 < -eps && d4 > eps));
}
function segCircle(s, c, r) {
  const [x0, y0, x1, y1] = s, dx = x1 - x0, dy = y1 - y0, L2 = dx * dx + dy * dy;
  const t = L2 ? Math.max(0, Math.min(1, ((c[0] - x0) * dx + (c[1] - y0) * dy) / L2)) : 0;
  return Math.hypot(x0 + t * dx - c[0], y0 + t * dy - c[1]) < r;
}

export class Occupancy {
  constructor() { this.texts = []; this.segs = []; this.circles = []; this.grid = new Map(); this.gid = 0; }
  _cells(b, fn) {
    const i0 = Math.floor(b[0] / CELL), i1 = Math.floor(b[2] / CELL), j0 = Math.floor(b[1] / CELL), j1 = Math.floor(b[3] / CELL);
    for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) fn(i * 4096 + j);
  }
  addText(box, cat, s, gid) { this.texts.push({ box, cat, s, gid }); }
  addSeg(seg, cat, gid) {
    const k = this.segs.length;
    this.segs.push({ seg, cat, gid });
    const b = [Math.min(seg[0], seg[2]), Math.min(seg[1], seg[3]), Math.max(seg[0], seg[2]), Math.max(seg[1], seg[3])];
    this._cells(b, (c) => { let l = this.grid.get(c); if (!l) this.grid.set(c, (l = [])); l.push(k); });
  }
  addCircle(c, r, cat, gid) { this.circles.push({ c, r, cat, gid }); }
  /** Segmentos registrados que atraviesan la caja (categorías opcionales). */
  segsIn(box, cats = null) {
    const seen = new Set(), out = [];
    this._cells(box, (c) => {
      for (const k of this.grid.get(c) ?? []) {
        if (seen.has(k)) continue;
        seen.add(k);
        const s = this.segs[k];
        if ((!cats || cats.includes(s.cat)) && segHitsBox(s.seg, box)) out.push(s);
      }
    });
    return out;
  }
  /** Número de conflictos que tendría una caja de texto en esa posición. */
  cost(box, { pad = 0.35, cats = null, ignoreGid = null, region = null } = {}) {
    let n = 0;
    const inner = grow(box, -pad);
    if (region && !(box[0] >= region[0] && box[1] >= region[1] && box[2] <= region[2] && box[3] <= region[3])) n += 50;
    for (const t of this.texts) if (t.gid !== ignoreGid && boxesOverlap(t.box, box, -0.6)) n += 10;
    for (const s of this.segsIn(inner, cats)) if (s.gid !== ignoreGid) n += s.cat === "hidden" ? 1 : 3;
    for (const c of this.circles) if (c.gid !== ignoreGid && circleHitsBox(c.c, c.r + 0.6, box)) n += 10;
    return n;
  }
  /** Coste de un círculo (globo) en esa posición. */
  circleCost(c, r, { region = null, gap = 1.2 } = {}) {
    let n = 0;
    const b = [c[0] - r, c[1] - r, c[0] + r, c[1] + r];
    if (region && !(b[0] >= region[0] && b[1] >= region[1] && b[2] <= region[2] && b[3] <= region[3])) n += 50;
    for (const t of this.texts) if (circleHitsBox(c, r + gap, t.box)) n += 10;
    for (const o of this.circles) if (Math.hypot(o.c[0] - c[0], o.c[1] - c[1]) < o.r + r + gap) n += 10;
    for (const s of this.segsIn(grow(b, gap))) if (segCircle(s.seg, c, r + gap)) n += s.cat === "hidden" ? 1 : s.cat === "geom" ? 4 : 3;
    return n;
  }
  /** Coste de una línea de referencia: atravesar textos, globos u otras líneas de referencia. */
  leaderCost(seg, { skipCircle = null } = {}) {
    let n = 0;
    for (const t of this.texts) if (segHitsBox(seg, grow(t.box, 0.3))) n += 10;
    for (const o of this.circles) if (o !== skipCircle && segCircle(seg, o.c, o.r + 0.4)) n += 10;
    const b = [Math.min(seg[0], seg[2]), Math.min(seg[1], seg[3]), Math.max(seg[0], seg[2]), Math.max(seg[1], seg[3])];
    for (const s of this.segsIn(grow(b, 0.1), ["leader", "dim"])) if (segsCross(seg, s.seg)) n += s.cat === "leader" ? 6 : 1;
    return n;
  }
}

/**
 * Auditoría de una hoja: devuelve la lista de conflictos de legibilidad.
 *   texto-texto         dos textos se pisan
 *   texto-linea         una línea (de cualquier tipo) atraviesa un texto
 *   globo               un globo pisa un texto, otro globo o una línea que no es la suya
 *   referencias-cruzadas  dos líneas de referencia se cruzan
 *   fuera-de-margen     texto fuera del marco o dentro del cuadro de rotulación sin pertenecer a él
 */
export function auditPage(occ, { frame = [20, 10, 410, 287], titleBlock = null } = {}) {
  const out = [];
  const T = occ.texts;
  for (let i = 0; i < T.length; i++) {
    const a = T[i];
    for (let j = i + 1; j < T.length; j++) {
      const b = T[j];
      if (boxesOverlap(a.box, b.box, 0.25)) out.push({ type: "texto-texto", a: a.s, b: b.s, at: a.box.map((v) => Math.round(v)) });
    }
    const inner = grow(a.box, -0.35);
    if (inner[2] > inner[0] && inner[3] > inner[1]) {
      const hits = occ.segsIn(inner);
      if (hits.length) out.push({ type: "texto-linea", a: a.s, b: [...new Set(hits.map((h) => h.cat))].join(","), n: hits.length, at: a.box.map((v) => Math.round(v)) });
    }
    if (a.cat !== "frame" && (a.box[0] < frame[0] || a.box[1] < frame[1] || a.box[2] > frame[2] || a.box[3] > frame[3]))
      out.push({ type: "fuera-de-margen", a: a.s, at: a.box.map((v) => Math.round(v)) });
    if (titleBlock && a.cat !== "tb" && boxesOverlap(a.box, titleBlock, 0)) out.push({ type: "fuera-de-margen", a: a.s, b: "cuadro de rotulación", at: a.box.map((v) => Math.round(v)) });
  }
  const C = occ.circles.filter((c) => c.cat === "balloon");
  for (let i = 0; i < C.length; i++) {
    const c = C[i];
    for (let j = i + 1; j < C.length; j++) if (Math.hypot(C[j].c[0] - c.c[0], C[j].c[1] - c.c[1]) < C[j].r + c.r + 0.3) out.push({ type: "globo", a: "globo", b: "globo", at: c.c.map(Math.round) });
    for (const t of T) if (t.gid !== c.gid && circleHitsBox(c.c, c.r + 0.2, t.box)) out.push({ type: "globo", a: "globo", b: t.s, at: c.c.map(Math.round) });
    const b = [c.c[0] - c.r, c.c[1] - c.r, c.c[0] + c.r, c.c[1] + c.r];
    const lines = occ.segsIn(b).filter((s) => s.gid !== c.gid && segCircle(s.seg, c.c, c.r - 0.2));
    if (lines.length) out.push({ type: "globo", a: "globo", b: [...new Set(lines.map((s) => s.cat))].join(","), at: c.c.map(Math.round) });
  }
  const L = occ.segs.filter((s) => s.cat === "leader");
  for (let i = 0; i < L.length; i++) for (let j = i + 1; j < L.length; j++)
    if (L[i].gid !== L[j].gid && segsCross(L[i].seg, L[j].seg)) out.push({ type: "referencias-cruzadas", at: L[i].seg.slice(0, 2).map(Math.round) });
  return out;
}

export function summarize(conflicts) {
  const by = {};
  for (const c of conflicts) by[c.type] = (by[c.type] ?? 0) + 1;
  return by;
}
