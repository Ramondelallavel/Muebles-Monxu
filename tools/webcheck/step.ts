// Escribe el STEP de conjunto y de una pieza con el motor del navegador (para verificarlos con OpenCascade).
import { family } from "../../frontend/src/engine/families";
import { build } from "../../frontend/src/engine/sizing";
import { assemblyStep, partStep } from "../../frontend/src/engine/step";
import { partGeometry } from "../../frontend/src/engine/geometry";
import * as fs from "node:fs";
const [fam, values, out] = process.argv.slice(2);
const f = family(fam);
const m = build(f, f.newParams(JSON.parse(values)));
const t0 = Date.now();
const s = assemblyStep(m);
fs.writeFileSync(out + "_conjunto.step", s);
const parts = Object.values(m.parts);
for (const p of parts) fs.writeFileSync(`${out}_${p.ref}.step`, partStep(m, p));
console.log(JSON.stringify({ ms: Date.now() - t0, bytes: s.length, instances: m.instances.length,
  volume: m.instances.reduce((a, i) => a + partGeometry(i.part).volume, 0),
  parts: Object.fromEntries(parts.map((p) => [p.ref, partGeometry(p).volume])) }));
