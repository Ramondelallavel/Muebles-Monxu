// @ts-nocheck
// Motor de verificación estructural (port de monxu/engineering/analysis.py).
import * as C from "./catalog";
import { Frame3D, lineLoadToNodes, navier } from "./fem";
import { centerOfMass } from "./geometry";
import { f as fx, g, pyRound } from "./util";

export const OK = "CUMPLE", FAIL = "NO_CUMPLE", PENDING = "PENDIENTE";
export const G_ACC = 9.81;
const MAX_ELEMENT = 100.0;
const N_ZERO = 1e-3;   // N: axil por debajo del cual la barra se considera sin compresión

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
      const ky = argmax((k) => Math.abs(dd[k][1]) - Math.abs(dd[k][0]));
      sups.forEach((sup, k) => {
        const n = this.frame.node(sup.point);
        const fxr = k === k0 || k === ky, fyr = k === k0 || k === kx;
        this.frame.support(n, [fxr, fyr, true, false, false, false]);
        sup.node = n;
        sup.restraint = (fxr ? "X" : "") + (fyr ? "Y" : "") + "Z";
      });
    }
  }
  selfWeight(c = "G") {
    let total = 0.0;
    for (const mm of Object.values(this.members)) {
      const w = mm.props.A * 1e-9 * mm.material.density * G_ACC;
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
  lineLoad(c, member, p, s0g, s1g, axis) {
    const chain = this.chains[member];
    const pairs = chain.map(([, n]) => [this.frame.nodes[n][axis], n]).sort((a, b) => a[0] - b[0]);
    const F = lineLoadToNodes(pairs.map((x) => x[0]), p, s0g, s1g);
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
      for (const mem of level.long) total += this.lineLoad(c, mem, (s) => q * Math.min(s - x0, x1 - s, b / 2), x0, x1, 0);
      for (const mem of [xm[k], xm[k + 1]]) total += this.lineLoad(c, mem, (s) => q * Math.min(s - yf, yb - s, a / 2), yf, yb, 1);
    }
    return total;
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
export function analyze(model, includeStability = true, includeWelds = true) {
  const crit = C.criteria();
  const pf = crit.partial_factors;
  const ps = model.params.values;
  const st = model.structure;
  const checks = [], hyp = [], pending = [];
  const limitations = [
    "Análisis elástico lineal de primer orden (sin efectos P-Δ ni imperfecciones globales explícitas).",
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
  // masas no estructurales colgadas de barras (p. ej. un panel atornillado a los montantes)
  for (const am of st.attached_masses ?? []) {
    const chain = sm.chains[am.member];
    if (!chain) continue;
    let best = chain[0], bd = Infinity;
    for (const c of chain) { const q = fr.nodes[c[1]], dd = Math.hypot(q[0] - am.point[0], q[1] - am.point[1], q[2] - am.point[2]); if (dd < bd) { bd = dd; best = c; } }
    const P = am.mass_kg * G_ACC;
    fr.addNodalLoad("G", best[1], [0, 0, -P]);
    Gm += P;
  }
  let gSheets = 0.0;
  const surfInfo = [];
  for (const surf of st.surfaces ?? []) {
    const lvl = levels[surf.level];
    const part = model.instance(surf.sheet_instance).part;
    const sheetMass = part.flat.netArea * part.spec.t * 1e-9 * C.material(part.material).density;
    const area = surf.area_mm2;
    const gx = lvl.grid_x, gy = lvl.grid_y;
    const scale = area / ((gx.at(-1) - gx[0]) * (gy[1] - gy[0]));
    const q_g = (sheetMass * G_ACC) / area;
    gSheets += sm.surfaceLoad("G", lvl, q_g * scale);
    const loadKg = ps[surf.load_param];
    const info = { surface: surf, level: lvl, q_g, sheet_mass: sheetMass, load_kg: loadKg, scale, part };
    if (loadKg) {
      const q = (loadKg * G_ACC) / area;
      const applied = sm.surfaceLoad("Q", lvl, q * scale);
      info.q = q;
      cases.push({ id: `Q_${surf.id}`, label: `Sobrecarga de uso uniforme en ${surf.label.toLowerCase()}`, value: `${g(loadKg)} kg (${fx(q * 1e6)} N/m²)`,
        total_N: pyRound(applied, 1) });
    } else pending.push(`Carga de uso sobre ${surf.label.toLowerCase()} no definida (${surf.load_param}): verificación de ${surf.label.toLowerCase()} pendiente.`);
    surfInfo.push(info);
  }
  cases.unshift({ id: "G", label: "Peso propio (perfiles y chapas, calculado desde la geometría)", value: `${fx((Gm + gSheets) / G_ACC, 1)} kg`,
    total_N: pyRound(Gm + gSheets, 1) });
  const hasQ = "Q" in fr.loads;
  const P_kg = ps.CARGA_PUNTUAL;
  const top = levels.SUP;
  if (P_kg && top) {
    const chain = sm.chains[top.long[0]];
    const smid = (chain[0][0] + chain.at(-1)[0]) / 2;
    let best = chain[0];
    for (const c of chain) if (Math.abs(c[0] - smid) < Math.abs(best[0] - smid)) best = c;
    fr.addNodalLoad("P", best[1], [0, 0, -P_kg * G_ACC]);
    cases.push({ id: "P", label: "Carga puntual en centro de vano del larguero delantero", value: `${g(P_kg)} kg`, total_N: pyRound(P_kg * G_ACC, 1) });
  }
  const H_N = ps.CARGA_HORIZONTAL || 0.0;
  const topNodes = [];
  if (H_N && top) {
    for (const lid of st.leg_ids) {
      const chain = sm.chains[lid];
      const zt = top.z - model.instance(top.long[0]).part.profile.H / 2;
      let best = chain[0];
      for (const c of chain) if (Math.abs(fr.nodes[c[1]][2] - zt) < Math.abs(fr.nodes[best[1]][2] - zt)) best = c;
      topNodes.push(best[1]);
    }
    for (const n of topNodes) { fr.addNodalLoad("HX", n, [H_N / topNodes.length, 0, 0]); fr.addNodalLoad("HY", n, [0, H_N / topNodes.length, 0]); }
    cases.push({ id: "HX/HY", label: "Empuje horizontal en el plano de la encimera (direcciones X e Y)", value: `${g(H_N)} N`, total_N: H_N });
    if (model.params.sources.CARGA_HORIZONTAL === "defecto") hyp.push(`Empuje horizontal de ${g(H_N)} N: ${crit.horizontal_service_load_note}`);
  }
  const gG = pf.gamma_G, gQ = pf.gamma_Q, psi = pf.psi0_Q;
  const uls = { "ELU-1": { G: gG } };
  if (hasQ) uls["ELU-1"] = { G: gG, Q: gQ };
  if ("HX" in fr.loads) {
    uls["ELU-2"] = { G: gG, Q: gQ * psi, HX: gQ };
    uls["ELU-3"] = { G: gG, Q: gQ * psi, HY: gQ };
    if (hasQ) uls["ELU-4"] = { G: gG, Q: gQ, HX: gQ * psi };
  }
  if ("P" in fr.loads) uls["ELU-5"] = { G: gG, P: gQ };
  const sls = hasQ ? { "ELS-1": { G: 1.0, Q: 1.0 } } : {};
  if ("P" in fr.loads) sls["ELS-2"] = { G: 1.0, P: 1.0 };
  if ("HX" in fr.loads) { sls["ELS-3"] = { HX: 1.0 }; sls["ELS-4"] = { HY: 1.0 }; }
  const all = { ...uls, ...sls };
  const res = fr.solve();
  const U = Object.fromEntries(Object.entries(all).map(([c, f]) => [c, res.combine(f)]));

  // ---------------------------------------------------------------- barras
  const alpha = crit.imperfection_factors[crit.buckling_curve_cold_formed_hollow];
  const betaLeg = crit.effective_length_factors.leg_sway;
  const memberResults = {};
  for (const [mid, mm] of Object.entries(sm.members)) {
    const { material: mat, profile: prof, props: sp } = mm;
    const fy = mat.fy, gM0 = mat.gamma_M0, gM1 = mat.gamma_M1;
    const cls = sectionClass(prof, fy);
    const Wy = cls <= 2 ? sp.Wpl_y : sp.Wel_y, Wz = cls <= 2 ? sp.Wpl_z : sp.Wel_z;
    const NRd = (sp.A * fy) / gM0, MyRd = (Wy * fy) / gM0, MzRd = (Wz * fy) / gM0;
    const VzRd = (sp.Av_z * fy) / Math.sqrt(3) / gM0, VyRd = (sp.Av_y * fy) / Math.sqrt(3) / gM0;
    const isLeg = mm.role === "pata" || mm.role === "montante";
    const beta = isLeg ? betaLeg : crit.effective_length_factors.braced_member;
    const Lcr = beta * mm.length;
    const lam1 = Math.PI * Math.sqrt(mat.E / fy);
    const lam = Lcr / Math.min(sp.iy, sp.iz) / lam1;
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
      const ub = Nc < -N_ZERO ? Math.abs(Nc) / ((chi * sp.A * fy) / gM1) + My_ / ((Wy * fy) / gM1) + Mz_ / ((Wz * fy) / gM1) : 0;
      const uAll = Math.max(ucs, ub, Vmax);
      if (uAll > best.u) best = { u: uAll, ucs, ub, uv: Vmax, combo: cname, Nc, My: My_, Mz: Mz_ };
    }
    const details = { clase: cls, N_Rd_kN: NRd / 1e3, My_Rd_kNm: MyRd / 1e6, Mz_Rd_kNm: MzRd / 1e6, L_mm: mm.length, Lcr_mm: Lcr, lambda_rel: lam, chi,
      N_Ed_kN: best.Nc / 1e3, My_Ed_kNm: best.My / 1e6, Mz_Ed_kNm: best.Mz / 1e6, u_seccion: best.ucs, u_pandeo: best.ub, u_cortante: best.uv };
    let stt = status(best.u);
    if (cls === 4) { stt = PENDING; pending.push(`${mm.instance.name}: sección clase 4, requiere sección eficaz (no implementado).`); }
    if (!hasQ && stt === OK) stt = PENDING;
    checks.push(check(`B.${mid}`, isLeg ? "pandeo" : "resistencia", mid, `${mm.instance.name} (${prof.code}, ${mat.code}): resistencia de sección`
      + (best.Nc < -N_ZERO ? " y pandeo por flexión" : ""), "EN 1993-1-1 §6.2, §6.3.1, §6.3.3", pyRound(best.u, 4), 1.0, "-", pyRound(best.u, 4), stt, best.combo, details));
    memberResults[mid] = best.u;
    if (!isLeg && Object.keys(sls).length) {
      let dmax = 0.0, cmax = "";
      for (const cname of Object.keys(sls)) if (cname === "ELS-1" || cname === "ELS-2") {
        const dv = sm.memberDeflection(mid, U[cname]);
        if (dv > dmax) { dmax = dv; cmax = cname; }
      }
      if (cmax) {
        const r = crit.deflection_limits.member_span_ratio;
        const lim = mm.length / r;
        checks.push(check(`D.${mid}`, "deformacion", mid, `${mm.instance.name}: flecha relativa`, `EN 1990 A1.4 (límite L/${r} adoptado)`,
          pyRound(dmax, 3), pyRound(lim, 3), "mm", pyRound(dmax / lim, 4), status(dmax / lim), cmax));
      }
    }
  }
  // ---------------------------------------------------------------- desplome
  if (U["ELS-3"] && topNodes.length) {
    const r = crit.deflection_limits.sway_height_ratio;
    const lim = st.worktop_height / r;
    for (const [cname, comp] of [["ELS-3", 0], ["ELS-4", 1]]) {
      const dx = Math.max(...topNodes.map((n) => Math.abs(U[cname][6 * n + comp])));
      checks.push(check(`S.${cname}`, "deformacion", "Estructura", `Desplome horizontal en dirección ${comp === 0 ? "X" : "Y"} bajo empuje de servicio`,
        `Criterio adoptado H/${r}`, pyRound(dx, 3), pyRound(lim, 3), "mm", pyRound(dx / lim, 4), status(dx / lim), cname));
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
    if (sls["ELS-1"]) {
      const rmax = Math.max(...reactions.filter((r) => r.combination === "ELS-1").map((r) => r.Rz_N));
      checks.push(check("A.PIES", "apoyos", supWord, `Reacción máxima de servicio frente a la capacidad nominal de ${comp.name}`,
        "Dato de catálogo genérico — confirmar con la ficha técnica del proveedor", pyRound(rmax, 1), pyRound(cap, 1), "N", pyRound(rmax / cap, 4),
        status(rmax / cap), "ELS-1", { fuente_capacidad: comp.rated_load_source ?? null }));
      if (comp.rated_load_source === "catalogo_generico") hyp.push(`Capacidad de ${comp.name}: ${comp.rated_load_kg} kg (catálogo genérico de referencia, `
        + "debe confirmarse con la ficha técnica del proveedor).");
    } else checks.push(check("A.PIES", "apoyos", supWord, `Capacidad de los ${supWord.toLowerCase()}`, "—", null, cap, "N", null, PENDING, "", {}));
  }
  // ---------------------------------------------------------------- placas
  const dl = crit.deflection_limits.panel_span_ratio;
  for (const info of surfInfo) {
    const { surface: surf, level: lvl, part } = info;
    const mat = C.material(part.material);
    const t = part.spec.t;
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
    if (info.load_kg) {
      const qu = gG * info.q_g + gQ * info.q, qs = info.q_g + info.q;
      const ru = navier(a, b, t, mat.E, mat.nu, qu), rs = navier(a, b, t, mat.E, mat.nu, qs);
      const fyd = mat.fy / mat.gamma_M0;
      checks.push(check(`PL.${sid}.S`, "placa", surf.label, `${surf.label}: tensión de flexión en panel ${fx(a)}×${fx(b)} mm, t = ${g(t)} mm (carga uniforme)`,
        "Teoría de placas (Navier) + EN 1993-1-1 §6.2.1", pyRound(ru.sigma, 2), pyRound(fyd, 1), "MPa", pyRound(ru.sigma / fyd, 4), status(ru.sigma / fyd),
        "ELU-1", { a, b, q_MPa: qu }));
      const lim = Math.min(a, b) / dl;
      const det = { a, b, q_MPa: qs };
      if (rs.w > t / 2) det.nota = "Flecha superior a t/2: el efecto membrana (no considerado) reduce la flecha real; el resultado lineal es conservador.";
      checks.push(check(`PL.${sid}.D`, "placa", surf.label, `${surf.label}: flecha del panel ${fx(a)}×${fx(b)} mm`, `Criterio adoptado L/${dl}`,
        pyRound(rs.w, 3), pyRound(lim, 3), "mm", pyRound(rs.w / lim, 4), status(rs.w / lim), "ELS-1", det));
    } else checks.push(check(`PL.${sid}`, "placa", surf.label, `${surf.label}: verificación de chapa`, "—", null, null, "-", null, PENDING, "",
      { motivo: `${surf.load_param} sin definir` }));
    if (sid === "encimera" && P_kg) {
      const size = crit.point_load_patch_mm;
      const rp = navier(a, b, t, mat.E, mat.nu, gG * info.q_g, [gQ * P_kg * G_ACC, size, size, a / 2, b / 2], null, 121);
      const fyd = mat.fy / mat.gamma_M0;
      checks.push(check(`PL.${sid}.P`, "placa", surf.label, `${surf.label}: carga puntual de ${g(P_kg)} kg sobre huella ${size}×${size} mm en el centro del panel`,
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
      const stt = hasQ ? status(best[0] / fvw) : PENDING;
      checks.push(check(`W.${j.id}`, "soldadura", j.id, `${j.description}: cordón en ángulo a${g(aw)} perimetral (${prof.code})`,
        "EN 1993-1-8 §4.5.3.3 (método simplificado)", pyRound(best[0], 2), pyRound(fvw, 1), "MPa", pyRound(best[0] / fvw, 4), stt, best[1],
        { a_mm: aw, longitud_mm: j.weld.length }));
    }
    if (model.joints.some((j) => (j.weld?.a ?? 3) < 3)) hyp.push("Cordones con garganta a < 3 mm en perfiles de pared delgada: fuera del ámbito de EN 1993-1-8 "
      + "§4.5.2(2); requieren procedimiento de soldeo cualificado (EN ISO 15614-1) y verificación según EN 1993-1-3.");
  }
  // ---------------------------------------------------------------- estabilidad
  let stability = null;
  if (includeStability && sups.length) {
    const Wtot = model.totalMass() * G_ACC;
    const cog = centerOfMass(model);
    const xs = sups.map((s) => s.point[0]), ys = sups.map((s) => s.point[1]);
    const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
    const levers = { "+X": xmax - cog[0], "-X": cog[0] - xmin, "+Y": ymax - cog[1], "-Y": cog[1] - ymin };
    const hgt = st.push_height ?? st.worktop_height;     // altura de empuje para el vuelco (carros: asa o mano)
    let [dirn, lev] = Object.entries(levers)[0];
    for (const [k, v] of Object.entries(levers)) if (v < lev) { dirn = k; lev = v; }
    if (H_N) {
      const Mstb = pf.gamma_G_stb * Wtot * lev, Mdst = pf.gamma_Q_dst * H_N * hgt;
      const ratio = Mstb > 0 ? Mdst / Mstb : Infinity;
      const what = st.product_word ?? "mesa";
      // empuje de servicio que el conjunto vacío resiste sin anclaje (EQU): γQ·H·h = γG,stb·W·brazo
      const det = { peso_N: Wtot, cdg_mm: cog.map((v) => pyRound(v, 1)), brazo_mm: lev, empuje_admisible_N: Math.floor(Mstb / (pf.gamma_Q_dst * hgt)) };
      if (ps.ANCLAJE === "al_suelo") {
        const base = dirn === "+Y" || dirn === "-Y" ? ymax - ymin : xmax - xmin;
        const T = base > 0 ? Math.max(0.0, (Mdst - Mstb) / base) : Infinity;
        const nA = Math.max(1, Math.floor(sups.length / 2));
        Object.assign(det, { traccion_total_N: pyRound(T, 1), anclajes_traccionados: nA, traccion_por_anclaje_N: pyRound(T / nA, 1) });
        pending.push(`Anclaje al suelo: tracción de cálculo ${fx(T / nA)} N por anclaje (${nA} anclajes en el lado traccionado). La capacidad del anclaje y del `
          + "soporte no está verificada (depende del taco y del suelo).");
        checks.push(check("E.ANCLAJE", "estabilidad", "Anclajes", `Vuelco impedido por anclaje al suelo: tracción de cálculo por anclaje bajo empuje de ${g(H_N)} N `
          + `(dirección ${dirn})`, "EN 1990 EQU + EN 1992-4 (anclajes, no evaluado)", pyRound(T / nA, 1), null, "N", null, PENDING, "EQU", det));
      } else checks.push(check("E.VUELCO", "estabilidad", "Conjunto", `Vuelco de la ${what} vacía bajo empuje horizontal de ${g(H_N)} N en la parte superior `
        + `(dirección ${dirn})`, "EN 1990 EQU (γG,stb = 0,9; γQ = 1,5)", pyRound(Mdst / 1e3, 2), pyRound(Mstb / 1e3, 2), "N·m", pyRound(ratio, 4), status(ratio), "EQU", det));
    }
    stability = { weight_N: Wtot, cog, levers };
  }
  // ---------------------------------------------------------------- resultado global
  const sts = checks.map((c) => c.status);
  const stG = sts.includes(FAIL) ? FAIL : sts.includes(PENDING) || pending.length ? PENDING : OK;
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
    status_label: { [OK]: "Verificación preliminar automatizada: CUMPLE", [FAIL]: "NO CUMPLE: requiere modificación del diseño",
      [PENDING]: "Verificación incompleta: datos pendientes" }[stG],
    validation_note: "Resultado de cálculo preliminar automatizado. La validación definitiva del producto estructural corresponde a un técnico competente.",
    governing, checks, load_cases: cases, combinations: { ELU: uls, ELS: sls }, partial_factors: pf,
    materials: Object.values(mats).map((m) => ({ code: m.code, name: m.name, standard: m.standard, E: m.E, fy: m.fy, fu: m.fu, density: m.density,
      fy_guaranteed: m.fy_guaranteed, design_code: m.design_code })),
    sections: [...secSet.values()].sort((a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1; return 0; }),
    hypotheses: [...hyp,
      "Apoyos: pies niveladores articulados con coacción horizontal isostática (un pie fijo en X-Y, uno deslizante en X, uno deslizante en Y y el cuarto sólo vertical); no se cuenta con el rozamiento.",
      "Cargas de superficie repartidas al emparrillado mediante la regla de 45° (áreas tributarias).",
      `Longitud de pandeo de patas: ${betaLeg}·L (pórtico traslacional, conservador).`,
      `Curva de pandeo '${crit.buckling_curve_cold_formed_hollow}' para perfiles huecos conformados en frío (EN 1993-1-1 tabla 6.2).`],
    boundary_conditions: sups.map((s) => ({ support: s.instance, node: s.node, point: s.point.map(Number), type: "articulado", restraint: s.restraint ?? null })),
    reactions, pending, limitations, stability,
    fem: { nodes: fr.nodes.length, elements: fr.elements.length, dof: fr.ndof() },
    member_utilization: memberResults,
    standards: C.standards(model.family).filter((s) => s.scope.includes("calculo") || s.scope.includes("soldadura")).map((s) => `${s.code}:${s.version}`),
  };
}
