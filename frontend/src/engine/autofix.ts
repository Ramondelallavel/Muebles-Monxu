// @ts-nocheck
// Corrección automática de un diseño que NO CUMPLE por valores fijados (port de monxu/engineering/autofix.py): se
// devuelven a 'auto' los valores que impiden cumplir, se ancla al suelo o, en un carro, se limita la fuerza de maniobra
// a la admisible; la corrección sólo se ofrece si, regenerado y verificado, el diseño CUMPLE.
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
  return out;
}

function verify(fam, values, sources, fix) {
  const trial = { ...values, ...fix };
  const src = Object.fromEntries(Object.keys(trial).map((k) => [k, k in fix ? "correccion" : sources?.[k] ?? "usuario"]));
  try { return analyze(build(fam, fam.newParams(trial, src))); } catch { return null; }
}

/** Primera corrección que hace CUMPLIR el diseño (comprobada regenerando y verificando), o null. */
export function proposeFix(fam, values, sources, eng) {
  if (eng.status !== "NO_CUMPLE") return null;
  for (let [fix, why] of candidates(fam, values, eng)) {
    let r = verify(fam, values, sources, fix);
    // carro: con menos fuerza el dimensionado aligera el carro y su peso estabiliza menos; se itera la admisible
    for (let it = 0; it < 5; it++) {
      if (!r || r.status === "CUMPLE" || !("CARGA_HORIZONTAL" in fix)) break;
      const vu = r.checks.find((c) => c.id === "E.VUELCO" && c.status === "NO_CUMPLE");
      const adm = vu?.details?.empuje_admisible_N;
      if (adm == null || adm < 5 || Math.floor(adm / 5) * 5 >= fix.CARGA_HORIZONTAL) break;
      fix = { ...fix, CARGA_HORIZONTAL: Math.floor(adm / 5) * 5 };
      why = [...why.filter((w) => !w.startsWith("Vuelco del carro")), `Vuelco del carro vacío: fuerza de maniobra limitada a ${g(fix.CARGA_HORIZONTAL)} N `
        + "(la admisible); indíquelo en las instrucciones de uso"];
      r = verify(fam, values, sources, fix);
    }
    if (r && r.status === "CUMPLE") return { params: fix, reasons: why, status: r.status, governing: r.governing?.description ?? null };
  }
  return null;
}
