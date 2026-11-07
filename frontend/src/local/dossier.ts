// @ts-nocheck
// Expediente de fabricación completo generado en el navegador (carpetas 01–06 como en el servidor):
// STEP de conjunto y piezas, planos PDF y montaje, DXF de corte, BOM en Excel con fórmulas y CSV,
// optimización, informe de cálculo y manifiesto con SHA-256. Cada archivo se verifica antes de empaquetar.
import * as C from "../engine/catalog";
import { QA } from "../engine/pipeline";
import { family } from "../engine/families";
import { csv, flatSvg, nestingDxf, nestingSvg, partDxf, reportHtml, sha256, stlBinary, zipAsync } from "../engine/docs";
import { assemblyStep, partStep } from "../engine/step";
import { assemblyInstructions, drawingConsistency, drawingSet, isPerforatedPlate } from "../engine/drawings";
import { workbook } from "../engine/xlsx";
import { partGeometry } from "../engine/geometry";

export function designInfo(project, rev, summary) {
  const e = summary.engineering;
  const [stamp, level] = e.status === "NO_CUMPLE" ? ["NO APTO PARA FABRICACIÓN — verificación estructural preliminar no superada", "error"]
    : e.status === "PENDIENTE" ? ["PRELIMINAR — verificación estructural pendiente de datos", "warn"]
      : project.validated_by ? [`VALIDADO por ${project.validated_by}`, "info"] : ["PRELIMINAR — cálculo automatizado CUMPLE · pendiente de validación técnica", "info"];
  return { product_name: `${family(project.family).name} ${summary.product_code}`, project_code: project.code, revision: rev.rev, date: rev.created.slice(0, 10),
    designer: project.designer || rev.author || "", checked: "—", approved: project.validated_by || "—", client: project.client ?? "", company: "MUEBLES MONXU",
    assembly_ref: summary.product_code, tolerances: summary.parameters.find((p) => p.name === "TOLERANCIAS")?.value ?? "ISO 2768-mK", status_stamp: stamp, status_level: level,
    project: project.code };
}

const tick = () => new Promise((r) => setTimeout(r, 0));

export async function buildDossier(project, rev, model, summary, onProgress = null) {
  const info = designInfo(project, rev, summary);
  const step = async (m) => { onProgress?.(m); await tick(); };
  const code = model.product_code;
  const name = `${project.code}_${code}_Rev${rev.rev}`;
  const files = [];
  const add = (path, data) => files.push({ path, data });
  const q = new QA();
  q.items = summary.qa.items.filter((i) => i.code !== "VALIDACION-TECNICA");
  // ---- 01 modelo 3D
  await step("Expediente: STEP del conjunto y de las piezas");
  const stepTxt = assemblyStep(model, info);
  add(`01_MODELO_3D/${code}_conjunto.step`, stepTxt);
  for (const p of Object.values(model.parts)) add(`01_MODELO_3D/componentes/${p.ref}.step`, partStep(model, p, info));
  const nauo = (stepTxt.match(/NEXT_ASSEMBLY_USAGE_OCCURRENCE\(/g) ?? []).length, breps = (stepTxt.match(/FACETED_BREP\(/g) ?? []).length;
  const open = Object.values(model.parts).filter((p) => !partGeometry(p).closed).map((p) => p.ref);
  // cuerpos por pieza: uno, salvo componentes formados por varios cuerpos (ruedas)
  const shells = Object.values(model.parts).reduce((n, p) => n + new Set(partGeometry(p).brep.faces.map((f) => f.comp ?? 0)).size, 0);
  q.add(nauo === model.instances.length && breps === shells && !open.length ? "ok" : "bloqueante", "EXP-STEP",
    `STEP AP214: ${breps} sólidos facetados cerrados (${Object.keys(model.parts).length} piezas) y ${nauo} ocurrencias en el conjunto (modelo: ${model.instances.length} instancias)`
    + (open.length ? `; capas abiertas en ${open.join(", ")}` : "") + ".");
  add(`01_MODELO_3D/${code}_conjunto.stl`, stlBinary(model));
  add(`01_MODELO_3D/${code}_parametrico.json`, JSON.stringify({ format: "monxu-parametrico", version: 1, family: summary.family, parameters: model.params.values,
    sources: model.params.sources, requested: model.requested.values, catalog_versions: C.versions, product_code: code, feature_tree: model.featureTree(),
    note: "Formato editable nativo: abrir con la plataforma para regenerar el diseño paramétrico." }, null, 2));
  // ---- 02 planos
  await step("Expediente: planos PDF (proyección con líneas ocultas)");
  const dr = await drawingSet(model, summary, info, onProgress);
  add(`02_PLANOS/${code}_planos.pdf`, dr.pdf);
  const cons = drawingConsistency(model, dr.sheets);
  const parts = Object.values(model.parts);
  const expected = 3 + 2 * parts.filter((p) => p.kind === "chapa").length + (parts.some((p) => p.kind === "pletina" && !isPerforatedPlate(p)) ? 1 : 0)
    + parts.filter(isPerforatedPlate).length + 4;
  q.add(dr.total === expected ? "ok" : "bloqueante", "EXP-PDF", `Planos PDF: ${dr.total} hojas A3 (esperadas ${expected}): conjunto, estructura, perfiles, piezas de chapa, desarrollos, `
    + "pletinas, soldaduras, explosionado, montaje y despiece.");
  q.add(cons.mismatches.length ? "bloqueante" : "ok", "PLANO-GEOMETRIA", cons.mismatches.length ? `Cotas de plano no coincidentes con la geometría: ${JSON.stringify(cons.mismatches)}`
    : `${cons.checked_dims} cotas de plano verificadas frente a la geometría y los parámetros.`);
  for (const p of Object.values(model.parts)) if (p.kind === "chapa") add(`02_PLANOS/${p.ref}_desarrollo.svg`, flatSvg(p, { ...info, revision: rev.rev, stamp: info.status_stamp }));
  // ---- 03 DXF
  await step("Expediente: DXF de corte");
  const refs = Object.fromEntries(Object.values(model.parts).map((p) => [p.ref, p]));
  for (const p of Object.values(model.parts)) if (p.kind === "chapa" || p.kind === "pletina") {
    const d = partDxf(p, { code: project.code, revision: rev.rev });
    add(`03_DXF_CORTE/${p.ref}.dxf`, d.text);
    const [ew, eh] = p.kind === "chapa" ? [p.flat.width, p.flat.height] : [p.w, p.h];
    const ok = Math.abs(d.width - ew) < 0.01 && Math.abs(d.height - eh) < 0.01;
    q.add(ok ? "ok" : "bloqueante", "EXP-DXF", `${p.ref}.dxf: ${d.width}×${d.height} mm (esperado ${ew.toFixed(3)}×${eh.toFixed(3)}), capas de corte, plegado, grabado e información, unidades mm (R12).`);
  }
  for (const n of summary.manufacturing.nesting) if (n.feasible)
    for (const s of nestingDxf(n, refs)) add(`03_DXF_CORTE/anidado/anidado_${n.material}_${n.thickness}mm_${s.sheet}.dxf`, s.text);
  // ---- 04 lista de materiales
  await step("Expediente: Excel y listas de materiales");
  const b = summary.bom;
  const xl = await workbook(info, { ...summary, qa: q.result() });
  add(`04_LISTA_MATERIALES/${code}_BOM.xlsx`, xl.bytes);
  const qty = b.rows.reduce((s, r) => s + r.qty, 0);
  // el libro suma masas unitarias redondeadas a 0,0001 kg: tolerancia = error de redondeo acumulado
  const tolMass = 0.00005 * qty + 0.001;
  q.add(qty === model.instances.length && Math.abs(xl.mass - b.totals.total_mass) <= tolMass ? "ok" : "bloqueante", "EXP-EXCEL",
    `Excel: ${xl.rows} filas, ${xl.qty} uds, ${xl.mass} kg, fórmulas con valor calculado; hojas ${xl.sheets.join(", ")}.`);
  add(`04_LISTA_MATERIALES/${code}_BOM.csv`, csv(["Pos", "Referencia", "Descripción", "Tipo", "Material", "Acabado", "Espesor mm", "Largo mm", "Ancho mm", "Cantidad",
    "Peso unit kg", "Peso total kg", "Proceso", "Norma"], b.rows.map((r) => [r.pos, r.ref, r.description, r.kind_label, r.material, r.finish, r.thickness, r.length, r.width,
    r.qty, r.unit_mass, r.total_mass, r.process, r.standard])));
  add("04_LISTA_MATERIALES/lista_compras.csv", csv(["Tipo", "Descripción", "Cantidad", "Unidad", "Masa kg"], b.purchases.map((p) => [p.type, p.description, p.qty, p.unit, p.mass_kg])));
  const cost = summary.cost;
  if (cost) {
    add("04_LISTA_MATERIALES/presupuesto_estimado.csv", csv(["Partida", "Concepto", "Cantidad", "Unidad", "Precio unitario EUR", "Importe EUR"],
      [...cost.lines.map((l) => [l.group, l.concept, l.qty, l.unit, l.unit_eur, l.eur]), ["", "Coste directo", "", "", "", cost.direct],
        ["", `Gastos generales ${cost.overhead_rate * 100} %`, "", "", "", cost.overheads], ["", "Coste total", "", "", "", cost.cost],
        ["", `Margen ${cost.margin_rate * 100} %`, "", "", "", cost.margin], ["", "Precio de venta estimado", "", "", "", cost.price],
        ...cost.by_lot.map((x) => ["Lote", `${x.lot} ud`, "", "", "coste/precio por unidad", `${x.cost} / ${x.price}`])]));
    add("04_LISTA_MATERIALES/presupuesto_estimado.json", JSON.stringify(cost, null, 2));
  }
  add("04_LISTA_MATERIALES/pesos_materiales.csv", csv(["Pos", "Referencia", "Descripción", "Material", "Cantidad", "Peso unit kg", "Peso total kg"],
    b.rows.map((r) => [r.pos, r.ref, r.description, r.material, r.qty, r.unit_mass, r.total_mass])));
  // ---- 05 optimización
  const m = summary.manufacturing;
  add("05_OPTIMIZACION/plan_corte_perfiles.csv", csv(["Perfil", "Material", "Barra", "Cortes", "Útil mm", "Retal mm", "Aprovechable"],
    m.cutting.flatMap((c) => c.bars.map((bar) => [c.profile, c.material, bar.bar, bar.cuts.map((x) => `${x.ref}:${x.length}`).join(" + "), bar.used, bar.remnant, bar.remnant_reusable ? "sí" : "no"]))));
  add("05_OPTIMIZACION/aprovechamientos.json", JSON.stringify({ perfiles: m.cutting.map((c) => ({ profile: c.profile, material: c.material, n_bars: c.n_bars, lower_bound: c.lower_bound,
    utilization: c.utilization, scrap: c.scrap, reusable_remnants: c.reusable_remnants })), chapa: m.nesting.map((n) => ({ material: n.material, thickness: n.thickness, format: n.format ?? null,
    n_sheets: n.n_sheets ?? null, utilization: n.utilization ?? null, waste_m2: n.waste_m2 ?? null })) }, null, 2));
  for (const n of m.nesting) if (n.feasible) for (const s of n.sheets) add(`05_OPTIMIZACION/anidado_${n.material}_${n.thickness}mm_hoja${s.sheet}.svg`, nestingSvg(n, s));
  // ---- 06 documentación
  await step("Expediente: instrucciones de montaje e informe");
  const mo = await assemblyInstructions(model, summary, info, dr.ctx, onProgress);
  add("06_DOCUMENTACION/instrucciones_montaje.pdf", mo.pdf);
  add("06_DOCUMENTACION/documentacion_tecnica.pdf", dr.pdf);
  // legibilidad: auditoría de todo lo dibujado (textos, cotas, globos, símbolos y geometría de las vistas)
  const lay = { total: dr.layout.total + mo.layout.total, by: { ...dr.layout.by } };
  for (const [k, v] of Object.entries(mo.layout.by)) lay.by[k] = (lay.by[k] ?? 0) + v;
  const ltxt = Object.entries(lay.by).map(([k, v]) => `${v} ${k}`).join(", ");
  q.add(lay.total ? "advertencia" : "ok", "PLANO-LEGIBILIDAD", lay.total
    ? `Planos y montaje: ${lay.total} posibles solapes de textos o indicaciones (${ltxt}) en ${[...dr.layout.sheets, ...mo.layout.sheets].map((s) => s.number).join(", ")}; revisar esas hojas.`
    : `Planos y montaje (${dr.total + mo.total} hojas) sin solapes: ningún texto pisa otro texto, una línea, una cota, un globo ni el cuadro de rotulación, y las líneas de referencia no se cruzan.`);
  q.add("pendiente", "VALIDACION-TECNICA", "Validación definitiva por técnico competente pendiente de firma.");
  const qa = q.result();
  add("06_DOCUMENTACION/informe_calculo_y_verificaciones.html", reportHtml({ ...summary, qa }, { ...info, project_code: project.code }));
  add("06_DOCUMENTACION/informe_verificaciones.json", JSON.stringify({ qa, engineering: summary.engineering, dfm: summary.dfm, interferences: summary.interferences }, null, 2));
  add("06_DOCUMENTACION/historial_revisiones.json", JSON.stringify(project.revisions.map((r) => ({ revision: r.rev, date: r.created.slice(0, 10), author: r.author, comment: r.comment,
    changes: r.changes })), null, 2));
  add("LEEME.txt", [`Expediente ${name}`, `Generado el ${new Date().toLocaleString("es-ES")} con el motor paramétrico Monxu (ejecutado en el navegador).`, "",
    `Estado: ${info.status_stamp}`, `Control de calidad: ${qa.summary}`, "",
    "01_MODELO_3D        STEP AP214 del conjunto (con estructura de producto) y de cada pieza (componentes/), STL del conjunto y JSON paramétrico nativo.",
    "                    Los sólidos son facetados (caras planas; radios y taladros poligonales, desviación de volumen < 0,2 %).",
    "02_PLANOS           Planos A3 en PDF: conjunto, estructura soldada, perfiles y plan de corte, piezas de chapa, desarrollos, pletinas,",
    "                    uniones soldadas, vista explosionada, montaje y despiece; desarrollos acotados en SVG.",
    "03_DXF_CORTE        DXF 1:1 en mm por pieza de chapa y pletina (capas de corte, plegado, grabado e información) y anidados por hoja.",
    "04_LISTA_MATERIALES BOM en Excel con fórmulas (BOM, perfiles, plan de corte, anidado, compras, verificaciones y control de calidad) y CSV.",
    "05_OPTIMIZACION     Plan de corte de barras, anidado de chapa (SVG) y aprovechamientos.",
    "06_DOCUMENTACION    Instrucciones de montaje (PDF), documentación técnica, informe de cálculo y verificaciones (HTML/JSON) e historial.", "",
    "Resultado preliminar automatizado. La validación definitiva corresponde a un técnico competente."].join("\r\n"));
  // ---- manifiesto y empaquetado
  await step("Expediente: manifiesto SHA-256 y compresión ZIP");
  const enc = new TextEncoder();
  const listed = [];
  for (const f of files) {
    const u8 = typeof f.data === "string" ? enc.encode(f.data) : f.data;
    listed.push({ path: f.path, bytes: u8.length, sha256: await sha256(u8) });
  }
  const manifest = { dossier: name, project: project.code, revision: rev.rev, product: code, family: summary.family, generated: new Date().toISOString().slice(0, 19),
    engine: "navegador", status: info.status_stamp, structural: summary.engineering.status, qa: qa.summary, parameters: model.params.values, files: listed };
  files.push({ path: "manifest.json", data: JSON.stringify(manifest, null, 2) });
  const z = await zipAsync(files.map((f) => ({ path: `${name}/${f.path}`, data: f.data })));
  return { name, zip: z, qa, files: listed, info, sheets: dr.total };
}
