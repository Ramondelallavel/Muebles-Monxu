// Genera un expediente con el motor del navegador (en node) para verificarlo con las herramientas del servidor.
import { regenerate } from "../../frontend/src/engine/pipeline";
import { buildDossier } from "../../frontend/src/local/dossier";
import * as AP from "../../frontend/src/engine/approval";
import * as fs from "node:fs";
// uso: node dossier.mjs FAMILIA 'VALORES_JSON' salida.zip [FUENTES_JSON]
// (opcionales: PROJECT_CODE=P-AAAA-NNNN, REV_DATE=AAAA-MM-DD y PROJECT_CLIENT para el cajetín)
const [fam, valuesJson, out, sourcesJson] = process.argv.slice(2);
const values = JSON.parse(valuesJson);
const { model, summary } = regenerate(fam, values, sourcesJson ? JSON.parse(sourcesJson) : {});
const rev = { rev: "A", created: `${process.env.REV_DATE ?? "2026-11-06"}T10:00:00`, author: "Ingeniería", comment: "prueba", params: model.params.values, sources: model.params.sources, changes: {} };
// como en la aplicación al emitir la revisión: el sello sale del estado de aprobación evaluado con el QA del diseño
const project = { code: process.env.PROJECT_CODE ?? "P-2026-0001", name: "Prueba", client: process.env.PROJECT_CLIENT ?? "Cliente", family: fam, designer: "Ingeniería", revisions: [rev],
  approval_eval: AP.evaluate(summary.qa, summary.engineering.status, null, {}) };
const d = await buildDossier(project, rev, model, summary);
fs.writeFileSync(out, d.zip);
console.log(JSON.stringify({ name: d.name, qa: d.qa.summary, release_blockers: d.qa.release_blockers, blocking: d.qa.items.filter((i) => i.level === "bloqueante"), files: d.files.length,
  expected: Object.fromEntries(Object.values(model.parts).filter((p) => p.kind === "chapa" || p.kind === "pletina").map((p) => [p.ref, p.kind === "chapa" ? [p.flat.width, p.flat.height] : [p.w, p.h]])) }));
