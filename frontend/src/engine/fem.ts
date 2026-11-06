// @ts-nocheck
// Pórtico espacial por el método de rigidez (port de monxu/engineering/fem.py) con solver skyline LDLᵀ
// y renumeración Cuthill-McKee inversa para que el cálculo sea rápido en el navegador.

export class Frame3D {
  constructor(mergeTol = 0.5) {
    this.nodes = []; this.elements = []; this.fixed = new Map(); this.mergeTol = mergeTol; this.loads = {};
    this._grid = new Map();
  }
  _cell(p) { return p.map((c) => Math.floor(c / 1.0)); }
  node(p) {
    // misma semántica que Python: el primer nodo (índice menor) a distancia <= tolerancia
    const [cx, cy, cz] = this._cell(p);
    const r = Math.ceil(this.mergeTol);
    let best = -1;
    for (let i = cx - r; i <= cx + r; i++) for (let j = cy - r; j <= cy + r; j++) for (let k = cz - r; k <= cz + r; k++) {
      const lst = this._grid.get(`${i},${j},${k}`);
      if (!lst) continue;
      for (const n of lst) {
        const q = this.nodes[n];
        if (Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]) <= this.mergeTol && (best < 0 || n < best)) best = n;
      }
    }
    if (best >= 0) return best;
    this.nodes.push([+p[0], +p[1], +p[2]]);
    const id = this.nodes.length - 1, key = `${cx},${cy},${cz}`;
    if (!this._grid.has(key)) this._grid.set(key, []);
    this._grid.get(key).push(id);
    return id;
  }
  element(i, j, E, G, A, Iy, Iz, J, up, member = "") {
    const d = [0, 1, 2].map((k) => this.nodes[j][k] - this.nodes[i][k]);
    const L = Math.hypot(...d);
    if (L < 1e-6) throw new Error("Elemento de longitud nula");
    const x = d.map((c) => c / L);
    const ux = up[0] * x[0] + up[1] * x[1] + up[2] * x[2];
    let z = up.map((c, k) => c - x[k] * ux);
    const nz = Math.hypot(...z);
    if (nz < 1e-9) throw new Error("Vector 'up' paralelo a la barra");
    z = z.map((c) => c / nz);
    const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
    const e = { i, j, E, G, A, Iy, Iz, J, up, member, L, R: [x, y, z] };
    e.k = kLocal(e);
    this.elements.push(e);
    return this.elements.length - 1;
  }
  support(n, dofs = [true, true, true, false, false, false]) { this.fixed.set(n, dofs); }
  ndof() { return 6 * this.nodes.length; }
  loadVector(c) { if (!this.loads[c]) this.loads[c] = new Float64Array(this.ndof()); return this.loads[c]; }
  addNodalLoad(c, n, F = [0, 0, 0], M = [0, 0, 0]) {
    const f = this.loadVector(c);
    for (let k = 0; k < 3; k++) { f[6 * n + k] += F[k]; f[6 * n + 3 + k] += M[k]; }
  }

  solve(cases = null) {
    const nd = this.ndof(), nn = this.nodes.length;
    // ---- renumeración de nodos (Cuthill-McKee inversa) para reducir el perfil
    const adj = Array.from({ length: nn }, () => new Set());
    for (const e of this.elements) { adj[e.i].add(e.j); adj[e.j].add(e.i); }
    const order = [], seen = new Uint8Array(nn);
    const deg = (n) => adj[n].size;
    while (order.length < nn) {
      let start = -1;
      for (let n = 0; n < nn; n++) if (!seen[n] && (start < 0 || deg(n) < deg(start))) start = n;
      const q = [start]; seen[start] = 1;
      while (q.length) {
        const n = q.shift(); order.push(n);
        const nb = [...adj[n]].filter((m) => !seen[m]).sort((a, b) => deg(a) - deg(b));
        for (const m of nb) { seen[m] = 1; q.push(m); }
      }
    }
    order.reverse();
    const newIdx = new Int32Array(nn);
    order.forEach((n, k) => (newIdx[n] = k));
    // ---- numeración de GDL libres
    const eq = new Int32Array(nd).fill(-1);
    let neq = 0;
    for (const n of order) {
      const fx = this.fixed.get(n);
      for (let k = 0; k < 6; k++) if (!(fx && fx[k])) eq[6 * n + k] = neq++;
    }
    // ---- perfil (skyline): primera ecuación no nula por columna
    const first = new Int32Array(neq);
    for (let c = 0; c < neq; c++) first[c] = c;
    for (const e of this.elements) {
      const dofs = elemDofs(e).map((d) => eq[d]).filter((d) => d >= 0);
      const mn = Math.min(...dofs);
      for (const d of dofs) if (mn < first[d]) first[d] = mn;
    }
    const ptr = new Int32Array(neq + 1);   // columna c ocupa [ptr[c], ptr[c+1]) con filas first[c]..c
    for (let c = 0; c < neq; c++) ptr[c + 1] = ptr[c] + (c - first[c] + 1);
    const K = new Float64Array(ptr[neq]);
    const at = (r, c) => ptr[c] + (r - first[c]);   // r <= c
    for (const e of this.elements) {
      const kg = globalK(e);
      const dofs = elemDofs(e);
      for (let a = 0; a < 12; a++) {
        const ra = eq[dofs[a]];
        if (ra < 0) continue;
        for (let b = 0; b < 12; b++) {
          const cb = eq[dofs[b]];
          if (cb < 0 || ra > cb) continue;
          K[at(ra, cb)] += kg[a * 12 + b];
        }
      }
    }
    // ---- factorización LDLᵀ en skyline (Crout por columnas)
    const D = new Float64Array(neq);
    for (let j = 0; j < neq; j++) {
      const fj = first[j];
      for (let i = fj; i < j; i++) {
        const fi = Math.max(first[i], fj);
        let s = K[at(i, j)];
        for (let k = fi; k < i; k++) s -= K[at(k, i)] * K[at(k, j)];
        K[at(i, j)] = s;
      }
      let dj = K[at(j, j)];
      for (let k = fj; k < j; k++) {
        const u = K[at(k, j)];
        const l = u / D[k];
        dj -= u * l;
        K[at(k, j)] = l;
      }
      if (!(Math.abs(dj) > 1e-12)) throw new Error("Matriz de rigidez singular: estructura inestable o mal conectada");
      D[j] = dj;
      K[at(j, j)] = 1;
    }
    const U = {};
    for (const c of cases || Object.keys(this.loads)) {
      const F = this.loadVector(c);
      const x = new Float64Array(neq);
      for (let d = 0; d < nd; d++) if (eq[d] >= 0) x[eq[d]] = F[d];
      for (let j = 0; j < neq; j++) { let s = x[j]; for (let k = first[j]; k < j; k++) s -= K[at(k, j)] * x[k]; x[j] = s; }
      for (let j = 0; j < neq; j++) x[j] /= D[j];
      for (let j = neq - 1; j >= 0; j--) { const xj = x[j]; for (let k = first[j]; k < j; k++) x[k] -= K[at(k, j)] * xj; }
      const u = new Float64Array(nd);
      for (let d = 0; d < nd; d++) if (eq[d] >= 0) u[d] = x[eq[d]];
      U[c] = u;
    }
    return new Results(this, U);
  }
}

const elemDofs = (e) => [...[0, 1, 2, 3, 4, 5].map((k) => 6 * e.i + k), ...[0, 1, 2, 3, 4, 5].map((k) => 6 * e.j + k)];

export function kLocal(e) {
  const { L, E, G } = e;
  const k = new Float64Array(144);
  const set = (r, s, v) => { k[r * 12 + s] = v; k[s * 12 + r] = v; };
  const EA = (E * e.A) / L, GJ = (G * e.J) / L;
  set(0, 0, EA); set(6, 6, EA); set(0, 6, -EA);
  set(3, 3, GJ); set(9, 9, GJ); set(3, 9, -GJ);
  let a = (12 * E * e.Iz) / L ** 3, b = (6 * E * e.Iz) / L ** 2, c = (4 * E * e.Iz) / L, d = (2 * E * e.Iz) / L;
  for (const [r, s, v] of [[1, 1, a], [1, 5, b], [1, 7, -a], [1, 11, b], [5, 5, c], [5, 7, -b], [5, 11, d], [7, 7, a], [7, 11, -b], [11, 11, c]]) set(r, s, v);
  a = (12 * E * e.Iy) / L ** 3; b = (6 * E * e.Iy) / L ** 2; c = (4 * E * e.Iy) / L; d = (2 * E * e.Iy) / L;
  for (const [r, s, v] of [[2, 2, a], [2, 4, -b], [2, 8, -a], [2, 10, -b], [4, 4, c], [4, 8, b], [4, 10, d], [8, 8, a], [8, 10, b], [10, 10, c]]) set(r, s, v);
  return k;
}
/** T·u (bloques 3×3 de R) */
function toLocal(e, ug) {
  const out = new Float64Array(12);
  for (let b = 0; b < 4; b++) for (let r = 0; r < 3; r++)
    out[3 * b + r] = e.R[r][0] * ug[3 * b] + e.R[r][1] * ug[3 * b + 1] + e.R[r][2] * ug[3 * b + 2];
  return out;
}
function globalK(e) {
  // Tᵀ k T
  const kg = new Float64Array(144);
  const T = new Float64Array(144);
  for (let b = 0; b < 4; b++) for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) T[(3 * b + r) * 12 + 3 * b + c] = e.R[r][c];
  const kT = new Float64Array(144);
  for (let i = 0; i < 12; i++) for (let j = 0; j < 12; j++) {
    let s = 0;
    for (let m = 0; m < 12; m++) s += e.k[i * 12 + m] * T[m * 12 + j];
    kT[i * 12 + j] = s;
  }
  for (let i = 0; i < 12; i++) for (let j = 0; j < 12; j++) {
    let s = 0;
    for (let m = 0; m < 12; m++) s += T[m * 12 + i] * kT[m * 12 + j];
    kg[i * 12 + j] = s;
  }
  return kg;
}

export class Results {
  constructor(frame, U) { this.frame = frame; this.U = U; }
  combine(factors) {
    const u = new Float64Array(this.frame.ndof());
    for (const [c, f] of Object.entries(factors)) if (this.U[c]) { const v = this.U[c]; for (let i = 0; i < u.length; i++) u[i] += f * v[i]; }
    return u;
  }
  combineLoads(factors) {
    const F = new Float64Array(this.frame.ndof());
    for (const [c, f] of Object.entries(factors)) if (this.frame.loads[c]) { const v = this.frame.loads[c]; for (let i = 0; i < F.length; i++) F[i] += f * v[i]; }
    return F;
  }
  /** Esfuerzos en extremos en ejes locales [N1,Vy1,Vz1,T1,My1,Mz1,N2,...] (acción sobre la barra). */
  elementForces(k, u) {
    const e = this.frame.elements[k];
    const ug = elemDofs(e).map((d) => u[d]);
    const ul = toLocal(e, ug);
    const f = new Float64Array(12);
    for (let i = 0; i < 12; i++) { let s = 0; for (let j = 0; j < 12; j++) s += e.k[i * 12 + j] * ul[j]; f[i] = s; }
    return f;
  }
  reactions(u, F) {
    const fr = this.frame;
    const r = new Float64Array(fr.ndof());
    for (let k = 0; k < fr.elements.length; k++) {
      const e = fr.elements[k];
      const fl = this.elementForces(k, u);
      const dofs = elemDofs(e);
      for (let b = 0; b < 4; b++) for (let c = 0; c < 3; c++) {
        // Tᵀ f_local
        r[dofs[3 * b + c]] += e.R[0][c] * fl[3 * b] + e.R[1][c] * fl[3 * b + 1] + e.R[2][c] * fl[3 * b + 2];
      }
    }
    const out = new Map();
    for (const n of fr.fixed.keys()) out.set(n, [0, 1, 2, 3, 4, 5].map((k) => r[6 * n + k] - F[6 * n + k]));
    return out;
  }
}

const GX = [-0.9324695142031519, -0.6612093864662645, -0.2386191860831969, 0.2386191860831969, 0.6612093864662645, 0.9324695142031519];
const GW = [0.17132449237917027, 0.3607615730481387, 0.46791393457269104, 0.46791393457269104, 0.3607615730481387, 0.17132449237917027];

/** Cargas nodales equivalentes (funciones de forma lineales) de una densidad p(s) en [s0, s1]. */
export function lineLoadToNodes(sNodes, p, s0, s1) {
  const out = new Float64Array(sNodes.length);
  const integrate = (a, b, fn) => {
    if (b <= a) return 0.0;
    const xm = (a + b) / 2, xr = (b - a) / 2;
    let s = 0;
    for (let i = 0; i < 6; i++) s += GW[i] * fn(xm + xr * GX[i]);
    return s * xr;
  };
  const lo = sNodes[0], hi = sNodes.at(-1);
  out[0] += integrate(s0, Math.min(s1, lo), p);
  out[out.length - 1] += integrate(Math.max(s0, hi), s1, p);
  for (let k = 0; k < sNodes.length - 1; k++) {
    const a = sNodes[k], b = sNodes[k + 1];
    const lo_ = Math.max(a, s0), hi_ = Math.min(b, s1);
    if (hi_ <= lo_) continue;
    const Lk = b - a;
    out[k] += integrate(lo_, hi_, (s) => (p(s) * (b - s)) / Lk);
    out[k + 1] += integrate(lo_, hi_, (s) => (p(s) * (s - a)) / Lk);
  }
  return out;
}

// ============================================================================ placa (Navier)
export function navier(a, b, t, E, nu, q = 0.0, patch = null, at = null, terms = 79) {
  const D = (E * t ** 3) / (12 * (1 - nu ** 2));
  if (at === null) at = patch ? [patch[3], patch[4]] : [a / 2, b / 2];
  const [x, y] = at;
  let w = 0, Mx = 0, My = 0;
  const pi = Math.PI;
  const sx = new Float64Array(terms + 1), sy = new Float64Array(terms + 1);
  for (let m = 1; m <= terms; m++) { sx[m] = Math.sin((m * pi * x) / a); sy[m] = Math.sin((m * pi * y) / b); }
  let pm = null, pn = null, q0 = 0;
  if (patch) {
    const [P, u, v, xi, eta] = patch;
    q0 = P / (u * v);
    pm = new Float64Array(terms + 1); pn = new Float64Array(terms + 1);
    for (let m = 1; m <= terms; m++) {
      pm[m] = Math.sin((m * pi * xi) / a) * Math.sin((m * pi * u) / (2 * a));
      pn[m] = Math.sin((m * pi * eta) / b) * Math.sin((m * pi * v) / (2 * b));
    }
  }
  for (let m = 1; m <= terms; m++) for (let n = 1; n <= terms; n++) {
    let qmn = 0;
    if (q && m % 2 === 1 && n % 2 === 1) qmn += (16 * q) / (pi ** 2 * m * n);
    if (patch) qmn += ((16 * q0) / (pi ** 2 * m * n)) * pm[m] * pn[n];
    if (qmn === 0) continue;
    const am = m / a, bn = n / b;
    const Wmn = qmn / (D * pi ** 4 * (am ** 2 + bn ** 2) ** 2);
    const S = sx[m] * sy[n];
    w += Wmn * S;
    Mx += D * pi ** 2 * Wmn * (am ** 2 + nu * bn ** 2) * S;
    My += D * pi ** 2 * Wmn * (nu * am ** 2 + bn ** 2) * S;
  }
  const M = Math.max(Math.abs(Mx), Math.abs(My));
  return { w, Mx, My, sigma: (6 * M) / t ** 2, D, at };
}
