// @ts-nocheck
// Proyección ortogonal con eliminación de líneas ocultas para los planos.
// Aristas = aristas vivas de los sólidos facetados + siluetas de las superficies teseladas (cilindros, radios).
// Visibilidad: z-buffer por software de todas las caras; cada arista se muestrea y se divide en tramos visibles y
// ocultos (bisección en las transiciones). Convenciones de vista iguales a las del servidor (primer diedro).
import { partGeometry } from "./geometry";

export const VIEWS = {
  alzado: [[0, -1, 0], [1, 0, 0]],
  perfil: [[-1, 0, 0], [0, -1, 0]],
  planta: [[0, 0, 1], [1, 0, 0]],
  perfil_der: [[1, 0, 0], [0, 1, 0]],
  iso: [[1, -1, 1], [1, 1, 0]],
  iso_izq: [[-1, -1, 1], [1, -1, 0]],
};
const nrm = (a) => { const n = Math.hypot(...a); return a.map((v) => v / n); };
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
export function projector(view) {
  const [z, x] = VIEWS[view];
  const W = nrm(z);
  let U = nrm(x);
  U = nrm(U.map((v, i) => v - W[i] * (U[0] * W[0] + U[1] * W[1] + U[2] * W[2])));
  const V = cross(W, U);
  return { U, V, W };
}
export const projectPoint = (p, view) => { const { U, V } = projector(view); return [p[0] * U[0] + p[1] * U[1] + p[2] * U[2], p[0] * V[0] + p[1] * V[1] + p[2] * V[2]]; };

/**
 * items: [{ part, T }] (T = matriz 4×4 de la instancia, ya con el desplazamiento de explosionado si procede).
 * Devuelve { visible: [[u1,v1,u2,v2]], hidden: [...], bbox: [u0,v0,u1,v1] } en mm de modelo.
 */
export function project(items, view, opts = {}) {
  const { hidden = true, res = 2600 } = opts;
  const { U, V, W } = projector(view);
  // ---- vértices proyectados por instancia
  const inst = items.map(({ part, T }) => {
    const g = partGeometry(part);
    const M = [0, 1, 2].map((r) => [0, 1, 2].map((c) => T[r][c]));
    const t = [T[0][3], T[1][3], T[2][3]];
    const pu = [U, V, W].map((A) => [A[0] * M[0][0] + A[1] * M[1][0] + A[2] * M[2][0], A[0] * M[0][1] + A[1] * M[1][1] + A[2] * M[2][1],
      A[0] * M[0][2] + A[1] * M[1][2] + A[2] * M[2][2], A[0] * t[0] + A[1] * t[1] + A[2] * t[2]]);
    return { g, pu, M };
  });
  let u0 = Infinity, v0 = Infinity, u1 = -Infinity, v1 = -Infinity;
  for (const it of inst) {
    const P = it.g.brep.verts, pu = it.pu;
    it.uvw = new Float64Array(P.length * 3);
    for (let k = 0; k < P.length; k++) {
      const p = P[k];
      for (let a = 0; a < 3; a++) it.uvw[3 * k + a] = pu[a][0] * p[0] + pu[a][1] * p[1] + pu[a][2] * p[2] + pu[a][3];
      const u = it.uvw[3 * k], v = it.uvw[3 * k + 1];
      if (u < u0) u0 = u; if (u > u1) u1 = u; if (v < v0) v0 = v; if (v > v1) v1 = v;
    }
  }
  if (!Number.isFinite(u0)) return { visible: [], hidden: [], bbox: [0, 0, 1, 1] };
  const px = Math.max(u1 - u0, v1 - v0, 1) / res;
  const NX = Math.ceil((u1 - u0) / px) + 3, NY = Math.ceil((v1 - v0) / px) + 3;
  const zb = new Float32Array(NX * NY).fill(-Infinity);
  const zs = new Float32Array(NX * NY);         // pendiente de profundidad (mm por píxel) de la superficie más cercana
  const X = (u) => (u - u0) / px + 1, Y = (v) => (v - v0) / px + 1;
  // ---- z-buffer por líneas de barrido; las caras traseras de sólidos cerrados nunca son las más cercanas
  const q = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (const it of inst) {
    const P = it.g.positions, pu = it.pu;
    for (let k = 0; k < P.length; k += 9) {
      for (let j = 0; j < 3; j++) {
        const x = P[k + 3 * j], y = P[k + 3 * j + 1], z = P[k + 3 * j + 2];
        q[j][0] = X(pu[0][0] * x + pu[0][1] * y + pu[0][2] * z + pu[0][3]);
        q[j][1] = Y(pu[1][0] * x + pu[1][1] * y + pu[1][2] * z + pu[1][3]);
        q[j][2] = pu[2][0] * x + pu[2][1] * y + pu[2][2] * z + pu[2][3];
      }
      const ax = q[0][0], ay = q[0][1], az = q[0][2], bx = q[1][0], by = q[1][1], bz = q[1][2], cx = q[2][0], cy = q[2][1], cz = q[2][2];
      const den = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay);
      if (den <= 1e-9) continue;                    // de canto o trasera
      // plano de profundidad d = A·x + B·y + D
      const A = ((bz - az) * (cy - ay) - (cz - az) * (by - ay)) / den;
      const B = ((cz - az) * (bx - ax) - (bz - az) * (cx - ax)) / den;
      const D = az - A * ax - B * ay;
      const slope = Math.max(Math.abs(A), Math.abs(B));
      const ymin = Math.max(0, Math.ceil(Math.min(ay, by, cy) - 0.5)), ymax = Math.min(NY - 1, Math.floor(Math.max(ay, by, cy) - 0.5));
      const E = [[ax, ay, bx, by], [bx, by, cx, cy], [cx, cy, ax, ay]];
      for (let y = ymin; y <= ymax; y++) {
        const sy = y + 0.5;
        let xl = Infinity, xr = -Infinity;
        for (const [x0, y0, x1, y1] of E) {
          if ((y0 <= sy && y1 >= sy) || (y1 <= sy && y0 >= sy)) {
            if (y1 === y0) { xl = Math.min(xl, x0, x1); xr = Math.max(xr, x0, x1); }
            else { const xx = x0 + ((sy - y0) * (x1 - x0)) / (y1 - y0); if (xx < xl) xl = xx; if (xx > xr) xr = xx; }
          }
        }
        const x0 = Math.max(0, Math.ceil(xl - 0.5)), x1 = Math.min(NX - 1, Math.floor(xr - 0.5));
        let dd = A * (x0 + 0.5) + B * sy + D, i = y * NX + x0;
        for (let x = x0; x <= x1; x++, i++, dd += A) if (dd > zb[i]) { zb[i] = dd; zs[i] = slope; }
      }
    }
  }
  // ---- visibilidad de un punto: mayoría de la vecindad 3×3 claramente por delante del punto
  const tol = 1.0 * px + 0.05;
  const isHidden = (u, v, d) => {
    const x = Math.floor(X(u)), y = Math.floor(Y(v));
    let n = 0;
    for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) {
      const xx = x + i, yy = y + j;
      if (xx < 0 || yy < 0 || xx >= NX || yy >= NY) continue;
      const c = yy * NX + xx;
      if (zb[c] > d + tol + 1.6 * zs[c]) n++;
    }
    return n >= 5;
  };
  // ---- aristas: vivas + siluetas
  const vis = [], hid = [];
  const seen = new Set();
  const edge = (it, a, b) => {
    const A = it.uvw, ua = A[3 * a], va = A[3 * a + 1], da = A[3 * a + 2], ub = A[3 * b], vb = A[3 * b + 1], db = A[3 * b + 2];
    const L = Math.hypot(ub - ua, vb - va);
    if (L < px * 0.3) return;                     // arista vista de punta
    const ka = `${Math.round(ua * 20)},${Math.round(va * 20)},${Math.round(da * 20)}`, kb = `${Math.round(ub * 20)},${Math.round(vb * 20)},${Math.round(db * 20)}`;
    const key = `${ka}|${kb}`, key2 = `${kb}|${ka}`;
    if (seen.has(key) || seen.has(key2)) return;
    seen.add(key);
    const at = (s) => isHidden(ua + (ub - ua) * s, va + (vb - va) * s, da + (db - da) * s);
    const step = Math.min(1, (3 * px) / L);
    const n = Math.ceil(1 / step);
    let sPrev = 0, hPrev = at(0), start = 0;
    const emit = (s0, s1, h) => { if (s1 - s0 < 1e-9) return; (h ? hid : vis).push([ua + (ub - ua) * s0, va + (vb - va) * s0, ua + (ub - ua) * s1, va + (vb - va) * s1]); };
    for (let k = 1; k <= n; k++) {
      const s = Math.min(1, k * step), h = at(s);
      if (h !== hPrev) {
        let lo = sPrev, hi = s;                     // bisección del cambio de visibilidad
        for (let it2 = 0; it2 < 8; it2++) { const m = (lo + hi) / 2; if (at(m) === hPrev) lo = m; else hi = m; }
        emit(start, lo, hPrev);
        start = hi; hPrev = h;
      }
      sPrev = s;
    }
    emit(start, 1, hPrev);
  };
  for (const it of inst) {
    const g = it.g;
    for (const [a, b] of g.featureEdges) edge(it, a, b);
    const F = g.brep.faces, M = it.M;
    const facing = (fi) => { const n = F[fi].n; return (W[0] * (M[0][0] * n[0] + M[0][1] * n[1] + M[0][2] * n[2]) + W[1] * (M[1][0] * n[0] + M[1][1] * n[1] + M[1][2] * n[2]) + W[2] * (M[2][0] * n[0] + M[2][1] * n[1] + M[2][2] * n[2])); };
    for (const [a, b, f1, f2] of g.smoothEdges) {
      const s1 = facing(f1), s2 = facing(f2);
      if ((s1 > 1e-9 && s2 <= 1e-9) || (s2 > 1e-9 && s1 <= 1e-9)) edge(it, a, b);
    }
    // radios (esquinas de tubo, pliegues): su línea media si las dos caras que une miran al observador
    for (const [a, b, fa, fb] of g.creaseEdges ?? []) if (facing(fa) > 0.02 && facing(fb) > 0.02) edge(it, a, b);
  }
  const visible = merge(vis);
  return { visible, hidden: hidden ? subtract(merge(hid), visible) : [], bbox: [u0, v0, u1, v1] };
}

const lineKey = (a, b, c, d) => {
  const ang = Math.atan2(d - b, c - a), nx = -Math.sin(ang), ny = Math.cos(ang);
  return [`${Math.round(ang * 2000)}|${Math.round((a * nx + b * ny) * 20)}`, Math.cos(ang), Math.sin(ang)];
};
const canon = ([a, b, c, d]) => (a > c || (a === c && b > d) ? [c, d, a, b] : [a, b, c, d]);
/** Quita de las líneas ocultas los tramos que coinciden con líneas visibles. */
function subtract(hid, vis) {
  const cover = new Map();
  for (const s of vis) {
    const [a, b, c, d] = canon(s), [k, ex, ey] = lineKey(a, b, c, d);
    if (!cover.has(k)) cover.set(k, []);
    cover.get(k).push([a * ex + b * ey, c * ex + d * ey]);
  }
  const out = [];
  for (const s of hid) {
    const [a, b, c, d] = canon(s), [k, ex, ey] = lineKey(a, b, c, d);
    const iv = (cover.get(k) ?? []).slice().sort((p, q) => p[0] - q[0]);
    const t0 = a * ex + b * ey, t1 = c * ex + d * ey, L = t1 - t0 || 1;
    let cur = t0;
    const at = (t) => [a + ((c - a) * (t - t0)) / L, b + ((d - b) * (t - t0)) / L];
    for (const [p, q] of iv) {
      if (q <= cur + 0.05 || p >= t1) continue;
      if (p > cur + 0.05) out.push([...at(cur), ...at(Math.min(p, t1))]);
      cur = Math.max(cur, q);
      if (cur >= t1) break;
    }
    if (cur < t1 - 0.05) out.push([...at(cur), ...at(t1)]);
  }
  return out;
}

/** Une segmentos colineales contiguos para aligerar el PDF. */
function merge(segs) {
  const groups = new Map();
  for (const s of segs) {
    let [a, b, c, d] = s;
    if (a > c || (a === c && b > d)) [a, b, c, d] = [c, d, a, b];
    const ang = Math.atan2(d - b, c - a);
    const nx = -Math.sin(ang), ny = Math.cos(ang);
    const off = a * nx + b * ny;
    const key = `${Math.round(ang * 2000)}|${Math.round(off * 20)}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push([a, b, c, d, Math.cos(ang), Math.sin(ang)]);
  }
  const out = [];
  for (const g of groups.values()) {
    const [, , , , ex, ey] = g[0];
    const t = (x, y) => x * ex + y * ey;
    g.sort((p, q) => t(p[0], p[1]) - t(q[0], q[1]));
    let cur = g[0].slice(0, 4);
    for (let k = 1; k < g.length; k++) {
      const s = g[k];
      if (t(s[0], s[1]) <= t(cur[2], cur[3]) + 0.05) { if (t(s[2], s[3]) > t(cur[2], cur[3])) { cur[2] = s[2]; cur[3] = s[3]; } }
      else { out.push(cur); cur = s.slice(0, 4); }
    }
    out.push(cur);
  }
  return out;
}
