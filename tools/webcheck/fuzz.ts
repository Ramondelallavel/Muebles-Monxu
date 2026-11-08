// Barrido aleatorio del motor del navegador: excepciones, valores no finitos, sólidos abiertos, interferencias y
// fallos al generar el expediente completo (STEP, planos, montaje, Excel, DXF).
// Uso: [FAMS=familia1,familia2] node fuzz.mjs N SEMILLA [cada_cuantos_expediente]
import { REGISTRY } from "../../frontend/src/engine/families";
import { regenerate } from "../../frontend/src/engine/pipeline";
import { partGeometry } from "../../frontend/src/engine/geometry";
import { buildDossier } from "../../frontend/src/local/dossier";
import * as fs from "node:fs";
const [N, SEED, EVERY] = process.argv.slice(2).map(Number);
let st = SEED || 1;
const rnd = () => { st = (st * 1103515245 + 12345) % 2147483648; return st / 2147483648; };
const pick = (a) => a[Math.floor(rnd() * a.length)];
const SKIP = new Set(["TOLERANCIAS", "CLASE_EJECUCION", "TIPO_APOYO", "FIJACION_ENCIMERA"]);
function sample(fam) {
  const v = {};
  for (const s of fam.specs()) {
    if (SKIP.has(s.name) || rnd() < 0.45) continue;
    if (s.type === "choice") v[s.name] = pick([...s.choices, ...(s.allow_auto ? ["auto"] : [])]);
    else if (s.type === "int") v[s.name] = s.allow_auto && rnd() < 0.5 ? "auto" : s.min + Math.floor(rnd() * (Math.min(s.max, 10) - s.min + 1));
    else if (s.type === "float") {
      if (s.allow_auto && rnd() < 0.5) v[s.name] = "auto";
      else if (s.nullable && rnd() < 0.3) v[s.name] = null;
      else {
        const lo = s.min, hi = s.name.startsWith("CARGA") ? Math.min(s.max, 800) : s.max;
        const x = lo + rnd() * (hi - lo);
        v[s.name] = s.name.startsWith("ESPESOR") ? Math.round(x / 0.5) * 0.5 : hi - lo < 10 ? Math.round(x * 1000) / 1000 : Math.round(x);
      }
    }
  }
  return v;
}
const out = { n: 0, ok: 0, param_errors: 0, crashes: [], nonfinite: [], open: [], interf: [], blocking: {}, dossier_fail: [], dossier_ok: 0, ms: [] };
// FAMS=familia1,familia2 limita el barrido a esas familias
const fams = process.env.FAMS ? process.env.FAMS.split(",") : Object.keys(REGISTRY);
for (let k = 0; k < N; k++) {
  const fid = pick(fams), vals = sample(REGISTRY[fid]);
  out.n++;
  const t0 = Date.now();
  let r;
  try { r = regenerate(fid, vals); }
  catch (e) {
    const msg = String(e?.message ?? e);
    if (e?.name === "ParamError" || /inferior al mínimo|superior al máximo|superan la altura|no está entre|Las patas deben|Los montantes deben/.test(msg)) out.param_errors++;
    else out.crashes.push({ k, fid, vals, msg, stack: String(e?.stack ?? "").split("\n").slice(0, 4).join(" | ") });
    continue;
  }
  out.ms.push(Date.now() - t0);
  out.ok++;
  const { model, summary } = r;
  const e = summary.engineering;
  const bad = e.checks.filter((c) => (c.utilization !== null && !Number.isFinite(c.utilization)) || (c.value !== null && typeof c.value === "number" && !Number.isFinite(c.value)));
  if (bad.length || !Number.isFinite(summary.mass_kg)) out.nonfinite.push({ k, fid, vals, checks: bad.map((c) => [c.id, c.value, c.utilization]), mass: summary.mass_kg });
  const open = Object.values(model.parts).filter((p) => !partGeometry(p).closed || !(partGeometry(p).volume > 0)).map((p) => [p.ref, p.name, partGeometry(p).openEdges]);
  if (open.length) out.open.push({ k, fid, vals, open });
  if (summary.interferences.interferences.length) out.interf.push({ k, fid, vals, list: summary.interferences.interferences.slice(0, 4) });
  for (const i of summary.qa.items) if (i.level === "bloqueante") out.blocking[i.code] = (out.blocking[i.code] ?? 0) + 1;
  if (EVERY && k % EVERY === 0 && summary.qa.blocking === 0) {
    const rev = { rev: "A", created: "2026-11-06T10:00:00", author: "QA", comment: "", params: model.params.values, sources: model.params.sources, changes: {} };
    const project = { code: "P-2026-0099", name: "Fuzz", client: "", family: fid, designer: "QA", revisions: [rev] };
    try {
      const d = await buildDossier(project, rev, model, summary);
      if (d.qa.blocking) out.dossier_fail.push({ k, fid, vals, items: d.qa.items.filter((i) => i.level === "bloqueante").map((i) => [i.code, i.message.slice(0, 160)]) });
      else out.dossier_ok++;
    } catch (err) { out.dossier_fail.push({ k, fid, vals, msg: String(err?.message ?? err), stack: String(err?.stack ?? "").split("\n").slice(0, 5).join(" | ") }); }
  }
}
out.ms.sort((a, b) => a - b);
const ms = out.ms; out.ms = { median: ms[Math.floor(ms.length / 2)], p95: ms[Math.floor(ms.length * 0.95)], max: ms.at(-1) };
fs.writeFileSync(process.env.OUT ?? "/dev/stdout", JSON.stringify(out, null, 1));
