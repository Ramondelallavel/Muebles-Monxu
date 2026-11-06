// @ts-nocheck
// Geometría de visualización: mallas cerradas de cada pieza (perfil hueco, chapa plegada, pletina y normalizados),
// envolventes y centros de gravedad. Sustituye en el navegador a la teselación del B-rep de OpenCascade:
// los taladros no se representan en la malla (sí en piezas, BOM, DXF y cálculo).
import { ShapeUtils, Vector2 } from "three";
import * as C from "./catalog";
import { frame, tp } from "./model";

const SEG = 6;        // segmentos por cuarto de circunferencia
const CYL = 28;       // segmentos de cilindro

class MB {
  constructor() { this.p = []; this.i = []; }
  v(x, y, z) { this.p.push(x, y, z); return this.p.length / 3 - 1; }
  tri(a, b, c) { this.i.push(a, b, c); }
  quad(a, b, c, d) { this.i.push(a, b, c, a, c, d); }
  merge(o, T = null) {
    const off = this.p.length / 3;
    for (let k = 0; k < o.p.length; k += 3) {
      const q = T ? tp(T, [o.p[k], o.p[k + 1], o.p[k + 2]]) : [o.p[k], o.p[k + 1], o.p[k + 2]];
      this.p.push(...q);
    }
    for (const k of o.i) this.i.push(k + off);
  }
}
const area2 = (L) => { let a = 0; for (let k = 0; k < L.length; k++) { const p = L[k], q = L[(k + 1) % L.length]; a += p[0] * q[1] - q[0] * p[1]; } return a / 2; };
const ccw = (L) => (area2(L) < 0 ? [...L].reverse() : L);

/** Prisma de una región plana (contorno CCW y agujeros) entre z0 y z1. */
function prism(outer, holes, z0, z1, mb = new MB()) {
  outer = ccw(outer);
  holes = holes.map((h) => [...ccw(h)].reverse());
  const all = [outer, ...holes].flat();
  const faces = ShapeUtils.triangulateShape(outer.map((p) => new Vector2(p[0], p[1])), holes.map((h) => h.map((p) => new Vector2(p[0], p[1]))));
  const bot = all.map((p) => mb.v(p[0], p[1], z0)), top = all.map((p) => mb.v(p[0], p[1], z1));
  for (let [a, b, c] of faces) {
    const cr = (all[b][0] - all[a][0]) * (all[c][1] - all[a][1]) - (all[b][1] - all[a][1]) * (all[c][0] - all[a][0]);
    if (cr < 0) [b, c] = [c, b];
    mb.tri(top[a], top[b], top[c]);
    mb.tri(bot[a], bot[c], bot[b]);
  }
  for (const loop of [outer, ...holes]) {
    const b0 = loop.map((p) => mb.v(p[0], p[1], z0)), t0 = loop.map((p) => mb.v(p[0], p[1], z1));
    for (let k = 0; k < loop.length; k++) { const n = (k + 1) % loop.length; mb.quad(b0[k], b0[n], t0[n], t0[k]); }
  }
  return mb;
}

export function roundedRect(b, h, r, cx = 0, cy = 0, seg = SEG) {
  if (r <= 1e-9) return [[cx + b / 2, cy - h / 2], [cx + b / 2, cy + h / 2], [cx - b / 2, cy + h / 2], [cx - b / 2, cy - h / 2]];
  const pts = [];
  const cs = [[b / 2 - r, h / 2 - r, 0], [-b / 2 + r, h / 2 - r, 90], [-b / 2 + r, -h / 2 + r, 180], [b / 2 - r, -h / 2 + r, 270]];
  for (const [x, y, a0] of cs) for (let i = 0; i <= seg; i++) {
    const a = ((a0 + (90 * i) / seg) * Math.PI) / 180;
    pts.push([cx + x + r * Math.cos(a), cy + y + r * Math.sin(a)]);
  }
  return pts;
}
const circle = (d, cx = 0, cy = 0, n = CYL) => Array.from({ length: n }, (_, k) => [cx + (d / 2) * Math.cos((2 * Math.PI * k) / n), cy + (d / 2) * Math.sin((2 * Math.PI * k) / n)]);

/** Tubo: anillo entre dos contornos redondeados con igual número de vértices. */
function tube(p, L) {
  const mb = new MB();
  const o = roundedRect(p.B, p.H, p.r_out), n = roundedRect(p.B - 2 * p.t, p.H - 2 * p.t, p.r_in);
  for (const [z, s] of [[0, -1], [L, 1]]) {
    const oi = o.map((q) => mb.v(q[0], q[1], z)), ii = n.map((q) => mb.v(q[0], q[1], z));
    for (let k = 0; k < o.length; k++) {
      const m = (k + 1) % o.length;
      if (s > 0) mb.quad(oi[k], oi[m], ii[m], ii[k]); else mb.quad(oi[k], ii[k], ii[m], oi[m]);
    }
  }
  for (const [loop, out] of [[o, true], [n, false]]) {
    const b = loop.map((q) => mb.v(q[0], q[1], 0)), t = loop.map((q) => mb.v(q[0], q[1], L));
    for (let k = 0; k < loop.length; k++) {
      const m = (k + 1) % loop.length;
      if (out) mb.quad(b[k], b[m], t[m], t[k]); else mb.quad(b[k], t[k], t[m], b[m]);
    }
  }
  return mb;
}

function arc(cx, cy, r, a0, a1, n = SEG) { return Array.from({ length: n + 1 }, (_, k) => { const a = a0 + ((a1 - a0) * k) / n; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; }); }

function sheetMesh(spec) {
  const mb = new MB();
  const t = spec.t, r = spec.r, R = spec.R;
  // base: unión de rectángulos (sin pliegues)
  const { rectUnionOutline } = spec;
  prism(rectUnionOutline(), [], -t, 0, mb);
  for (const f of spec.flanges) {
    const [s0, s1] = spec.flangeExtent(f.edge);
    const h = f.height;
    // sección en (X = n̂ hacia el interior, Y = z): exterior R desde (R,0) a (0,-R), interior r desde (t,-R) a (R,-t)
    let sec = [...arc(R, -R, R, Math.PI / 2, Math.PI), [0, -h], [t, -h], ...arc(R, -R, r, Math.PI, Math.PI / 2)];
    if (f.direction === "up") sec = sec.map(([x, y]) => [x, -t - y]);
    const piece = prism(sec, [], 0, s1 - s0);
    const [n, c, o] = edgeFrame(spec, f.edge, s0, s1);
    const T = frame(o, n, [0, 0, 1]);
    if (Math.abs(T[0][2] - c[0]) + Math.abs(T[1][2] - c[1]) + Math.abs(T[2][2] - c[2]) > 1e-9) throw new Error("Marco de pestaña incoherente");
    mb.merge(piece, T);
  }
  return mb;
}
function edgeFrame(spec, edge, s0, s1) {
  if (edge === "x0") return [[1, 0, 0], [0, -1, 0], [0, s1, 0]];
  if (edge === "x1") return [[-1, 0, 0], [0, 1, 0], [spec.Lx, s0, 0]];
  if (edge === "y0") return [[0, 1, 0], [1, 0, 0], [s0, 0, 0]];
  return [[0, -1, 0], [-1, 0, 0], [s1, spec.Ly, 0]];
}

function cyl(mb, d, z0, z1) { prism(circle(d), [], z0, z1, mb); }

function standardMesh(part) {
  const c = part.data, code = part.code, mb = new MB();
  if (c.category === "patas") {
    const d = parseFloat(c.thread.slice(1));
    cyl(mb, c.base_d, 0, c.base_h);
    cyl(mb, d * 1.6, c.base_h, c.base_h + 6);
    cyl(mb, d, c.base_h + 6, c.base_h + 6 + c.stem_len);
  } else if (code.startsWith("TUERCA_SOLDAR")) {
    const R = c.s / Math.cos(Math.PI / 6) / 2;
    prism(Array.from({ length: 6 }, (_, k) => [R * Math.cos((k * Math.PI) / 3), R * Math.sin((k * Math.PI) / 3)]), [circle(parseFloat(c.thread.slice(1)), 0, 0, 16)], 0, c.m, mb);
  } else if (code.startsWith("TUERCA_REMACHABLE")) {
    cyl(mb, c.head_d, 0, c.head_h);
    cyl(mb, c.body_d, -c.body_l, 0);
  } else if (code.startsWith("TORNILLO_ISO7380")) {
    cyl(mb, c.head_d, 0, c.head_h * 0.45);
    cyl(mb, c.head_d * 0.78, c.head_h * 0.45, c.head_h * 0.8);
    cyl(mb, c.head_d * 0.45, c.head_h * 0.8, c.head_h);
    cyl(mb, c.d, -c.length, 0);
  } else {
    const [a, b, h] = c.dims ?? [20, 20, 10];
    prism([[-a / 2, -b / 2], [a / 2, -b / 2], [a / 2, b / 2], [-a / 2, b / 2]], [], 0, h, mb);
  }
  return mb;
}

function massProps(mb) {
  let V = 0, cx = 0, cy = 0, cz = 0;
  const P = mb.p;
  for (let k = 0; k < mb.i.length; k += 3) {
    const a = 3 * mb.i[k], b = 3 * mb.i[k + 1], c = 3 * mb.i[k + 2];
    const v = (P[a] * (P[b + 1] * P[c + 2] - P[b + 2] * P[c + 1]) - P[a + 1] * (P[b] * P[c + 2] - P[b + 2] * P[c]) + P[a + 2] * (P[b] * P[c + 1] - P[b + 1] * P[c])) / 6;
    V += v; cx += (v * (P[a] + P[b] + P[c])) / 4; cy += (v * (P[a + 1] + P[b + 1] + P[c + 1])) / 4; cz += (v * (P[a + 2] + P[b + 2] + P[c + 2])) / 4;
  }
  // malla cerrada y orientada: cada arista dirigida a→b tiene su opuesta b→a (claves por posición)
  const key = (k) => `${Math.round(P[3 * k] * 1e4)},${Math.round(P[3 * k + 1] * 1e4)},${Math.round(P[3 * k + 2] * 1e4)}`;
  const bal = new Map();
  for (let k = 0; k < mb.i.length; k += 3) for (let j = 0; j < 3; j++) {
    const a = key(mb.i[k + j]), b = key(mb.i[k + ((j + 1) % 3)]);
    if (a === b) continue;
    const e = a < b ? `${a}|${b}` : `${b}|${a}`;
    bal.set(e, (bal.get(e) ?? 0) + (a < b ? 1 : -1));
  }
  let open = 0;
  for (const v of bal.values()) if (v !== 0) open++;
  let lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let k = 0; k < P.length; k += 3) for (let j = 0; j < 3; j++) { lo[j] = Math.min(lo[j], P[k + j]); hi[j] = Math.max(hi[j], P[k + j]); }
  return { volume: V, centroid: [cx / V, cy / V, cz / V], bbox: [lo, hi], closed: open === 0, openEdges: open };
}

/** Malla y propiedades de una definición de pieza (con caché en la propia pieza). */
export function partGeometry(part) {
  if (part._geo) return part._geo;
  let mb;
  if (part.kind === "perfil") mb = tube(part.profile, part.length);
  else if (part.kind === "chapa") mb = sheetMesh(part.spec);
  else if (part.kind === "pletina") mb = prism(roundedRect(part.w, part.h, part.corner_r, part.w / 2, part.h / 2), [], 0, part.t);
  else mb = standardMesh(part);
  const mp = massProps(mb);
  part._geo = { positions: new Float32Array(mb.p), indices: new Uint32Array(mb.i), ...mp };
  return part._geo;
}

/** Envolvente global de una instancia (exacta para giros de 90°, que son los únicos que usan las familias). */
export function instanceBBox(inst) {
  if (inst._bbox) return inst._bbox;
  const [lo, hi] = partGeometry(inst.part).bbox;
  const lo2 = [Infinity, Infinity, Infinity], hi2 = [-Infinity, -Infinity, -Infinity];
  for (const x of [lo[0], hi[0]]) for (const y of [lo[1], hi[1]]) for (const z of [lo[2], hi[2]]) {
    const q = tp(inst.T, [x, y, z]);
    for (let j = 0; j < 3; j++) { lo2[j] = Math.min(lo2[j], q[j]); hi2[j] = Math.max(hi2[j], q[j]); }
  }
  inst._bbox = [lo2, hi2];
  return inst._bbox;
}
export function instanceCentroid(inst) {
  if (inst.part.kind === "normalizado") { const [lo, hi] = instanceBBox(inst); return lo.map((v, j) => (v + hi[j]) / 2); }
  return tp(inst.T, partGeometry(inst.part).centroid);
}
export function centerOfMass(model) {
  let m = 0; const c = [0, 0, 0];
  for (const i of model.instances) { const mi = i.part.mass, ci = instanceCentroid(i); m += mi; for (let j = 0; j < 3; j++) c[j] += mi * ci[j]; }
  return c.map((v) => v / m);
}
export function modelBBox(model) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const i of model.instances) { const [a, b] = instanceBBox(i); for (let j = 0; j < 3; j++) { lo[j] = Math.min(lo[j], a[j]); hi[j] = Math.max(hi[j], b[j]); } }
  return [lo, hi];
}

export function colorOf(inst) {
  const p = inst.part;
  if (p.finish) return C.finish(p.finish).color;
  if (p.material) return C.material(p.material).render_color;
  return p.kind === "normalizado" ? [0.62, 0.64, 0.66] : [0.5, 0.5, 0.5];
}

/** Carga útil del visor, con la misma estructura que la del servidor (mallas como arrays tipados). */
export function viewerPayload(model) {
  const parts = {};
  for (const [key, p] of Object.entries(model.parts)) {
    const g = partGeometry(p);
    parts[key] = { positions: g.positions, indices: g.indices, ref: p.ref, kind: p.kind, name: p.name, material: p.material,
      mass: Math.round(p.mass * 1000) / 1000, dims: p.bomDims() };
  }
  const instances = model.instances.map((i) => {
    const sa = model.subassemblies[i.group];
    const ex = sa.explode.map((v, k) => v + (i.tags.explode_extra?.[k] ?? 0));
    const T = i.T;
    const matrix = [];
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) matrix.push(T[r][c]);    // por columnas (three.js)
    return { id: i.id, name: i.name, part: i.part.key, ref: i.part.ref, group: i.group, kind: i.part.kind, matrix, color: colorOf(i),
      explode: ex, bbox: instanceBBox(i), feature: i.feature };
  });
  return { product_code: model.product_code, parts, instances, bbox: modelBBox(model),
    subassemblies: Object.entries(model.subassemblies).map(([k, v]) => ({ id: k, name: v.name, explode: v.explode })), tree: model.componentTree() };
}
