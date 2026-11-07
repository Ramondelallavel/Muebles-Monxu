// @ts-nocheck
// Resolución de parámetros 'auto' por reglas y cálculo (port de monxu/engineering/sizing.py).
import * as C from "./catalog";
import { analyze, surfaceSheet } from "./analysis";
import { navier } from "./fem";
import { AUTO, copyParams } from "./model";
import { g, pyRound } from "./util";

const G_ACC = 9.81;

function plateSizing(family, ps, tgt, notes, autoT, autoN) {
  const crit = C.criteria();
  const gG = crit.partial_factors.gamma_G, gQ = crit.partial_factors.gamma_Q;
  const dl = crit.deflection_limits.panel_span_ratio;
  const { surface, t_param, n_param } = tgt;
  const mat = C.material(ps.values[tgt.mat_param ?? "MATERIAL_CHAPA"]);
  const load = ps.values[tgt.load_param];
  const tMin = tgt.min_t_by_use ? crit.min_sheet_thickness_by_use_mm[ps.values.USO ?? "montaje"] ?? 1.5 : 1.0;
  const tMax = 6.0;
  const tOpts = autoT ? (tgt.t_options ?? C.sheetThicknesses(mat.code)).filter((t) => tMin <= t && t <= (tgt.t_max ?? tMax)) : [ps.values[t_param]];
  const minBay = crit.min_support_spacing_mm;
  const code = `DIM-${surface.toUpperCase()}`;
  for (let k = notes.length - 1; k >= 0; k--) if (notes[k].code === code) notes.splice(k, 1);
  const alternatives = [];
  for (const t of tOpts) {
    const trial = copyParams(ps);
    trial.values[t_param] = t;
    trial.values[n_param] = autoN ? 0 : ps.values[n_param];
    const m = family.construct(trial);
    if (m.design_notes.some((n) => n.code.startsWith("DFM-FIJ") && n.level === "error")) continue;
    const surf = m.structure.surfaces.find((s) => s.id === surface);
    const lvl = m.structure.levels[surf.level];
    const gx = lvl.grid_x, [yf, yb] = lvl.grid_y;
    const span = gx.at(-1) - gx[0], b = yb - yf;
    const q = (load * G_ACC) / surf.area_mm2;
    // peso propio igual que en la verificación: chapa real (con pestañas y escotaduras) repartida en la superficie
    const qg = (surfaceSheet(m.instance(surf.sheet_instance).part)[0] * G_ACC) / surf.area_mm2;
    const eta = surf.ligament_efficiency ?? 1.0;
    const P_kg = surface === "encimera" ? ps.values.CARGA_PUNTUAL : null;
    const fyd = mat.fy / mat.gamma_M0;
    const prof = C.profile(trial.values[tgt.trv_param]);
    const crossLen = yb - yf - prof.B;
    const rhoS = C.material(trial.values.MATERIAL_ESTRUCTURAL).density;
    for (const n of autoN ? Array.from({ length: 25 }, (_, i) => i) : [ps.values[n_param]]) {
      const a = span / (n + 1);
      if (a < minBay) break;
      const ru = { sigma: navier(a, b, t, mat.E, mat.nu, gG * qg + gQ * q).sigma / eta };
      const rs = { w: navier(a, b, t, mat.E, mat.nu, qg + q).w / eta };
      let okP = true;
      if (P_kg) {          // carga puntual sobre la encimera: misma comprobación que la verificación final
        const size = crit.point_load_patch_mm;
        okP = navier(a, b, t, mat.E, mat.nu, gG * qg, [gQ * P_kg * G_ACC, size, size, a / 2, b / 2], null, 121).sigma / eta <= fyd;
      }
      if (ru.sigma <= fyd && rs.w <= Math.min(a, b) / dl && okP) {
        const sheet = surf.area_mm2 * t * 1e-9 * mat.density;
        const cross = n * crossLen * 1e-3 * prof.massPerM(rhoS);
        alternatives.push({ t, n, vano: pyRound(a, 1), masa_kg: pyRound(sheet + cross, 2), sigma: pyRound(ru.sigma, 1), w: pyRound(rs.w, 2) });
        break;
      }
    }
  }
  const label = { encimera: "la encimera", balda: "la balda inferior", estante: "el estante superior" }[surface] ?? `la bandeja (${surface})`;
  if (!alternatives.length) {
    const fixed = [[t_param, autoT], [n_param, autoN]].filter(([, a]) => !a).map(([p]) => p);
    const maxT = tOpts.length ? Math.max(...tOpts) : 0;
    notes.push({ level: "error", code, message: `No se encuentra combinación de espesor y travesaños que verifique ${label} con ${g(load)} kg`
      + (fixed.length ? ` manteniendo fijo ${fixed.join(", ")}` : "")
      + ` (espesores disponibles en ${mat.code}: ${tOpts.map(g).join(", ") || "—"} mm; separación mínima de apoyos ${minBay} mm). Ponga esos parámetros en 'auto', `
      + "reduzca la carga" + (mat.fy_guaranteed && maxT >= tMax ? "" : ", use un material de chapa con más espesores o límite elástico garantizado (p. ej. S235JR)")
      + " o prevea refuerzos específicos." });
    if (autoT) { ps.values[t_param] = maxT; ps.sources[t_param] = "calculo"; }
    return;
  }
  const sorted = alternatives.map((a, i) => ({ a, i })).sort((x, y) => x.a.masa_kg - y.a.masa_kg || x.i - y.i).map((x) => x.a);
  const best = sorted[0];
  if (autoT) { ps.values[t_param] = best.t; ps.sources[t_param] = "calculo"; }
  if (autoN) { ps.values[n_param] = best.n; ps.sources[n_param] = "calculo"; }
  const altTxt = sorted.slice(0, 4).map((a) => `t=${g(a.t)} mm con ${a.n} travesaños (vano ${pyRound(a.vano, 0).toFixed(0)} mm, ${a.masa_kg} kg)`).join("; ");
  notes.push({ level: "propuesta", code, message: `Propuesta para ${label}: chapa de ${g(best.t)} mm y ${best.n} travesaños intermedios `
    + `(vano ${pyRound(best.vano, 0).toFixed(0)} mm), mínima masa entre las alternativas que verifican (espesor mínimo ${g(tMin)} mm, separación mínima de apoyos `
    + `${minBay} mm): ${altTxt}.`, alternatives });
}

export function resolveAuto(family, params, autos, onProgress = null) {
  const cands = family.candidates, defaults = family.constructive_defaults;
  const ps = copyParams(params);
  const notes = [];
  const v = ps.values;
  const haveLoad = family.verticalLoadPresent(v);
  const profAutos = autos.filter((k) => k in cands);
  for (const k of profAutos) { v[k] = haveLoad ? cands[k][0] : defaults[k]; ps.sources[k] = "regla_diseno"; }
  if (haveLoad && profAutos.includes("PERFIL_LARGUERO") && "PERFIL_LARGUERO" in defaults) v.PERFIL_LARGUERO = defaults.PERFIL_LARGUERO;
  for (const [k, val] of Object.entries(family.sheetDefaultsWithoutLoad(v))) if (v[k] === AUTO) { v[k] = val; ps.sources[k] = "regla_diseno"; }
  if (!haveLoad && (profAutos.length || autos.some((k) => k in defaults)))
    notes.push({ level: "propuesta", code: "DIM-SIN-CARGA", message: "Sin carga vertical de trabajo definida: espesores y separación de apoyos según reglas "
      + "constructivas; los perfiles sólo se comprueban frente al empuje horizontal. La resistencia a cargas verticales queda PENDIENTE de verificación." });
  const sp = family.support_param ?? "PIE_NIVELADOR";
  const footAuto = v[sp] === AUTO;
  if (footAuto) { v[sp] = defaults[sp] ?? "PIE_NIV_M12_D60"; ps.sources[sp] = "regla_diseno"; }
  const targets = family.plateTargets(v);
  const sized = new Set(targets.map((t) => t.t_param));
  for (const k of Object.keys(v)) if (v[k] === AUTO && k in defaults && !(k in cands) && !sized.has(k)) { v[k] = defaults[k]; ps.sources[k] = "regla_diseno"; }

  const plates = () => {
    for (const t of targets) if (ps.values[t.t_param] === AUTO) ps.values[t.t_param] = defaults[t.t_param] ?? 2.0;
    for (const t of targets) {
      const at = autos.includes(t.t_param), an = autos.includes(t.n_param);
      if (at || an) plateSizing(family, ps, t, notes, at, an);
    }
  };
  plates();
  let iterTotal = 0;
  const sizeProfiles = () => {
    const idx = Object.fromEntries(profAutos.map((k) => [k, cands[k].includes(v[k]) ? cands[k].indexOf(v[k]) : 0]));
    for (const k of profAutos) ps.values[k] = cands[k][idx[k]];
    if (fitLeg(family, ps, profAutos)) idx[family.leg_param] = cands[family.leg_param].indexOf(ps.values[family.leg_param]);
    let iterations = 0;
    for (iterations = 1; iterations <= 40; iterations++) {
      iterTotal++;
      onProgress?.(`Dimensionado de perfiles: iteración ${iterations}`);
      const m = family.construct(ps);
      const rep = analyze(m, false, true);
      const failing = new Set();
      for (const c of rep.checks) {
        if (c.status !== "NO_CUMPLE") continue;
        if (c.id.startsWith("S.")) { if (profAutos.includes(family.leg_param)) failing.add(family.leg_param); continue; }
        let role = m.structure.member_roles[c.element] ?? null;
        if (role === null && c.category === "soldadura") {
          const j = m.joints.find((x) => x.id === c.element);
          role = j ? m.instance(j.weld.fem.member).role : null;
        }
        const prm = role ? family.paramForRole(role) : null;
        if (profAutos.includes(prm)) failing.add(prm);
      }
      if (!failing.size) break;
      let bumped = false;
      for (const k of failing) if (idx[k] + 1 < cands[k].length) { idx[k]++; ps.values[k] = cands[k][idx[k]]; bumped = true; }
      const lp = family.leg_param;
      if (profAutos.includes(lp)) {
        for (const k of family.frame_params)
          while (k in ps.values && C.profile(ps.values[k]).B > C.profile(ps.values[lp]).B && idx[lp] + 1 < cands[lp].length) { idx[lp]++; ps.values[lp] = cands[lp][idx[lp]]; }
        fitLeg(family, ps, profAutos);
        idx[lp] = cands[lp].indexOf(ps.values[lp]);
      }
      if (!bumped) {
        notes.push({ level: "error", code: "DIM-PERFILES", message: "Se han agotado los perfiles candidatos sin verificar todas las comprobaciones: " + [...failing].sort().join(", ") });
        break;
      }
    }
    if (iterations > 40) iterations = 40;
    for (const k of profAutos) ps.sources[k] = "calculo";
    notes.push({ level: "propuesta", code: "DIM-PERFILES", message: "Perfiles dimensionados por cálculo preliminar (sección mínima de la serie que verifica resistencia, "
      + "pandeo, flechas y soldaduras): " + profAutos.map((k) => `${k} = ${ps.values[k]}`).join(", "), iterations });
    plates();
    fitLeg(family, ps, profAutos);
  };
  const runProfiles = !!(profAutos.length && (haveLoad || v.CARGA_HORIZONTAL));
  if (runProfiles) sizeProfiles();
  for (const k of Object.keys(ps.values)) if (ps.values[k] === AUTO && k in defaults) ps.values[k] = defaults[k];
  fitLeg(family, ps, profAutos);
  if (footAuto && haveLoad) {
    for (let it = 0; it < 3; it++) {
      const before = ps.values[sp];
      selectFeet(family, ps, notes);
      if (ps.values[sp] === before || !runProfiles) break;
      for (let k = notes.length - 1; k >= 0; k--) if (notes[k].code === "DIM-PERFILES" || notes[k].code === "DIM-PIES") notes.splice(k, 1);
      sizeProfiles();
    }
  }
  return [ps, notes, iterTotal];
}

/** Regla constructiva propia de la familia sobre la pata/montante (legFits): aumenta el perfil 'auto' de la serie hasta cumplirla. */
function fitLeg(family, ps, profAutos) {
  const lp = family.leg_param, series = family.candidates[lp];
  if (!family.legFits || !profAutos.includes(lp) || !series.includes(ps.values[lp])) return false;
  let changed = false;
  while (!family.legFits(ps.values) && series.indexOf(ps.values[lp]) + 1 < series.length) {
    ps.values[lp] = series[series.indexOf(ps.values[lp]) + 1];
    changed = true;
  }
  return changed;
}

function selectFeet(family, ps, notes) {
  const m = family.construct(ps);
  const rep = analyze(m, false, false);
  const rz = rep.reactions.filter((r) => r.combination === "ELS-1").map((r) => r.Rz_N);
  if (!rz.length) return;
  const need = Math.max(...rz) / G_ACC;
  const sp = family.support_param ?? "PIE_NIVELADOR", cat = family.support_category ?? "patas";
  const word = cat.startsWith("ruedas") ? "Rueda" : "Pie nivelador";
  const feet = Object.entries(C.components()).filter(([, c]) => c.category === cat && !c.brake).map((x, i) => ({ x, i }))
    .sort((a, b) => a.x[1].rated_load_kg - b.x[1].rated_load_kg || a.i - b.i).map((o) => o.x);
  const leg = C.profile(ps.values[family.leg_param]);
  for (const [code, c] of feet) {
    const nut = C.component(`TUERCA_SOLDAR_${c.thread}`);
    const fits = nut.s / 0.8660254 <= leg.B - 2 * leg.t - 1;
    if (c.rated_load_kg >= need && fits) {
      ps.values[sp] = code;
      ps.sources[sp] = "calculo";
      notes.push({ level: "propuesta", code: "DIM-PIES", message: `${word} seleccionad${word === "Rueda" ? "a" : "o"} por cálculo: ${c.name} (capacidad nominal de catálogo `
        + `${c.rated_load_kg} kg ≥ reacción de servicio ${pyRound(need, 0).toFixed(0)} kg por apoyo). Capacidad a confirmar con la ficha del proveedor.` });
      return;
    }
  }
  notes.push({ level: "advertencia", code: "DIM-PIES", message: `Ningún ${word.toLowerCase()} del catálogo admite ${pyRound(need, 0).toFixed(0)} kg por apoyo con la pata/montante `
    + `${leg.code}: se mantiene ${ps.values[sp]} y la comprobación no se cumplirá.` });
}

/** Resuelve los 'auto' y construye el modelo (ProductFamily.build). */
export function build(family, params, onProgress = null) {
  const autos = Object.entries(params.values).filter(([, v]) => v === AUTO).map(([k]) => k);
  const [resolved, notes] = autos.length ? resolveAuto(family, params, autos, onProgress) : [copyParams(params), []];
  const model = family.construct(resolved);
  model.requested = params;
  for (const n of notes) model.design_notes.unshift(n);
  return model;
}
