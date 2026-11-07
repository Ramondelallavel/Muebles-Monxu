// @ts-nocheck
// Presupuesto estimado de fabricación (port exacto de monxu/manufacturing/costing.py): coste unitario por lote con las
// tarifas orientativas de monxu/catalog/data/costs.json.
import * as C from "./catalog";
import { f as fx, g, pyRound } from "./util";

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
  const add = (group, concept, qty, unit, unit_eur, eur = null) => {
    lines.push({ group, concept, qty: pyRound(qty, 4), unit, unit_eur: pyRound(unit_eur, 4), eur: eur ?? qty * unit_eur });
  };
  const counts = {};
  for (const i of model.instances) counts[i.part.key] = (counts[i.part.key] ?? 0) + 1;
  // ---------------------------------------------------------------- material
  const byUse = op.imputacion_material === "consumo";
  for (const c of plan.cutting) {
    const used = c.pieces_length + c.pieces * c.kerf;
    const eurKg = materialRate(R, c.material, "tubo");
    let kg, txt;
    if (byUse) {
      kg = (used / c.bar_length) * (1 + op.merma_perfil) * c.mass_per_bar_kg;
      txt = `Perfil ${c.profile} ${c.material} (${fx(used / 1000, 2)} m + ${g(op.merma_perfil * 100)} % de merma)`;
    } else {
      const bars = lot === 1 ? c.n_bars : Math.ceil((lot * used) / (c.bar_length - c.trim));
      kg = (bars * c.mass_per_bar_kg) / lot;
      txt = `Perfil ${c.profile} ${c.material} (barras de ${g(c.bar_length)} mm: ${bars} por lote)`;
    }
    add("Material", txt, kg, "kg", eurKg);
  }
  for (const n of plan.nesting) {
    const mat = C.material(n.material);
    const eurKg = materialRate(R, n.material, mat.forms.includes("chapa") ? "chapa" : "pletina");
    const u = op.aprovechamiento_chapa_lote;
    let kg, txt;
    if (byUse || !n.feasible) {
      kg = (n.parts_area_m2 * 1e6 * n.thickness * 1e-9 * mat.density) / u;
      txt = `Chapa ${n.material} e=${g(n.thickness)} mm (${fx(n.parts_area_m2, 3)} m² de piezas, aprovechamiento ${g(u * 100)} %)`;
    } else {
      const sheets = lot === 1 ? n.n_sheets : Math.ceil((lot * n.parts_area_m2) / (n.sheet_area_m2 * u));
      kg = (sheets * n.mass_per_sheet_kg) / lot;
      txt = `Chapa ${n.material} e=${g(n.thickness)} mm (formato ${n.format}: ${sheets} por lote)`;
    }
    add("Material", txt, kg, "kg", eurKg);
  }
  // ---------------------------------------------------------------- normalizados
  const std = {};
  for (const i of model.instances) if (i.part.kind === "normalizado") std[i.part.code] = (std[i.part.code] ?? 0) + 1;
  const unpriced = [];
  for (const code of Object.keys(std).sort()) {
    const [eur, known] = componentPrice(R, code);
    if (!known) unpriced.push(code);
    add("Normalizados", C.component(code).name, std[code], "ud", eur);
  }
  // ---------------------------------------------------------------- fabricación
  let cuts = 0, holes = 0, pierces = 0, bends = 0, sheetRefs = 0, laserRefs = 0, surf = 0.0, galvKg = 0.0;
  const laser = new Map();
  const addLaser = (t, fam, m) => { const k = JSON.stringify([t, fam]); laser.set(k, (laser.get(k) ?? 0) + m); };
  for (const [k, p] of Object.entries(model.parts)) {
    const q = counts[k] ?? 0;
    if (p.kind === "perfil") { cuts += q; holes += q * p.holes.length; }
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
  if (cuts) add("Fabricación", "Corte de perfiles en sierra", cuts, "corte", op.sierra_eur_corte);
  if (holes) add("Fabricación", "Taladrado de perfiles", holes, "taladro", op.taladro_eur);
  const lk = [...laser.keys()].map((k) => JSON.parse(k)).sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
  for (const [t, fam] of lk) add("Fabricación", `Corte por láser e=${g(t)} mm (${fam.replaceAll("_", " ")})`, laser.get(JSON.stringify([t, fam])), "m", laserRate(R, t, fam));
  if (pierces) add("Fabricación", "Perforaciones del láser (contornos y taladros)", pierces, "ud", op.laser_eur_perforacion);
  if (bends) add("Fabricación", "Plegado a 90°", bends, "pliegue", op.plegado_eur_pliegue);
  const w = plan.welding;
  if (w.joints) {
    const h = w.arc_time_h / op.soldadura_factor_marcha;
    add("Fabricación", `Soldadura MAG (${fx(w.total_length_mm / 1000, 2)} m de cordón, factor de marcha ${g(op.soldadura_factor_marcha)})`, h, "h", lab.soldadura);
    add("Consumibles", "Hilo de soldadura", w.wire_kg, "kg", R.consumables_eur.hilo_kg);
    add("Consumibles", "Gas de protección", w.gas_l, "l", R.consumables_eur.gas_l);
  }
  // ---------------------------------------------------------------- acabado
  const fin = model.params.values.ACABADO;
  const [base, eurF] = finishRate(R, fin);
  if (eurF) {
    const name = fin ? C.finish(fin).name : "Acabado";
    if (base === "kg") add("Acabado", name, galvKg, "kg", eurF); else add("Acabado", name, surf, "m²", eurF);
  }
  // ---------------------------------------------------------------- montaje
  const mm = op.montaje_min;
  const roles = {};
  for (const i of model.instances) roles[i.part.role] = (roles[i.part.role] ?? 0) + 1;
  const minutes = (roles.tornillo ?? 0) * mm.tornillo + (roles.tuerca_remachable ?? 0) * mm.tuerca_remachable
    + ((roles.pie_nivelador ?? 0) + (roles.rueda ?? 0)) * mm.apoyo + mm.por_unidad;
  add("Montaje", "Montaje, ajuste y control final", minutes / 60, "h", lab.montaje);
  // ---------------------------------------------------------------- preparación del lote
  const prep = plan.cutting.length * setup.sierra_por_perfil + laserRefs * setup.laser_por_referencia + sheetRefs * setup.plegado_por_referencia
    + (w.joints ? setup.soldadura_util : 0.0);
  add("Preparación", `Programación y preparación de máquinas y útil (${lot} ud por lote)`, 1 / lot, "lote", prep);
  // ---------------------------------------------------------------- totales
  const groups = {};
  for (const ln of lines) groups[ln.group] = (groups[ln.group] ?? 0) + ln.eur;
  const direct = Object.values(groups).reduce((s, v) => s + v, 0);
  const oh = direct * R.overheads.gastos_generales, cost = direct + oh, margin = cost * R.overheads.margen, price = cost + margin;
  const mass = model.instances.reduce((s, i) => s + i.part.mass, 0);
  for (const ln of lines) ln.eur = pyRound(ln.eur, 2);
  return { currency: R._meta.currency, lot, lines, groups: Object.fromEntries(Object.entries(groups).map(([k, v]) => [k, pyRound(v, 2)])),
    direct: pyRound(direct, 2), overheads: pyRound(oh, 2), cost: pyRound(cost, 2), margin: pyRound(margin, 2), price: pyRound(price, 2),
    eur_per_kg: mass ? pyRound(cost / mass, 2) : null,
    hours: { soldadura: w.joints ? pyRound(w.arc_time_h / op.soldadura_factor_marcha, 3) : 0.0, montaje: pyRound(minutes / 60, 3) },
    rates_version: R._meta.version, unpriced, material_basis: op.imputacion_material, overhead_rate: R.overheads.gastos_generales,
    margin_rate: R.overheads.margen, note: R._meta.note };
}

/** Presupuesto del lote unitario y coste por unidad según el tamaño de lote. */
export function quotation(model, plan, R = C.costRates()) {
  const base = estimate(model, plan, 1, R);
  base.by_lot = R.lots.map((n) => { const e = estimate(model, plan, n, R); return { lot: n, direct: e.direct, cost: e.cost, price: e.price }; });
  return base;
}
