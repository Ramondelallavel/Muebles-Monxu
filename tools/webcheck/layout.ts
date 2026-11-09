// Auditoría de legibilidad de los planos generados por el navegador: solapes de textos, cotas, globos y símbolos.
// Uso: node layout.mjs <familia> '<valores JSON>' [salida.pdf]   (o un array de casos [{family, values, id}] por stdin con "-")
import { regenerate } from "../../frontend/src/engine/pipeline";
import { assemblyInstructions, drawingSet } from "../../frontend/src/engine/drawings";
import * as fs from "node:fs";
const args = process.argv.slice(2);
const cases = args[0] === "-" ? JSON.parse(fs.readFileSync(0, "utf8")) : [{ id: args[0], family: args[0], values: JSON.parse(args[1]), out: args[2] }];
const info = { product_name: "", project_code: "P-2026-0001", revision: "A", date: "2026-11-06", designer: "Ingeniería", client: "Cliente",
  tolerances: "ISO 2768-mK", status_stamp: "CÁLCULO VERIFICADO — CUMPLE (EN 1990 / EN 1993)", status_level: "info" };
const res = [];
for (const c of cases) {
  const { model, summary } = regenerate(c.family, c.values);
  const inf = { ...info, product_name: `${model.family_name} ${model.product_code}` };
  const r = await drawingSet(model, summary, inf);
  const a = await assemblyInstructions(model, summary, inf, r.ctx);
  if (c.out) { fs.writeFileSync(c.out + "_planos.pdf", r.pdf); fs.writeFileSync(c.out + "_montaje.pdf", a.pdf); }
  res.push({ id: c.id, planos: r.layout, montaje: a.layout });
}
console.log(JSON.stringify(res));
