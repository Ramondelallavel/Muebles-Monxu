// @ts-nocheck
// Presupuesto estimado de fabricación (port exacto de monxu/manufacturing/costing.py): coste unitario por lote con las
// tarifas orientativas de monxu/catalog/data/costs.json.
import * as C from "./catalog";
import { f as fx, g, pyRound } from "./util";
import { materialPurchase } from "./manufacturing";

const materialRate = (R, code, form) => R.material_overrides_eur_kg[code] ?? (R.material_eur_kg[C.material(code).family] ?? R.material_eur_kg.acero_carbono)[form];
function componentPrice(R, code) {
  for (const [prefix, eur] of R.components_eur) if (code.startsWith(prefix)) return [eur, true];
  return [R.component_default_eur, false];
}
function laserRate(R, t, family) {
  const table = R.operations.laser_eur_m;
  let eur = table.at(-1)[1];
  for (const [tmax, v] of table) if (t <= tmax + 1e-9) { eur = v; break; }
  return eur * (R.operations.laser_factor_material[family] ?? 1.0);
}
function finishRate(R, finish) {
  const F = R.finishes_eur;
  if (!finish) return ["m2", 0.0];
  if (finish === "CATAFORESIS_POLVO") return ["m2", F.CATAFORESIS_POLVO_m2];
  if (finish.endsWith("_POLVO")) return ["m2", F.POLVO_m2];
  if (`${finish}_kg` in F) return ["kg", F[`${finish}_kg`]];
  return ["m2", F[`${finish}_m2`] ?? 0.0];
}
function surfaceMm2(p) {
  if (p.kind === "perfil") return (2 * (p.profile.B + p.profile.H) - (8 - 2 * Math.PI) * p.profile.r_out) * p.length;
  if (p.kind === "chapa") return 2 * p.flat.netArea;
  if (p.kind === "pletina") return 2 * p.w * p.h + 2 * (p.w + p.h) * p.t;
  return 0.0;
}
const plateCutMm = (p) => 2 * (p.w + p.h) - (8 - 2 * Math.PI) * p.corner_r + p.holes.reduce((s, h) => s + Math.PI * h[2], 0);

export function estimate(model, plan, lot = 1, R = C.costRates()) {
  lot = Math.max(1, Math.floor(lot));
  const op = R.operations, lab = R.labor_eur_h, setup = R.setup_eur;
  const lines = [];
  const add = (group, concept, qty, unit, unit_eur, eur = null, basis = "") => {
    lines.push({ group, concept, qty: pyRound(qty, 4), unit, unit_eur: pyRound(unit_eur, 4), eur: eur ?? qty * unit_eur, basis });
  };
  const counts = {};
  for (const i of model.instances) counts[i.part.key] = (counts[i.part.key] ?? 0) + 1;
  // el material del lote sale de su propio plan de corte y anidado (el del proyecto si coincide el lote)
  const mp = (plan.lot ?? 1) === lot ? plan : materialPurchase(model, lot);
  const basis = op.imputacion_material;
  if (basis !== "compra" && basis !== "consumo") throw new Error(`imputacion_material desconocida: ${basis}`);
  // ---------------------------------------------------------------- material
  for (const c of mp.cutting) {
    const eurKg = materialRate(R, c.material, "tubo");
    const k = c.kg_per_m / 1000;
    let kg, what;
    if (basis === "compra") { kg = c.purchased_length * k; what = `${c.n_bars} barras de ${g(c.bar_length)} mm compradas`; }
    else { kg = (c.purchased_length + c.stock_length - c.reusable_length) * k; what = `consumo ${fx((c.purchased_length + c.stock_length - c.reusable_length) / 1000, 2)} m`; }
    const txt = `Perfil ${c.profile} ${c.material}: ${what} por lote de ${lot} (neto ${fx(c.pieces_length / 1000, 2)} m, desperdicio ${fx(c.waste_length / 1000, 2)} m, `
      + `retal reutilizable ${fx(c.reusable_length / 1000, 2)} m)`;
    add("Material", txt, kg / lot, "kg", eurKg, null, "plan de corte");
  }
  for (const n of mp.nesting) {
    const mat = C.material(n.material);
    const eurKg = materialRate(R, n.material, mat.forms.includes("chapa") ? "chapa" : "pletina");
    const k = n.thickness * 1e-3 * mat.density;
    if (!n.feasible) {
      const kg = n.parts_area_m2 * k;
      add("Material", `Chapa ${n.material} e=${g(n.thickness)} mm: sin formato comercial válido, superficie neta de piezas ${fx(n.parts_area_m2, 3)} m² `
        + "(PENDIENTE: la pieza no cabe en ningún formato)", kg / lot, "kg", eurKg, null, "superficie neta (sin anidado válido)");
      continue;
    }
    const pu = n.purchase;
    let kg, what;
    if (basis === "compra") {
      kg = pu.purchased_area_m2 * k;
      what = (pu.n_full ? `${pu.n_full} chapas ${n.format}` : "") + (pu.n_custom ? `${pu.n_full ? " + " : ""}${pu.n_custom} cortada a medida` : "");
    } else {
      kg = (pu.purchased_area_m2 + pu.stock_area_m2 - pu.reusable_area_m2) * k;
      what = `consumo ${fx(pu.purchased_area_m2 + pu.stock_area_m2 - pu.reusable_area_m2, 3)} m²`;
    }
    add("Material", `Chapa ${n.material} e=${g(n.thickness)} mm: ${what || "retales de inventario"} por lote de ${lot} (piezas ${fx(pu.parts_area_m2, 3)} m², `
      + `aprovechamiento real ${fx(pu.utilization * 100, 1)} %)`, kg / lot, "kg", eurKg, null, "anidado");
  }
  // ---------------------------------------------------------------- normalizados
  const std = {};
  for (const i of model.instances) if (i.part.kind === "normalizado") std[i.part.code] = (std[i.part.code] ?? 0) + 1;
  const unpriced = [];
  for (const code of Object.keys(std).sort()) {
    const [eur, known] = componentPrice(R, code);
    if (!known) unpriced.push(code);
    add("Normalizados", C.component(code).name, std[code], "ud", eur, null, "BOM");
  }
  // ---------------------------------------------------------------- fabricación
  let holes = 0, pierces = 0, bends = 0, sheetRefs = 0, laserRefs = 0, surf = 0.0, galvKg = 0.0;
  const laser = new Map();
  const addLaser = (t, fam, m) => { const k = JSON.stringify([t, fam]); laser.set(k, (laser.get(k) ?? 0) + m); };
  for (const [k, p] of Object.entries(model.parts)) {
    const q = counts[k] ?? 0;
    if (p.kind === "perfil") holes += q * p.holes.length;
    else if (p.kind === "chapa") {
      const fp = p.flat;
      addLaser(p.spec.t, C.material(p.material).family, (q * fp.cutLength) / 1000);
      pierces += q * (1 + fp.holes.length); bends += q * p.spec.flanges.length; sheetRefs++; laserRefs++;
    } else if (p.kind === "pletina") {
      addLaser(p.t, C.material(p.material).family, (q * plateCutMm(p)) / 1000);
      pierces += q * (1 + p.holes.length); laserRefs++;
    }
    if (p.kind !== "normalizado" && p.finish) {
      surf += (q * surfaceMm2(p)) / 1e6;
      if (p.finish === "GALVANIZADO") galvKg += q * p.mass;
    }
  }
  const cuts = mp.cutting.reduce((t, c) => t + c.n_cuts, 0);
  if (cuts) add("Fabricación", `Corte de perfiles en sierra (${cuts} cortes por lote de ${lot}: refrentado de cada barra y uno por pieza)`, cuts / lot, "corte",
    op.sierra_eur_corte, null, "plan de corte");
  if (holes) add("Fabricación", "Taladrado de perfiles", holes, "taladro", op.taladro_eur, null, "geometría (taladros de perfiles)");
  const lk = [...laser.keys()].map((k) => JSON.parse(k)).sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
  for (const [t, fam] of lk) add("Fabricación", `Corte por láser e=${g(t)} mm (${fam.replaceAll("_", " ")})`, laser.get(JSON.stringify([t, fam])), "m", laserRate(R, t, fam),
    null, "contornos exteriores e interiores de los desarrollos");
  if (pierces) add("Fabricación", "Perforaciones del láser (una por contorno cerrado)", pierces, "ud", op.laser_eur_perforacion, null, "contornos de los desarrollos");
  if (bends) add("Fabricación", "Plegado a 90°", bends, "pliegue", op.plegado_eur_pliegue, null, "pliegues del modelo");
  const w = plan.welding;
  if (w.joints) {
    const h = w.arc_time_h / op.soldadura_factor_marcha;
    add("Fabricación", `Soldadura MAG (${fx(w.total_length_mm / 1000, 2)} m de cordón, factor de marcha ${g(op.soldadura_factor_marcha)})`, h, "h", lab.soldadura, null,
      "cordones del modelo");
    add("Consumibles", "Hilo de soldadura", w.wire_kg, "kg", R.consumables_eur.hilo_kg, null, "cordones del modelo");
    add("Consumibles", "Gas de protección", w.gas_l, "l", R.consumables_eur.gas_l, null, "tiempo de arco");
  }
  // ---------------------------------------------------------------- acabado
  const fin = model.params.values.ACABADO;
  const [base, eurF] = finishRate(R, fin);
  if (eurF) {
    const name = fin ? C.finish(fin).name : "Acabado";
    if (base === "kg") add("Acabado", name, galvKg, "kg", eurF, null, "masa de las piezas"); else add("Acabado", name, surf, "m²", eurF, null, "superficie de las piezas");
  }
  // ---------------------------------------------------------------- montaje
  const mm = op.montaje_min;
  const roles = {};
  for (const i of model.instances) roles[i.part.role] = (roles[i.part.role] ?? 0) + 1;
  const minutes = (roles.tornillo ?? 0) * mm.tornillo + (roles.tuerca_remachable ?? 0) * mm.tuerca_remachable
    + ((roles.pie_nivelador ?? 0) + (roles.rueda ?? 0)) * mm.apoyo + mm.por_unidad;
  add("Montaje", "Montaje y ajuste final", minutes / 60, "h", lab.montaje, null, "componentes del modelo");
  // ---------------------------------------------------------------- control de calidad
  const cm = op.control_min;
  if (cm) add("Control de calidad", `Control dimensional y visual de soldaduras (${w.joints} uniones soldadas)`, (cm.por_unidad + cm.por_union_soldada * w.joints) / 60,
    "h", lab.control, null, "uniones del modelo");
  // ---------------------------------------------------------------- preparación del lote
  const prep = mp.cutting.length * setup.sierra_por_perfil + laserRefs * setup.laser_por_referencia + sheetRefs * setup.plegado_por_referencia
    + (w.joints ? setup.soldadura_util : 0.0);
  add("Preparación", `Programación y preparación de máquinas y útil (${lot} ud por lote)`, 1 / lot, "lote", prep, null, "referencias del modelo");
  // ---------------------------------------------------------------- totales
  const groups = {};
  for (const ln of lines) groups[ln.group] = (groups[ln.group] ?? 0) + ln.eur;
  const direct = Object.values(groups).reduce((s, v) => s + v, 0);
  const oh = direct * R.overheads.gastos_generales, cost = direct + oh, margin = cost * R.overheads.margen, price = cost + margin;
  const mass = model.instances.reduce((s, i) => s + i.part.mass, 0);
  for (const ln of lines) ln.eur = pyRound(ln.eur, 2);
  const matKg = lines.filter((ln) => ln.group === "Material").reduce((t, ln) => t + ln.qty, 0);
  return { currency: R._meta.currency, lot, lines, groups: Object.fromEntries(Object.entries(groups).map(([k, v]) => [k, pyRound(v, 2)])),
    direct: pyRound(direct, 2), overheads: pyRound(oh, 2), cost: pyRound(cost, 2), margin: pyRound(margin, 2), price: pyRound(price, 2),
    eur_per_kg: mass ? pyRound(cost / mass, 2) : null,
    hours: { soldadura: w.joints ? pyRound(w.arc_time_h / op.soldadura_factor_marcha, 3) : 0.0, montaje: pyRound(minutes / 60, 3) },
    rates_version: R._meta.version, unpriced, material_basis: basis, material_kg_per_unit: pyRound(matKg, 3), saw_cuts_lot: cuts,
    overhead_rate: R.overheads.gastos_generales, margin_rate: R.overheads.margen, note: R._meta.note };
}

/** Presupuesto del lote unitario y coste por unidad según el tamaño de lote. */
export function quotation(model, plan, R = C.costRates()) {
  const lot = Math.max(1, Math.floor(+(model.params.values.LOTE_FABRICACION || 1)));     // lote del proyecto (parámetro avanzado)
  const base = estimate(model, plan, lot, R);
  const lots = [...new Set([...R.lots, lot])].sort((a, b) => a - b);
  base.by_lot = lots.map((n) => { const e = n === lot ? base : estimate(model, plan, n, R);
    return { lot: n, direct: e.direct, cost: e.cost, price: e.price, material: e.groups.Material ?? 0.0 }; });
  return base;
}
