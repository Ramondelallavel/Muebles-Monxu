// @ts-nocheck
// Mapa de dependencias documento → parámetros (port de monxu/docs/dependencies.py).
const PROCESS = { plan_corte: ["LONGITUD_BARRA", "CORTE_SIERRA", "LOTE_FABRICACION"], anidado: ["FORMATO_CHAPA", "LOTE_FABRICACION"],
  presupuesto: ["ACABADO", "ESPESOR_PINTURA", "LOTE_FABRICACION", "LONGITUD_BARRA", "CORTE_SIERRA", "FORMATO_CHAPA"], planos: ["TOLERANCIAS", "ACABADO", "CLASE_EJECUCION"] };
export const DOCUMENTS = { modelo_3d: "Modelo 3D (STEP, STL, JSON paramétrico)", planos: "Planos PDF", dxf: "DXF de corte y desarrollos", bom: "BOM (Excel y CSV)",
  plan_corte: "Plan de corte de perfiles", anidado: "Anidado de chapa", compras: "Lista de compras", presupuesto: "Presupuesto", calculo: "Informe de cálculo",
  montaje: "Instrucciones de montaje", verificaciones: "Informe de verificaciones (QA)" };
const U = (...sets) => new Set(sets.flatMap((s) => [...s]));
export function dependencyMap(model) {
  const tree = model.featureTree();
  const inst = Object.fromEntries(model.instances.map((i) => [i.id, i]));
  const kp = { perfil: new Set(), chapa: new Set(), pletina: new Set(), normalizado: new Set() };
  const geo = new Set();
  for (const f of tree) {
    for (const p of f.params) geo.add(p);
    for (const iid of f.produces) if (inst[iid]) for (const p of f.params) kp[inst[iid].part.kind].add(p);
  }
  const specs = model.params.specs;
  const loads = new Set(Object.entries(specs).filter(([, s]) => s.group === "cargas").map(([n]) => n));
  const sheet = U(kp.chapa, kp.pletina);
  const deps = { modelo_3d: geo, planos: U(geo, PROCESS.planos, loads), dxf: sheet, bom: U(geo, ["ACABADO"]), plan_corte: U(kp.perfil, PROCESS.plan_corte),
    anidado: U(sheet, PROCESS.anidado), compras: U(kp.perfil, sheet, kp.normalizado, PROCESS.plan_corte, PROCESS.anidado), presupuesto: U(geo, PROCESS.presupuesto),
    calculo: U(geo, loads), montaje: U(kp.normalizado, ["ANCLAJE", "TACO_ANCLAJE", "TIPO_APOYO"].filter((n) => n in specs)) };
  deps.verificaciones = U(...Object.values(deps));
  return Object.fromEntries(Object.entries(deps).map(([k, v]) => [k, [...v].filter((n) => n in specs).sort()]));
}
export const affectedDocuments = (dep, changed) => Object.entries(dep).filter(([, v]) => v.some((n) => changed.includes(n))).map(([k]) => DOCUMENTS[k]);
