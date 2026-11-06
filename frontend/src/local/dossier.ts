// @ts-nocheck
// Expediente de fabricación generado en el navegador (estructura de carpetas 01–06 del servidor).
import * as C from "../engine/catalog";
import { QA } from "../engine/pipeline";
import { family } from "../engine/families";
import { csv, flatSvg, nestingDxf, nestingSvg, partDxf, reportHtml, sha256, stlBinary, zip } from "../engine/docs";

export function designInfo(project, rev, summary) {
  const e = summary.engineering;
  const stamp = e.status === "NO_CUMPLE" ? "NO APTO PARA FABRICACIÓN — verificación estructural preliminar no superada"
    : e.status === "PENDIENTE" ? "PRELIMINAR — verificación estructural pendiente de datos"
      : project.validated_by ? `VALIDADO por ${project.validated_by}` : "PRELIMINAR — cálculo automatizado CUMPLE · pendiente de validación técnica";
  return { product_name: `${family(project.family).name} ${summary.product_code}`,
    project_code: project.code, revision: rev.rev, date: rev.created.slice(0, 10), designer: project.designer || rev.author || "", client: project.client ?? "",
    tolerances: summary.parameters.find((p) => p.name === "TOLERANCIAS")?.value ?? "ISO 2768-mK", status_stamp: stamp, project: project.code };
}

export async function buildDossier(project, rev, model, summary) {
  const info = designInfo(project, rev, summary);
  const code = model.product_code;
  const name = `${project.code}_${code}_Rev${rev.rev}`;
  const files = [];
  const add = (path, data) => files.push({ path, data });
  const q = new QA();
  q.items = summary.qa.items.filter((i) => i.code !== "VALIDACION-TECNICA");
  // ---- 01 modelo 3D
  add(`01_MODELO_3D/${code}_parametrico.json`, JSON.stringify({ format: "monxu-parametrico", version: 1, family: summary.family, parameters: model.params.values,
    sources: model.params.sources, requested: model.requested.values, catalog_versions: C.versions, product_code: code, feature_tree: model.featureTree(),
    note: "Formato editable nativo: abrir con la plataforma (servidor) para regenerar la geometría B-rep, STEP y planos PDF." }, null, 2));
  add(`01_MODELO_3D/${code}_malla_visualizacion.stl`, stlBinary(model));
  // ---- 02 planos (desarrollos de chapa en SVG)
  for (const p of Object.values(model.parts)) if (p.kind === "chapa") add(`02_PLANOS/${p.ref}_desarrollo.svg`, flatSvg(p, { ...info, revision: rev.rev, stamp: info.status_stamp }));
  // ---- 03 DXF
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
  const b = summary.bom;
  add(`04_LISTA_MATERIALES/${code}_BOM.csv`, csv(["Pos", "Referencia", "Descripción", "Tipo", "Material", "Acabado", "Espesor mm", "Largo mm", "Ancho mm", "Cantidad",
    "Peso unit kg", "Peso total kg", "Proceso", "Norma"], b.rows.map((r) => [r.pos, r.ref, r.description, r.kind_label, r.material, r.finish, r.thickness, r.length, r.width,
    r.qty, r.unit_mass, r.total_mass, r.process, r.standard])));
  add("04_LISTA_MATERIALES/lista_compras.csv", csv(["Tipo", "Descripción", "Cantidad", "Unidad", "Masa kg"], b.purchases.map((p) => [p.type, p.description, p.qty, p.unit, p.mass_kg])));
  add("04_LISTA_MATERIALES/pesos_materiales.csv", csv(["Pos", "Referencia", "Descripción", "Material", "Cantidad", "Peso unit kg", "Peso total kg"],
    b.rows.map((r) => [r.pos, r.ref, r.description, r.material, r.qty, r.unit_mass, r.total_mass])));
  const qty = b.rows.reduce((s, r) => s + r.qty, 0), mass = b.rows.reduce((s, r) => s + r.mass_exact, 0);
  q.add(qty === model.instances.length && Math.abs(mass - b.totals.total_mass) < 0.001 ? "ok" : "bloqueante", "EXP-BOM",
    `BOM exportada: ${b.rows.length} filas, ${qty} uds, ${b.totals.total_mass.toFixed(3)} kg (modelo: ${model.instances.length} instancias).`);
  // ---- 05 optimización
  const m = summary.manufacturing;
  add("05_OPTIMIZACION/plan_corte_perfiles.csv", csv(["Perfil", "Material", "Barra", "Cortes", "Útil mm", "Retal mm", "Aprovechable"],
    m.cutting.flatMap((c) => c.bars.map((bar) => [c.profile, c.material, bar.bar, bar.cuts.map((x) => `${x.ref}:${x.length}`).join(" + "), bar.used, bar.remnant, bar.remnant_reusable ? "sí" : "no"]))));
  add("05_OPTIMIZACION/aprovechamientos.json", JSON.stringify({ perfiles: m.cutting.map((c) => ({ profile: c.profile, material: c.material, n_bars: c.n_bars, lower_bound: c.lower_bound,
    utilization: c.utilization, scrap: c.scrap, reusable_remnants: c.reusable_remnants })), chapa: m.nesting.map((n) => ({ material: n.material, thickness: n.thickness, format: n.format ?? null,
    n_sheets: n.n_sheets ?? null, utilization: n.utilization ?? null, waste_m2: n.waste_m2 ?? null })) }, null, 2));
  for (const n of m.nesting) if (n.feasible) for (const s of n.sheets) add(`05_OPTIMIZACION/anidado_${n.material}_${n.thickness}mm_hoja${s.sheet}.svg`, nestingSvg(n, s));
  // ---- 06 documentación
  q.add("pendiente", "EXP-SERVIDOR", "STEP B-rep, interferencias por volumen común, planos PDF con proyección de líneas ocultas y Excel con fórmulas: se generan con el servidor "
    + "a partir de 01_MODELO_3D/*_parametrico.json (mismo motor de parámetros, validado frente al del navegador).");
  q.add("pendiente", "VALIDACION-TECNICA", "Validación definitiva por técnico competente pendiente de firma.");
  const qa = q.result();
  add("06_DOCUMENTACION/informe_calculo_y_verificaciones.html", reportHtml({ ...summary, qa }, { ...info, project_code: project.code }));
  add("06_DOCUMENTACION/informe_verificaciones.json", JSON.stringify({ qa, engineering: summary.engineering, dfm: summary.dfm }, null, 2));
  add("06_DOCUMENTACION/historial_revisiones.json", JSON.stringify(project.revisions.map((r) => ({ revision: r.rev, date: r.created.slice(0, 10), author: r.author, comment: r.comment,
    changes: r.changes })), null, 2));
  add("LEEME.txt", [`Expediente ${name}`, `Generado en el navegador el ${new Date().toLocaleString("es-ES")} con el motor paramétrico Monxu.`, "",
    `Estado: ${info.status_stamp}`, `Control de calidad: ${qa.summary}`, "",
    "Contenido:", "01_MODELO_3D  parámetros resueltos (formato nativo, regenerable) y malla STL de visualización (los taladros no se representan en la malla).",
    "02_PLANOS     desarrollos de chapa acotados (SVG).", "03_DXF_CORTE  DXF 1:1 en mm de chapas y pletinas, con capas de corte, plegado, grabado e información; anidados por hoja.",
    "04_LISTA_MATERIALES  BOM, lista de compras y pesos (CSV ; UTF-8).", "05_OPTIMIZACION  plan de corte de barras, anidado de chapa (SVG) y aprovechamientos.",
    "06_DOCUMENTACION  informe de cálculo y verificaciones (HTML), resultados (JSON) e historial de revisiones.", "",
    "No incluido en el navegador (requiere el servidor con OpenCascade): STEP del conjunto y de cada pieza, comprobación de interferencias B-rep,",
    "planos PDF (conjunto, despiece, estructura, chapas, montaje) y Excel con fórmulas. El JSON paramétrico de 01_MODELO_3D los regenera.", "",
    "Resultado preliminar automatizado. La validación definitiva corresponde a un técnico competente."].join("\r\n"));
  // ---- manifiesto
  const enc = new TextEncoder();
  const listed = [];
  for (const f of files) {
    const u8 = typeof f.data === "string" ? enc.encode(f.data) : f.data;
    listed.push({ path: f.path, bytes: u8.length, sha256: await sha256(u8) });
  }
  const manifest = { dossier: name, project: project.code, revision: rev.rev, product: code, family: summary.family, generated: new Date().toISOString().slice(0, 19),
    engine: "navegador", status: info.status_stamp, structural: summary.engineering.status, qa: qa.summary, parameters: model.params.values, files: listed };
  files.push({ path: "manifest.json", data: JSON.stringify(manifest, null, 2) });
  const z = zip(files.map((f) => ({ path: `${name}/${f.path}`, data: f.data })));
  return { name, zip: z, qa, files: listed, info };
}
