// Genera un expediente con el motor del navegador (en node) para verificarlo con las herramientas del servidor.
import { regenerate } from "../../frontend/src/engine/pipeline";
import { buildDossier } from "../../frontend/src/local/dossier";
import * as fs from "node:fs";
const [fam, valuesJson, out] = process.argv.slice(2);
const values = JSON.parse(valuesJson);
const { model, summary } = regenerate(fam, values);
const rev = { rev: "A", created: "2026-11-06T10:00:00", author: "Ingeniería", comment: "prueba", params: model.params.values, sources: model.params.sources, changes: {} };
const project = { code: "P-2026-0001", name: "Prueba", client: "Cliente", family: fam, designer: "Ingeniería", revisions: [rev] };
const d = await buildDossier(project, rev, model, summary);
fs.writeFileSync(out, d.zip);
console.log(JSON.stringify({ name: d.name, qa: d.qa.summary, blocking: d.qa.items.filter((i) => i.level === "bloqueante"), files: d.files.length,
  expected: Object.fromEntries(Object.values(model.parts).filter((p) => p.kind === "chapa" || p.kind === "pletina").map((p) => [p.ref, p.kind === "chapa" ? [p.flat.width, p.flat.height] : [p.w, p.h]])) }));
