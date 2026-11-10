// @ts-nocheck
// Motor de verificación estructural (port de monxu/engineering/analysis.py).
import * as C from "./catalog";
import { Frame3D, lineLoadToNodes, navier } from "./fem";
import { instanceBBox, instanceCentroid } from "./geometry";
import { AUTO } from "./model";
import { f as fx, g, pyRound } from "./util";

export const OK = "CUMPLE", FAIL = "NO_CUMPLE", PENDING = "PENDIENTE";
/** Comprobación calculada con datos no certificados o hipótesis por validar, y comprobación que no procede. */
export const VAL = "PENDIENTE_VALIDACION", NA = "NO_APLICA";
const PHI0 = 1 / 200;
export const G_ACC = 9.81;
const MAX_ELEMENT = 100.0;
const N_ZERO = 1e-3;   // N: axil por debajo del cual la barra se considera sin compresión
const MASCULINE_WORDS = ["carro", "puesto", "armario", "escalón"];     // concordancia del texto de vuelco ("del carro vacío", "de la mesa vacía")

const status = (u) => (u === null || u === undefined ? PENDING : u <= 1.0 + 1e-9 ? OK : FAIL);
const check = (id, category, element, description, standard, value, limit, unit, utilization, st, combination = "", details = {}) =>
  ({ id, category, element, description, standard, value, limit, unit, utilization, status: st, combination, details });

export function bucklingChi(lam, alpha) {
  if (lam <= 0.2) return 1.0;
  const phi = 0.5 * (1 + alpha * (lam - 0.2) + lam ** 2);
  return Math.min(1.0, 1.0 / (phi + Math.sqrt(phi ** 2 - lam ** 2)));
}
export function sectionClass(prof, fy) {
  const eps = Math.sqrt(235 / fy);
  const ct = Math.max(prof.H - 3 * prof.t, prof.B - 3 * prof.t) / prof.t;
  if (ct <= 33 * eps) return 1;
  if (ct <= 38 * eps) return 2;
  if (ct <= 42 * eps) return 3;
  return 4;
}
/** Coeficiente dinámico de las cargas de uso (carros rodando sobre juntas y umbrales); 1 si no se indica. */
export const dynamicFactor = (ps) => Math.max(1.0, +(ps.COEF_DINAMICO || 1.0));
/** Lado de la huella cuadrada de la carga puntual: el del proyecto, el de la superficie o el del criterio general. */
export const patchSize = (ps, surf) => +(ps.HUELLA_CARGA_PUNTUAL || surf.patch_mm || C.criteria().point_load_patch_mm);
/** Límites de flecha (L/…) de barras y chapas y de desplome (H/…): los del proyecto o los del criterio general. */
export function deflectionRatios(ps) {
  const dl = C.criteria().deflection_limits;
  return [+(ps.LIMITE_FLECHA_BARRAS || dl.member_span_ratio), +(ps.LIMITE_FLECHA_CHAPA || dl.panel_span_ratio), +(ps.LIMITE_DESPLOME || dl.sway_height_ratio)];
}
/** Carros: la maniobra actúa en la dirección de la marcha; lateralmente (giros, empujes ocasionales) esta fracción. */
export const LATERAL_FACTOR_MOBILE = 0.5;
const DIRS = ["+X", "-X", "+Y", "-Y"];
const lc = (name) => name.slice(0, 1).toLowerCase() + name.slice(1);

/** Peso (N) y centro de gravedad del conjunto sin los tacos de anclaje, que quedan en el suelo. */
export function ownWeight(model) {
  let m = 0; const c = [0, 0, 0];
  for (const i of model.instances) {
    if (i.part.role === "anclaje") continue;
    const mi = i.part.mass, ci = instanceCentroid(i); m += mi; for (let j = 0; j < 3; j++) c[j] += mi * ci[j];
  }
  return [m * G_ACC, c.map((v) => v / m)];
}
function supportLevers(sups, cog) {
  const xs = sups.map((s) => s.point[0]), ys = sups.map((s) => s.point[1]);
  const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
  return { "+X": xmax - cog[0], "-X": cog[0] - xmin, "+Y": ymax - cog[1], "-Y": cog[1] - ymin };
}

/** Vuelco del conjunto vacío (EN 1990 EQU) en las cuatro direcciones; carros ("mobile"): empuje completo en la marcha (X)
 * y LATERAL_FACTOR_MOBILE en la lateral (Y). Dirección determinante (mayor Mdst/Mstb) y tracción de anclaje (la mayor). */
export function overturning(model, ps, st = model.structure) {
  const sups = st.supports ?? [];
  const H_N = ps.CARGA_HORIZONTAL || 0.0;
  if (!sups.length || !H_N) return null;
  const pf = C.criteria().partial_factors;
  const [Wtot, cog] = ownWeight(model);
  const levers = supportLevers(sups, cog);
  const xs = sups.map((s) => s.point[0]), ys = sups.map((s) => s.point[1]);
  // distancia de cada apoyo a la arista de vuelco de cada dirección
  const xM = Math.max(...xs), xm = Math.min(...xs), yM = Math.max(...ys), ym = Math.min(...ys);
  const dist = { "+X": xs.map((x) => xM - x), "-X": xs.map((x) => x - xm), "+Y": ys.map((y) => yM - y), "-Y": ys.map((y) => y - ym) };
  const hgt = st.push_height ?? st.worktop_height;
  const mobile = !!st.mobile;
  const force = {}, res = {};
  for (const d of DIRS) force[d] = H_N * (mobile && (d === "+Y" || d === "-Y") ? LATERAL_FACTOR_MOBILE : 1.0);
  for (const d of DIRS) {
    const Mstb = pf.gamma_G_stb * Wtot * levers[d], Mdst = pf.gamma_Q_dst * force[d] * hgt;
    // giro rígido alrededor de la arista: tracción de cada taco proporcional a su distancia a ella (T_i = M·d_i / Σd²)
    const Mnet = Math.max(0.0, Mdst - Mstb);
    const s2 = dist[d].reduce((a, v) => a + v * v, 0), s1 = dist[d].reduce((a, v) => a + v, 0);
    const T_per = s2 > 0 ? (Mnet * Math.max(...dist[d])) / s2 : (Mnet > 0 ? Infinity : 0.0);
    const T = s2 > 0 ? (Mnet * s1) / s2 : (Mnet > 0 ? Infinity : 0.0);
    res[d] = { ratio: Mstb > 0 ? Mdst / Mstb : Infinity, Mstb, Mdst, T, T_per, n: dist[d].filter((v) => v > 1e-6).length };
  }
  let dirn = DIRS[0], dT = DIRS[0];
  for (const d of DIRS) { if (res[d].ratio > res[dirn].ratio) dirn = d; if (res[d].T_per > res[dT].T_per) dT = d; }
  const r = res[dirn];
  return { dirn, ratio: r.ratio, Mstb: r.Mstb, Mdst: r.Mdst, lever: levers[dirn], force: force[dirn], H_N, hgt, mobile, Wtot, cog, levers,
    T: res[dT].T, dirn_T: dT, n_anchor: Math.max(1, res[dT].n), T_per: res[dT].T_per,
    admissible_N: Math.max(0, Math.floor(r.Mstb / (pf.gamma_Q_dst * hgt) / (force[dirn] / H_N))) };
}

/** EN 1993-1-5 §4.4: reducción de la pared más esbelta de un tubo rectangular en compresión uniforme (ψ = 1, kσ = 4),
 * aplicada a toda la sección (área y módulos), del lado de la seguridad. */
export function class4Rho(prof, fy) {
  const eps = Math.sqrt(235.0 / fy);
  const ct = Math.max(prof.H - 3 * prof.t, prof.B - 3 * prof.t) / prof.t;
  const lp = ct / (28.4 * eps * 2.0);
  return lp <= 0.673 ? 1.0 : Math.min(1.0, (lp - 0.22) / lp ** 2);
}
const vsub = (a, b) => a.map((v, i) => v - b[i]);
const vdot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// ============================================================================ modelo de barras
export class StructuralModel {
  constructor(model, maxElement = MAX_ELEMENT) {
    this.model = model; this.frame = new Frame3D(); this.members = {}; this.chains = {};
    this._build(maxElement);
  }
  _build(maxElement) {
    const m = this.model;
    const structural = m.instances.filter((i) => i.structural);
    const ends = Object.fromEntries(structural.map((i) => [i.id, [[...i.axis[0]], [...i.axis[1]]]]));
    const extra = Object.fromEntries(structural.map((i) => [i.id, []]));
    const femJ = m.joints.filter((j) => j.weld?.fem && ends[j.weld.fem.member] && ends[j.weld.fem.onto]).map((j) => j.weld.fem);
    for (let it = 0; it < 3; it++) for (const fm of femJ) {
      const [p0, p1] = ends[fm.onto];
      const q = m.instance(fm.member).axis[fm.end];
      const d = vsub(p1, p0);
      const s = Math.min(1, Math.max(0, vdot(vsub(q, p0), d) / vdot(d, d)));
      ends[fm.member][fm.end] = p0.map((v, k) => v + s * d[k]);
    }
    for (const fm of femJ) extra[fm.onto].push(ends[fm.member][fm.end]);
    for (const sup of m.structure.supports ?? []) if (extra[sup.leg]) extra[sup.leg].push([...sup.point]);
    for (const i of structural) {
      const mat = C.material(i.part.material), prof = i.part.profile, sp = prof.props;
      const [p0, p1] = ends[i.id];
      const d = vsub(p1, p0);
      const Lm = Math.hypot(...d);
      const x = d.map((v) => v / Lm);
      const set = new Set([0.0, pyRound(Lm, 3)]);
      for (const q of [p0, p1, ...extra[i.id]]) set.add(pyRound(vdot(vsub(q, p0), x), 3));
      const pts = [...set].sort((a, b) => a - b).filter((s) => s >= -1e-3 && s <= Lm + 1e-3);   // puntos redondeados a 0,001 mm
      const fine = [];
      for (let k = 0; k < pts.length - 1; k++) {
        const a = pts[k], b = pts[k + 1];
        const n = Math.max(1, Math.ceil((b - a) / maxElement));
        for (let j = 0; j < n; j++) fine.push(a + ((b - a) * j) / n);
      }
      fine.push(pts.at(-1));
      const chain = fine.map((s) => [s, this.frame.node(p0.map((v, k) => v + s * x[k]))]);
      const dedup = [];
      for (const [s, n] of chain) if (!dedup.length || dedup.at(-1)[1] !== n) dedup.push([s, n]);
      this.chains[i.id] = dedup;
      const elems = [];
      for (let k = 0; k < dedup.length - 1; k++)
        elems.push(this.frame.element(dedup[k][1], dedup[k + 1][1], mat.E, mat.G, sp.A, sp.Iy, sp.Iz, sp.It, i.up, i.id));
      this.members[i.id] = { instance: i, profile: prof, props: sp, material: mat, length: Lm, p0, p1, x, elements: elems, role: i.role };
    }
    const sups = m.structure.supports ?? [];
    if (sups.length) {
      const P = sups.map((s) => s.point);
      const argmin = (f) => { let b = 0; for (let k = 1; k < P.length; k++) if (f(k) < f(b)) b = k; return b; };
      const argmax = (f) => { let b = 0; for (let k = 1; k < P.length; k++) if (f(k) > f(b)) b = k; return b; };
      const k0 = argmin((k) => P[k][0] + P[k][1]);
      const dd = P.map((p) => vsub(p, P[k0]));
      const kx = argmax((k) => Math.abs(dd[k][0]) - Math.abs(dd[k][1]));
      // tres coacciones en planta (isostáticas): un pie fijo en X-Y y otro, alejado en X, deslizante en X
      sups.forEach((sup, k) => {
        const n = this.frame.node(sup.point);
        const fxr = k === k0, fyr = k === k0 || k === kx;
        this.frame.support(n, [fxr, fyr, true, false, false, false]);
        sup.node = n;
        sup.restraint = (fxr ? "X" : "") + (fyr ? "Y" : "") + "Z";
      });
    }
  }
  /** Peso de las barras: la masa real de cada pieza (la del BOM) repartida a lo largo de su eje de cálculo. */
  selfWeight(c = "G") {
    let total = 0.0;
    for (const mm of Object.values(this.members)) {
      const Lt = mm.elements.reduce((t, k) => t + this.frame.elements[k].L, 0);
      const w = (mm.instance.part.mass * G_ACC) / Lt;
      for (const k of mm.elements) {
        const e = this.frame.elements[k];
        const P = w * e.L;
        total += P;
        this.frame.addNodalLoad(c, e.i, [0, 0, -P / 2]);
        this.frame.addNodalLoad(c, e.j, [0, 0, -P / 2]);
      }
    }
    return total;
  }
  lineLoad(c, member, p, s0g, s1g, axis, breaks = []) {
    const chain = this.chains[member];
    const pairs = chain.map(([, n]) => [this.frame.nodes[n][axis], n]).sort((a, b) => a[0] - b[0]);
    const F = lineLoadToNodes(pairs.map((x) => x[0]), p, s0g, s1g, breaks);
    let tot = 0;
    pairs.forEach(([, n], k) => { this.frame.addNodalLoad(c, n, [0, 0, -F[k]]); tot += F[k]; });
    return tot;
  }
  surfaceLoad(c, level, q) {
    const gx = level.grid_x, [yf, yb] = level.grid_y;
    const b = yb - yf;
    const xm = [level.end[0], ...level.int, level.end[1]];
    let total = 0.0;
    for (let k = 0; k < gx.length - 1; k++) {
      const x0 = gx[k], x1 = gx[k + 1], a = x1 - x0;
      for (const mem of level.long) total += this.lineLoad(c, mem, (s) => q * Math.min(s - x0, x1 - s, b / 2), x0, x1, 0,
        [x0 + b / 2, x1 - b / 2, (x0 + x1) / 2]);
      for (const mem of [xm[k], xm[k + 1]]) total += this.lineLoad(c, mem, (s) => q * Math.min(s - yf, yb - s, a / 2), yf, yb, 1,
        [yf + a / 2, yb - a / 2, (yf + yb) / 2]);
    }
    return total;
  }
  /** Flecha propia de un voladizo: punta respecto a la tangente en su arranque (extremo 0), perpendicular a la barra. */
  cantileverDeflection(mid, u) {
    const chain = this.chains[mid], x = this.members[mid].x;
    const n0 = chain[0][1], n1 = chain.at(-1)[1];
    const r = vsub(this.frame.nodes[n1], this.frame.nodes[n0]);
    const th = [u[6 * n0 + 3], u[6 * n0 + 4], u[6 * n0 + 5]];
    const cr = [th[1] * r[2] - th[2] * r[1], th[2] * r[0] - th[0] * r[2], th[0] * r[1] - th[1] * r[0]];
    const rel = [0, 1, 2].map((k) => u[6 * n1 + k] - (u[6 * n0 + k] + cr[k]));
    const a = vdot(rel, x);
    return Math.hypot(rel[0] - a * x[0], rel[1] - a * x[1], rel[2] - a * x[2]);
  }
  memberDeflection(mid, u) {
    const chain = this.chains[mid], x = this.members[mid].x;
    const disp = chain.map(([, n]) => [u[6 * n], u[6 * n + 1], u[6 * n + 2]]);
    const s = chain.map((c) => c[0]);
    const perp = disp.map((d) => { const a = vdot(d, x); return d.map((v, k) => v - a * x[k]); });
    const Ls = s.at(-1) - s[0];
    let mx = 0;
    perp.forEach((p, k) => {
      const f = (s[k] - s[0]) / Ls;
      const ch = perp[0].map((v, j) => v + f * (perp.at(-1)[j] - v));
      mx = Math.max(mx, Math.hypot(p[0] - ch[0], p[1] - ch[1], p[2] - ch[2]));
    });
    return mx;
  }
}

// ============================================================================ análisis
/** [masa en kg, espesor en mm] de la chapa plegada o placa de una superficie de carga. */
export function surfaceSheet(part) {
  return [part.mass, part.kind === "chapa" ? part.spec.t : part.t];
}
/** Componentes bajo los apoyos: su peso va directamente al suelo y no carga la estructura. */
const BELOW_SUPPORT_ROLES = ["pie_nivelador", "rueda", "anclaje"];
/** Masas de las piezas que no son barras, chapas de superficie ni masas colgadas declaradas, en el nudo más próximo
 *  al centro de su envolvente (= analysis.lump_remaining_masses). */
export function lumpRemainingMasses(model, sm, c = "G") {
  const st = model.structure;
  const covered = new Set([...Object.keys(sm.members), ...(st.surfaces ?? []).map((s) => s.sheet_instance), ...(st.attached_instances ?? [])]);
  const nodes = sm.frame.nodes;
  let lumped = 0.0, below = 0.0, nLumped = 0;
  for (const i of model.instances) {
    if (covered.has(i.id)) continue;
    const m = i.part.mass;
    if (BELOW_SUPPORT_ROLES.includes(i.part.role)) { below += m; continue; }
    const [lo, hi] = instanceBBox(i);
    const cc = [0, 1, 2].map((k) => (lo[k] + hi[k]) / 2);
    let best = 0, bd = Infinity;
    nodes.forEach((q, n) => { const dx = q[0] - cc[0], dy = q[1] - cc[1], dz = q[2] - cc[2]; const dd = dx * dx + dy * dy + dz * dz; if (dd < bd) { best = n; bd = dd; } });
    sm.frame.addNodalLoad(c, best, [0, 0, -m * G_ACC]);
    lumped += m; nLumped++;
  }
  return { lumped_kg: lumped, n_lumped: nLumped, below_supports_kg: below };
}

/** Fuerzas horizontales equivalentes a la imperfección global φ·N en X (IX<c>) y en Y (IY<c>) para G y Q (= analysis.imperfection_cases). */
export function imperfectionCases(model, sm, casesV = ["G", "Q"]) {
  const fr = sm.frame;
  const sups = model.structure.supports ?? [];
  const z0 = sups.length ? Math.min(...sups.map((s) => s.point[2])) : Math.min(...fr.nodes.map((n) => n[2]));
  const h = Math.max(...fr.nodes.map((n) => n[2])) - z0;
  const alpha_h = Math.min(1.0, Math.max(2 / 3, 2 / Math.sqrt(Math.max(h, 1.0) / 1000)));
  const phi = PHI0 * alpha_h;
  const V = {};
  for (const c of casesV) {
    if (!(c in fr.loads)) continue;
    const F = fr.loads[c];
    let tot = 0.0;
    for (let n = 0; n < fr.nodes.length; n++) {
      const fz = F[6 * n + 2];
      if (fz !== 0.0) { fr.addNodalLoad(`IX${c}`, n, [-fz * phi, 0, 0]); fr.addNodalLoad(`IY${c}`, n, [0, -fz * phi, 0]); tot += -fz; }
    }
    V[c] = tot;
  }
  return { phi, alpha_h, h, V };
}
/** α_cr por el método de Horne (EN 1993-1-1 §5.2.1(4)B) en X y en Y (= analysis.alpha_cr). */
export function alphaCr(res, imp, fac) {
  const out = {};
  const nn = res.frame.nodes.length;
  for (const [d, comp] of [["X", 0], ["Y", 1]]) {
    const f = {};
    for (const c of Object.keys(imp.V)) if (c in fac) f[`I${d}${c}`] = fac[c];
    if (!Object.keys(f).length) continue;
    const u = res.combine(f);
    let delta = 0;
    for (let n = 0; n < nn; n++) delta = Math.max(delta, Math.abs(u[6 * n + comp]));
    out[d] = { alpha_cr: delta > 1e-12 ? (imp.phi * imp.h) / delta : Infinity, delta_mm: delta };
  }
  return out;
}
/** Normas que aplican al proyecto: por familia, material empleado, procesos presentes y normas de producto. */
export function applicableStandards(model) {
  const mats = new Set(model.instances.filter((i) => i.part.material).map((i) => i.part.material));
  const fams = new Set([...mats].map((m) => C.material(m).family));
  const mstd = new Set([...[...mats].map((m) => C.material(m).standard), ...model.instances.filter((i) => i.part.kind === "perfil").map((i) => i.part.profile.standard)]);
  const procs = new Set();
  if (model.joints.some((j) => j.kind === "soldadura")) procs.add("soldadura");
  if (model.instances.some((i) => i.part.kind === "chapa" || i.part.kind === "pletina")) procs.add("corte_termico");
  return C.standards(model.family, fams, procs, mstd);
}
/** CUMPLE / NO CUMPLE / PENDIENTE DE VALIDACIÓN / NO APLICABLE de cada comprobación (= analysis.classify_checks). */
export function classifyChecks(model, sm, checks) {
  const ps = model.params.values;
  const sups = model.structure.supports ?? [];
  const comp = sups.length ? C.component(sups[0].component) : null;
  const anc = model.instances.find((i) => i.part.role === "anclaje")?.part.data ?? null;
  const unguaranteed = new Set(model.instances.filter((i) => i.part.material && !C.material(i.part.material).fy_guaranteed).map((i) => C.material(i.part.material).code));
  for (const c of checks) {
    if (c.status !== OK) continue;
    let reason = null;
    if (c.id === "A.PIES" && comp && (comp.rated_load_source === "catalogo_generico" || comp.validation?.status !== "definido_por_norma"))
      reason = `capacidad de ${comp.name} de catálogo genérico, no certificada (ficha del fabricante pendiente)`;
    else if (c.id.startsWith("E.ANCLAJE") && anc && anc.rated_load_source === "catalogo_generico" && c.utilization !== null)
      reason = "resistencia del taco de catálogo genérico (ETA y soporte real pendientes)";
    else if (c.category === "placa" && unguaranteed.size) {
      const sf = (model.structure.surfaces ?? []).find((s) => s.label === c.element);
      if (sf && unguaranteed.has(model.instance(sf.sheet_instance).part.material)) reason = "límite elástico no garantizado por la norma del material (certificado 3.1 pendiente)";
    }
    if (reason) { c.status = VAL; c.details = { ...(c.details ?? {}), validacion: reason }; }
  }
  const na = C.criteria().national_annex ?? {};
  checks.push(check("N.ANEJO-NACIONAL", "criterios", "Conjunto", "Coeficientes parciales y de combinación", "EN 1990 / EN 1993 (valores recomendados)", null, null, "-", null,
    na.applied ? OK : VAL, "", na.applied ? { anejo: na.applied } : { validacion: na.note ?? "anejo nacional no fijado" }));
  const exterior = ps.ENTORNO === "exterior";
  checks.push(check("N.VIENTO-NIEVE", "acciones", "Conjunto", "Acciones de viento y nieve", "EN 1991-1-4 / EN 1991-1-3", null, null, "-", null, exterior ? VAL : NA, "",
    exterior ? { validacion: "uso en exterior: acciones de viento y nieve no evaluadas por la aplicación" } : { motivo: "uso en interior: no hay acciones de viento ni de nieve" }));
  const seen = new Set();
  for (const mm of Object.values(sm.members)) {
    const prof = mm.profile, mat = mm.material, key = `${prof.code}|${mat.code}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const eps = Math.sqrt(235 / mat.fy), r = (Math.max(prof.H, prof.B) - 3 * prof.t) / prof.t, lim = 72 * eps;
    checks.push(check(`B.ABOLL.${prof.code}.${mat.code}`, "resistencia", prof.code, `Abolladura por cortante del alma (${prof.code}, ${mat.code}): c/t = ${fx(r, 1)} ≤ 72ε/η = ${fx(lim, 1)}`,
      "EN 1993-1-1 §6.2.6(6) (η = 1)", pyRound(r, 2), pyRound(lim, 2), "-", null, r <= lim ? NA : VAL, "",
      r <= lim ? { motivo: "alma poco esbelta: no requiere comprobación de abolladura (EN 1993-1-5)" } : { validacion: "alma esbelta: comprobar abolladura según EN 1993-1-5" }));
  }
}

export function analyze(model, includeStability = true, includeWelds = true) {
  const crit = C.criteria();
  const pf = crit.partial_factors;
  const ps = model.params.values;
  const st = model.structure;
  const checks = [], hyp = [], pending = [];
  const limitations = [
    "Análisis elástico lineal de primer orden con imperfecciones globales equivalentes (EN 1993-1-1 §5.3.2) y sensibilidad a segundo orden por α_cr con el método de Horne (§5.2.1(4)B), válido para pórticos con poca compresión en las vigas; sin análisis de segundo orden explícito (con α_cr < 3 la verificación no se da por superada). Las imperfecciones de barra quedan incluidas en las curvas de pandeo.",
    "Uniones soldadas consideradas rígidas; excentricidades de unión entre ejes no modeladas.",
    "Chapas de encimera y balda verificadas como placas simplemente apoyadas en el emparrillado (Navier); no se considera su contribución a la rigidez del bastidor.",
    "Comprobaciones de barras por el método simplificado lineal de EN 1993-1-1 §6.2.1(7) y §6.3.3 con coeficientes de interacción unitarios (conservador).",
    "No se analizan concentraciones de tensiones locales, fatiga ni comportamiento dinámico.",
  ];
  const sm = new StructuralModel(model);
  const fr = sm.frame;
  const levels = st.levels ?? {};
  const cases = [];
  let Gm = sm.selfWeight("G");
  const G_members = Gm;
  let G_attached = 0.0;
  // masas no estructurales colgadas de barras (p. ej. un panel atornillado a los montantes)
  for (const am of st.attached_masses ?? []) {
    const chain = sm.chains[am.member];
    if (!chain) continue;
    let best = chain[0], bd = Infinity;
    for (const c of chain) { const q = fr.nodes[c[1]], dd = Math.hypot(q[0] - am.point[0], q[1] - am.point[1], q[2] - am.point[2]); if (dd < bd) { bd = dd; best = c; } }
    const P = am.mass_kg * G_ACC;
    fr.addNodalLoad("G", best[1], [0, 0, -P]);
    Gm += P;
    G_attached += P;
  }
  // resto de piezas y componentes (placas base, tuercas, tornillería, tapones...) en el nudo más próximo
  const lump = lumpRemainingMasses(model, sm, "G");
  Gm += lump.lumped_kg * G_ACC;
  let gSheets = 0.0;
  const phi = dynamicFactor(ps);
  if (phi > 1.0) hyp.push(`Cargas de uso y carga puntual amplificadas por el coeficiente dinámico φ = ${g(phi)} (rodadura sobre juntas, rampas o umbrales).`);
  const surfInfo = [], undefinedLoads = [];
  for (const surf of st.surfaces ?? []) {
    const lvl = levels[surf.level];
    const part = model.instance(surf.sheet_instance).part;
    const [sheetMass] = surfaceSheet(part);
    const area = surf.area_mm2;
    const gx = lvl.grid_x, gy = lvl.grid_y;
    const scale = area / ((gx.at(-1) - gx[0]) * (gy[1] - gy[0]));
    const q_g = (sheetMass * G_ACC) / area;
    gSheets += sm.surfaceLoad("G", lvl, q_g * scale);
    // carga propia de la superficie (p. ej. kN/m² por su área, en un peldaño) o la del parámetro; coeficiente dinámico (carros)
    const raw = "load_kg" in surf ? surf.load_kg : ps[surf.load_param];
    const loadKg = raw ? raw * phi : raw;
    const info = { surface: surf, level: lvl, q_g, sheet_mass: sheetMass, load_kg: loadKg, scale, part };
    if (loadKg) {
      const q = (loadKg * G_ACC) / area;
      const applied = sm.surfaceLoad("Q", lvl, q * scale);
      info.q = q;
      cases.push({ id: `Q_${surf.id}`, label: `Sobrecarga de uso uniforme en ${surf.label.toLowerCase()}`, value: `${g(loadKg)} kg (${fx(q * 1e6)} N/m²)`,
        total_N: pyRound(applied, 1) });
    } else if (loadKg != null) {        // 0 kg indicado: sin sobrecarga de uso (se verifica con el peso propio)
      info.q = 0.0;
      hyp.push(`${surf.label}: sin sobrecarga de uso (0 kg indicados); se verifica con su peso propio.`);
    } else {
      undefinedLoads.push(surf.load_param);
      pending.push(`Carga de uso sobre ${surf.label.toLowerCase()} no definida (${surf.load_param}): verificación de ${surf.label.toLowerCase()} pendiente.`);
    }
    surfInfo.push(info);
  }
  // cargas lineales uniformes sobre barras (p. ej. los brazos de una cantilever), en su tramo útil; a dos caras, además, el caso
  // asimétrico con sólo los brazos delanteros cargados (el que más flecta la columna)
  const lls = st.line_loads ?? [];
  const asym = lls.some((ll) => ll.side === "T");
  const llTot = { Q: 0.0, QA: 0.0 }, llKg = {};
  for (const ll of lls) {
    const kg = ps[ll.load_param];
    if (kg == null) {
      if (!undefinedLoads.includes(ll.load_param)) {
        undefinedLoads.push(ll.load_param);
        pending.push(`${st.line_load_label ?? "Carga lineal"} no definida (${ll.load_param}): verificación pendiente.`);
      }
      continue;
    }
    llKg[ll.load_param] = kg;
    if (!kg) continue;
    const [y0, y1] = ll.span;
    const w = (kg * phi * G_ACC) / (y1 - y0);
    llTot.Q += sm.lineLoad("Q", ll.member, () => w, y0, y1, ll.axis ?? 1);
    if (asym && ll.side !== "T") llTot.QA += sm.lineLoad("QA", ll.member, () => w, y0, y1, ll.axis ?? 1);
  }
  for (const [prm, kg] of Object.entries(llKg)) {
    const lab = st.line_load_label ?? "Carga lineal uniforme";
    if (kg) {
      const nLl = lls.filter((ll) => ll.load_param === prm).length;
      cases.push({ id: `Q_${prm}`, label: `${lab} (todas las barras cargadas)`, value: `${g(kg * phi)} kg × ${nLl}`, total_N: pyRound(llTot.Q, 1) });
      if (llTot.QA) {
        cases.push({ id: "QA", label: `${lab}: sólo ${st.line_load_side_label ?? "una cara"} (carga asimétrica)`,
          value: `${g(kg * phi)} kg × ${Math.floor(nLl / 2)}`, total_N: pyRound(llTot.QA, 1) });
        hyp.push(`Carga asimétrica: sólo ${st.line_load_side_label ?? "una cara"} cargados (descarga de la cara opuesta), además de todos los brazos cargados.`);
      }
    } else hyp.push(`${lab}: sin sobrecarga de uso (0 kg indicados); se verifica con el peso propio.`);
  }
  cases.unshift({ id: "G", label: "Peso propio (masas reales de barras, chapas, piezas y componentes)", value: `${fx((Gm + gSheets) / G_ACC, 1)} kg`,
    total_N: pyRound(Gm + gSheets, 1) });
  const selfWeightInfo = { members_kg: pyRound(G_members / G_ACC, 3), surfaces_kg: pyRound(gSheets / G_ACC, 3), attached_kg: pyRound(G_attached / G_ACC, 3),
    lumped_kg: pyRound(lump.lumped_kg, 3), n_lumped: lump.n_lumped, below_supports_kg: pyRound(lump.below_supports_kg, 3),
    applied_kg: pyRound((Gm + gSheets) / G_ACC, 3), total_kg: pyRound((Gm + gSheets) / G_ACC + lump.below_supports_kg, 3) };
  hyp.push(`Peso propio con la masa real de cada pieza (la del BOM): barras ${fx(selfWeightInfo.members_kg, 2)} kg, chapas de superficie ${fx(selfWeightInfo.surfaces_kg, 2)} kg, `
    + `masas colgadas ${fx(selfWeightInfo.attached_kg, 2)} kg y ${lump.n_lumped} piezas y componentes (${fx(selfWeightInfo.lumped_kg, 2)} kg) en el nudo más próximo a su centro; `
    + `${fx(selfWeightInfo.below_supports_kg, 2)} kg de pies, ruedas y tacos bajo los apoyos no cargan la estructura.`);
  const hasQ = "Q" in fr.loads;
  // verificación completa si hay sobrecarga o si todas las cargas de uso están indicadas (0 kg incluidos)
  const qDefined = hasQ || !undefinedLoads.length;
  const P_kg = (ps.CARGA_PUNTUAL || 0.0) * phi || null;
  const top = levels.SUP;
  if (P_kg && top) {
    const chain = sm.chains[top.long[0]];
    const smid = (chain[0][0] + chain.at(-1)[0]) / 2;
    let best = chain[0];
    for (const c of chain) if (Math.abs(c[0] - smid) < Math.abs(best[0] - smid)) best = c;
    fr.addNodalLoad("P", best[1], [0, 0, -P_kg * G_ACC]);
    cases.push({ id: "P", label: "Carga puntual en centro de vano del larguero delantero", value: `${g(P_kg)} kg`, total_N: pyRound(P_kg * G_ACC, 1) });
  }
  // cargas puntuales de accesorios (p. ej. apoyo del pie en el reposapiés) en el centro de su barra
  for (const pl of st.point_loads ?? []) {
    if (!(pl.member in sm.chains)) continue;
    const chain = sm.chains[pl.member];
    const smid = (chain[0][0] + chain.at(-1)[0]) / 2;
    let best = chain[0];
    for (const c of chain) if (Math.abs(c[0] - smid) < Math.abs(best[0] - smid)) best = c;
    fr.addNodalLoad(pl.id, best[1], [0, 0, -pl.load_N]);
    cases.push({ id: pl.id, label: pl.label, value: `${g(pl.load_N)} N`, total_N: pl.load_N });
    hyp.push(pl.hypothesis);
  }
  const H_N = ps.CARGA_HORIZONTAL || 0.0;
  const topNodes = [];
  const push = st.push_points;      // puntos de empuje propios (p. ej. el asa de un carro): [{member, z}]
  const nearest = (chain, zt) => {
    let best = chain[0];
    for (const c of chain) if (Math.abs(fr.nodes[c[1]][2] - zt) < Math.abs(fr.nodes[best[1]][2] - zt)) best = c;
    return best[1];
  };
  if (H_N && (push?.length || top)) {
    if (push?.length) for (const pp of push) topNodes.push(nearest(sm.chains[pp.member], pp.z));
    else for (const lid of st.leg_ids) topNodes.push(nearest(sm.chains[lid], top.z - model.instance(top.long[0]).part.profile.H / 2));
    for (const n of topNodes) { fr.addNodalLoad("HX", n, [H_N / topNodes.length, 0, 0]); fr.addNodalLoad("HY", n, [0, H_N / topNodes.length, 0]); }
    cases.push({ id: "HX/HY", label: st.push_label ?? "Empuje horizontal en el plano de la encimera (direcciones X e Y)", value: `${g(H_N)} N`, total_N: H_N });
    if (model.params.sources.CARGA_HORIZONTAL === "defecto") hyp.push(`Empuje horizontal de ${g(H_N)} N: ${st.push_note ?? crit.horizontal_service_load_note}`);
  }
  // ---------------------------------------------------------------- imperfecciones globales (EN 1993-1-1 §5.3.2)
  const imp = imperfectionCases(model, sm);
  const gG = pf.gamma_G, gQ = pf.gamma_Q, psi = pf.psi0_Q;
  const V_Ed = gG * (imp.V.G ?? 0.0) + gQ * (imp.V.Q ?? 0.0);
  const H_Ed = "HX" in fr.loads ? gQ * H_N : 0.0;
  const useImp = !(H_Ed >= 0.15 * V_Ed && 0.15 * V_Ed > 0);       // §5.3.2(4)B: se pueden omitir si H_Ed ≥ 0,15·V_Ed
  let uls = { "ELU-1": { G: gG } };
  if (hasQ) uls["ELU-1"] = { G: gG, Q: gQ };
  if ("HX" in fr.loads) {
    uls["ELU-2"] = { G: gG, Q: gQ * psi, HX: gQ };
    uls["ELU-3"] = { G: gG, Q: gQ * psi, HY: gQ };
    if (hasQ) uls["ELU-4"] = { G: gG, Q: gQ, HX: gQ * psi };
  }
  if ("P" in fr.loads) uls["ELU-5"] = { G: gG, P: gQ };
  if ("QA" in fr.loads) uls["ELU-QA"] = { G: gG, QA: gQ };
  // sin sobrecarga (0 kg indicados) la combinación de servicio es la del peso propio: apoyos y flechas también se comprueban
  const sls = hasQ ? { "ELS-1": { G: 1.0, Q: 1.0 } } : { "ELS-1": { G: 1.0 } };
  if ("P" in fr.loads) sls["ELS-2"] = { G: 1.0, P: 1.0 };
  if ("QA" in fr.loads) sls["ELS-QA"] = { G: 1.0, QA: 1.0 };
  for (const pl of st.point_loads ?? []) if (pl.id in fr.loads) { uls[`ELU-${pl.id}`] = { G: gG, [pl.id]: gQ }; sls[`ELS-${pl.id}`] = { G: 1.0, [pl.id]: 1.0 }; }
  if ("HX" in fr.loads) { sls["ELS-3"] = { HX: 1.0 }; sls["ELS-4"] = { HY: 1.0 }; }
  const res = fr.solve();
  // sensibilidad a segundo orden y amplificación de las acciones horizontales (EN 1993-1-1 §5.2.1, §5.2.2(5)B)
  const acr = alphaCr(res, imp, { G: gG, Q: gQ });
  const kAmp = Object.fromEntries(Object.entries(acr).map(([d, v]) => [d, v.alpha_cr >= 3.0 && v.alpha_cr < 10.0 ? 1 / (1 - 1 / v.alpha_cr) : 1.0]));
  if (useImp) {            // fuerzas equivalentes en las combinaciones de ELU, con los factores de G y Q de cada una
    const nu = {};
    for (const [cname, f] of Object.entries(uls)) {
      nu[cname] = { ...f };
      if (cname === "ELU-1") for (const d of ["X", "Y"]) {
        const add = {};
        for (const c of Object.keys(imp.V)) if (c in f) add[`I${d}${c}`] = f[c];
        nu[`ELU-1${d}`] = { ...f, ...add };
      }
    }
    for (const [cname, d] of [["ELU-2", "X"], ["ELU-3", "Y"], ["ELU-4", "X"]]) if (cname in nu)
      for (const c of Object.keys(imp.V)) if (c in nu[cname]) nu[cname][`I${d}${c}`] = nu[cname][c];
    uls = nu;
  }
  for (const f of Object.values(uls)) for (const cs of Object.keys(f)) {   // 3 ≤ α_cr < 10: acciones horizontales × 1/(1 − 1/α_cr)
    const d = cs === "HX" || cs.startsWith("IX") ? "X" : cs === "HY" || cs.startsWith("IY") ? "Y" : null;
    if (d && (kAmp[d] ?? 1.0) !== 1.0) f[cs] = f[cs] * kAmp[d];
  }
  const all = { ...uls, ...sls };
  const U = Object.fromEntries(Object.entries(all).map(([c, f]) => [c, res.combine(f)]));
  const phiImp = imp.phi;
  checks.push(check("S.IMPERF", "estabilidad", "Estructura", `Imperfecciones globales equivalentes φ = φ0·αh·αm = 1/200 × ${fx(imp.alpha_h, 3)} × 1 = ${fx(phiImp, 5)} (h = ${fx(imp.h)} mm)`,
    "EN 1993-1-1 §5.3.2(3) y (4)B", pyRound(phiImp, 6), null, "rad", null, useImp ? OK : NA, "ELU",
    { h_mm: imp.h, alpha_h: imp.alpha_h, alpha_m: 1.0, H_Ed_N: H_Ed, V_Ed_N: V_Ed, incluidas: useImp }));
  if (useImp) hyp.push(`Imperfección global: fuerzas horizontales equivalentes φ·N (φ = ${fx(phiImp, 5)}, αm = 1 del lado de la seguridad) en X y en Y con las cargas verticales G y Q de cada combinación de ELU.`);
  else hyp.push(`Imperfección global omitida: H_Ed = ${fx(H_Ed)} N ≥ 0,15·V_Ed = ${fx(0.15 * V_Ed)} N (EN 1993-1-1 §5.3.2(4)B).`);
  for (const [d, v] of Object.entries(acr)) {
    const a = v.alpha_cr, fin = Number.isFinite(a);
    const note = a >= 10 ? "análisis de primer orden suficiente (α_cr ≥ 10)" : a >= 3 ? `efectos de segundo orden por amplificación 1/(1 − 1/α_cr) = ${fx(kAmp[d], 3)} de las acciones horizontales`
      : "α_cr < 3: requiere análisis de segundo orden, no disponible en este método";
    checks.push(check(`S.ALFA-CR-${d}`, "estabilidad", "Estructura", `Sensibilidad a efectos de segundo orden en ${d} (método de Horne): ${note}`,
      "EN 1993-1-1 §5.2.1(3) y (4)B, §5.2.2(5)B", fin ? pyRound(a, 2) : null, 3.0, "-", fin ? pyRound(3.0 / a, 4) : 0.0, fin ? status(3.0 / a) : OK, "ELU",
      { delta_mm: v.delta_mm, h_mm: imp.h, k_amplificacion: kAmp[d] }));
  }

  // ---------------------------------------------------------------- barras
  const alpha = crit.imperfection_factors[crit.buckling_curve_cold_formed_hollow];
  const betaLeg = crit.effective_length_factors.leg_sway;
  const memberResults = {};
  const class4 = new Set();
  const cantilevers = new Set(st.cantilevers ?? []);
  if (cantilevers.size) {
    const [rm, , rs] = deflectionRatios(ps);
    hyp.push(`Brazos en voladizo: flecha propia en punta (respecto a la tangente en el arranque) limitada a 2L/${g(rm)} = L/${g(rm / 2)}; `
      + `el desplome de las columnas bajo la carga vertical se limita a H/${g(rs)}.`);
  }
  for (const [mid, mm] of Object.entries(sm.members)) {
    const { material: mat, profile: prof, props: sp } = mm;
    const fy = mat.fy, gM0 = mat.gamma_M0, gM1 = mat.gamma_M1;
    const cls = sectionClass(prof, fy);
    const rho = cls === 4 ? class4Rho(prof, fy) : 1.0;           // clase 4: sección eficaz (EN 1993-1-5)
    const Aeff = sp.A * rho;
    const Wy = cls <= 2 ? sp.Wpl_y : sp.Wel_y * rho, Wz = cls <= 2 ? sp.Wpl_z : sp.Wel_z * rho;
    const NRd = (Aeff * fy) / gM0, MyRd = (Wy * fy) / gM0, MzRd = (Wz * fy) / gM0;
    const VzRd = (sp.Av_z * fy) / Math.sqrt(3) / gM0, VyRd = (sp.Av_y * fy) / Math.sqrt(3) / gM0;
    const isLeg = mm.role === "pata" || mm.role === "montante";
    const beta = isLeg ? betaLeg : crit.effective_length_factors.braced_member;
    const Lcr = beta * mm.length;
    const lam1 = Math.PI * Math.sqrt(mat.E / fy);
    const lam = Lcr / Math.min(sp.iy, sp.iz) / lam1 * Math.sqrt(rho);     // EN 1993-1-1 (6.51) con A_eff
    const chi = bucklingChi(lam, alpha);
    let best = { u: -1 };
    for (const [cname, u] of Object.entries(U)) {
      if (!(cname in uls)) continue;
      let Nc = 0.0, My_ = 0.0, Mz_ = 0.0, Vmax = 0.0, ucs = 0.0;
      for (const k of mm.elements) {
        const f = res.elementForces(k, u);
        for (const end of [0, 6]) {
          const N = end === 6 ? f[6] : -f[0];
          const My = Math.abs(f[end + 4]), Mz = Math.abs(f[end + 5]);
          const Vy = Math.abs(f[end + 1]), Vz = Math.abs(f[end + 2]);
          ucs = Math.max(ucs, Math.abs(N) / NRd + My / MyRd + Mz / MzRd);
          Nc = Math.min(Nc, N);
          My_ = Math.max(My_, My); Mz_ = Math.max(Mz_, Mz);
          Vmax = Math.max(Vmax, Vy / VyRd, Vz / VzRd);
        }
      }
      const ub = Nc < -N_ZERO ? Math.abs(Nc) / ((chi * Aeff * fy) / gM1) + My_ / ((Wy * fy) / gM1) + Mz_ / ((Wz * fy) / gM1) : 0;
      const uAll = Math.max(ucs, ub, Vmax);
      if (uAll > best.u) best = { u: uAll, ucs, ub, uv: Vmax, combo: cname, Nc, My: My_, Mz: Mz_ };
    }
    const details = { clase: cls, N_Rd_kN: NRd / 1e3, My_Rd_kNm: MyRd / 1e6, Mz_Rd_kNm: MzRd / 1e6, L_mm: mm.length, Lcr_mm: Lcr, lambda_rel: lam, chi,
      N_Ed_kN: best.Nc / 1e3, My_Ed_kNm: best.My / 1e6, Mz_Ed_kNm: best.Mz / 1e6, u_seccion: best.ucs, u_pandeo: best.ub, u_cortante: best.uv };
    if (cls === 4) { details.rho_clase4 = rho; class4.add(`${prof.code} en ${mat.code} (ρ = ${rho.toFixed(3)})`); }
    let stt = status(best.u);
    if (!qDefined && stt === OK) stt = PENDING;
    checks.push(check(`B.${mid}`, isLeg ? "pandeo" : "resistencia", mid, `${mm.instance.name} (${prof.code}, ${mat.code}): resistencia de sección`
      + (best.Nc < -N_ZERO ? " y pandeo por flexión" : ""), "EN 1993-1-1 §6.2, §6.3.1, §6.3.3", pyRound(best.u, 4), 1.0, "-", pyRound(best.u, 4), stt, best.combo, details));
    memberResults[mid] = best.u;
    if (!isLeg && Object.keys(sls).length) {
      const cant = cantilevers.has(mid);
      let dmax = 0.0, cmax = "";
      for (const cname of Object.keys(sls)) if (cname === "ELS-1" || cname === "ELS-2" || cname === "ELS-QA" || cname.startsWith("ELS-F")) {
        const dv = cant ? sm.cantileverDeflection(mid, U[cname]) : sm.memberDeflection(mid, U[cname]);
        if (dv > dmax) { dmax = dv; cmax = cname; }
      }
      if (cmax) {
        const r = deflectionRatios(ps)[0];
        // voladizo: luz física del brazo (desde la cara de la columna)
        const lim = cant ? (2 * mm.instance.part.length) / r : mm.length / r;
        checks.push(check(`D.${mid}`, "deformacion", mid, cant ? `${mm.instance.name}: flecha en punta del voladizo` : `${mm.instance.name}: flecha relativa`,
          cant ? `EN 1990 A1.4 (límite 2L/${g(r)} adoptado en voladizo)` : `EN 1990 A1.4 (límite L/${g(r)} adoptado)`,
          pyRound(dmax, 3), pyRound(lim, 3), "mm", pyRound(dmax / lim, 4), status(dmax / lim), cmax));
      }
    }
  }
  if (class4.size) hyp.push("Secciones clase 4 (" + [...class4].sort().join(", ") + "): sección eficaz según EN 1993-1-5 §4.4 con la "
    + "reducción de la pared más esbelta en compresión uniforme aplicada a toda la sección (del lado de la seguridad).");
  // ---------------------------------------------------------------- desplome
  if (U["ELS-3"] && topNodes.length) {
    const r = deflectionRatios(ps)[2];
    const lim = (st.sway_height ?? st.worktop_height) / r;     // altura del punto de empuje (encimera o asa)
    for (const [cname, comp] of [["ELS-3", 0], ["ELS-4", 1]]) {
      const dx = Math.max(...topNodes.map((n) => Math.abs(U[cname][6 * n + comp])));
      checks.push(check(`S.${cname}`, "deformacion", "Estructura", `Desplome horizontal en dirección ${comp === 0 ? "X" : "Y"} bajo empuje de servicio`,
        `Criterio adoptado H/${g(r)}`, pyRound(dx, 3), pyRound(lim, 3), "mm", pyRound(dx / lim, 4), status(dx / lim), cname));
    }
  }
  // voladizos: las columnas se desploman bajo la propia carga vertical (brazos a una cara, o cargados a un lado)
  if (cantilevers.size && st.push_points?.length) {
    const r = deflectionRatios(ps)[2];
    const lim = (st.sway_height ?? st.worktop_height) / r;
    const cnodes = st.push_points.map((pp) => nearest(sm.chains[pp.member], pp.z));
    let worst = [0.0, "", 1];
    for (const cname of ["ELS-1", "ELS-QA"]) if (U[cname]) for (const comp of [0, 1]) {
      const dv = Math.max(...cnodes.map((n) => Math.abs(U[cname][6 * n + comp])));
      if (dv > worst[0]) worst = [dv, cname, comp];
    }
    if (worst[1]) {
      const [dv, cname, comp] = worst;
      checks.push(check("S.ELS-G", "deformacion", "Estructura", `Desplome de las columnas en dirección ${comp === 0 ? "X" : "Y"} bajo la carga `
        + "vertical de servicio (brazos en voladizo)", `Criterio adoptado H/${g(r)}`, pyRound(dv, 3), pyRound(lim, 3), "mm", pyRound(dv / lim, 4),
      status(dv / lim), cname));
    }
  }
  // ---------------------------------------------------------------- reacciones y apoyos
  const reactions = [];
  const sups = st.supports ?? [];
  for (const cname of Object.keys(all)) {
    const F = res.combineLoads(all[cname]);
    const R = res.reactions(U[cname], F);
    for (const sup of sups) {
      const r = R.get(sup.node);
      reactions.push({ combination: cname, support: sup.instance, Rx_N: pyRound(r[0], 1), Ry_N: pyRound(r[1], 1), Rz_N: pyRound(r[2], 1) });
    }
  }
  if (sups.length) {
    const comp = C.component(sups[0].component);
    const cap = comp.rated_load_kg * G_ACC;
    const supWord = comp.category.startsWith("ruedas") ? "Ruedas" : "Pies niveladores";
    // peor reacción de servicio con gravedad (uniforme, carga puntual, reposapiés...), no sólo ELS-1
    let rmax = -Infinity, slsV = null;
    for (const cname of Object.keys(sls).filter((c) => "G" in sls[c]))
      for (const r of reactions) if (r.combination === cname && r.Rz_N > rmax) { rmax = r.Rz_N; slsV = cname; }
    if (slsV) {
      checks.push(check("A.PIES", "apoyos", supWord, `Reacción máxima de servicio frente a la capacidad nominal de ${comp.name}`,
        "Dato de catálogo genérico — confirmar con la ficha técnica del proveedor", pyRound(rmax, 1), pyRound(cap, 1), "N", pyRound(rmax / cap, 4),
        status(rmax / cap), slsV, { fuente_capacidad: comp.rated_load_source ?? null }));
      if (comp.rated_load_source === "catalogo_generico") hyp.push(`Capacidad de ${comp.name}: ${comp.rated_load_kg} kg (catálogo genérico de referencia, `
        + "debe confirmarse con la ficha técnica del proveedor).");
    } else checks.push(check("A.PIES", "apoyos", supWord, `Capacidad de los ${supWord.toLowerCase()}`, "—", null, cap, "N", null, PENDING, "", {}));
  }
  // ---------------------------------------------------------------- placas
  const dl = deflectionRatios(ps)[1];
  for (const info of surfInfo) {
    const { surface: surf, level: lvl, part } = info;
    const mat = C.material(part.material);
    const t = surfaceSheet(part)[1];
    // placa perforada: rigidez y resistencia reducidas por la eficiencia de ligamento (p − d)/p
    const eta = surf.ligament_efficiency ?? 1.0;
    const perf = eta < 1 ? ` (placa perforada, η = ${eta.toFixed(2)})` : "";
    const gx = lvl.grid_x, [yf, yb] = lvl.grid_y;
    let a = 0;
    for (let k = 0; k < gx.length - 1; k++) a = Math.max(a, gx[k + 1] - gx[k]);
    const b = yb - yf, sid = surf.id;
    if (!mat.structural) {
      checks.push(check(`PL.${sid}`, "placa", surf.label, `${surf.label}: material sin propiedades resistentes en catálogo`, "—", null, null, "-", null, PENDING));
      continue;
    }
    if (!mat.fy_guaranteed) hyp.push(`${mat.name}: la norma ${mat.standard} no garantiza límite elástico mínimo; se adopta fy = ${mat.fy} MPa como hipótesis `
      + "(confirmar con certificado 3.1).");
    if (info.load_kg != null) {
      const qu = gG * info.q_g + gQ * info.q, qs = info.q_g + info.q;
      const ru0 = navier(a, b, t, mat.E, mat.nu, qu), rs0 = navier(a, b, t, mat.E, mat.nu, qs);
      const ru = { ...ru0, sigma: ru0.sigma / eta }, rs = { ...rs0, w: rs0.w / eta };
      const fyd = mat.fy / mat.gamma_M0;
      checks.push(check(`PL.${sid}.S`, "placa", surf.label, `${surf.label}: tensión de flexión en panel ${fx(a)}×${fx(b)} mm, t = ${g(t)} mm (carga uniforme)${perf}`,
        "Teoría de placas (Navier) + EN 1993-1-1 §6.2.1", pyRound(ru.sigma, 2), pyRound(fyd, 1), "MPa", pyRound(ru.sigma / fyd, 4), status(ru.sigma / fyd),
        "ELU-1", { a, b, q_MPa: qu }));
      const lim = Math.min(a, b) / dl;
      const det = { a, b, q_MPa: qs };
      if (rs.w > t / 2) det.nota = "Flecha superior a t/2: el efecto membrana (no considerado) reduce la flecha real; el resultado lineal es conservador.";
      checks.push(check(`PL.${sid}.D`, "placa", surf.label, `${surf.label}: flecha del panel ${fx(a)}×${fx(b)} mm`, `Criterio adoptado L/${dl}`,
        pyRound(rs.w, 3), pyRound(lim, 3), "mm", pyRound(rs.w / lim, 4), status(rs.w / lim), "ELS-1", det));
    } else checks.push(check(`PL.${sid}`, "placa", surf.label, `${surf.label}: verificación de chapa`, "—", null, null, "-", null, PENDING, "",
      { motivo: `${surf.load_param} sin definir` }));
    if ((sid === "encimera" || surf.point_load) && P_kg) {
      const size = patchSize(ps, surf);        // huella de la carga concentrada
      const rp0 = navier(a, b, t, mat.E, mat.nu, gG * info.q_g, [gQ * P_kg * G_ACC, size, size, a / 2, b / 2], null, 121);
      const rp = { ...rp0, sigma: rp0.sigma / eta };
      const fyd = mat.fy / mat.gamma_M0;
      checks.push(check(`PL.${sid}.P`, "placa", surf.label, `${surf.label}: carga puntual de ${g(P_kg)} kg sobre huella ${g(size)}×${g(size)} mm en el centro del panel`,
        "Navier + EN 1993-1-1 §6.2.1", pyRound(rp.sigma, 2), pyRound(fyd, 1), "MPa", pyRound(rp.sigma / fyd, 4), status(rp.sigma / fyd), "ELU-5"));
    }
  }
  // ---------------------------------------------------------------- soldaduras
  if (includeWelds) {
    for (const j of model.joints) {
      const fm = j.weld?.fem;
      if (!fm || !sm.members[fm.member]) continue;
      const mm = sm.members[fm.member];
      const mat = mm.material, prof = mm.profile;
      const aw = j.weld.a;
      const chain = sm.chains[fm.member];
      const node = fm.end === 0 ? chain[0][1] : chain.at(-1)[1];
      const elem = mm.elements.find((k) => fr.elements[k].i === node || fr.elements[k].j === node);
      const Aw = aw * 2 * (prof.B + prof.H);
      const Wy = aw * (prof.B * prof.H + prof.H ** 2 / 3), Wz = aw * (prof.H * prof.B + prof.B ** 2 / 3);
      const Aenc = prof.B * prof.H;
      const fvw = mat.fu / (Math.sqrt(3) * mat.beta_w * mat.gamma_M2);
      let best = [0.0, ""];
      for (const cname of Object.keys(uls)) {
        const f = res.elementForces(elem, U[cname]);
        const o = fr.elements[elem].i === node ? 0 : 6;
        const [N, Vy, Vz, T, My, Mz] = [0, 1, 2, 3, 4, 5].map((k) => Math.abs(f[o + k]));
        const sigma = N / Aw + My / Wy + Mz / Wz;
        const tau = Math.hypot(Vy, Vz) / Aw + T / (2 * Aenc * aw);
        const s = Math.hypot(sigma, tau);
        if (s > best[0]) best = [s, cname];
      }
      const stt = qDefined ? status(best[0] / fvw) : PENDING;
      checks.push(check(`W.${j.id}`, "soldadura", j.id, `${j.description}: cordón en ángulo a${g(aw)} perimetral (${prof.code})`,
        "EN 1993-1-8 §4.5.3.3 (método simplificado)", pyRound(best[0], 2), pyRound(fvw, 1), "MPa", pyRound(best[0] / fvw, 4), stt, best[1],
        { a_mm: aw, longitud_mm: j.weld.length }));
    }
    if (model.joints.some((j) => (j.weld?.a ?? 3) < 3)) hyp.push("Cordones con garganta a < 3 mm en perfiles de pared delgada: fuera del ámbito de EN 1993-1-8 "
      + "§4.5.2(2); requieren procedimiento de soldeo cualificado (EN ISO 15614-1) y verificación según EN 1993-1-3.");
  }
  // ---------------------------------------------------------------- estabilidad
  let stability = null;
  const ov = includeStability ? overturning(model, ps, st) : null;
  if (ov) {
    const w = st.product_word ?? "mesa";
    const what = MASCULINE_WORDS.includes(w) ? `del ${w} vacío` : `de la ${w} vacía`;
    const { dirn, H_N } = ov;
    // empuje de servicio que el conjunto vacío resiste sin anclaje (EQU): γQ·H·h = γG,stb·W·brazo
    const det = { peso_N: ov.Wtot, cdg_mm: ov.cog.map((v) => pyRound(v, 1)), brazo_mm: ov.lever, empuje_admisible_N: ov.admissible_N };
    const loadTxt = ov.mobile ? `maniobra de ${g(H_N)} N en la dirección de la marcha y ${g(H_N * LATERAL_FACTOR_MOBILE)} N lateral` : `empuje horizontal de ${g(H_N)} N`;
    if (ov.mobile) hyp.push(`Maniobra del carro: ${g(H_N)} N en la dirección de la marcha y ${(LATERAL_FACTOR_MOBILE * 100).toFixed(0)} % `
      + "en la lateral (giros y empujes ocasionales), a la altura de empuje, con el carro vacío.");
    if (ps.ANCLAJE === "al_suelo") {
      const { T, n_anchor: nA, T_per } = ov;
      Object.assign(det, { traccion_total_N: pyRound(T, 1), anclajes_traccionados: nA, traccion_por_anclaje_N: pyRound(T_per, 1), direccion_traccion: ov.dirn_T });
      const code = ps.TACO_ANCLAJE;
      const anchor = code != null && code !== AUTO && code in C.components() ? C.component(code) : null;
      if (anchor) {
        const cap = +anchor.tension_kN * 1000.0, u = T_per / cap;
        hyp.push(`Anclaje al suelo: un ${lc(anchor.name)} por apoyo, a través de la base del pie; tracción admisible ${g(anchor.tension_kN)} kN en hormigón `
          + "C20/25 no fisurado (catálogo genérico de referencia, a confirmar con la ETA del taco y el soporte real).");
        checks.push(check("E.ANCLAJE", "estabilidad", "Anclajes", `Tracción por taco de anclaje bajo ${loadTxt} (dirección ${ov.dirn_T}, ${nA} tacos traccionados)`,
          "EN 1990 EQU; capacidad del taco según catálogo (ETA)", pyRound(T_per, 1), pyRound(cap, 1), "N", pyRound(u, 4), status(u), "EQU", det));
      } else {
        pending.push(`Anclaje al suelo: tracción de cálculo ${fx(T_per)} N por anclaje (${nA} anclajes en el lado traccionado). La capacidad del anclaje y del `
          + "soporte no está verificada (depende del taco y del suelo).");
        checks.push(check("E.ANCLAJE", "estabilidad", "Anclajes", `Vuelco impedido por anclaje al suelo: tracción de cálculo por anclaje bajo ${loadTxt} `
          + `(dirección ${ov.dirn_T})`, "EN 1990 EQU + EN 1992-4 (anclajes, no evaluado)", pyRound(T_per, 1), null, "N", null, PENDING, "EQU", det));
      }
    } else checks.push(check("E.VUELCO", "estabilidad", "Conjunto", `Vuelco ${what} bajo ${loadTxt} ${st.push_where ?? "en la parte superior"} `
      + `(dirección ${dirn})`, "EN 1990 EQU (γG,stb = 0,9; γQ = 1,5)", pyRound(ov.Mdst / 1e3, 2), pyRound(ov.Mstb / 1e3, 2), "N·m", pyRound(ov.ratio, 4),
      status(ov.ratio), "EQU", det));
    stability = { weight_N: ov.Wtot, cog: ov.cog, levers: ov.levers };
  } else if (includeStability && sups.length) {
    const [Wtot, cog] = ownWeight(model);
    stability = { weight_N: Wtot, cog, levers: supportLevers(sups, cog) };
  }
  // ---------------------------------------------------------------- comprobaciones no aplicables y validaciones
  classifyChecks(model, sm, checks);
  // ---------------------------------------------------------------- resultado global
  const sts = checks.map((c) => c.status);
  const stG = sts.includes(FAIL) ? FAIL : sts.includes(PENDING) || pending.length ? PENDING : OK;
  const toValidate = checks.filter((c) => c.status === VAL);
  const verdict = stG === FAIL ? "NO CUMPLE" : stG === PENDING ? "PENDIENTE" : toValidate.length ? "PENDIENTE DE VALIDACIÓN" : "CUMPLE";
  let governing = null;
  for (const c of checks) if (c.utilization !== null && (!governing || c.utilization > governing.utilization)) governing = c;
  const mats = {};
  for (const mm of Object.values(sm.members)) mats[mm.material.code] = mm.material;
  for (const info of surfInfo) mats[info.part.material] = C.material(info.part.material);
  const secSet = new Map();
  for (const mm of Object.values(sm.members)) {
    const p = mm.props;
    const row = [mm.profile.code, pyRound(p.A, 1), pyRound(p.Iy / 1e4, 3), pyRound(p.Iz / 1e4, 3), pyRound(p.Wpl_y / 1e3, 3), pyRound(p.Wpl_z / 1e3, 3)];
    secSet.set(JSON.stringify(row), row);
  }
  return {
    status: stG,
    verdict, self_weight: selfWeightInfo,
    validation_pending: toValidate.map((c) => ({ id: c.id, description: c.description, reason: c.details?.validacion ?? "" })),
    not_applicable: checks.filter((c) => c.status === NA).map((c) => ({ id: c.id, description: c.description, reason: c.details?.motivo ?? "" })),
    status_label: { [OK]: toValidate.length ? `Comprobaciones calculadas: CUMPLEN · PENDIENTE DE VALIDACIÓN: ${toValidate.length} comprobaciones con datos no certificados o hipótesis por validar`
      : "Verificación estructural automatizada completa: CUMPLE (EN 1990 · EN 1993)", [FAIL]: "NO CUMPLE: requiere modificación del diseño",
      [PENDING]: "Verificación incompleta: datos pendientes" }[stG],
    validation_note: "Cálculo automatizado según EN 1990 y EN 1993 con las hipótesis indicadas. El expediente lo firma el responsable técnico del fabricante.",
    governing, checks, load_cases: cases, combinations: { ELU: uls, ELS: sls }, partial_factors: pf,
    materials: Object.values(mats).map((m) => ({ code: m.code, name: m.name, standard: m.standard, E: m.E, fy: m.fy, fu: m.fu, density: m.density,
      fy_guaranteed: m.fy_guaranteed, design_code: m.design_code })),
    sections: [...secSet.values()].sort((a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1; return 0; }),
    hypotheses: [...new Set(hyp),     // sin repetir (p. ej. la de DC01, una por bandeja)
      "Apoyos: pies niveladores articulados con coacción horizontal isostática (un pie fijo en X-Y, otro deslizante en X que impide el giro en planta, y los demás sólo verticales); no se cuenta con el rozamiento.",
      "Cargas de superficie repartidas al emparrillado mediante la regla de 45° (áreas tributarias).",
      `Longitud de pandeo de patas: ${betaLeg}·L (pórtico traslacional, conservador).`,
      `Curva de pandeo '${crit.buckling_curve_cold_formed_hollow}' para perfiles huecos conformados en frío (EN 1993-1-1 tabla 6.2).`],
    boundary_conditions: sups.map((s) => ({ support: s.instance, node: s.node, point: s.point.map(Number), type: "articulado", restraint: s.restraint ?? null })),
    reactions, pending, limitations, stability,
    fem: { nodes: fr.nodes.length, elements: fr.elements.length, dof: fr.ndof() },
    member_utilization: memberResults,
    standards: applicableStandards(model).filter((s) => s.scope.includes("calculo") || s.scope.includes("soldadura")).map((s) => `${s.code}:${s.version}`),
    applicable_standards: applicableStandards(model).map((s) => ({ code: s.code, version: s.version, title: s.title, applicability: s.applicability ?? null, scope: s.scope })),
  };
}
