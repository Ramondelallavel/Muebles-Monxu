// Ejecuta el motor del navegador en node: lee casos JSON por stdin y escribe los resultados.
import { regenerate } from "../../frontend/src/engine/pipeline";
import { partGeometry } from "../../frontend/src/engine/geometry";
import * as fs from "node:fs";
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = [];
for (const c of cases) {
  try {
    const t0 = Date.now();
    const { model, summary } = regenerate(c.family, c.values);
    const e = summary.engineering;
    out.push({ id: c.id, ok: true, ms: Date.now() - t0, product_code: summary.product_code,
      params: Object.fromEntries(summary.parameters.filter((p) => !p.derived).map((p) => [p.name, p.value])),
      sources: Object.fromEntries(summary.parameters.filter((p) => !p.derived).map((p) => [p.name, p.source])),
      derived: Object.fromEntries(summary.parameters.filter((p) => p.derived).map((p) => [p.name, p.value])),
      n_instances: model.instances.length, n_parts: Object.keys(model.parts).length, mass: summary.mass_kg,
      parts: Object.fromEntries(Object.values(model.parts).map((p) => [p.ref, { key: p.key, mass: p.mass, vol_mesh: partGeometry(p).volume, vol: p.volume }])),
      cost: { direct: summary.cost.direct, cost: summary.cost.cost, price: summary.cost.price, by_lot: summary.cost.by_lot.map((b) => [b.lot, b.price]),
        lines: summary.cost.lines.map((l) => [l.group, l.concept, l.eur]) },
      status: e.status, fem: e.fem, checks: Object.fromEntries(e.checks.map((k) => [k.id, [k.status, k.utilization, k.value]])),
      reactions: e.reactions.filter((r) => r.combination === "ELS-1" || r.combination === "ELU-1"),
      notes: summary.design_notes.map((n) => [n.level, n.code]),
      qa: summary.qa.items.map((i) => [i.level, i.code]),
      cutting: summary.manufacturing.cutting.map((k) => [k.profile, k.n_bars, k.utilization]),
      nesting: summary.manufacturing.nesting.map((k) => [k.material, k.thickness, k.n_sheets ?? null, k.format ?? null, k.utilization ?? null]),
      welding: summary.manufacturing.welding, painting: summary.manufacturing.painting,
      dfm: summary.dfm.map((d) => [d.level, d.code, d.element]), bom_totals: summary.bom.totals,
      fix: summary.fix ? summary.fix.params : null });
  } catch (err) { out.push({ id: c.id, ok: false, error: String(err && err.stack || err) }); }
}
process.stdout.write(JSON.stringify(out));
