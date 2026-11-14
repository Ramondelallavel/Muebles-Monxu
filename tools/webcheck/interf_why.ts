// Para cada caso con interferencias: ¿hay otro error geométrico/DFM que las explique?
import { regenerate } from "../../frontend/src/engine/pipeline";
import * as fs from "node:fs";
const d = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const sus = [];
for (const c of d.interf) {
  const { summary } = regenerate(c.fid, c.vals);
  const codes = summary.qa.items.filter((i) => i.level === "bloqueante" && i.code !== "GEO-INTERFERENCIAS").map((i) => i.code);
  const pairs = summary.interferences.interferences.map((x) => `${x.a.replace(/\.\w+$/, "")}~${x.b.replace(/\.[\w]+$/, "")}:${x.penetration_mm ?? "C"}`);
  const kinds = [...new Set(pairs.map((p) => p.split(":")[0]))];
  if (!codes.length) sus.push({ k: c.k, fid: c.fid, kinds, vals: c.vals });
  console.log(c.k, c.fid, "| otros:", codes.join(",") || "NINGUNO", "|", kinds.join(" "));
}
fs.writeFileSync(process.argv[3], JSON.stringify(sus, null, 1));
console.log("SOSPECHOSOS (sin otro error)", sus.length);
