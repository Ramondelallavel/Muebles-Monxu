// @ts-nocheck
// Geometría sólida en el navegador: B-rep poligonal (facetado) de cada pieza, con taladros.
//   · perfil hueco = 4 paredes (con sus taladros) + 4 esquinas de radio EN 10219-2
//   · chapa plegada = base + zonas de pliegue + alas (con sus taladros)
//   · pletina con taladros; normalizados por revolución o prisma
// Las piezas elementales que se tocan se fusionan eliminando las caras coincidentes, de modo que cada pieza
// es una única capa cerrada y orientada. De este modelo salen la malla del visor, el STEP, las aristas de
// los planos, la masa de control y los centros de gravedad.
import { ShapeUtils, Vector2 } from "three";
import * as C from "./catalog";
import { frame, tp } from "./model";

const SEG = 8;        // segmentos por cuarto de circunferencia (radios de perfil y de plegado)
const HOLE = 20;      // segmentos por taladro
const REV = 28;       // segmentos de revolución
export const FEATURE_ANGLE = 20;    // grados: arista viva entre caras

// ---------------------------------------------------------------------------- vectores
const vsub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const vcross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const vdot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const vnorm = (a) => { const n = Math.hypot(...a) || 1; return [a[0] / n, a[1] / n, a[2] / n]; };
const rot = (T, n) => [0, 1, 2].map((i) => T[i][0] * n[0] + T[i][1] * n[1] + T[i][2] * n[2]);
const area2 = (L) => { let a = 0; for (let k = 0; k < L.length; k++) { const p = L[k], q = L[(k + 1) % L.length]; a += p[0] * q[1] - q[0] * p[1]; } return a / 2; };
const ccw = (L) => (area2(L) < 0 ? [...L].reverse() : L);
function newell(loop) {
  let n = [0, 0, 0];
  for (let k = 0; k < loop.length; k++) {
    const a = loop[k], b = loop[(k + 1) % loop.length];
    n = [n[0] + (a[1] - b[1]) * (a[2] + b[2]), n[1] + (a[2] - b[2]) * (a[0] + b[0]), n[2] + (a[0] - b[0]) * (a[1] + b[1])];
  }
  return vnorm(n);
}

// ---------------------------------------------------------------------------- sólidos elementales
/** Sólido = lista de caras; cara = { loops: [exterior, ...agujeros] de puntos 3D, n: normal exterior }. */
const solid = (faces = []) => ({ faces });
function transform(s, T) {
  return solid(s.faces.map((f) => ({ loops: f.loops.map((l) => l.map((p) => tp(T, p))), n: rot(T, f.n) })));
}
/** Prisma de una región plana (contorno y agujeros en XY) entre z0 y z1 (z1 > z0). */
export function prism(outer, holes, z0, z1) {
  outer = ccw(outer);
  holes = holes.map((h) => [...ccw(h)].reverse());
  const P = (p, z) => [p[0], p[1], z];
  const faces = [
    { loops: [outer.map((p) => P(p, z1)), ...holes.map((h) => h.map((p) => P(p, z1)))], n: [0, 0, 1] },
    { loops: [[...outer].reverse().map((p) => P(p, z0)), ...holes.map((h) => [...h].reverse().map((p) => P(p, z0)))], n: [0, 0, -1] },
  ];
  for (const loop of [outer, ...holes]) for (let k = 0; k < loop.length; k++) {
    const a = loop[k], b = loop[(k + 1) % loop.length];
    const q = [P(a, z0), P(b, z0), P(b, z1), P(a, z1)];
    faces.push({ loops: [q], n: newell(q) });
  }
  return solid(faces);
}
/** Sólido de revolución alrededor de Z de un perfil cerrado (r, z) con r >= 0. */
function revolve(profile, n = REV) {
  const faces = [];
  const pt = (r, z, j) => { const a = (2 * Math.PI * j) / n; return [r * Math.cos(a), r * Math.sin(a), z]; };
  for (let i = 0; i < profile.length; i++) {
    const [r0, z0] = profile[i], [r1, z1] = profile[(i + 1) % profile.length];
    if (r0 < 1e-9 && r1 < 1e-9) continue;
    for (let j = 0; j < n; j++) {
      let q = [pt(r0, z0, j), pt(r1, z1, j), pt(r1, z1, j + 1), pt(r0, z0, j + 1)];
      if (r0 < 1e-9) q = [q[0], q[1], q[2]];
      else if (r1 < 1e-9) q = [q[0], q[1], q[3]];
      faces.push({ loops: [q], n: newell(q) });
    }
  }
  const s = solid(faces);
  if (signedVolume(s) < 0) for (const f of s.faces) { f.loops = f.loops.map((l) => [...l].reverse()); f.n = f.n.map((v) => -v); }
  return s;
}
const circle = (d, cx = 0, cy = 0, n = HOLE) => Array.from({ length: n }, (_, k) => [cx + (d / 2) * Math.cos((2 * Math.PI * k) / n), cy + (d / 2) * Math.sin((2 * Math.PI * k) / n)]);
/** Taladro facetado circunscrito: el polígono contiene el círculo real (un eje del mismo diámetro, inscrito, no lo invade). */
const holeLoop = (d, cx = 0, cy = 0, n = HOLE) => circle(d / Math.cos(Math.PI / n), cx, cy, n);
const arc = (cx, cy, r, a0, a1, n = SEG) => Array.from({ length: n + 1 }, (_, k) => { const a = a0 + ((a1 - a0) * k) / n; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; });
export function roundedRect(b, h, r, cx = 0, cy = 0, seg = SEG) {
  if (r <= 1e-9) return [[cx + b / 2, cy - h / 2], [cx + b / 2, cy + h / 2], [cx - b / 2, cy + h / 2], [cx - b / 2, cy - h / 2]];
  const pts = [];
  for (const [x, y, a0] of [[b / 2 - r, h / 2 - r, 0], [-b / 2 + r, h / 2 - r, 90], [-b / 2 + r, -h / 2 + r, 180], [b / 2 - r, -h / 2 + r, 270]])
    for (let i = 0; i <= seg; i++) { const a = ((a0 + (90 * i) / seg) * Math.PI) / 180; pts.push([cx + x + r * Math.cos(a), cy + y + r * Math.sin(a)]); }
  return pts;
}
/** Círculos de taladro que caben enteros en el rectángulo y no se solapan (los demás los señala el DFM). */
function holesIn(rect, circles, margin = 0.05) {
  const [u0, v0, u1, v1] = rect, out = [], kept = [];
  for (const [u, v, d] of circles) {
    const r = d / 2;
    if (u - r < u0 + margin || u + r > u1 - margin || v - r < v0 + margin || v + r > v1 - margin) continue;
    if (kept.some(([a, b, dd]) => Math.hypot(a - u, b - v) < r + dd / 2 + margin)) continue;
    kept.push([u, v, d]);
    out.push(holeLoop(d, u, v));
  }
  return out;
}
const basis = (eu, ev, ew, o) => [[eu[0], ev[0], ew[0], o[0]], [eu[1], ev[1], ew[1], o[1]], [eu[2], ev[2], ew[2], o[2]], [0, 0, 0, 1]];

// ---------------------------------------------------------------------------- fusión en una capa cerrada
class Welder {
  constructor(tol = 1e-5) { this.tol = tol; this.pts = []; this.grid = new Map(); }
  id(p) {
    const c = p.map((v) => Math.round(v * 100));
    for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) for (let k = -1; k <= 1; k++) {
      const l = this.grid.get(`${c[0] + i},${c[1] + j},${c[2] + k}`);
      if (l) for (const n of l) { const q = this.pts[n]; if (Math.abs(q[0] - p[0]) <= this.tol && Math.abs(q[1] - p[1]) <= this.tol && Math.abs(q[2] - p[2]) <= this.tol) return n; }
    }
    this.pts.push(p);
    const key = c.join(",");
    if (!this.grid.has(key)) this.grid.set(key, []);
    this.grid.get(key).push(this.pts.length - 1);
    return this.pts.length - 1;
  }
}
/** Une sólidos que se tocan por caras completas: las parejas de caras coincidentes y opuestas desaparecen. */
function fuse(solids) {
  const W = new Welder();
  let faces = [];
  solids.forEach((s, si) => { for (const f of s.faces) {
    const loops = f.loops.map((l) => { const ids = l.map((p) => W.id(p)); return ids.filter((v, k) => v !== ids[(k + 1) % ids.length]); }).filter((l) => l.length >= 3);
    if (loops.length) faces.push({ loops, n: f.n, src: si });
  } });
  // componentes conexos: dos sólidos elementales quedan unidos cuando comparten una cara (que se elimina)
  const par = solids.map((_, i) => i);
  const find = (a) => { while (par[a] !== a) { par[a] = par[par[a]]; a = par[a]; } return a; };
  const byKey = new Map();
  faces.forEach((f, i) => { const k = [...new Set(f.loops.flat())].sort((a, b) => a - b).join(","); if (!byKey.has(k)) byKey.set(k, []); byKey.get(k).push(i); });
  const drop = new Set();
  for (const ids of byKey.values()) for (let a = 0; a < ids.length; a++) for (let b = a + 1; b < ids.length; b++) {
    if (drop.has(ids[a]) || drop.has(ids[b])) continue;
    if (vdot(faces[ids[a]].n, faces[ids[b]].n) < -0.999) { drop.add(ids[a]); drop.add(ids[b]); par[find(faces[ids[a]].src)] = find(faces[ids[b]].src); }
  }
  faces = faces.filter((_, i) => !drop.has(i)).map((f) => ({ loops: f.loops, n: f.n, comp: find(f.src) }));
  return { verts: W.pts, faces };
}

// ---------------------------------------------------------------------------- piezas
function tubeSolids(p, L, holes) {
  const { B, H, t, r_out: ro, r_in: ri } = p;
  const cx = B / 2 - ro, cy = H / 2 - ro;
  const S = [];
  // paredes: región (u, z) con taladros, extruida en el espesor
  const walls = [
    { face: "+x", eu: [0, 1, 0], ew: [1, 0, 0], w0: B / 2 - t, w1: B / 2, span: cy, map: (off) => off },
    { face: "-x", eu: [0, 1, 0], ew: [1, 0, 0], w0: -B / 2, w1: -B / 2 + t, span: cy, map: (off) => off },
    { face: "+y", eu: [-1, 0, 0], ew: [0, 1, 0], w0: H / 2 - t, w1: H / 2, span: cx, map: (off) => -off },
    { face: "-y", eu: [-1, 0, 0], ew: [0, 1, 0], w0: -H / 2, w1: -H / 2 + t, span: cx, map: (off) => -off },
  ];
  for (const w of walls) {
    const rect = [-w.span, 0, w.span, L];
    const hs = holesIn(rect, holes.filter((h) => h[0] === w.face).map(([, z, off, d]) => [w.map(off), z, d]));
    const pr = prism([[-w.span, 0], [w.span, 0], [w.span, L], [-w.span, L]], hs, w.w0, w.w1);
    S.push(transform(pr, basis(w.eu, [0, 0, 1], w.ew, [0, 0, 0])));
  }
  for (const [sx, sy, a0] of [[1, 1, 0], [-1, 1, 90], [-1, -1, 180], [1, -1, 270]]) {
    const a = (a0 * Math.PI) / 180, b = ((a0 + 90) * Math.PI) / 180;
    const sec = [...arc(sx * cx, sy * cy, ro, a, b), ...arc(sx * cx, sy * cy, ri, b, a)];
    S.push(prism(sec, [], 0, L));
  }
  return S;
}

function sheetSolids(spec) {
  const { t, r, R } = spec;
  const S = [];
  const baseHoles = (spec.holes ?? []).map((h) => (h[0] === "round" ? holeLoop(h[3], h[1], h[2]) : [[h[1] - h[3] / 2, h[2] - h[4] / 2], [h[1] + h[3] / 2, h[2] - h[4] / 2],
    [h[1] + h[3] / 2, h[2] + h[4] / 2], [h[1] - h[3] / 2, h[2] + h[4] / 2]]));
  S.push(prism(spec.rectUnionOutline(), baseHoles, -t, 0));
  for (const f of spec.flanges) {
    const [s0, s1] = spec.flangeExtent(f.edge);
    const up = f.direction === "up";
    // zona de pliegue: sección (X = n̂ hacia el interior, Y = z) extruida a lo largo del borde
    let sec = [...arc(R, -R, R, Math.PI / 2, Math.PI), ...arc(R, -R, r, Math.PI, Math.PI / 2)];
    if (up) sec = sec.map(([x, y]) => [x, -t - y]);
    const [n, c, o] = edgeFrame(spec, f.edge, s0, s1);
    const T = frame(o, n, [0, 0, 1]);
    if (Math.abs(T[0][2] - c[0]) + Math.abs(T[1][2] - c[1]) + Math.abs(T[2][2] - c[2]) > 1e-9) throw new Error("Marco de pestaña incoherente");
    S.push(transform(prism(sec, [], 0, s1 - s0), T));
    // ala recta con sus taladros: región (u = posición a lo largo del borde, v = z) extruida en el espesor según n̂
    // (si la pestaña no supera el pliegue sólo queda el arco: diseño ya señalado por el DFM como PLG-ALA-MIN)
    if (f.height - R < 0.01) continue;
    const [v0, v1] = up ? [R - t, f.height - t] : [-f.height, -R];
    const L = legFrame(spec, f.edge);
    const us = [L.u(s0), L.u(s1)].sort((a, b) => a - b);
    const rect = [us[0], v0, us[1], v1];
    const hs = holesIn(rect, f.holes.map(([s, hh, d]) => [L.u(s), up ? -t + hh : -hh, d]));
    S.push(transform(prism([[rect[0], v0], [rect[2], v0], [rect[2], v1], [rect[0], v1]], hs, 0, t), L.T));
  }
  return S;
}
function edgeFrame(spec, edge, s0, s1) {
  if (edge === "x0") return [[1, 0, 0], [0, -1, 0], [0, s1, 0]];
  if (edge === "x1") return [[-1, 0, 0], [0, 1, 0], [spec.Lx, s0, 0]];
  if (edge === "y0") return [[0, 1, 0], [1, 0, 0], [s0, 0, 0]];
  return [[0, -1, 0], [-1, 0, 0], [s1, spec.Ly, 0]];
}
function legFrame(spec, edge) {
  if (edge === "x0") return { T: basis([0, 1, 0], [0, 0, 1], [1, 0, 0], [0, 0, 0]), u: (s) => s };
  if (edge === "x1") return { T: basis([0, -1, 0], [0, 0, 1], [-1, 0, 0], [spec.Lx, 0, 0]), u: (s) => -s };
  if (edge === "y0") return { T: basis([-1, 0, 0], [0, 0, 1], [0, 1, 0], [0, 0, 0]), u: (s) => -s };
  return { T: basis([1, 0, 0], [0, 0, 1], [0, -1, 0], [0, spec.Ly, 0]), u: (s) => s };
}

function plateSolids(part) {
  const rect = [0, 0, part.w, part.h];
  return [prism(roundedRect(part.w, part.h, part.corner_r, part.w / 2, part.h / 2), holesIn(rect, part.holes.map(([x, y, d]) => [x, y, d]), part.corner_r), 0, part.t)];
}

function standardSolids(part) {
  const c = part.data, code = part.code;
  if (c.category === "patas") {
    const d = parseFloat(c.thread.slice(1)), h1 = c.base_h, h2 = c.base_h + 6, h3 = c.base_h + 6 + c.stem_len;
    return [revolve([[0, 0], [c.base_d / 2, 0], [c.base_d / 2, h1], [d * 0.8, h1], [d * 0.8, h2], [d / 2, h2], [d / 2, h3], [0, h3]])];
  }
  if (code.startsWith("TUERCA_SOLDAR")) {
    const Rr = c.s / Math.cos(Math.PI / 6) / 2;
    return [prism(Array.from({ length: 6 }, (_, k) => [Rr * Math.cos((k * Math.PI) / 3), Rr * Math.sin((k * Math.PI) / 3)]), [holeLoop(parseFloat(c.thread.slice(1)), 0, 0, 16)], 0, c.m)];
  }
  if (code.startsWith("TUERCA_REMACHABLE")) {
    const d = parseFloat(c.thread.slice(1)), ri = d / 2 / Math.cos(Math.PI / 24);     // rosca interior circunscrita
    return [revolve([[ri, -c.body_l], [c.body_d / 2, -c.body_l], [c.body_d / 2, 0], [c.head_d / 2, 0], [c.head_d / 2, c.head_h], [ri, c.head_h]], 24)];
  }
  if (code.startsWith("TORNILLO_ISO7380")) {
    const R = c.head_d / 2, h = c.head_h;
    const dome = Array.from({ length: 6 }, (_, k) => { const a = (Math.PI / 2) * (k / 5); return [R * Math.cos(a) * 0.98, h * 0.35 + h * 0.65 * Math.sin(a)]; });
    return [revolve([[0, -c.length], [c.d / 2, -c.length], [c.d / 2, 0], [R, 0], [R, h * 0.35], ...dome.slice(1, -1), [0, h]], 24)];
  }
  if (c.category === "ruedas_espiga") {
    // horquilla (puente + brazos) como un único prisma en U; el resto según la descomposición común
    const parts = castorParts(c);
    const D = +c.wheel_d, w = +c.wheel_w, nh = +c.nominal_height, tf = 3.0, yo = w / 2 + 1.0 + tf, fl = Math.round(0.6 * D * 1000) / 1000;
    const U = [[-yo, D / 2 - 6], [-yo + tf, D / 2 - 6], [-yo + tf, nh - 12], [yo - tf, nh - 12], [yo - tf, D / 2 - 6], [yo, D / 2 - 6], [yo, nh - 8], [-yo, nh - 8]];
    const fork = transform(prism(U, [], -fl / 2, fl / 2), [[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]]);
    return [fork, ...parts.filter((_, k) => k < 2 || k > 4).map(([kind, a]) => (kind === "cyl" ? cylinder(...a) : box(...a)))];
  }
  const [a, b, h] = c.dims ?? [20, 20, 10];
  return [prism([[-a / 2, -b / 2], [a / 2, -b / 2], [a / 2, b / 2], [-a / 2, b / 2]], [], 0, h)];
}
/** Cilindro de diámetro d y longitud L desde `base` según +Z o +Y (los únicos ejes usados). */
function cylinder(d, L, base, dir) {
  const s = revolve([[0, 0], [d / 2, 0], [d / 2, L], [0, L]]);
  const T = dir[1] > 0.5 ? [[1, 0, 0, base[0]], [0, 0, 1, base[1]], [0, -1, 0, base[2]], [0, 0, 0, 1]]
    : [[1, 0, 0, base[0]], [0, 1, 0, base[1]], [0, 0, 1, base[2]], [0, 0, 0, 1]];
  return transform(s, T);
}
const box = (x0, y0, z0, x1, y1, z1) => prism([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], [], z0, z1);
/** Rueda giratoria de espiga roscada: misma descomposición que geometry.stem_castor_parts del servidor. */
export function castorParts(c) {
  const d = parseFloat(c.thread.slice(1)), D = +c.wheel_d, w = +c.wheel_w, nh = +c.nominal_height, hd = +c.head_d;
  const tf = 3.0, gap = 1.0, yo = w / 2 + gap + tf, fl = Math.round(0.6 * D * 1000) / 1000;
  const out = [["cyl", [d, c.stem_len, [0, 0, nh], [0, 0, 1]]], ["cyl", [hd, 8.0, [0, 0, nh - 8.0], [0, 0, 1]]],
    ["box", [-fl / 2, -yo, nh - 12.0, fl / 2, yo, nh - 8.0]],
    ["box", [-fl / 2, -yo, D / 2 - 6.0, fl / 2, -yo + tf, nh - 12.0]], ["box", [-fl / 2, yo - tf, D / 2 - 6.0, fl / 2, yo, nh - 12.0]],
    ["cyl", [D, w, [0, -w / 2, D / 2], [0, 1, 0]]]];
  if (c.brake) out.push(["box", [fl / 2 + 1.0, -yo, nh - 12.0, D / 2 + 18.0, yo, nh - 8.0]]);
  return out;
}

// ---------------------------------------------------------------------------- triangulación y propiedades
function signedVolume(s) {
  let V = 0;
  for (const f of s.faces) for (const [a, b, c] of triangulateFace(f.loops, f.n)) V += vdot(a, vcross(b, c)) / 6;
  return V;
}
/** Triángulos (puntos) de una cara plana con agujeros, orientados según su normal. */
function triangulateFace(loops, n) {
  const out = [];
  const outer = loops[0];
  if (loops.length === 1 && outer.length <= 4) {
    for (let k = 1; k < outer.length - 1; k++) out.push([outer[0], outer[k], outer[k + 1]]);
    return out;
  }
  const ax = Math.abs(n[0]) > Math.abs(n[1]) ? (Math.abs(n[0]) > Math.abs(n[2]) ? 0 : 2) : Math.abs(n[1]) > Math.abs(n[2]) ? 1 : 2;
  const [i, j] = ax === 0 ? [1, 2] : ax === 1 ? [2, 0] : [0, 1];
  const all = loops.flat();
  const tris = ShapeUtils.triangulateShape(outer.map((p) => new Vector2(p[i], p[j])), loops.slice(1).map((l) => l.map((p) => new Vector2(p[i], p[j]))));
  for (const [a, b, c] of tris) {
    const t = [all[a], all[b], all[c]];
    if (vdot(vcross(vsub(t[1], t[0]), vsub(t[2], t[0])), n) < 0) out.push([t[0], t[2], t[1]]); else out.push(t);
  }
  return out;
}

function build(solids) {
  const B = fuse(solids);
  const V = B.verts;
  const pos = [], nor = [];
  let vol = 0, cx = 0, cy = 0, cz = 0;
  // normales suavizadas sólo entre caras casi coplanarias (radios teselados); aristas vivas nítidas
  const incident = new Map();
  B.faces.forEach((f, fi) => { for (const l of f.loops) for (const v of l) { if (!incident.has(v)) incident.set(v, []); incident.get(v).push(fi); } });
  const cosS = Math.cos((25 * Math.PI) / 180);
  const smooth = (v, fi) => {
    const n0 = B.faces[fi].n; let s = [0, 0, 0];
    for (const g of incident.get(v)) { const n = B.faces[g].n; if (vdot(n, n0) >= cosS) s = [s[0] + n[0], s[1] + n[1], s[2] + n[2]]; }
    return vnorm(s);
  };
  B.faces.forEach((f, fi) => {
    const pts = f.loops.map((l) => l.map((k) => V[k]));
    const idx = f.loops.map((l) => [...l]);
    const flatIdx = idx.flat(), flatPts = pts.flat();
    const lookup = new Map(flatPts.map((p, k) => [p, flatIdx[k]]));
    for (const tri of triangulateFace(pts, f.n)) {
      for (const p of tri) { pos.push(p[0], p[1], p[2]); nor.push(...smooth(lookup.get(p), fi)); }
      const [a, b, c] = tri;
      const v = vdot(a, vcross(b, c)) / 6;
      vol += v; cx += (v * (a[0] + b[0] + c[0])) / 4; cy += (v * (a[1] + b[1] + c[1])) / 4; cz += (v * (a[2] + b[2] + c[2])) / 4;
    }
  });
  // aristas: cierre de la capa y aristas vivas
  const edges = new Map();
  B.faces.forEach((f, fi) => { for (const l of f.loops) for (let k = 0; k < l.length; k++) {
    const a = l[k], b = l[(k + 1) % l.length];
    const key = a < b ? `${a},${b}` : `${b},${a}`;
    if (!edges.has(key)) edges.set(key, { a: Math.min(a, b), b: Math.max(a, b), faces: [], bal: 0 });
    const e = edges.get(key); e.faces.push(fi); e.bal += a < b ? 1 : -1;
  } });
  let open = 0;
  const cosF = Math.cos((FEATURE_ANGLE * Math.PI) / 180);
  const feature = [], smoothE = [];
  for (const e of edges.values()) {
    if (e.bal !== 0 || e.faces.length !== 2) open++;
    if (e.faces.length !== 2) { feature.push([e.a, e.b]); continue; }
    const d = vdot(B.faces[e.faces[0]].n, B.faces[e.faces[1]].n);
    if (d < cosF) feature.push([e.a, e.b]);
    else if (d < 0.99999) smoothE.push([e.a, e.b, e.faces[0], e.faces[1]]);    // candidatas a silueta
  }
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const p of V) for (let j = 0; j < 3; j++) { lo[j] = Math.min(lo[j], p[j]); hi[j] = Math.max(hi[j], p[j]); }
  return { positions: new Float32Array(pos), normals: new Float32Array(nor), indices: Uint32Array.from({ length: pos.length / 3 }, (_, k) => k),
    volume: vol, centroid: [cx / vol, cy / vol, cz / vol], bbox: [lo, hi], closed: open === 0, openEdges: open,
    brep: { verts: V, faces: B.faces }, featureEdges: feature, smoothEdges: smoothE };
}

/** Sólido, malla y propiedades de una definición de pieza (con caché en la propia pieza). */
export function partGeometry(part) {
  if (part._geo) return part._geo;
  let S;
  if (part.kind === "perfil") S = tubeSolids(part.profile, part.length, part.holes);
  else if (part.kind === "chapa") S = sheetSolids(part.spec);
  else if (part.kind === "pletina") S = plateSolids(part);
  else S = standardSolids(part);
  part._geo = build(S);
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
export function modelBBox(model, insts = model.instances) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const i of insts) { const [a, b] = instanceBBox(i); for (let j = 0; j < 3; j++) { lo[j] = Math.min(lo[j], a[j]); hi[j] = Math.max(hi[j], b[j]); } }
  return [lo, hi];
}

export function colorOf(inst) {
  const p = inst.part;
  if (p.finish) return C.finish(p.finish).color;
  if (p.material) return C.material(p.material).render_color;
  return p.kind === "normalizado" ? [0.62, 0.64, 0.66] : [0.5, 0.5, 0.5];
}
export const explodeOf = (model, i) => model.subassemblies[i.group].explode.map((v, k) => v + (i.tags.explode_extra?.[k] ?? 0));

/** Carga útil del visor, con la misma estructura que la del servidor (mallas como arrays tipados). */
export function viewerPayload(model) {
  const parts = {};
  for (const [key, p] of Object.entries(model.parts)) {
    const g = partGeometry(p);
    parts[key] = { positions: g.positions, normals: g.normals, indices: g.indices, ref: p.ref, kind: p.kind, name: p.name, material: p.material,
      mass: Math.round(p.mass * 1000) / 1000, dims: p.bomDims() };
  }
  const instances = model.instances.map((i) => {
    const T = i.T;
    const matrix = [];
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) matrix.push(T[r][c]);    // por columnas (three.js)
    return { id: i.id, name: i.name, part: i.part.key, ref: i.part.ref, group: i.group, kind: i.part.kind, matrix, color: colorOf(i),
      explode: explodeOf(model, i), bbox: instanceBBox(i), feature: i.feature };
  });
  return { product_code: model.product_code, parts, instances, bbox: modelBBox(model),
    subassemblies: Object.entries(model.subassemblies).map(([k, v]) => ({ id: k, name: v.name, explode: v.explode })), tree: model.componentTree() };
}
