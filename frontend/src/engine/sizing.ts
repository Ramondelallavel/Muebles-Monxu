// @ts-nocheck
// Resolución de parámetros 'auto' por reglas y cálculo (port de monxu/engineering/sizing.py).
import * as C from "./catalog";
import { analyze, deflectionRatios, dynamicFactor, overturning, patchSize, surfaceSheet } from "./analysis";
import { navier } from "./fem";
import { autoExplode } from "./geometry";
import { AUTO, copyParams } from "./model";
import { f as fx, g, pyRound } from "./util";

const G_ACC = 9.81;

function plateSizing(family, ps, tgt, notes, autoT, autoN) {
  const crit = C.criteria();
  const gG = crit.partial_factors.gamma_G, gQ = crit.partial_factors.gamma_Q;
  const dl = deflectionRatios(ps.values)[1];
  const { surface, t_param, n_param } = tgt;
  const mat = C.material(ps.values[tgt.mat_param ?? "MATERIAL_CHAPA"]);
  const phi = dynamicFactor(ps.values);                 // coeficiente dinámico (carros)
  const load = (ps.values[tgt.load_param] ?? 0) * phi;   // p. ej. sólo carga puntual sobre la encimera
  const tMin = tgt.min_t_by_use ? crit.min_sheet_thickness_by_use_mm[ps.values.USO ?? "montaje"] ?? 1.5 : 1.0;
  const tMax = 6.0;
  const tOpts = autoT ? (tgt.t_options ?? C.sheetThicknesses(mat.code)).filter((t) => tMin <= t && t <= (tgt.t_max ?? tMax)) : [ps.values[t_param]];
  const minBay = crit.min_support_spacing_mm;
  const code = `DIM-${surface.toUpperCase()}`;
  for (let k = notes.length - 1; k >= 0; k--) if (notes[k].code === code) notes.splice(k, 1);
  const alternatives = [];
  let pointOnly = false;          // la carga repartida se verifica pero la puntual no
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
    const P_kg = surface === "encimera" ? (ps.values.CARGA_PUNTUAL || 0.0) * phi || null : null;
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
        const size = patchSize(ps.values, surf);
        okP = navier(a, b, t, mat.E, mat.nu, gG * qg, [gQ * P_kg * G_ACC, size, size, a / 2, b / 2], null, 121).sigma / eta <= fyd;
      }
      if (ru.sigma <= fyd && rs.w <= Math.min(a, b) / dl && !okP) pointOnly = true;
      if (ru.sigma <= fyd && rs.w <= Math.min(a, b) / dl && okP) {
        const sheet = surf.area_mm2 * t * 1e-9 * mat.density;
        const cross = n * crossLen * 1e-3 * prof.massPerM(rhoS);
        alternatives.push({ t, n, vano: pyRound(a, 1), masa_kg: pyRound(sheet + cross, 2), sigma: pyRound(ru.sigma, 1), w: pyRound(rs.w, 2) });
        break;
      }
    }
  }
  const label = tgt.label ?? { encimera: "la encimera", balda: "la balda inferior", estante: "el estante superior" }[surface] ?? `la bandeja (${surface})`;
  if (!alternatives.length) {
    const fixed = [[t_param, autoT], [n_param, autoN]].filter(([, a]) => !a).map(([p]) => p);
    const maxT = tOpts.length ? Math.max(...tOpts) : 0;
    const Pk = surface === "encimera" ? (ps.values.CARGA_PUNTUAL || 0.0) * phi || null : null;
    const what = pointOnly && Pk ? `la carga puntual de ${g(Pk)} kg (la carga repartida de ${g(load)} kg sí se verifica; la flexión local `
      + "bajo una pieza concentrada depende del espesor, no del vano)" : `${g(load)} kg`;
    notes.push({ level: "error", code, message: `No se encuentra combinación de espesor y travesaños que verifique ${label} con ${what}`
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
    notes.push({ level: "propuesta", code: "DIM-SIN-CARGA", message: "Sin carga vertical de uso (0 kg indicados): espesores y separación de apoyos según reglas "
      + "constructivas; la estructura se verifica con su peso propio y el empuje horizontal." });
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
    if (fitLeg(family, ps, profAutos)) for (const k of profAutos) if (cands[k].includes(ps.values[k])) idx[k] = cands[k].indexOf(ps.values[k]);
    let iterations = 0;
    for (iterations = 1; iterations <= 40; iterations++) {
      iterTotal++;
      onProgress?.(`Dimensionado de perfiles: iteración ${iterations}`);
      const m = family.construct(ps);
      const rep = analyze(m, false, true);
      const failing = new Set(), why = {};
      for (const c of rep.checks) {
        if (c.status !== "NO_CUMPLE") continue;
        if (c.id.startsWith("S.")) {          // desplome del conjunto: pórtico de patas y vigas
          const prm = swayMember(family, m, ps, profAutos, idx, cands, c.id === "S.ELS-3" ? 0 : 1);
          if (prm) { failing.add(prm); why[prm] ??= c.description; }
          continue;
        }
        let role = m.structure.member_roles[c.element] ?? null;
        if (role === null && c.category === "soldadura") {
          const j = m.joints.find((x) => x.id === c.element);
          role = j ? m.instance(j.weld.fem.member).role : null;
        }
        const prm = role ? family.paramForRole(role) : null;
        if (profAutos.includes(prm)) { failing.add(prm); why[prm] ??= c.description; }
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
      } else fitLeg(family, ps, profAutos);
      for (const k of profAutos) if (cands[k].includes(ps.values[k])) idx[k] = cands[k].indexOf(ps.values[k]);
      if (!bumped) {
        notes.push({ level: "error", code: "DIM-PERFILES", message: "Se han agotado los perfiles candidatos sin verificar todas las comprobaciones: "
          + [...failing].sort().map((k) => `${k} = ${ps.values[k]} (${why[k]})`).join("; ")
          + ". Use un material más rígido (acero), ancle o arriostre la estructura, o reduzca cargas y dimensiones." });
        break;
      }
    }
    if (iterations > 40) iterations = 40;
    for (const k of profAutos) ps.sources[k] = "calculo";
    notes.push({ level: "propuesta", code: "DIM-PERFILES", message: "Perfiles dimensionados por cálculo (sección mínima de la serie que verifica resistencia, "
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
  if (ps.values.TACO_ANCLAJE === AUTO) selectAnchor(family, ps, notes);
  return [ps, notes, iterTotal];
}

const lc = (name) => name.slice(0, 1).toLowerCase() + name.slice(1);

/** Taco de anclaje de menor capacidad que resiste la tracción de cálculo por taco (vuelco EQU del conjunto vacío bajo el
 * empuje horizontal). Sin anclaje al suelo, el taco no se usa: valor constructivo. */
function selectAnchor(family, ps, notes) {
  const anchors = Object.entries(C.components()).filter(([, c]) => c.category === "anclajes").map((x, i) => ({ x, i }))
    .sort((a, b) => a.x[1].tension_kN - b.x[1].tension_kN || a.i - b.i).map((o) => o.x);
  if (ps.values.ANCLAJE !== "al_suelo") {
    ps.values.TACO_ANCLAJE = family.constructive_defaults.TACO_ANCLAJE ?? anchors[0][0];
    ps.sources.TACO_ANCLAJE = "regla_diseno";
    return;
  }
  ps.values.TACO_ANCLAJE = anchors[0][0];        // provisional: el taco no cambia el vuelco
  const ov = overturning(family.construct(ps), ps.values);
  const need = ov ? ov.T_per : 0.0;
  for (const [code, c] of anchors) {
    if (c.tension_kN * 1000.0 >= need) {
      ps.values.TACO_ANCLAJE = code;
      ps.sources.TACO_ANCLAJE = "calculo";
      notes.push({ level: "propuesta", code: "DIM-ANCLAJE", message: `Taco de anclaje seleccionado por cálculo: ${lc(c.name)} (tracción de cálculo `
        + `${fx(need)} N por taco ≤ ${fx(c.tension_kN * 1000)} N de catálogo). Capacidad a confirmar con la ETA del fabricante y el soporte real.` });
      return;
    }
  }
  const [code, c] = anchors[anchors.length - 1];
  ps.values.TACO_ANCLAJE = code;
  ps.sources.TACO_ANCLAJE = "calculo";
  notes.push({ level: "advertencia", code: "DIM-ANCLAJE", message: `Ningún taco del catálogo resiste ${fx(need)} N de tracción por taco: se mantiene el `
    + `${lc(c.name)} y la comprobación no se cumplirá (reduzca el empuje o amplíe la base).` });
}

/** Perfil que hay que aumentar cuando falla el desplome en la dirección axis (0 = X, 1 = Y): el más flexible del pórtico,
 * pata (EI/h) o viga de esa dirección (EI/L, L = vano entre patas). */
function swayMember(family, m, ps, profAutos, idx, cands, axis) {
  const lp = family.leg_param, beam = family.swayBeamParam(axis);
  const opts = [lp, beam].filter((k) => k && profAutos.includes(k) && idx[k] + 1 < cands[k].length);
  if (opts.length < 2) return opts.length ? opts[0] : profAutos.includes(lp) ? lp : null;
  const pts = [...new Set((m.structure.supports ?? []).map((s) => pyRound(s.point[axis], 3)))].sort((a, b) => a - b);
  let span = 0;
  for (let k = 1; k < pts.length; k++) span = Math.max(span, pts[k] - pts[k - 1]);
  const h = m.structure.worktop_height;
  const kLeg = C.profile(ps.values[lp]).props.Iy / h;
  const kBeam = span > 0 ? C.profile(ps.values[beam]).props.Iy / span : Infinity;
  return kBeam < kLeg ? beam : lp;
}

/** Reglas constructivas propias de la familia: sobre la pata/montante (legFits: aumenta el perfil 'auto' de la serie hasta
 * cumplirla) y sobre otros perfiles (fitProfiles, p. ej. una base al menos tan ancha como la columna que lleva encima). */
function fitLeg(family, ps, profAutos) {
  const lp = family.leg_param, series = family.candidates[lp];
  let changed = false;
  if (family.legFits && profAutos.includes(lp) && series.includes(ps.values[lp]))
    while (!family.legFits(ps.values) && series.indexOf(ps.values[lp]) + 1 < series.length) {
      ps.values[lp] = series[series.indexOf(ps.values[lp]) + 1];
      changed = true;
    }
  if (family.fitProfiles && family.fitProfiles(ps.values, profAutos)) changed = true;
  return changed;
}

/** Peor reacción vertical de servicio por apoyo (kg) con los apoyos que tiene ps. */
function supportNeed(family, ps) {
  const rep = analyze(family.construct(ps), false, false);
  const grav = new Set(Object.entries(rep.combinations.ELS).filter(([, f]) => "G" in f).map(([c]) => c));
  const rz = rep.reactions.filter((r) => grav.has(r.combination)).map((r) => r.Rz_N);
  return rz.length ? Math.max(...rz) / G_ACC : null;
}

/** Pie o rueda de menor capacidad que soporta la peor reacción de servicio, comprobada con el propio apoyo montado. */
function selectFeet(family, ps, notes) {
  let need = supportNeed(family, ps);
  if (need === null) return;
  const sp = family.support_param ?? "PIE_NIVELADOR", cat = family.support_category ?? "patas";
  const word = cat.startsWith("ruedas") ? "Rueda" : "Pie nivelador";
  const feet = Object.entries(C.components()).filter(([, c]) => c.category === cat && !c.brake).map((x, i) => ({ x, i }))
    .sort((a, b) => a.x[1].rated_load_kg - b.x[1].rated_load_kg || a.i - b.i).map((o) => o.x);
  const leg = C.profile(ps.values[family.leg_param]);
  const before = ps.values[sp];
  for (const [code, c] of feet) {
    const nut = C.component(`TUERCA_SOLDAR_${c.thread}`);
    const fits = nut.s / 0.8660254 <= leg.B - 2 * leg.t - 1;
    if (!fits || c.rated_load_kg < need) continue;
    ps.values[sp] = code;
    const own = supportNeed(family, ps);          // con este apoyo montado
    if (own !== null && c.rated_load_kg < own) { need = Math.max(need, own); continue; }
    if (own !== null) need = own;
    ps.sources[sp] = "calculo";
    notes.push({ level: "propuesta", code: "DIM-PIES", message: `${word} seleccionad${word === "Rueda" ? "a" : "o"} por cálculo: ${c.name} (capacidad nominal de catálogo `
      + `${c.rated_load_kg} kg ≥ reacción de servicio ${pyRound(need, 0).toFixed(0)} kg por apoyo). Capacidad a confirmar con la ficha del proveedor.` });
    return;
  }
  ps.values[sp] = before;
  notes.push({ level: "advertencia", code: "DIM-PIES", message: `Ningún ${word.toLowerCase()} del catálogo admite ${pyRound(need, 0).toFixed(0)} kg por apoyo con la pata/montante `
    + `${leg.code}: se mantiene ${ps.values[sp]} y la comprobación no se cumplirá.` });
}

/** Resuelve los 'auto' y construye el modelo (ProductFamily.build). */
export function build(family, params, onProgress = null) {
  let ruleNotes = [];
  const ruled = new Set();          // la regla puede reajustar lo que ella misma fijó (el redimensionado cambia perfiles)
  let model, notes;
  // cargas de uso no indicadas: se adoptan las del uso previsto (el diseño queda siempre verificado)
  const dl = Object.entries(family.defaultLoads ? family.defaultLoads(params.values) : {}).filter(([k]) => params.values[k] == null);
  if (dl.length) {
    params = copyParams(params);
    for (const [k, [kg]] of dl) { params.values[k] = kg; params.sources[k] = "por_uso"; }
    const label = Object.fromEntries(family.specs().map((sp) => [sp.name, sp.label]));
    ruleNotes.push({ level: "propuesta", code: "CARGA-USO", message: "Carga de uso no indicada: se adopta "
      + dl.map(([k, [kg, why]]) => `${(label[k] ?? k).toLowerCase()} ${g(kg)} kg (${why})`).join("; ") + ". Confírmela o indique la real." });
  }
  const anchorable = family.specs().some((sp) => sp.name === "ANCLAJE" && (sp.choices ?? []).includes("al_suelo"));
  for (let it = 0; it < 5; it++) {
    const autos = Object.entries(params.values).filter(([, v]) => v === AUTO).map(([k]) => k);
    let resolved;
    [resolved, notes] = autos.length ? resolveAuto(family, params, autos, onProgress) : [copyParams(params), []];
    model = family.construct(resolved);
    // valores por defecto incompatibles (nunca los del usuario): se corrigen y se vuelve a dimensionar
    const fixes = Object.entries(model.rule_fixes).filter(([k, [val]]) => (params.sources[k] === "defecto" || ruled.has(k)) && params.values[k] !== val);
    // sin anclaje (por defecto) el conjunto vacío volcaría con el empuje: se ancla al suelo
    if (!fixes.length && anchorable && params.sources.ANCLAJE === "defecto" && params.values.ANCLAJE === "ninguno") {
      const ov = overturning(model, model.params.values);
      if (ov && ov.ratio > 1.0 + 1e-9) fixes.push(["ANCLAJE", ["al_suelo", `Anclaje al suelo (regla de diseño): sin anclar, el conjunto vacío vuelca con el `
        + `empuje de ${g(ov.H_N)} N (aprovechamiento ${fx(ov.ratio, 2)}; admite ${ov.admissible_N} N).`]]);
    }
    if (!fixes.length) break;
    params = copyParams(params);
    for (const [k, [val, why]] of fixes) {
      params.values[k] = val; params.sources[k] = "regla_diseno";
      ruleNotes = ruleNotes.filter((n) => n.code !== `REGLA-${k}`);
      ruleNotes.push({ level: "propuesta", code: `REGLA-${k}`, message: why });
      ruled.add(k);
    }
  }
  model.requested = params;
  for (const n of [...notes, ...ruleNotes]) model.design_notes.unshift(n);
  autoExplode(model);          // explosionado sin solapes entre subconjuntos
  return model;
}
