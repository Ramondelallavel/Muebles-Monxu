// Auditoría de legibilidad de los planos en configuraciones aleatorias (dimensiones y opciones principales).
// Uso: node layout_fuzz.mjs N SEMILLA
import { REGISTRY } from "../../frontend/src/engine/families";
import { regenerate } from "../../frontend/src/engine/pipeline";
import { assemblyInstructions, drawingSet } from "../../frontend/src/engine/drawings";
const [N, SEED] = process.argv.slice(2).map(Number);
let st = SEED || 1;
const rnd = () => { st = (st * 1103515245 + 12345) % 2147483648; return st / 2147483648; };
const pick = (a) => a[Math.floor(rnd() * a.length)];
const KEEP = /^(LONGITUD|ANCHURA|PROFUNDIDAD|ALTURA|NUMERO_|CARGA_|ALA_|ESPESOR_|PERFIL_|PIE_|ALTURA_)/;
function sample(fam) {
  const v = {};
  for (const s of fam.specs()) {
    if (!KEEP.test(s.name) || rnd() < 0.4) continue;
    if (s.type === "choice") v[s.name] = pick([...s.choices, ...(s.allow_auto ? ["auto"] : [])]);
    else if (s.type === "int") v[s.name] = s.allow_auto && rnd() < 0.5 ? "auto" : s.min + Math.floor(rnd() * (Math.min(s.max, 8) - s.min + 1));
    else if (s.type === "float") {
      if (s.allow_auto && rnd() < 0.5) v[s.name] = "auto";
      else {
        const lo = s.min, hi = s.name.startsWith("CARGA") ? Math.min(s.max, 600) : s.max;
        const x = lo + rnd() * (hi - lo);
        v[s.name] = s.name.startsWith("ESPESOR") ? Math.round(x / 0.5) * 0.5 : Math.round(x);
      }
    }
  }
  return v;
}
const info = { product_name: "Fuzz", project_code: "P-2026-0099", revision: "A", date: "2026-11-06", designer: "QA", client: "", status_stamp: "PRELIMINAR", status_level: "warn" };
const tot = { cases: 0, built: 0, sheets: 0, conflicts: 0, by: {}, worst: [] };
const fams = Object.keys(REGISTRY);
for (let k = 0; k < N; k++) {
  const fid = pick(fams), vals = sample(REGISTRY[fid]);
  tot.cases++;
  let r;
  try { r = regenerate(fid, vals); } catch { continue; }
  tot.built++;
  const p = await drawingSet(r.model, r.summary, info);
  const a = await assemblyInstructions(r.model, r.summary, info, p.ctx);
  tot.sheets += p.total + a.total;
  const n = p.layout.total + a.layout.total;
  tot.conflicts += n;
  for (const L of [p.layout, a.layout]) for (const [t, c] of Object.entries(L.by)) tot.by[t] = (tot.by[t] ?? 0) + c;
  if (n) tot.worst.push({ k, fid, vals, n, sheets: [...p.layout.sheets, ...a.layout.sheets].map((s) => [s.number, s.by, s.sample.slice(0, 3)]) });
}
tot.worst.sort((a, b) => b.n - a.n);
tot.worst = tot.worst.slice(0, 12);
console.log(JSON.stringify(tot));
