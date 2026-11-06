// Comprueba los sólidos facetados de todas las plantillas: capa cerrada, volumen frente al analítico, tiempos.
import { allTemplates, family } from "../../frontend/src/engine/families";
import { build } from "../../frontend/src/engine/sizing";
import { partGeometry } from "../../frontend/src/engine/geometry";
let bad = 0;
const extra = [{ id: "notch-big", family: "estanteria", values: { NUMERO_NIVELES: 3, PERFIL_MONTANTE: "SHS 80x80x4", PERFIL_LARGUERO: "RHS 40x20x2", PERFIL_TRAVESANO: "RHS 40x20x2" } }];
for (const t of [...allTemplates(), ...extra]) {
  const f = family(t.family);
  const m = build(f, f.newParams(t.values));
  const t0 = Date.now();
  let tris = 0, worst = 0, faces = 0;
  for (const p of Object.values(m.parts)) {
    const g = partGeometry(p);
    tris += g.positions.length / 9; faces += g.brep.faces.length;
    const ref = p.kind === "normalizado" ? null : p.volume;
    const dev = ref ? Math.abs(g.volume - ref) / ref : 0;
    worst = Math.max(worst, dev);
    if (!g.closed || !(g.volume > 0) || dev > 5e-3) { bad++; console.log("  MAL", p.ref, p.kind, p.name, "cerrado", g.closed, "abiertas", g.openEdges, "dev", dev.toExponential(2)); }
  }
  console.log(t.id.padEnd(20), "piezas", Object.keys(m.parts).length, "caras", faces, "triángulos", tris, "desv. máx", worst.toExponential(2), Date.now() - t0, "ms");
}
console.log("PIEZAS CON PROBLEMAS", bad);
