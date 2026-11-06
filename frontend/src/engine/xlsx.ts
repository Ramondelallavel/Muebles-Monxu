// @ts-nocheck
// Libro Excel (OOXML) de fabricación generado en el navegador (port de monxu/docs/excel.py):
// BOM con fórmulas, perfiles, plan de corte, anidado, compras, verificaciones, presupuesto y control de calidad.
// Cada fórmula lleva su valor calculado en caché para que el libro se lea correctamente sin recalcular.
import { zipAsync } from "./docs";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");
const col = (c) => { let s = ""; c += 1; while (c) { const m = (c - 1) % 26; s = String.fromCharCode(65 + m) + s; c = Math.floor((c - 1) / 26); } return s; };
const ref = (r, c) => `${col(c)}${r + 1}`;
// estilos (índices de cellXfs)
const S = { normal: 0, title: 1, head: 2, cell: 3, n4: 4, n1: 5, bold: 6, pct: 7, n3: 8, n2: 9, n3b: 10, good: 11, bad: 12 };
const FMT = { n4: 164, n1: 165, pct: 166, n3: 167, n2: 168 };

class Sheet {
  constructor(name) { this.name = name; this.rows = new Map(); this.widths = []; this.freeze = null; this.filter = null; }
  set(r, c, v, s = S.cell) { if (!this.rows.has(r)) this.rows.set(r, new Map()); this.rows.get(r).set(c, { v, s }); }
  xml() {
    const rows = [...this.rows.entries()].sort((a, b) => a[0] - b[0]).map(([r, cells]) => {
      const cs = [...cells.entries()].sort((a, b) => a[0] - b[0]).map(([c, { v, s }]) => {
        const at = `r="${ref(r, c)}"${s ? ` s="${s}"` : ""}`;
        if (v === null || v === undefined || v === "") return `<c ${at}/>`;
        if (typeof v === "object" && "f" in v) {
          const val = v.v;
          if (typeof val === "string") return `<c ${at} t="str"><f>${esc(v.f)}</f><v>${esc(val)}</v></c>`;
          return `<c ${at}><f>${esc(v.f)}</f>${Number.isFinite(val) ? `<v>${val}</v>` : ""}</c>`;
        }
        if (typeof v === "number") return Number.isFinite(v) ? `<c ${at}><v>${v}</v></c>` : `<c ${at}/>`;
        if (typeof v === "boolean") return `<c ${at} t="b"><v>${v ? 1 : 0}</v></c>`;
        return `<c ${at} t="inlineStr"><is><t xml:space="preserve">${esc(v)}</t></is></c>`;
      }).join("");
      return `<row r="${r + 1}">${cs}</row>`;
    }).join("");
    const cols = this.widths.length ? `<cols>${this.widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join("")}</cols>` : "";
    const pane = this.freeze ? `<sheetViews><sheetView workbookViewId="0"><pane ySplit="${this.freeze}" topLeftCell="A${this.freeze + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>`
      : `<sheetViews><sheetView workbookViewId="0"/></sheetViews>`;
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">`
      + `${pane}<sheetFormatPr defaultRowHeight="15"/>${cols}<sheetData>${rows}</sheetData>${this.filter ? `<autoFilter ref="${this.filter}"/>` : ""}</worksheet>`;
  }
}

function header(ws, info, title) {
  ws.set(0, 0, title, S.title);
  [["Proyecto", info.project_code], ["Producto", info.product_name], ["Revisión", info.revision], ["Fecha", info.date], ["Cliente", info.client]]
    .forEach(([a, b], k) => { ws.set(k + 1, 0, a, S.bold); ws.set(k + 1, 1, b ?? "", S.normal); });
  return 7;
}
function table(ws, r0, headers, rows, widths, formats = {}) {
  headers.forEach((h, c) => ws.set(r0, c, h, S.head));
  rows.forEach((row, i) => row.forEach((v, c) => ws.set(r0 + 1 + i, c, v, formats[c] ?? S.cell)));
  const last = r0 + Math.max(1, rows.length);
  if (rows.length) ws.filter = `A${r0 + 1}:${col(headers.length - 1)}${last + 1}`;
  ws.widths = widths;
  ws.freeze = r0 + 1;
  return last;
}

export async function workbook(info, summary) {
  const bom = summary.bom, plan = summary.manufacturing, eng = summary.engineering, qa = summary.qa;
  const sheets = [];
  // ---------------------------------------------------------------- BOM
  const ws = new Sheet("BOM"); sheets.push(ws);
  let r0 = header(ws, info, "LISTA DE MATERIALES (BOM)");
  const rows = bom.rows.map((r, i) => {
    const k = r0 + 2 + i;                           // fila Excel (1-base)
    return [r.pos, r.ref, r.description, r.material ?? "", r.thickness, r.length, r.width, r.qty, r.unit_mass,
      { f: `H${k}*I${k}`, v: Math.round(r.qty * r.unit_mass * 1e4) / 1e4 }, r.kind_label, r.process, r.finish];
  });
  let last = table(ws, r0, ["Posición", "Referencia", "Descripción", "Material", "Espesor (mm)", "Largo (mm)", "Ancho (mm)", "Cantidad", "Peso unitario (kg)", "Peso total (kg)",
    "Tipo", "Proceso", "Acabado"], rows, [9, 22, 52, 22, 11, 11, 11, 10, 15, 15, 20, 48, 40], { 4: S.n1, 5: S.n1, 6: S.n1, 8: S.n4, 9: S.n4 });
  const a = r0 + 2, b = last + 1, tr = last + 2;
  const qty = bom.rows.reduce((s, r) => s + r.qty, 0), mass = bom.rows.reduce((s, r) => s + r.qty * r.unit_mass, 0);
  ws.set(tr, 6, "TOTALES", S.bold);
  ws.set(tr, 7, { f: `SUBTOTAL(109,H${a}:H${b})`, v: qty }, S.bold);
  ws.set(tr, 9, { f: `SUBTOTAL(109,J${a}:J${b})`, v: Math.round(mass * 1e4) / 1e4 }, S.n3b);
  const nStd = bom.rows.filter((r) => r.kind === "normalizado").reduce((s, r) => s + r.qty, 0);
  ws.set(tr + 1, 6, "Componentes fabricados", S.normal);
  ws.set(tr + 1, 7, { f: `SUMIF(K${a}:K${b},"<>Elemento normalizado",H${a}:H${b})`, v: qty - nStd }, S.normal);
  ws.set(tr + 2, 6, "Elementos normalizados", S.normal);
  ws.set(tr + 2, 7, { f: `SUMIF(K${a}:K${b},"Elemento normalizado",H${a}:H${b})`, v: nStd }, S.normal);
  // ---------------------------------------------------------------- perfiles
  const wp = new Sheet("Perfiles"); sheets.push(wp);
  r0 = header(wp, info, "METROS DE PERFIL");
  const prows = bom.rows.filter((r) => r.kind === "perfil");
  last = table(wp, r0, ["Referencia", "Sección", "Material", "Longitud (mm)", "Cantidad", "Metros (m)", "Peso unit. (kg)", "Peso total (kg)"],
    prows.map((r, i) => { const k = r0 + 2 + i; return [r.ref, r.section, r.material, r.length, r.qty, { f: `D${k}*E${k}/1000`, v: (r.length * r.qty) / 1000 }, r.unit_mass, { f: `E${k}*G${k}`, v: r.qty * r.unit_mass }]; }),
    [22, 16, 14, 14, 10, 12, 14, 14], { 5: S.n3, 6: S.n3, 7: S.n3 });
  const rr = last + 2;
  wp.set(rr, 0, "Resumen por sección", S.bold);
  [...new Set(prows.map((r) => r.section))].sort().forEach((sec, n) => {
    wp.set(rr + 1 + n, 1, sec, S.normal);
    const v = prows.filter((r) => r.section === sec).reduce((s, r) => s + (r.length * r.qty) / 1000, 0);
    wp.set(rr + 1 + n, 5, { f: `SUMIF(B${r0 + 2}:B${last + 1},B${rr + 2 + n},F${r0 + 2}:F${last + 1})`, v }, S.n3);
  });
  // ---------------------------------------------------------------- plan de corte
  const wc = new Sheet("Plan de corte"); sheets.push(wc);
  r0 = header(wc, info, "PLAN DE CORTE DE BARRAS");
  const crow = [];
  for (const c of plan.cutting) for (const bb of c.bars) crow.push([c.profile, c.material, bb.bar, c.bar_length, bb.cuts.length,
    bb.cuts.map((x) => `${x.ref.split("-").at(-1)}:${x.length}`).join(" + "), bb.used, bb.kerf_loss, bb.remnant, bb.remnant_reusable ? "Sí" : "No"]);
  last = table(wc, r0, ["Perfil", "Material", "Barra", "Long. barra (mm)", "Nº cortes", "Cortes (pos:long)", "Útil (mm)", "Pérdida sierra+refrentado (mm)", "Retal (mm)", "Retal aprovechable"],
    crow, [14, 12, 8, 14, 10, 70, 12, 16, 12, 14]);
  const used = crow.reduce((s, r) => s + r[6], 0), barL = crow.reduce((s, r) => s + r[3], 0);
  wc.set(last + 2, 5, "Aprovechamiento global", S.bold);
  wc.set(last + 2, 6, { f: `SUM(G${r0 + 2}:G${last + 1})/SUM(D${r0 + 2}:D${last + 1})`, v: barL ? used / barL : 0 }, S.pct);
  // ---------------------------------------------------------------- anidado
  const wn = new Sheet("Anidado chapa"); sheets.push(wn);
  r0 = header(wn, info, "ANIDADO DE CHAPA");
  const nrow = [];
  for (const n of plan.nesting) {
    if (!n.feasible) { nrow.push([n.material, n.thickness, "—", 0, null, null, null, 0, n.reason ?? ""]); continue; }
    for (const s of n.sheets) {
      const pa = Math.round((s.parts_area_mm2 / 1e6) * 1e4) / 1e4, sa = Math.round(((n.length * n.width) / 1e6) * 1e4) / 1e4;
      nrow.push([n.material, n.thickness, n.format, s.sheet, s.placements.length, pa, sa, null, s.placements.map((p) => p.ref.split("-").at(-1) + (p.rot ? "(R)" : "")).join(", ")]);
    }
  }
  table(wn, r0, ["Material", "Espesor (mm)", "Formato", "Chapa nº", "Piezas", "Superficie piezas (m²)", "Superficie chapa (m²)", "Aprovechamiento", "Piezas (R = girada)"],
    nrow.map((r, i) => { const k = r0 + 2 + i; return [...r.slice(0, 7), { f: `IFERROR(F${k}/G${k},0)`, v: r[5] && r[6] ? r[5] / r[6] : 0 }, r[8]]; }),
    [12, 12, 12, 9, 8, 18, 18, 15, 50], { 5: S.n4, 6: S.n4, 7: S.pct });
  // ---------------------------------------------------------------- compras
  const wb = new Sheet("Compras"); sheets.push(wb);
  r0 = header(wb, info, "LISTA DE COMPRAS");
  last = table(wb, r0, ["Tipo", "Descripción", "Cantidad", "Unidad", "Masa (kg)"], bom.purchases.map((p) => [p.type, p.description, p.qty, p.unit, p.mass_kg]), [26, 80, 10, 10, 12], { 4: S.n2 });
  wb.set(last + 2, 3, "Total", S.bold);
  wb.set(last + 2, 4, { f: `SUBTOTAL(109,E${r0 + 2}:E${last + 1})`, v: Math.round(bom.purchases.reduce((s, p) => s + p.mass_kg, 0) * 100) / 100 }, S.n2);
  wb.set(last + 4, 0, "CONSUMIBLES", S.bold);
  bom.consumables.forEach((c, n) => { wb.set(last + 5 + n, 1, c.description, S.normal); wb.set(last + 5 + n, 2, c.qty, S.normal); wb.set(last + 5 + n, 3, c.unit, S.normal); });
  // ---------------------------------------------------------------- verificaciones
  const wv = new Sheet("Verificaciones"); sheets.push(wv);
  r0 = header(wv, info, "VERIFICACIONES ESTRUCTURALES (CÁLCULO PRELIMINAR AUTOMATIZADO)");
  wv.set(r0 - 1, 0, eng.status_label, eng.status === "CUMPLE" ? S.good : S.bad);
  table(wv, r0, ["Id", "Categoría", "Comprobación", "Referencia", "Comb.", "Valor", "Límite", "Unidad", "Aprovechamiento", "Estado"],
    eng.checks.map((c) => [c.id, c.category, c.description, c.standard, c.combination, c.value, c.limit, c.unit, c.utilization, c.status]), [26, 12, 70, 34, 8, 10, 10, 8, 14, 14], { 8: S.n3 });
  // ---------------------------------------------------------------- presupuesto
  const cost = summary.cost;
  if (cost) {
    const wk = new Sheet("Presupuesto"); sheets.push(wk);
    r0 = header(wk, info, `PRESUPUESTO ESTIMADO POR UNIDAD (lote de ${cost.lot} ud)`);
    wk.set(r0 - 1, 0, `Tarifas orientativas ${cost.rates_version}: ${cost.note}`, S.normal);
    const rows = cost.lines.map((ln, i) => [ln.group, ln.concept, ln.qty, ln.unit, ln.unit_eur, { f: `C${r0 + 2 + i}*E${r0 + 2 + i}`, v: Math.round(ln.qty * ln.unit_eur * 100) / 100 }]);
    last = table(wk, r0, ["Partida", "Concepto", "Cantidad", "Unidad", "Precio unitario (€)", "Importe (€)"], rows, [16, 80, 12, 10, 18, 14], { 2: S.n3, 4: S.n4, 5: S.n2 });
    let r = last + 2;
    const first = r;
    for (const [gname, v] of Object.entries(cost.groups)) {
      wk.set(r, 1, gname, S.bold);
      wk.set(r, 5, { f: `SUMIF(A${r0 + 2}:A${last + 1},"${gname}",F${r0 + 2}:F${last + 1})`, v }, S.n2);
      r++;
    }
    const R1 = r + 1;   // fila de Excel (1-based) del coste directo
    wk.set(r, 1, "Coste directo", S.bold); wk.set(r, 5, { f: `SUM(F${first + 1}:F${r})`, v: cost.direct }, S.n2);
    wk.set(r + 1, 1, `Gastos generales (${cost.overhead_rate * 100} %)`, S.normal); wk.set(r + 1, 4, cost.overhead_rate, S.normal);
    wk.set(r + 1, 5, { f: `F${R1}*E${R1 + 1}`, v: cost.overheads }, S.n2);
    wk.set(r + 2, 1, "Coste total", S.bold); wk.set(r + 2, 5, { f: `F${R1}+F${R1 + 1}`, v: cost.cost }, S.n2);
    wk.set(r + 3, 1, `Margen (${cost.margin_rate * 100} %)`, S.normal); wk.set(r + 3, 4, cost.margin_rate, S.normal);
    wk.set(r + 3, 5, { f: `F${R1 + 2}*E${R1 + 3}`, v: cost.margin }, S.n2);
    wk.set(r + 4, 1, "Precio de venta estimado", S.bold); wk.set(r + 4, 5, { f: `F${R1 + 2}+F${R1 + 3}`, v: cost.price }, S.n2);
    const k = r + 6;
    wk.set(k, 1, "COSTE UNITARIO SEGÚN LOTE", S.bold);
    ["Lote (ud)", "Coste directo (€)", "Coste total (€)", "Precio (€)"].forEach((h, c) => wk.set(k + 1, 1 + c, h, S.bold));
    cost.by_lot.forEach((b, n) => [b.lot, b.direct, b.cost, b.price].forEach((v, c) => wk.set(k + 2 + n, 1 + c, v, c ? S.n2 : S.cell)));
  }
  // ---------------------------------------------------------------- control de calidad
  const wq = new Sheet("Control de calidad"); sheets.push(wq);
  r0 = header(wq, info, "CONTROL DE CALIDAD PREVIO A EXPORTACIÓN");
  table(wq, r0, ["Nivel", "Código", "Descripción"], qa.items.map((q) => [q.level, q.code, q.message]), [16, 26, 120]);

  // ---------------------------------------------------------------- paquete OOXML
  const ct = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">`
    + `<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>`
    + `<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>`
    + `<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>`
    + `<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>`
    + sheets.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("") + `</Types>`;
  const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
    + `<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>`
    + `<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>`;
  const wbx = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">`
    + `<bookViews><workbookView/></bookViews><sheets>${sheets.map((s, i) => `<sheet name="${esc(s.name)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("")}</sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>`;
  const wbr = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">`
    + sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join("")
    + `<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`;
  const border = `<border><left style="thin"><color rgb="FF9AA7B5"/></left><right style="thin"><color rgb="FF9AA7B5"/></right><top style="thin"><color rgb="FF9AA7B5"/></top><bottom style="thin"><color rgb="FF9AA7B5"/></bottom><diagonal/></border>`;
  const xf = (fmt, font, fill, bd, extra = "") => `<xf numFmtId="${fmt}" fontId="${font}" fillId="${fill}" borderId="${bd}" xfId="0"${fmt ? ' applyNumberFormat="1"' : ""}${font ? ' applyFont="1"' : ""}${fill ? ' applyFill="1"' : ""}${bd ? ' applyBorder="1"' : ""}${extra ? ' applyAlignment="1">' + extra + "</xf>" : "/>"}`;
  const styles = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">`
    + `<numFmts count="5"><numFmt numFmtId="${FMT.n4}" formatCode="0.0000"/><numFmt numFmtId="${FMT.n1}" formatCode="0.0"/><numFmt numFmtId="${FMT.pct}" formatCode="0.0%"/><numFmt numFmtId="${FMT.n3}" formatCode="0.000"/><numFmt numFmtId="${FMT.n2}" formatCode="0.00"/></numFmts>`
    + `<fonts count="6"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="14"/><color rgb="FF1F3A5F"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>`
    + `<font><b/><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FF1B5E20"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFB00020"/><name val="Calibri"/></font></fonts>`
    + `<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F3A5F"/><bgColor indexed="64"/></patternFill></fill></fills>`
    + `<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>${border}</borders>`
    + `<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>`
    + `<cellXfs count="13">${xf(0, 0, 0, 0)}${xf(0, 1, 0, 0)}${xf(0, 2, 2, 1, '<alignment horizontal="center" vertical="center" wrapText="1"/>')}${xf(0, 0, 0, 1)}${xf(FMT.n4, 0, 0, 1)}${xf(FMT.n1, 0, 0, 1)}`
    + `${xf(0, 3, 0, 0)}${xf(FMT.pct, 0, 0, 1)}${xf(FMT.n3, 0, 0, 1)}${xf(FMT.n2, 0, 0, 1)}${xf(FMT.n3, 3, 0, 0)}${xf(0, 4, 0, 0)}${xf(0, 5, 0, 0)}</cellXfs>`
    + `<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`;
  const now = new Date().toISOString().slice(0, 19) + "Z";
  const core = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">`
    + `<dc:title>${esc(`BOM ${info.product_name ?? ""}`)}</dc:title><dc:creator>${esc(info.designer ?? "Monxu")}</dc:creator><dcterms:created xsi:type="dcterms:W3CDTF">${now}</dcterms:created></cp:coreProperties>`;
  const files = [{ path: "[Content_Types].xml", data: ct }, { path: "_rels/.rels", data: rels }, { path: "docProps/core.xml", data: core }, { path: "xl/workbook.xml", data: wbx },
    { path: "xl/_rels/workbook.xml.rels", data: wbr }, { path: "xl/styles.xml", data: styles }, ...sheets.map((s, i) => ({ path: `xl/worksheets/sheet${i + 1}.xml`, data: s.xml() }))];
  return { bytes: await zipAsync(files), rows: bom.rows.length, qty, mass: Math.round(mass * 1000) / 1000, sheets: sheets.map((s) => s.name) };
}
