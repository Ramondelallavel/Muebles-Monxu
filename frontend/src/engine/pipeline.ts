// @ts-nocheck
// Regeneración completa desde la fuente única de parámetros y control de calidad (port de monxu/pipeline.py y
// monxu/validation/qa.py). Lo que en el navegador no puede verificarse con B-rep se declara PENDIENTE.
import * as C from "./catalog";
import { analyze } from "./analysis";
import { proposeFix } from "./autofix";
import { family } from "./families";
import { instanceBBox, modelBBox, partGeometry } from "./geometry";
import { buildBom, dfmCheck, manufacturingPlan } from "./manufacturing";
import { quotation } from "./costing";
import { build } from "./sizing";
import { checkInterferences } from "./interference";
import { f as fx, g, pyRound } from "./util";
import { assemblyNotes, designationIssues, foreignWords, stepTexts } from "./drawings";
import { dependencyMap } from "./dependencies";

const BLOCK = "bloqueante", WARN = "advertencia", OKL = "ok", PEND = "pendiente";
export const SEVERITIES = ["CRÍTICO", "BLOQUEANTE", "ADVERTENCIA", "INFORMATIVO"];
const CRITICAL_PREFIXES = ["XDOC-", "GEO-VALIDA", "GEO-INTERFERENCIAS", "GEO-DIMENSIONES", "BOM-", "EXP-", "PLANO-", "CALC-NO"];
const DOCUMENTS = [["XDOC-", "Documentación cruzada"], ["GEO-", "Modelo 3D"], ["UNI-", "Modelo 3D"], ["BOM-", "BOM"], ["CHAPA-", "Desarrollos y DXF"], ["MAT-", "Materiales"],
  ["CALC", "Cálculo estructural"], ["COMP-", "Componentes comerciales"], ["SOL-", "Soldadura"], ["EXP-STEP", "STEP"], ["EXP-STL", "STL"], ["EXP-DXF", "DXF"],
  ["EXP-EXCEL", "Excel BOM"], ["EXP-PDF", "Planos"], ["PLANO-", "Planos"], ["DFM", "Fabricación (DFM)"], ["LAS-", "Fabricación (DFM)"], ["PLG-", "Fabricación (DFM)"],
  ["PRF-", "Fabricación (DFM)"], ["MON-", "Montaje y tornillería"], ["GAL-", "Fabricación (DFM)"]];
const RESULTS = { [BLOCK]: "NO CUMPLE", [WARN]: "ADVERTENCIA", [PEND]: "PENDIENTE DE VALIDACIÓN", [OKL]: "CUMPLE" };
const docOf = (code) => DOCUMENTS.find(([p]) => code.startsWith(p))?.[1] ?? "Modelo";

/** Motor central de validaciones (= monxu/validation/qa.py): cada comprobación con código, descripción, resultado, severidad, documento,
 *  valor esperado y obtenido, diferencia, criterio y acción. ``level`` se conserva: bloqueante impide exportar; bloqueante, pendiente y
 *  ``release_block`` impiden liberar para fabricación. */
export class QA {
  constructor() { this.items = []; }
  add(level, code, message, data = {}) {
    const { severity, result, description, document, expected, obtained, difference, criterion, action, release_block, ...rest } = data;
    this.items.push({ level, code, message,
      severity: severity ?? (level === BLOCK ? (CRITICAL_PREFIXES.some((p) => code.startsWith(p)) ? "CRÍTICO" : "BLOQUEANTE") : level === PEND ? "BLOQUEANTE" : level === WARN ? "ADVERTENCIA" : "INFORMATIVO"),
      result: result ?? RESULTS[level], description: description ?? message, document: document ?? docOf(code), expected: expected ?? null, obtained: obtained ?? null,
      difference: difference ?? null, criterion: criterion ?? null, action: action ?? null, release_block: release_block ?? (level === BLOCK || level === PEND), ...rest });
  }
  result() {
    const lv = this.items.map((i) => i.level);
    const n = (x) => lv.filter((l) => l === x).length;
    const blocking = n(BLOCK);
    const by_severity = Object.fromEntries(SEVERITIES.map((s) => [s, this.items.filter((i) => i.severity === s && i.level !== OKL).length]));
    return { result: blocking ? "bloqueante" : lv.includes(WARN) ? "advertencia" : "ok", blocking, warnings: n(WARN), pending: n(PEND), ok: n(OKL),
      items: this.items, by_severity, release_blockers: this.items.filter((i) => i.release_block).map((i) => i.code),
      summary: `${blocking} errores bloqueantes, ${n(WARN)} advertencias, ${n(PEND)} validaciones pendientes, ${n(OKL)} comprobaciones satisfactorias.` };
  }
}

export function modelChecks(model, eng, dfm, bom, interf, plan = null, cost = null) {
  const q = new QA();
  const ps = model.params.values;
  // geometría: mallas cerradas y volumen positivo (la validez B-rep se comprueba en el servidor)
  const bad = [];
  for (const p of Object.values(model.parts)) {
    const g = partGeometry(p);
    if ((p.kind !== "normalizado" && !(p.volume > 0)) || !(g.volume > 0) || !g.closed) bad.push(`${p.ref}${g.closed ? "" : ` (${g.openEdges} aristas abiertas)`}`);
  }
  q.add(bad.length ? BLOCK : OKL, "GEO-VALIDA", bad.length ? `Sólidos no válidos: ${bad}` :
    `${Object.keys(model.parts).length} definiciones de pieza con volumen positivo y malla cerrada y orientada (la validez B-rep se comprueba en el servidor).`);
  const seen = new Map(), dup = [];
  for (const i of model.instances) {
    const k = i.part.key + "|" + i.T.flat().map((v) => Math.round(v * 1e4) / 1e4).join(",");
    if (seen.has(k)) dup.push([seen.get(k), i.id]);
    seen.set(k, i.id);
  }
  q.add(dup.length ? BLOCK : OKL, "GEO-DUPLICADOS", dup.length ? `Componentes duplicados en la misma posición: ${JSON.stringify(dup)}` : "Sin componentes duplicados coincidentes.");
  const nI = interf.interferences.length;
  q.add(nI ? BLOCK : OKL, "GEO-INTERFERENCIAS", nI ? `${nI} interferencias: ` + interf.interferences.map((x) => `${x.a}↔${x.b} ${x.penetration_mm ?? "contenida"} mm`).join("; ")
    : `Sin interferencias (${interf.pairs_checked} parejas con envolventes solapadas evaluadas sobre los sólidos facetados; penetración admitida ${String(interf.tolerance_mm).replace(".", ",")} mm por teselado).`);
  for (const n of model.design_notes) {
    if (n.level === "error") q.add(BLOCK, n.code, n.message);
    else if (n.level === "advertencia") q.add(WARN, n.code, n.message);
  }
  const env = model.dims.envelope;
  if (env) {
    const insts = env.ids ? env.ids.map((i) => model.instance(i)) : model.instances.filter((i) => (env.groups ?? []).includes(i.group));
    const lo = [0, 1, 2].map((j) => Math.min(...insts.map((i) => instanceBBox(i)[0][j])));
    const hi = [0, 1, 2].map((j) => Math.max(...insts.map((i) => instanceBBox(i)[1][j])));
    const [nx, ny] = env.names ?? ["LONGITUD", "ANCHURA"];
    const devs = { [nx]: hi[0] - lo[0] - env.dx, [ny]: hi[1] - lo[1] - env.dy, ALTURA: hi[2] - env.zmax };
    const badD = Object.fromEntries(Object.entries(devs).filter(([, v]) => Math.abs(v) > 0.01).map(([k, v]) => [k, Math.round(v * 1e4) / 1e4]));
    q.add(Object.keys(badD).length ? BLOCK : OKL, "GEO-DIMENSIONES", Object.keys(badD).length ? `Desviación entre geometría y parámetros: ${JSON.stringify(badD)}`
      : "Dimensiones generales de la geometría coinciden con los parámetros (±0,01 mm).");
    const [blo, bhi] = modelBBox(model);
    const over = Math.max(lo[0] - blo[0], lo[1] - blo[1], bhi[0] - hi[0], bhi[1] - hi[1]);
    if (over > 0.5) {     // qué sobresale (pies, ruedas, manetas...), no siempre los apoyos
      const names = [];
      for (const i of model.instances) {
        const [b0, b1] = instanceBBox(i);
        if (Math.max(lo[0] - b0[0], lo[1] - b0[1], b1[0] - hi[0], b1[1] - hi[1]) > 0.5 && !names.includes(i.part.name)) names.push(i.part.name);
      }
      q.add(WARN, "GEO-SALIENTE", `Elementos sobresalen ${fx(over, 1)} mm del contorno del producto (${names.slice(0, 3).join("; ")}${names.length > 3 ? "…" : ""}): considerar en implantación.`,
        { expected: `contorno ${fx(hi[0] - lo[0], 1)} × ${fx(hi[1] - lo[1], 1)} mm`, obtained: `envolvente máxima ${fx(bhi[0] - blo[0], 1)} × ${fx(bhi[1] - blo[1], 1)} × ${fx(bhi[2] - blo[2], 1)} mm`,
          difference: pyRound(over, 2), criterion: "Las cotas generales son las del contorno declarado; la envolvente máxima (cabezas de tornillo, pies, manetas) figura en el plano de conjunto",
          action: "Considerar la envolvente máxima en la implantación y el embalaje" });
    }
  }
  const gD = model.ctx.derived.HOLGURA_ENC, rD = model.ctx.derived.RADIO_ENC;
  if (gD && rD && gD.value && rD.value) q.add(gD.value >= rD.value ? OKL : BLOCK, "GEO-HOLGURAS", gD.value >= rD.value
    ? `Holgura estructura–pestaña ${gD.value} mm ≥ radio de plegado ${rD.value} mm.` : "Holgura menor que el radio de plegado.");
  const fin = C.finish(ps.ACABADO);
  const fams = new Set(Object.values(model.parts).filter((p) => p.material).map((p) => C.material(p.material).family));
  const inc = [...fams].filter((f) => !fin.compatible.includes(f));
  q.add(inc.length ? WARN : OKL, "MAT-ACABADO", inc.length ? `Acabado '${fin.name}' no indicado para ${JSON.stringify(inc)}.`
    : `Acabado compatible con los materiales (${[...fams].sort().join(", ")}).`);
  if ((fams.has("acero_carbono") && fams.has("acero_inoxidable")) || (fams.has("aluminio") && fams.has("acero_carbono")))
    q.add(WARN, "MAT-GALVANICO", "Contacto entre metales distintos: riesgo de corrosión galvánica; prever aislamiento.");
  for (const p of Object.values(model.parts)) {
    if (p.material && C.material(p.material).haz_reduction_required && model.joints.some((j) => j.kind === "soldadura" && j.members.some((m) => model.instance(m).part === p))) {
      q.add(PEND, "MAT-HAZ", "Aluminio soldado: reducción de resistencia en ZAT (EN 1999-1-1 §6.1.6) no evaluada.");
      break;
    }
  }
  if (["exterior", "interior_humedo"].includes(ps.ENTORNO) && fams.has("acero_carbono") && ps.ACABADO !== "GALVANIZADO")
    q.add(WARN, "MAT-ENTORNO", "Entorno húmedo/exterior con acero al carbono pintado: valorar galvanizado o inoxidable.");
  if (ps.ENTORNO === "alimentario" && [...fams].some((f) => f !== "acero_inoxidable"))
    q.add(WARN, "MAT-ALIMENTARIO", "Uso alimentario: se recomienda acero inoxidable en superficies de contacto.");
  for (const f of dfm) if (f.level === "error") q.add(BLOCK, f.code, `${f.element}: ${f.message} ${f.proposal ?? ""}`.trim());
  q.add(OKL, "DFM", `${dfm.filter((f) => f.level === "error").length} errores de fabricabilidad, ${dfm.filter((f) => f.level === "advertencia").length} advertencias de fabricación.`);
  const members = model.instances.filter((i) => i.structural).map((i) => i.id);
  const welded = new Set(model.joints.filter((j) => j.kind === "soldadura").flatMap((j) => j.members));
  const loose = members.filter((m) => !welded.has(m));
  q.add(loose.length ? BLOCK : OKL, "UNI-CONECTIVIDAD", loose.length ? `Barras sin unión: ${loose}` :
    `Todas las barras estructurales (${members.length}) están unidas; ${model.joints.length} uniones definidas.`);
  const instMass = model.instances.reduce((s, i) => s + i.part.mass, 0);
  q.add(Math.abs(instMass - bom.totals.total_mass) <= 0.0005 + 1e-6 * instMass ? OKL : BLOCK, "BOM-PESO",
    `Masa del BOM ${bom.totals.total_mass.toFixed(3)} kg = suma de instancias ${instMass.toFixed(3)} kg.`);
  const devs = [];
  for (const r of bom.rows) if (r.nominal_mass) { const dv = Math.abs(r.unit_mass - r.nominal_mass) / r.nominal_mass; if (dv > 0.02) devs.push([r.ref, Math.round(dv * 1e4) / 100]); }
  q.add(devs.length ? WARN : OKL, "BOM-PESO-NOMINAL", devs.length ? `Diferencias > 2 % entre masa del sólido y masa nominal: ${JSON.stringify(devs)}`
    : "Masas de los sólidos coherentes con las masas nominales (perfil kg/m, desarrollo×espesor) < 2 %.");
  const qty = bom.rows.reduce((s, r) => s + r.qty, 0);
  q.add(qty === model.instances.length ? OKL : BLOCK, "BOM-CANTIDADES", `Cantidades del BOM (${qty}) = instancias del modelo (${model.instances.length}).`);
  const refs = Object.values(model.parts).map((p) => p.ref);
  q.add(new Set(refs).size === refs.length && refs.every(Boolean) ? OKL : BLOCK, "BOM-REFERENCIAS",
    new Set(refs).size === refs.length ? "Referencias únicas asignadas a todas las piezas." : "Referencias duplicadas.");
  // sólido facetado frente a la definición analítica de cada pieza (volumen con taladros)
  const volDev = [];
  for (const p of Object.values(model.parts)) {
    if (p.kind === "normalizado") continue;
    const dev = Math.abs(partGeometry(p).volume - p.volume) / p.volume;
    if (p.kind === "chapa") {
      q.add(dev < 2e-3 ? OKL : BLOCK, "CHAPA-DESARROLLO", dev < 2e-3
        ? `${p.ref}: desarrollo coherente con el sólido 3D plegado con taladros (desviación de volumen ${dev.toExponential(1)}, radios teselados).`
        : `${p.ref}: el desarrollo NO coincide con el sólido 3D (desviación de volumen ${dev.toExponential(1)}): revisar taladros en zona de pliegue.`);
    } else if (dev > 5e-3) volDev.push(`${p.ref} ${(dev * 100).toFixed(2)} %`);
  }
  q.add(volDev.length ? BLOCK : OKL, "GEO-VOLUMEN", volDev.length ? `Volumen del sólido distinto del analítico: ${volDev.join("; ")}`
    : "Volumen de cada sólido (perfiles con taladros y pletinas) coherente con su definición analítica (< 0,5 %, radios teselados).");
  if (eng.status === "NO_CUMPLE") {
    const fails = eng.checks.filter((c) => c.status === "NO_CUMPLE");
    let advice = "";
    const v = fails.find((c) => c.id === "E.VUELCO");
    if (v?.details?.empuje_admisible_N != null) advice = ` · Propuesta frente al vuelco: vacía, la configuración admite ${Math.round(v.details.empuje_admisible_N)} N de empuje `
      + `horizontal sin anclar (supuesto actual ${Math.round(ps.CARGA_HORIZONTAL ?? 0)} N). Confirme el empuje real en «Cargas y uso» o elija ANCLAJE = al suelo.`;
    if (fails.some((c) => c.id !== "E.VUELCO")) advice += " · Las demás comprobaciones se corrigen dejando los perfiles y espesores en «auto» para que el dimensionado los aumente.";
    q.add(WARN, "CALC-NO-CUMPLE", "Verificación estructural NO superada (no apto para fabricación hasta modificar el diseño): "
      + fails.map((c) => c.description).join("; ") + advice, { release_block: true, severity: "CRÍTICO", result: "NO CUMPLE", action: "Modificar el diseño (perfiles, espesores o cargas)" });
  }
  else if (eng.status === "PENDIENTE") q.add(PEND, "CALC-PENDIENTE", "Verificación estructural incompleta: " + (eng.pending.length ? eng.pending : ["datos pendientes"]).join("; "));
  else q.add(OKL, "CALC", eng.validation_pending?.length ? "Comprobaciones estructurales calculadas: CUMPLEN." : "Verificación estructural automatizada completa: CUMPLE.");
  for (const v of eng.validation_pending ?? []) q.add(PEND, `CALC-VAL-${v.id}`, `Cálculo pendiente de validación — ${v.description}: ${v.reason}.`, { document: "Cálculo estructural",
    criterion: "Dato certificado (ficha técnica, ETA, certificado 3.1 o anejo nacional) que sustituya la hipótesis",
    action: "Validar con el documento correspondiente y registrar su referencia en la validación técnica" });
  if (plan) crossChecks(q, model, eng, dfm, bom, plan, cost);
  return q;
}

const counter = (xs) => { const c = {}; for (const x of xs) c[x] = (c[x] ?? 0) + 1; return c; };
/** Controles cruzados entre documentos generados desde el modelo maestro (= qa.cross_checks). */
export function crossChecks(q, model, eng, dfm, bom, plan, cost) {
  const lot = plan.lot ?? 1;
  const inst = counter(model.instances.map((i) => i.part.key));
  const nInst = model.instances.length, nBom = bom.rows.reduce((t, r) => t + r.qty, 0);
  let bad = [];
  for (const p of Object.values(model.parts)) for (const r of bom.rows) if (r.ref === p.ref && r.qty !== inst[p.key]) bad.push(`${r.ref}: BOM ${r.qty} / 3D ${inst[p.key]}`);
  q.add(bad.length ? BLOCK : OKL, "XDOC-BOM-3D", "BOM frente a instancias del modelo 3D: " + (bad.length ? bad.join("; ") : `${bom.rows.length} referencias, ${nInst} instancias coincidentes.`),
    { expected: nInst, obtained: nBom, difference: nBom - nInst, criterion: "Cantidad de cada referencia del BOM = instancias del 3D", action: "Regenerar el BOM desde el modelo" });
  const byRef = Object.fromEntries(Object.values(model.parts).map((p) => [p.ref, inst[p.key] * lot]));
  const cut = counter(plan.cutting.flatMap((c) => c.bars.flatMap((b) => b.cuts.map((x) => x.ref))));
  const nest = counter(plan.nesting.filter((n) => n.feasible).flatMap((n) => n.sheets.flatMap((sh) => sh.placements.map((pl) => pl.ref))));
  const allFeasible = plan.nesting.every((n) => n.feasible);
  bad = [];
  for (const p of Object.values(model.parts)) {
    if (p.kind === "perfil" && (cut[p.ref] ?? 0) !== byRef[p.ref]) bad.push(`${p.ref}: plan ${cut[p.ref] ?? 0} / BOM ${byRef[p.ref]}`);
    if ((p.kind === "chapa" || p.kind === "pletina") && allFeasible && (nest[p.ref] ?? 0) !== byRef[p.ref]) bad.push(`${p.ref}: anidado ${nest[p.ref] ?? 0} / BOM ${byRef[p.ref]}`);
  }
  const sumv = (o) => Object.values(o).reduce((t, v) => t + v, 0);
  q.add(bad.length ? BLOCK : OKL, "XDOC-BOM-CORTE", "Piezas del plan de corte y del anidado frente al BOM: " + (bad.length ? bad.join("; ")
    : `${sumv(cut)} piezas de perfil y ${sumv(nest)} de chapa (lote de ${lot}).`), { expected: "cantidad BOM × lote", obtained: "piezas cortadas y anidadas",
    criterion: "Cada pieza del BOM aparece en el plan de corte o en el anidado tantas veces como unidades × lote", action: "Regenerar el plan de fabricación" });
  const std = counter(model.instances.filter((i) => i.part.kind === "normalizado").map((i) => i.part.code));
  const pur = Object.fromEntries(plan.purchases.items.filter((p) => p.type === "Comercial").map((p) => [p.code, p.qty]));
  bad = Object.keys(std).sort().filter((c) => pur[c] !== std[c] * lot).map((c) => `N-${c}: compras ${pur[c] ?? null} / BOM ${std[c] * lot}`);
  bad.push(...Object.keys(pur).filter((c) => !(c in std)).map((c) => `N-${c} sobrante en compras`));
  q.add(bad.length ? BLOCK : OKL, "XDOC-BOM-COMPRAS", "Componentes comerciales de la lista de compras frente al BOM: " + (bad.length ? bad.join("; ")
    : `${Object.keys(std).length} referencias coincidentes (lote de ${lot}).`), { criterion: "Unidades compradas = unidades del BOM × lote", action: "Regenerar la lista de compras" });
  // componentes comerciales del BOM: referencia N-<código> del catálogo y masa de catálogo positiva
  bad = bom.rows.filter((r) => r.kind === "normalizado" && (!r.code || r.ref !== `N-${r.code}` || !(r.unit_mass > 0))).map((r) => r.ref);
  q.add(bad.length ? BLOCK : OKL, "BOM-COMERCIALES", "Componentes comerciales del BOM: " + (bad.length ? "sin referencia de catálogo o sin masa: " + bad.join(", ")
    : `${Object.keys(std).length} referencias N-<código> con masa de catálogo.`), { criterion: "Cada componente comercial tiene referencia de catálogo y masa positiva",
    action: "Completar el componente en la base de componentes comerciales" });
  const bars = Object.fromEntries(plan.purchases.items.filter((p) => p.type === "Perfil").map((p) => [p.group, p.qty]));
  bad = [];
  for (const c of plan.cutting) { const grp = `${c.profile} ${c.material}`; if ((bars[grp] ?? 0) !== c.n_bars) bad.push(`${grp}: compras ${bars[grp] ?? 0} / plan ${c.n_bars}`); }
  for (const n of plan.nesting) {
    if (!n.feasible) continue;
    const grp = `${n.material} e=${g(n.thickness)} mm`;
    const full = plan.purchases.items.filter((p) => p.group === grp && p.type === "Chapa").reduce((t, p) => t + p.qty, 0);
    const cust = plan.purchases.items.filter((p) => p.group === grp && p.type === "Chapa (corte a medida)").reduce((t, p) => t + p.qty, 0);
    if (full !== n.purchase.n_full || cust !== n.purchase.n_custom) bad.push(`${grp}: compras ${full}+${cust} / anidado ${n.purchase.n_full}+${n.purchase.n_custom}`);
  }
  q.add(bad.length ? BLOCK : OKL, "XDOC-COMPRAS-OPT", "Lista de compras frente al plan de corte y al anidado: " + (bad.length ? bad.join("; ")
    : "barras y chapas compradas = las del plan de corte y del anidado."), { criterion: "Barras y chapas de la lista de compras = las de la optimización", action: "Regenerar la lista de compras" });
  bad = plan.cutting.flatMap((c) => c.bars.filter((b) => Math.abs(b.balance_mm) > 1e-6).map((b) => `${c.profile} barra ${b.bar}: ${g(b.balance_mm)} mm`));
  bad.push(...plan.balance.rows.filter((r) => r.balance !== null && Math.abs(r.balance) > 1e-6).map((r) => `${r.group}: ${r.balance}`));
  q.add(bad.length ? BLOCK : OKL, "XDOC-BALANCE", "Balance de material: " + (bad.length ? bad.join("; ")
    : "cada barra cumple L = despunte inicial + piezas + sierra + despunte final + retal, y lo comprado = neto + desperdicio + retales en cada grupo."),
  { expected: 0.0, obtained: Math.max(0.0, ...plan.cutting.flatMap((c) => c.bars.map((b) => Math.abs(b.balance_mm)))), criterion: "Balance nulo (±1e-6)", action: "Revisar el optimizador" });
  const t = bom.totals, sw = eng.self_weight;
  if (sw) {
    const d = sw.total_kg - t.mass_product_kg, ok = Math.abs(d) <= 0.002 * t.mass_product_kg + 0.01;
    q.add(ok ? OKL : BLOCK, "XDOC-PESO-CALC", `Peso propio del cálculo ${fx(sw.total_kg, 3)} kg (aplicado ${fx(sw.applied_kg, 3)} kg + ${fx(sw.below_supports_kg, 3)} kg bajo los apoyos) `
      + `frente a la masa del producto del BOM ${fx(t.mass_product_kg, 3)} kg.`, { expected: t.mass_product_kg, obtained: sw.total_kg, difference: pyRound(d, 3),
      criterion: "|diferencia| ≤ 0,2 % + 0,01 kg (definición analítica frente a sólido)", action: "Revisar las masas que no se aplican al modelo de cálculo" });
  }
  q.add(OKL, "XDOC-PESO-COMPRA", `Masas separadas: producto ${fx(t.mass_product_kg, 2)} kg/ud (fabricadas ${fx(t.mass_manufactured_kg, 2)} + comerciales ${fx(t.mass_commercial_kg, 2)}); `
    + `material comprado ${fx(t.mass_purchased_kg, 2)} kg, desperdicio ${fx(t.mass_waste_kg, 2)} kg y retales ${fx(t.mass_reusable_kg, 2)} kg para el lote de ${lot}: no se suman entre sí.`,
  { severity: "INFORMATIVO" });
  if (cost) {
    const raw = plan.purchases.items.filter((p) => (p.type.startsWith("Perfil") || p.type.startsWith("Chapa")) && p.purchase !== false && p.mass_kg !== null).reduce((s, p) => s + p.mass_kg, 0);
    if (cost.material_basis === "compra" && cost.lot === lot) {
      const mkg = cost.material_kg_per_unit * lot, ok = Math.abs(mkg - raw) <= 0.01 * Math.max(1, plan.purchases.items.length);
      q.add(ok ? OKL : BLOCK, "XDOC-PRESUPUESTO-COMPRAS", `Material del presupuesto ${fx(mkg, 3)} kg frente al material comprado ${fx(raw, 3)} kg (lote de ${lot}).`,
        { expected: pyRound(raw, 3), obtained: pyRound(mkg, 3), difference: pyRound(mkg - raw, 3), criterion: "Material presupuestado = barras y chapas compradas",
          action: "Recalcular el presupuesto con el plan de fabricación" });
    }
  }
  const texts = Object.values(stepTexts(model));
  bad = designationIssues(model, texts);
  q.add(bad.length ? BLOCK : OKL, "XDOC-TORNILLERIA-INSTR", "Referencias de las instrucciones de montaje frente al BOM: " + (bad.length ? bad.join(", ") + " no están en el BOM"
    : "todas las referencias y designaciones citadas están en el BOM y en el 3D."), { expected: "referencias del BOM", obtained: bad.join(", ") || "coincidentes",
    criterion: "Las instrucciones usan exactamente las referencias del BOM y del 3D", action: "Corregir el texto de montaje de la familia" });
  // textos generados ↔ producto: nada de vocabulario de otra familia (p. ej. «encimera» en una estantería)
  bad = foreignWords(model, [...texts, ...assemblyNotes(model), ...dfm.map((f) => f.message), ...(eng.hypotheses ?? []), ...(eng.limitations ?? []),
    ...(eng.load_cases ?? []).map((c) => c.label)]);
  q.add(bad.length ? BLOCK : OKL, "XDOC-TEXTOS-PRODUCTO", "Textos de montaje, fabricación y cálculo frente al producto: " + (bad.length
    ? "mencionan una encimera que el producto no tiene: " + bad.join(" | ") : "sin vocabulario de otro tipo de producto."),
  { expected: "textos propios del producto", obtained: bad.length ? `${bad.length} textos ajenos` : "coherentes",
    criterion: "Los textos generados solo nombran elementos que existen en el modelo", action: "Corregir el texto por defecto o el de la familia" });
  const joints = Object.fromEntries(model.joints.map((j) => [j.id, j]));
  bad = eng.checks.filter((c) => c.id.startsWith("W.") && joints[c.id.slice(2)] && c.details?.a_mm != null && Math.abs(c.details.a_mm - joints[c.id.slice(2)].weld.a) > 1e-9).map((c) => c.id);
  q.add(bad.length ? BLOCK : OKL, "XDOC-SOLDADURA-CALC", "Gargantas del cálculo frente a las de las uniones del modelo: " + (bad.length ? bad.join(", ") : "coincidentes."),
    { criterion: "El cálculo usa la garganta de cada unión del modelo", action: "Regenerar el cálculo" });
  for (const code of Object.keys(std).sort()) {
    const c = C.component(code), v = c.validation ?? {};
    if (v.status !== "definido_por_norma") q.add(PEND, `COMP-${code}`, `N-${code} (${c.name}): pendiente de validación — faltan ${(v.missing ?? ["datos técnicos"]).join(", ")}.`,
      { document: "Componentes comerciales", criterion: "Fabricante, modelo, ficha técnica y capacidades certificadas", action: "Seleccionar el modelo comercial y registrar su ficha en la validación" });
  }
  const thin = model.joints.filter((j) => j.kind === "soldadura" && j.weld.a < 3);
  if (thin.length) q.add(PEND, "SOL-WPS", `${thin.length} cordones con garganta < 3 mm en pared delgada: requieren WPS cualificada (EN ISO 15614-1) y control de penetración antes de fabricar.`,
    { document: "Soldadura", criterion: "WPS cualificada y soldadores cualificados (EN ISO 9606-1) para el espesor y la posición", action: "Cualificar la WPS y registrar su referencia en la validación técnica" });
}

/** Regenera modelo, cálculo, fabricación, BOM y QA. Devuelve el resumen con la misma estructura que el servidor. */
export function regenerate(familyId, values, sources = {}, onProgress = null, stock = null) {
  const t = {};
  const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
  const t0 = now();
  const fam = family(familyId);
  const ps = fam.newParams(values, Object.fromEntries(Object.keys(values).map((k) => [k, sources[k] ?? "usuario"])));
  const model = build(fam, ps, onProgress);
  t.modelo = (now() - t0) / 1000;
  let t1 = now();
  for (const p of Object.values(model.parts)) partGeometry(p);
  t.geometria = (now() - t1) / 1000;
  t1 = now();
  const eng = analyze(model);
  t.calculo = (now() - t1) / 1000;
  t1 = now();
  const plan = manufacturingPlan(model, stock);
  const dfm = dfmCheck(model, plan);
  const bom = buildBom(model, plan);
  t.fabricacion = (now() - t1) / 1000;
  t1 = now();
  const interf = checkInterferences(model);
  t.interferencias = (now() - t1) / 1000;
  const cost = quotation(model, plan);
  const q = modelChecks(model, eng, dfm, bom, interf, plan, cost);
  let fix = null;
  // corrección mínima de los valores fijados (cálculo o geometría), comprobada antes de ofrecerla
  if (eng.status === "NO_CUMPLE" || Object.keys(model.rule_fixes ?? {}).length) {
    t1 = now();
    fix = proposeFix(fam, values, sources, eng, model);
    t.correccion = (now() - t1) / 1000;
  }
  t.total = (now() - t0) / 1000;
  const qa = q.result();
  const summary = {
    family: familyId, product_code: model.product_code, parameters: model.parameterTable(), requested: { ...model.requested.values },
    design_notes: model.design_notes, feature_tree: model.featureTree(), component_tree: model.componentTree(),
    engineering: eng, manufacturing: plan, bom, dfm,
    interferences: interf,
    qa, status: { geometry_complete: qa.blocking === 0, technically_verified: eng.verdict === "CUMPLE", structural: eng.status, structural_label: eng.status_label },
    mass_kg: bom.totals.total_mass, timings: Object.fromEntries(Object.entries(t).map(([k, v]) => [k, Math.round(v * 1000) / 1000])),
    cost, fix, verdict: eng.verdict, dependencies: dependencyMap(model),
    catalog_versions: C.versions, engine: "navegador",
  };
  return { model, summary };
}
