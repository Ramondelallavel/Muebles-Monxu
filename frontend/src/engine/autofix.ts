// @ts-nocheck
// Corrección automática de un diseño que NO CUMPLE por valores fijados (port de monxu/engineering/autofix.py): se
// devuelven a 'auto' los valores que impiden cumplir, se ancla al suelo o, en un carro, se limita la fuerza de maniobra
// a la admisible; la corrección sólo se ofrece si, regenerado y verificado, no queda ninguna comprobación en NO CUMPLE.
// La propuesta lleva el veredicto del diseño corregido (puede seguir PENDIENTE DE VALIDACIÓN).
import { analyze } from "./analysis";
import { AUTO } from "./model";
import { build } from "./sizing";
import { g } from "./util";

const STRUCTURAL_SHEET = "S235JR";
const MEMBER_CATEGORIES = ["resistencia", "pandeo", "deformacion", "soldadura", "desplome"];
const fixed = (values, k) => k in values && values[k] != null && values[k] !== AUTO;

function candidates(fam, values, eng) {
  const specs = Object.fromEntries(fam.specs().map((s) => [s.name, s]));
  const fails = eng.checks.filter((c) => c.status === "NO_CUMPLE");
  const fix = {}, why = [];
  const toAuto = (keys, reason) => {
    const ks = keys.filter((k) => k && specs[k]?.allow_auto && fixed(values, k) && !(k in fix));
    for (const k of ks) fix[k] = AUTO;
    if (ks.length) why.push(reason + ": " + ks.map((k) => specs[k].label).join(", ") + " → auto");
  };
  const merged = () => ({ ...Object.fromEntries(Object.entries(specs).map(([k, s]) => [k, s.default])), ...values });
  const profiles = Object.keys(specs).filter((k) => k.startsWith("PERFIL_"));
  for (const c of fails) {
    const cid = c.id;
    if (cid === "E.VUELCO") {
      const anc = specs.ANCLAJE;
      if (anc && (anc.choices ?? []).includes("al_suelo")) {
        if (values.ANCLAJE !== "al_suelo") {
          fix.ANCLAJE = "al_suelo";
          if (specs.TACO_ANCLAJE) fix.TACO_ANCLAJE = AUTO;
          why.push("Vuelco sin anclar: anclaje al suelo con el taco dimensionado por cálculo");
        }
      } else {          // carro: no se ancla; la maniobra admisible del carro vacío
        const adm = c.details?.empuje_admisible_N;
        if (adm != null && adm >= 5) {
          const v = Math.floor(adm / 5) * 5;
          fix.CARGA_HORIZONTAL = v;
          why.push(`Vuelco del carro vacío: fuerza de maniobra limitada a ${g(v)} N (la admisible); indíquelo en las instrucciones de uso`);
        }
      }
    } else if (cid === "E.ANCLAJE") toAuto(["TACO_ANCLAJE"], "Taco de anclaje insuficiente");
    else if (cid.startsWith("PL.")) for (const t of fam.plateTargets(merged()) ?? []) toAuto([t.t_param, t.n_param], "Chapa que no verifica");
    else if (cid === "A.PIES") toAuto([fam.support_param], "Apoyos con capacidad insuficiente");
    else if (MEMBER_CATEGORIES.includes(c.category) || /^(B|D|S|W)\./.test(cid)) toAuto(profiles, "Perfiles fijados que no verifican");
  }
  const out = Object.keys(fix).length ? [[{ ...fix }, [...why]]] : [];
  // segundo intento: si falla una chapa con un material sin límite elástico garantizado, chapa estructural S235JR
  if (fails.some((c) => c.id.startsWith("PL."))) {
    for (const mp of ["MATERIAL_CHAPA", "MATERIAL_PLACA"]) {
      const sp = specs[mp];
      if (sp && fixed(values, mp) && values[mp] !== STRUCTURAL_SHEET && (sp.choices ?? []).includes(STRUCTURAL_SHEET)) {
        const fix2 = { ...fix, [mp]: STRUCTURAL_SHEET };
        for (const t of fam.plateTargets(merged()) ?? []) for (const k of [t.t_param, t.n_param]) if (k && specs[k]?.allow_auto) fix2[k] = AUTO;
        out.push([fix2, [...why, `${sp.label}: ${STRUCTURAL_SHEET} (límite elástico garantizado) con espesor por cálculo`]]);
      }
    }
  }
  // estabilidad global insuficiente (α_cr < 3) sin anclar: anclaje al suelo. Con los apoyos anclados la comprobación
  // no se da por buena: queda PENDIENTE DE VALIDACIÓN (cortante de los tacos), y así se indica en la propuesta
  const anc = specs.ANCLAJE;
  if (fails.some((c) => c.id.startsWith("S.ALFA-CR")) && anc && (anc.choices ?? []).includes("al_suelo") && values.ANCLAJE !== "al_suelo" && !("ANCLAJE" in fix)) {
    const fix3 = { ...fix, ANCLAJE: "al_suelo" };
    if (specs.TACO_ANCLAJE) fix3.TACO_ANCLAJE = AUTO;
    out.push([fix3, [...why, "Estabilidad global insuficiente sin anclar (α_cr < 3): anclaje al suelo; la coacción horizontal de los tacos queda pendiente de validación"]]);
  }
  return out;
}

/** Regenera y verifica con la corrección; el informe lleva los errores que queden en las notas del diseño. */
function verify(fam, values, sources, fix) {
  const trial = { ...values, ...fix };
  const src = Object.fromEntries(Object.keys(trial).map((k) => [k, k in fix ? "correccion" : sources?.[k] ?? "usuario"]));
  try {
    const m = build(fam, fam.newParams(trial, src));
    const r = analyze(m);
    r._errors = m.design_notes.filter((n) => n.level === "error").map((n) => n.code);
    return r;
  } catch { return null; }
}
const ok = (r) => !!r && r.status === "CUMPLE" && !r._errors.length;

/** Valores fijados que la geometría no admite: el valor válido más próximo que calcula la propia familia (rule_fixes). */
export function geometricFixes(fam, values, model) {
  const specs = Object.fromEntries(fam.specs().map((s) => [s.name, s]));
  const fix = {}, why = [];
  for (const [k, [v]] of Object.entries(model?.rule_fixes ?? {})) {
    if (fixed(values, k) && values[k] !== v && specs[k]) {
      fix[k] = v;
      why.push(typeof v === "number" ? `${specs[k].label}: ${g(v)}${specs[k].unit ? ` ${specs[k].unit}` : ""}, el valor válido más próximo para la geometría`
        : `${specs[k].label}: ${v}`);
    }
  }
  return [fix, why];
}

/** Primera corrección que hace CUMPLIR el diseño sin errores (comprobada regenerando y verificando), o null. */
export function proposeFix(fam, values, sources, eng, model = null) {
  const [geo, geoWhy] = model ? geometricFixes(fam, values, model) : [{}, []];
  const failing = eng.status === "NO_CUMPLE";
  if (!failing && !Object.keys(geo).length) return null;
  let cands = failing ? candidates(fam, values, eng).map(([f, w]) => [{ ...geo, ...f }, [...geoWhy, ...w]]) : [];
  if (Object.keys(geo).length && !cands.length) cands = [[geo, geoWhy]];
  const attempt = (fix, why) => {
    let r = verify(fam, values, sources, fix);
    // carro: con menos fuerza el dimensionado aligera el carro y su peso estabiliza menos; se itera la admisible
    for (let it = 0; it < 5; it++) {
      if (!r || ok(r) || !("CARGA_HORIZONTAL" in fix)) break;
      const vu = r.checks.find((c) => c.id === "E.VUELCO" && c.status === "NO_CUMPLE");
      const adm = vu?.details?.empuje_admisible_N;
      if (adm == null || adm < 5 || Math.floor(adm / 5) * 5 >= fix.CARGA_HORIZONTAL) break;
      fix = { ...fix, CARGA_HORIZONTAL: Math.floor(adm / 5) * 5 };
      why = [...why.filter((w) => !w.startsWith("Vuelco del carro")), `Vuelco del carro vacío: fuerza de maniobra limitada a ${g(fix.CARGA_HORIZONTAL)} N `
        + "(la admisible); indíquelo en las instrucciones de uso"];
      r = verify(fam, values, sources, fix);
    }
    return [fix, why, r];
  };
  // el veredicto del diseño corregido acompaña a la propuesta: «sin NO CUMPLE» no equivale a verificado
  const result = (fix, why, r) => ({ params: fix, reasons: why, status: r.status, verdict: r.verdict ?? null,
    validation_pending: (r.validation_pending ?? []).length, governing: r.governing?.description ?? null });
  for (const [fix0, why0] of cands) {
    const [fix, why, r] = attempt(fix0, why0);
    if (ok(r)) return result(fix, why, r);
    // corregida la geometría, el cálculo puede no cumplir aún: se añade la corrección de cálculo sobre ella
    if (Object.keys(geo).length && r && r.status === "NO_CUMPLE" && !r._errors.length) {
      for (const [f2, w2] of candidates(fam, { ...values, ...fix }, r)) {
        const [fix2, why2, r2] = attempt({ ...fix, ...f2 }, [...why, ...w2]);
        if (ok(r2)) return result(fix2, why2, r2);
      }
    }
  }
  return null;
}
