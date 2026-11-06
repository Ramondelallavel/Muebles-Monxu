// @ts-nocheck
// Interferencias entre sólidos facetados (navegador): para cada pareja de instancias con envolventes solapadas se
// buscan triángulos que se atraviesan con penetración mayor que la tolerancia. Los contactos (caras apoyadas,
// vástagos en taladros ajustados) y las diferencias de teselado (< tolerancia) no cuentan como interferencia.
import { instanceBBox, partGeometry } from "./geometry";

export const PENETRATION_TOL = 0.25;    // mm (el teselado de radios y taladros es < 0,1 mm)

function worldTris(inst, box) {
  const P = partGeometry(inst.part).positions, T = inst.T, out = [];
  for (let k = 0; k < P.length; k += 9) {
    const t = [0, 1, 2].map((j) => { const x = P[k + 3 * j], y = P[k + 3 * j + 1], z = P[k + 3 * j + 2];
      return [T[0][0] * x + T[0][1] * y + T[0][2] * z + T[0][3], T[1][0] * x + T[1][1] * y + T[1][2] * z + T[1][3], T[2][0] * x + T[2][1] * y + T[2][2] * z + T[2][3]]; });
    const lo = [0, 1, 2].map((a) => Math.min(t[0][a], t[1][a], t[2][a])), hi = [0, 1, 2].map((a) => Math.max(t[0][a], t[1][a], t[2][a]));
    if (lo.every((v, a) => v <= box[1][a]) && hi.every((v, a) => v >= box[0][a])) out.push({ t, lo, hi });
  }
  return out;
}
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

/** Profundidad de penetración aproximada entre dos triángulos (0 si sólo se tocan o no se cruzan). */
function penetration(A, B) {
  const nB = cross(sub(B[1], B[0]), sub(B[2], B[0])), lB = Math.hypot(...nB);
  const nA = cross(sub(A[1], A[0]), sub(A[2], A[0])), lA = Math.hypot(...nA);
  if (lA < 1e-12 || lB < 1e-12) return 0;
  const dA = A.map((p) => dot(sub(p, B[0]), nB) / lB), dB = B.map((p) => dot(sub(p, A[0]), nA) / lA);
  const pA = Math.min(Math.max(...dA), -Math.min(...dA)), pB = Math.min(Math.max(...dB), -Math.min(...dB));
  if (pA <= 0 || pB <= 0) return 0;                  // uno no atraviesa el plano del otro
  // intervalo de cada triángulo sobre la recta de intersección de los dos planos (Möller)
  const D = cross(nA, nB), Dl = Math.hypot(...D);
  if (Dl < 1e-12) return 0;
  const interval = (T, d) => {
    const pr = T.map((p) => dot(p, D) / Dl), ts = [];
    for (let i = 0; i < 3; i++) { const j = (i + 1) % 3; if ((d[i] > 0) !== (d[j] > 0)) ts.push(pr[i] + ((pr[j] - pr[i]) * d[i]) / (d[i] - d[j])); }
    return ts.length >= 2 ? [Math.min(...ts), Math.max(...ts)] : null;
  };
  const iA = interval(A, dA), iB = interval(B, dB);
  if (!iA || !iB) return 0;
  const ov = Math.min(iA[1], iB[1]) - Math.max(iA[0], iB[0]);
  return ov > 0 ? Math.min(pA, pB, ov) : 0;
}

export function checkInterferences(model, tol = PENETRATION_TOL) {
  const insts = model.instances;
  const boxes = insts.map((i) => instanceBBox(i));
  const found = [];
  let pairs = 0;
  for (let a = 0; a < insts.length; a++) for (let b = a + 1; b < insts.length; b++) {
    const A = boxes[a], B = boxes[b];
    const lo = [0, 1, 2].map((k) => Math.max(A[0][k], B[0][k])), hi = [0, 1, 2].map((k) => Math.min(A[1][k], B[1][k]));
    if (!lo.every((v, k) => v < hi[k] - 0.01)) continue;
    pairs++;
    const box = [lo.map((v) => v - 0.01), hi.map((v) => v + 0.01)];
    const ta = worldTris(insts[a], box), tb = worldTris(insts[b], box);
    let worst = 0;
    for (const x of ta) for (const y of tb) {
      if (x.lo[0] > y.hi[0] || y.lo[0] > x.hi[0] || x.lo[1] > y.hi[1] || y.lo[1] > x.hi[1] || x.lo[2] > y.hi[2] || y.lo[2] > x.hi[2]) continue;
      const p = penetration(x.t, y.t);
      if (p > worst) { worst = p; if (worst > 5 * tol) break; }
    }
    if (worst <= tol) {                 // sin cruces: ¿una pieza entera dentro de la otra?
      for (const [i, j, tris] of [[a, b, tb], [b, a, ta]]) {
        const [li, hi2] = boxes[i];
        if (!li.every((v, k) => v >= boxes[j][0][k] - 0.01 && hi2[k] <= boxes[j][1][k] + 0.01)) continue;
        const c = materialPoint(insts[i]);
        const bj = [boxes[j][0].map((v) => v - 0.5), boxes[j][1].map((v) => v + 0.5)];     // margen: las mallas son Float32
        if (c && inside(c, worldTris(insts[j], bj))) { worst = Infinity; break; }
      }
    }
    if (worst > tol) found.push({ a: insts[a].id, b: insts[b].id, a_name: insts[a].name, b_name: insts[b].name, penetration_mm: Number.isFinite(worst) ? Math.round(worst * 100) / 100 : null, volume_mm3: null });
  }
  return { pairs_checked: pairs, instances: insts.length, interferences: found, tolerance_mm3: null, tolerance_mm: tol, evaluated: true,
    method: "Cruce de triángulos de los sólidos facetados (penetración > tolerancia)" };
}

/** Punto dentro de una capa cerrada (paridad de cortes de un rayo en +X ligeramente inclinado). */
function inside(p, tris) {
  const d = [1, 0.000123, 0.000457];
  let n = 0;
  for (const { t } of tris) {
    const e1 = sub(t[1], t[0]), e2 = sub(t[2], t[0]), h = cross(d, e2), a = dot(e1, h);
    if (Math.abs(a) < 1e-12) continue;
    const f = 1 / a, s = sub(p, t[0]), u = f * dot(s, h);
    if (u < 0 || u > 1) continue;
    const q = cross(s, e1), v = f * dot(d, q);
    if (v < 0 || u + v > 1) continue;
    if (f * dot(e2, q) > 1e-9) n++;
  }
  return n % 2 === 1;
}

/** Un punto del material de la pieza: centro del mayor triángulo desplazado hacia dentro (no el centro de gravedad, que puede caer en un taladro). */
function materialPoint(inst) {
  const P = partGeometry(inst.part).positions, T = inst.T;
  let best = -1, at = 0;
  for (let k = 0; k < P.length; k += 9) {
    const a = [P[k], P[k + 1], P[k + 2]], b = [P[k + 3], P[k + 4], P[k + 5]], c = [P[k + 6], P[k + 7], P[k + 8]];
    const ar = Math.hypot(...cross(sub(b, a), sub(c, a)));
    if (ar > best) { best = ar; at = k; }
  }
  if (best <= 0) return null;
  const a = [P[at], P[at + 1], P[at + 2]], b = [P[at + 3], P[at + 4], P[at + 5]], c = [P[at + 6], P[at + 7], P[at + 8]];
  const n = cross(sub(b, a), sub(c, a)), ln = Math.hypot(...n);
  const p = [0, 1, 2].map((i) => (a[i] + b[i] + c[i]) / 3 - (n[i] / ln) * 0.05);
  return [0, 1, 2].map((r) => T[r][0] * p[0] + T[r][1] * p[1] + T[r][2] * p[2] + T[r][3]);
}
