// @ts-nocheck
// Expediente de fabricación completo generado en el navegador (carpetas 01–06 como en el servidor):
// STEP de conjunto y piezas, planos PDF y montaje, DXF de corte, BOM en Excel con fórmulas y CSV,
// optimización, informe de cálculo y manifiesto con SHA-256. Cada archivo se verifica antes de empaquetar.
import * as C from "../engine/catalog";
import { QA } from "../engine/pipeline";
import * as AP from "../engine/approval";
import { family } from "../engine/families";
import { BALANCE_HEADER, CUT_PLAN_HEADER, PURCHASE_HEADER, balanceRows, csv, cutPlanRows, flatSvg, nestingDxf, nestingSvg, optimizationSummary, partDxf, purchaseRows,
  reportHtml, sha256, stlBinary, verifyNestingDxf, verifyStl, weightSummaryRows, zipAsync } from "../engine/docs";
import { assemblyStep, partStep } from "../engine/step";
import { assemblyInstructions, drawingConsistency, drawingSet } from "../engine/drawings";
import { workbook } from "../engine/xlsx";
import { g, pyRound } from "../engine/util";
import { modelBBox, partGeometry } from "../engine/geometry";

/** Cajetín y sello (= pipeline.design_info): el sello sale del estado de aprobación; nunca «verificado» o «aprobado» con las
 *  firmas vacías. */
export function designInfo(project, rev, summary) {
  const ev = project.approval_eval ?? { state: "diseno_generado", label: AP.LABELS.diseno_generado };
  const sig = rev.approval?.signoffs ?? {};
  const st = AP.stamp(ev.state, summary.engineering.status, sig);
  return { product_name: `${family(project.family).name} ${summary.product_code}`, project_code: project.code, revision: rev.rev, date: rev.created.slice(0, 10),
    designer: project.designer || rev.author || "", checked: sig.calculo?.by || "—", approved: sig.aprobacion?.by || "—", client: project.client ?? "", company: "MUEBLES MONXU",
    assembly_ref: summary.product_code, tolerances: summary.parameters.find((p) => p.name === "TOLERANCIAS")?.value ?? "ISO 2768-mK", status_stamp: st.text, status_level: st.level,
    approval_state: ev.state, approval_label: AP.LABELS[ev.state], structural_verdict: summary.engineering.verdict ?? null, project: project.code };
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
  const stl = stlBinary(model);
  add(`01_MODELO_3D/${code}_conjunto.stl`, stl);
  { // STL frente al modelo maestro: triángulos, volumen y envolvente
    const vs = verifyStl(stl);
    const ntri = model.instances.reduce((t, i) => t + partGeometry(i.part).indices.length / 3, 0);
    const vol = model.instances.reduce((t, i) => t + partGeometry(i.part).volume, 0);
    const [blo, bhi] = modelBBox(model);
    const dBox = Math.max(...[0, 1, 2].flatMap((j) => [Math.abs(vs.bbox[0][j] - blo[j]), Math.abs(vs.bbox[1][j] - bhi[j])]));
    const dVol = Math.abs(vs.volume - vol) / vol;
    const ok = vs.bytes_ok && vs.triangles === ntri && dVol < 1e-4 && dBox < 0.01;
    q.add(ok ? "ok" : "bloqueante", "EXP-STL", `STL binario releído: ${vs.triangles} triángulos (modelo ${ntri}), volumen ${(vs.volume / 1e6).toFixed(4)} dm³ (modelo ${(vol / 1e6).toFixed(4)} dm³), `
      + `envolvente con desviación máxima ${dBox.toFixed(4)} mm; unidades mm, ejes del modelo.`, { expected: ntri, obtained: vs.triangles, difference: pyRound(dVol, 8),
      criterion: "Mismos triángulos, volumen (±0,01 %) y envolvente (±0,01 mm) que la malla del modelo", action: "Regenerar el STL" });
  }
  q.add("ok", "EXP-STEP-TIPO", "STEP del navegador: sólidos facetados (FACETED_BREP, caras planas). No es geometría exacta: radios y taladros son poligonales "
    + "(desviación de volumen < 0,2 %). El STEP exacto (B-rep analítico) lo genera el servidor.", { severity: "INFORMATIVO", document: "STEP" });
  add(`01_MODELO_3D/${code}_parametrico.json`, JSON.stringify({ format: "monxu-parametrico", version: 1, family: summary.family, parameters: model.params.values,
    sources: model.params.sources, requested: model.requested.values, catalog_versions: C.versions, product_code: code, feature_tree: model.featureTree(),
    note: "Formato editable nativo: abrir con la plataforma para regenerar el diseño paramétrico." }, null, 2));
  // ---- 02 planos
  await step("Expediente: planos PDF (proyección con líneas ocultas)");
  const dr = await drawingSet(model, summary, info, onProgress);
  add(`02_PLANOS/${code}_planos.pdf`, dr.pdf);
  const cons = drawingConsistency(model, dr);
  const expected = dr.announced;      // hojas calculadas antes de dibujar (perfiles y despiece pueden ocupar varias)
  q.add(dr.total === expected ? "ok" : "bloqueante", "EXP-PDF", `Planos PDF: ${dr.total} hojas A3 (esperadas ${expected}): conjunto, estructura, perfiles, piezas de chapa, desarrollos, `
    + "pletinas, soldaduras, explosionado, montaje y despiece.");
  q.add(cons.mismatches.length ? "bloqueante" : "ok", "PLANO-GEOMETRIA", cons.mismatches.length
    ? `Planos no coincidentes con el modelo (cotas, cantidades, pesos, taladros, barras del plan de corte o textos cortados): ${JSON.stringify(cons.mismatches)}`
    : `${cons.checked_dims} cotas y registros de plano verificados frente a la geometría, los parámetros, el despiece y el plan de corte; ninguno ausente ni truncado.`);
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
    for (const s of nestingDxf(n, refs)) {
      add(`03_DXF_CORTE/anidado/anidado_${n.material}_${n.thickness}mm_${s.sheet}.dxf`, s.text);
      // DXF del anidado frente al anidado del plan (JSON y SVG salen del mismo objeto): contornos y formato
      const sh = n.sheets.find((x) => x.sheet === s.sheet), vd = verifyNestingDxf(s.text);
      const ok = vd.cut_contours === sh.placements.length && vd.format && Math.abs(vd.format[0] - sh.length) < 0.01 && Math.abs(vd.format[1] - sh.width) < 0.01;
      q.add(ok ? "ok" : "bloqueante", "EXP-DXF-ANIDADO", `anidado_${n.material}_${n.thickness}mm_${s.sheet}.dxf: ${vd.cut_contours} contornos exteriores (anidado ${sh.placements.length}), `
        + `chapa ${vd.format ? vd.format.map((v) => v.toFixed(1)).join("×") : "—"} mm (anidado ${g(sh.length)}×${g(sh.width)}).`, { expected: sh.placements.length, obtained: vd.cut_contours,
        criterion: "El DXF del anidado tiene las mismas piezas y la misma chapa que el anidado del plan", action: "Regenerar el anidado" });
    }
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
  add("04_LISTA_MATERIALES/lista_compras.csv", csv(PURCHASE_HEADER, purchaseRows(b, summary.manufacturing.lot ?? 1)));
  const cost = summary.cost;
  if (cost) {
    add("04_LISTA_MATERIALES/presupuesto_estimado.csv", csv(["Partida", "Concepto", "Cantidad", "Unidad", "Precio unitario EUR", "Importe EUR", "Base"],
      [...cost.lines.map((l) => [l.group, l.concept, l.qty, l.unit, l.unit_eur, l.eur, l.basis ?? ""]), ["", "Coste directo", "", "", "", cost.direct, ""],
        ["", `Gastos generales ${g(cost.overhead_rate * 100)} %`, "", "", "", cost.overheads, ""], ["", "Coste total", "", "", "", cost.cost, ""],
        ["", `Margen ${g(cost.margin_rate * 100)} %`, "", "", "", cost.margin, ""], ["", "Precio de venta estimado", "", "", "", cost.price, `material: ${cost.material_basis}`],
        // mismas celdas que el servidor: importes con coma decimal también dentro del texto «coste / precio»
        ...cost.by_lot.map((x) => ["Lote", `${x.lot} ud`, "", "", "coste/precio por unidad", `${String(x.cost).replace(".", ",")} / ${String(x.price).replace(".", ",")}`, ""])]));
    add("04_LISTA_MATERIALES/presupuesto_estimado.json", JSON.stringify(cost, null, 2));
  }
  add("04_LISTA_MATERIALES/pesos_materiales.csv", csv(["Pos", "Referencia", "Descripción", "Material", "Cantidad", "Peso unit kg", "Peso total kg"],
    [...b.rows.map((r) => [r.pos, r.ref, r.description, r.material, r.qty, r.unit_mass, r.total_mass]), ...weightSummaryRows(b)]));
  // ---- 05 optimización
  const m = summary.manufacturing;
  add("05_OPTIMIZACION/plan_corte_perfiles.csv", csv(CUT_PLAN_HEADER, cutPlanRows(m)));
  add("05_OPTIMIZACION/balance_material.csv", csv(BALANCE_HEADER, balanceRows(m)));
  add("05_OPTIMIZACION/aprovechamientos.json", JSON.stringify(optimizationSummary(m), null, 2));
  for (const n of m.nesting) if (n.feasible) for (const s of n.sheets) add(`05_OPTIMIZACION/anidado_${n.material}_${n.thickness}mm_hoja${s.sheet}.svg`, nestingSvg(n, s));
  // ---- 06 documentación
  await step("Expediente: instrucciones de montaje e informe");
  const mo = await assemblyInstructions(model, summary, info, dr.ctx, onProgress);
  add("06_DOCUMENTACION/instrucciones_montaje.pdf", mo.pdf);
  add("06_DOCUMENTACION/documentacion_tecnica.pdf", dr.pdf);
  // tablas de piezas de cada paso: referencias y descripciones completas (son las que cita el texto del paso)
  const cut = mo.sheets.flatMap((sh) => (sh.truncated ?? []).map((t) => `${sh.number}: ${t}`));
  q.add(cut.length ? "bloqueante" : "ok", "PLANO-MONTAJE", cut.length ? `Instrucciones de montaje con textos cortados o tablas incompletas: ${cut.join("; ")}`
    : `Instrucciones de montaje (${mo.total} hojas): tablas de piezas completas, sin referencias ni descripciones cortadas.`);
  // legibilidad: auditoría de todo lo dibujado (textos, cotas, globos, símbolos y geometría de las vistas)
  const lay = { total: dr.layout.total + mo.layout.total, by: { ...dr.layout.by } };
  for (const [k, v] of Object.entries(mo.layout.by)) lay.by[k] = (lay.by[k] ?? 0) + v;
  const ltxt = Object.entries(lay.by).map(([k, v]) => `${v} ${k}`).join(", ");
  q.add(lay.total ? "advertencia" : "ok", "PLANO-LEGIBILIDAD", lay.total
    ? `Planos y montaje: ${lay.total} posibles solapes de textos o indicaciones (${ltxt}) en ${[...dr.layout.sheets, ...mo.layout.sheets].map((s) => s.number).join(", ")}; revisar esas hojas.`
    : `Planos y montaje (${dr.total + mo.total} hojas) sin solapes: ningún texto pisa otro texto, una línea, una cota, un globo ni el cuadro de rotulación, y las líneas de referencia no se cruzan.`);
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
    `Estado de aprobación al generar: ${info.approval_label}. Sello: ${info.status_stamp}.`,
    "Cálculo automatizado según EN 1990 y EN 1993 con las hipótesis del informe; el expediente solo es apto para fabricar cuando su estado es «Liberado para fabricación»."].join("\r\n"));
  // ---- manifiesto y empaquetado
  await step("Expediente: manifiesto SHA-256 y compresión ZIP");
  const enc = new TextEncoder();
  const listed = [];
  for (const f of files) {
    const u8 = typeof f.data === "string" ? enc.encode(f.data) : f.data;
    listed.push({ path: f.path, bytes: u8.length, sha256: await sha256(u8) });
  }
  const manifest = { dossier: name, project: project.code, revision: rev.rev, product: code, family: summary.family, generated: new Date().toISOString().slice(0, 19),
    engine: "navegador", status: info.status_stamp, approval_state: info.approval_state, structural: summary.engineering.status,
    structural_verdict: summary.engineering.verdict ?? null, qa: qa.summary, release_blockers: qa.release_blockers ?? [], parameters: model.params.values, files: listed };
  files.push({ path: "manifest.json", data: JSON.stringify(manifest, null, 2) });
  const z = await zipAsync(files.map((f) => ({ path: `${name}/${f.path}`, data: f.data })));
  return { name, zip: z, qa, files: listed, info, sheets: dr.total };
}
