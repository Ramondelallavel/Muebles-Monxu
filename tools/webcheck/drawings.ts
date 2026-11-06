// Genera planos y montaje con el motor del navegador (para revisarlos con pdfplumber).
import { regenerate } from "../../frontend/src/engine/pipeline";
import { assemblyInstructions, drawingConsistency, drawingSet } from "../../frontend/src/engine/drawings";
import * as fs from "node:fs";
const [fam, values, out] = process.argv.slice(2);
const { model, summary } = regenerate(fam, JSON.parse(values));
const info = { product_name: `${model.family_name} ${model.product_code}`, project_code: "P-2026-0001", revision: "A", date: "2026-11-06", designer: "Ingeniería",
  client: "Cliente", tolerances: "ISO 2768-mK", status_stamp: "PRELIMINAR", status_level: "warn" };
let t0 = Date.now();
const r = await drawingSet(model, summary, info, (m) => process.stderr.write(m + "\n"));
fs.writeFileSync(out + "_planos.pdf", r.pdf);
const t1 = Date.now() - t0; t0 = Date.now();
const a = await assemblyInstructions(model, summary, info, r.ctx);
fs.writeFileSync(out + "_montaje.pdf", a.pdf);
console.log(JSON.stringify({ planos_ms: t1, montaje_ms: Date.now() - t0, pages: r.total, bytes: r.pdf.length, montaje_pages: a.total, montaje_bytes: a.pdf.length,
  sheets: r.sheets.map((s) => [s.number, s.title, s.dims.length]), consistency: drawingConsistency(model, r.sheets) }));
