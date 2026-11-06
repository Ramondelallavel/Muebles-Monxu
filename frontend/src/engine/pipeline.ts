// @ts-nocheck
// Regeneración completa desde la fuente única de parámetros y control de calidad (port de monxu/pipeline.py y
// monxu/validation/qa.py). Lo que en el navegador no puede verificarse con B-rep se declara PENDIENTE.
import * as C from "./catalog";
import { analyze } from "./analysis";
import { family } from "./families";
import { instanceBBox, modelBBox, partGeometry } from "./geometry";
import { buildBom, dfmCheck, manufacturingPlan } from "./manufacturing";
import { build } from "./sizing";
import { checkInterferences } from "./interference";
import { f as fx } from "./util";

const BLOCK = "bloqueante", WARN = "advertencia", OKL = "ok", PEND = "pendiente";

export class QA {
  constructor() { this.items = []; }
  add(level, code, message, data = {}) { this.items.push({ level, code, message, ...data }); }
  result() {
    const lv = this.items.map((i) => i.level);
    const n = (x) => lv.filter((l) => l === x).length;
    const blocking = n(BLOCK);
    return { result: blocking ? "bloqueante" : lv.includes(WARN) ? "advertencia" : "ok", blocking, warnings: n(WARN), pending: n(PEND), ok: n(OKL),
      items: this.items, summary: `${blocking} errores bloqueantes, ${n(WARN)} advertencias, ${n(PEND)} validaciones pendientes, ${n(OKL)} comprobaciones satisfactorias.` };
  }
}

export function modelChecks(model, eng, dfm, bom, interf) {
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
    if (over > 0.5) q.add(WARN, "GEO-SALIENTE", `Elementos sobresalen ${fx(over, 1)} mm del contorno del producto (bases de pies niveladores): considerar en implantación.`);
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
    q.add(WARN, "CALC-NO-CUMPLE", "Verificación estructural preliminar NO superada (no apto para fabricación hasta modificar el diseño): "
      + fails.map((c) => c.description).join("; ") + advice);
  }
  else if (eng.status === "PENDIENTE") q.add(PEND, "CALC-PENDIENTE", "Verificación estructural incompleta: " + (eng.pending.length ? eng.pending : ["datos pendientes"]).join("; "));
  else q.add(OKL, "CALC", "Verificación estructural preliminar automatizada: CUMPLE.");
  q.add(PEND, "VALIDACION-TECNICA", "Validación definitiva por técnico competente pendiente de firma.");
  return q;
}

/** Regenera modelo, cálculo, fabricación, BOM y QA. Devuelve el resumen con la misma estructura que el servidor. */
export function regenerate(familyId, values, sources = {}, onProgress = null) {
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
  const plan = manufacturingPlan(model);
  const dfm = dfmCheck(model, plan);
  const bom = buildBom(model, plan);
  t.fabricacion = (now() - t1) / 1000;
  t1 = now();
  const interf = checkInterferences(model);
  t.interferencias = (now() - t1) / 1000;
  const q = modelChecks(model, eng, dfm, bom, interf);
  t.total = (now() - t0) / 1000;
  const qa = q.result();
  const summary = {
    family: familyId, product_code: model.product_code, parameters: model.parameterTable(), requested: { ...model.requested.values },
    design_notes: model.design_notes, feature_tree: model.featureTree(), component_tree: model.componentTree(),
    engineering: eng, manufacturing: plan, bom, dfm,
    interferences: interf,
    qa, status: { geometry_complete: qa.blocking === 0, technically_verified: eng.status === "CUMPLE", structural: eng.status, structural_label: eng.status_label },
    mass_kg: bom.totals.total_mass, timings: Object.fromEntries(Object.entries(t).map(([k, v]) => [k, Math.round(v * 1000) / 1000])),
    catalog_versions: C.versions, engine: "navegador",
  };
  return { model, summary };
}
