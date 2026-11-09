// @ts-nocheck
// Optimización de corte y anidado, plan de fabricación, DFM y BOM (port de monxu/manufacturing y monxu/docs/bom.py).
import * as C from "./catalog";
import { KIND_LABEL } from "./model";
import { f as fx, g, pyRound } from "./util";

const cmpTuple = (a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1; return 0; };

// ============================================================================ 1D
export function optimizeBars(pieces, bar_length = 6000.0, kerf = 3.0, trim = 10.0, reusable_min = 500.0) {
  let items = [];
  for (const p of pieces) {
    if (p.length + trim + kerf > bar_length) throw new Error(`La pieza ${p.ref} (${p.length} mm) supera la longitud de barra ${bar_length} mm`);
    for (let i = 0; i < p.qty; i++) items.push({ ...p });
  }
  items = items.map((p, i) => ({ p, i })).sort((a, b) => b.p.length - a.p.length || a.i - b.i).map((x) => x.p);   // orden estable
  let bars = [];
  for (const it of items) {
    const need = it.length + kerf;
    let best = null, bestRem = null;
    for (const b of bars) {
      const rem = b.free - need;
      if (rem >= -kerf + 1e-9 && (bestRem === null || rem < bestRem)) { best = b; bestRem = rem; }
    }
    if (!best) { best = { cuts: [], free: bar_length - trim }; bars.push(best); }
    best.cuts.push({ ref: it.ref, label: it.label ?? "", length: it.length });
    best.free -= need;
  }
  // cota inferior válida: cada barra admite hasta un ancho de sierra más (la última pieza puede apurarla)
  const lb0 = items.length ? Math.ceil(items.reduce((s, p) => s + p.length + kerf, 0) / (bar_length - trim + kerf) - 1e-9) : 0;
  if (bars.length > lb0 && items.length <= 60) {
    for (let k = lb0; k < bars.length; k++) {
      const exact = exactPack(items, bar_length - trim + kerf, kerf, k);
      if (exact) {
        bars = exact.map((b) => ({ cuts: b.map((it) => ({ ref: it.ref, label: it.label ?? "", length: it.length })),
          free: bar_length - trim - b.reduce((s, it) => s + it.length + kerf, 0) }));
        break;
      }
    }
  }
  const total = items.reduce((s, p) => s + p.length, 0);
  const out = bars.map((b, n) => {
    const rem = Math.max(0.0, b.free);
    return { bar: n + 1, cuts: b.cuts, used: pyRound(b.cuts.reduce((s, c) => s + c.length, 0), 1), kerf_loss: pyRound(kerf * b.cuts.length + trim + Math.min(0.0, b.free), 1),
      remnant: pyRound(rem, 1), remnant_reusable: rem >= reusable_min };
  });
  const nb = bars.length;
  return { bar_length, kerf, trim, reusable_min, bars: out, n_bars: nb, lower_bound: lb0, optimal: nb === lb0, pieces: items.length,
    pieces_length: pyRound(total, 1), utilization: nb ? pyRound(total / (nb * bar_length), 4) : 0.0,
    reusable_remnants: out.filter((b) => b.remnant_reusable).map((b) => b.remnant),
    scrap: pyRound(out.filter((b) => !b.remnant_reusable).reduce((s, b) => s + b.remnant, 0) + out.reduce((s, b) => s + b.kerf_loss, 0), 1) };
}

function exactPack(items, cap, kerf, k, nodeLimit = 200000) {
  const need = items.map((it) => it.length + kerf);
  const order = items.map((_, i) => i).sort((a, b) => need[b] - need[a] || a - b);
  const free = Array(k).fill(cap);
  const assign = Array.from({ length: k }, () => []);
  let nodes = 0;
  const rec = (n) => {
    if (n === order.length) return true;
    if (++nodes > nodeLimit) return false;
    const i = order[n];
    const tried = new Set();
    for (let b = 0; b < k; b++) {
      if (free[b] + 1e-9 >= need[i] && !tried.has(free[b])) {
        tried.add(free[b]);
        free[b] -= need[i]; assign[b].push(i);
        if (rec(n + 1)) return true;
        assign[b].pop(); free[b] += need[i];
      }
    }
    return false;
  };
  return rec(0) ? assign.filter((b) => b.length).map((b) => b.map((i) => items[i])) : null;
}

// ============================================================================ 2D (MaxRects BSSF)
const contains = (a, o) => o.x >= a.x - 1e-9 && o.y >= a.y - 1e-9 && o.x + o.w <= a.x + a.w + 1e-9 && o.y + o.h <= a.y + a.h + 1e-9;
class Bin {
  constructor(W, H) { this.W = W; this.H = H; this.free = [{ x: 0, y: 0, w: W, h: H }]; this.used = []; }
  find(w, h, allowRot) {
    let best = null;
    for (const fr of this.free)
      for (const [rot, ww, hh] of [[false, w, h], [true, h, w]]) {
        if (rot && !allowRot) continue;
        if (ww <= fr.w + 1e-9 && hh <= fr.h + 1e-9) {
          const key = [Math.min(fr.w - ww, fr.h - hh), Math.max(fr.w - ww, fr.h - hh)];
          if (!best || cmpTuple(key, best[0]) < 0) best = [key, { x: fr.x, y: fr.y, w: ww, h: hh }, rot];
        }
      }
    return best;
  }
  place(r) {
    const nf = [];
    for (const fr of this.free) {
      if (r.x >= fr.x + fr.w || r.x + r.w <= fr.x || r.y >= fr.y + fr.h || r.y + r.h <= fr.y) { nf.push(fr); continue; }
      if (r.x > fr.x) nf.push({ x: fr.x, y: fr.y, w: r.x - fr.x, h: fr.h });
      if (r.x + r.w < fr.x + fr.w) nf.push({ x: r.x + r.w, y: fr.y, w: fr.x + fr.w - r.x - r.w, h: fr.h });
      if (r.y > fr.y) nf.push({ x: fr.x, y: fr.y, w: fr.w, h: r.y - fr.y });
      if (r.y + r.h < fr.y + fr.h) nf.push({ x: fr.x, y: r.y + r.h, w: fr.w, h: fr.y + fr.h - r.y - r.h });
    }
    this.free = nf.filter((a, i) => a.w > 1e-9 && a.h > 1e-9 && !nf.some((b, j) => j !== i && contains(b, a) && !(contains(a, b) && j > i)));
  }
}

export function nestSheets(parts, sheet_l, sheet_w, margin = 10.0, spacing = 8.0, kerf = 0.3) {
  const gap = spacing + kerf;
  const UW = sheet_l - 2 * margin + gap, UH = sheet_w - 2 * margin + gap;
  let items = [];
  for (const p of parts) {
    const rot = p.rotate ?? true;
    if (!((p.w + gap <= UW && p.h + gap <= UH) || (rot && p.h + gap <= UW && p.w + gap <= UH)))
      return { feasible: false, reason: `${p.ref} (${fx(p.w)}×${fx(p.h)} mm) no cabe en el formato ${fx(sheet_l)}×${fx(sheet_w)} mm con márgenes de ${margin.toFixed(1)} mm` };
    for (let i = 0; i < p.qty; i++) items.push(p);
  }
  items = items.map((p, i) => ({ p, i })).sort((a, b) => b.p.w * b.p.h - a.p.w * a.p.h || a.i - b.i).map((x) => x.p);
  const bins = [];
  const put = (b, p, fnd) => {
    b.place(fnd[1]);
    b.used.push({ ref: p.ref, x: fnd[1].x + margin, y: fnd[1].y + margin, rot: fnd[2], w: fnd[2] ? p.h : p.w, h: fnd[2] ? p.w : p.h, area: p.area });
  };
  for (const p of items) {
    let placed = false;
    for (const b of bins) { const fnd = b.find(p.w + gap, p.h + gap, p.rotate ?? true); if (fnd) { put(b, p, fnd); placed = true; break; } }
    if (!placed) { const b = new Bin(UW, UH); put(b, p, b.find(p.w + gap, p.h + gap, p.rotate ?? true)); bins.push(b); }
  }
  const sheetArea = sheet_l * sheet_w;
  const sheets = bins.map((b, n) => {
    const used = b.used.reduce((s, u) => s + u.area, 0);
    return { sheet: n + 1, placements: b.used, parts_area_mm2: pyRound(used, 1), utilization: pyRound(used / sheetArea, 4) };
  });
  const tot = sheets.reduce((s, x) => s + x.parts_area_mm2, 0);
  return { feasible: true, format: `${fx(sheet_l)}x${fx(sheet_w)}`, length: sheet_l, width: sheet_w, margin, spacing, kerf, sheets,
    n_sheets: sheets.length, parts_area_m2: pyRound(tot / 1e6, 4), sheet_area_m2: pyRound((sheets.length * sheetArea) / 1e6, 4),
    utilization: sheets.length ? pyRound(tot / (sheets.length * sheetArea), 4) : 0, waste_m2: pyRound((sheets.length * sheetArea - tot) / 1e6, 4) };
}

export function bestFormat(parts, formats, kw) {
  const results = formats.map((f) => ({ ...nestSheets(parts, f.length, f.width, kw.margin, kw.spacing, kw.kerf), format_code: f.code }));
  const feasible = results.filter((r) => r.feasible);
  // sin formato válido el presupuesto estima por superficie de piezas (antes faltaba el dato y fallaba)
  if (!feasible.length) return { feasible: false, alternatives: results, reason: "Ninguna pieza cabe en los formatos comerciales configurados",
    parts_area_m2: pyRound(parts.reduce((s, p) => s + p.area * p.qty, 0) / 1e6, 4) };
  let best = feasible[0];
  for (const r of feasible) if (cmpTuple([r.sheet_area_m2, r.n_sheets], [best.sheet_area_m2, best.n_sheets]) < 0) best = r;
  return { ...best, alternatives: results.map((r) => ({ format: r.format_code, feasible: r.feasible, n_sheets: r.n_sheets ?? null,
    utilization: r.utilization ?? null, reason: r.reason ?? null })) };
}

// ============================================================================ plan
const counts = (model) => { const c = {}; for (const i of model.instances) c[i.part.key] = (c[i.part.key] ?? 0) + 1; return c; };
export function routing(p) {
  if (p.kind === "perfil") {
    const r = ["Corte por sierra de cinta (90°)"];
    if (p.holes.length) r.push(`Taladrado Ø${g(p.holes[0][3])} (${p.holes.length} uds)`);
    return [...r, "Soldadura MAG (en conjunto)"];
  }
  if (p.kind === "chapa") return ["Corte por láser", `Plegado (${p.spec.flanges.length} pliegues a 90°)`];
  if (p.kind === "pletina") return ["Corte por láser"];
  return ["Compra"];
}
const plateArea = (p) => p.outlineArea - p.holes.reduce((s, h) => s + (Math.PI * h[2] * h[2]) / 4, 0);

/** µm: espesor de referencia del consumo de polvo del catálogo. */
const PAINT_REF_UM = 80.0;
/** Longitud de barra comercial: la del proyecto (LONGITUD_BARRA) o la del catálogo. */
export const barLength = (model) => +(model.params.values.LONGITUD_BARRA || C.profileMeta().default_bar_length_mm);

export function manufacturingPlan(model) {
  const cnt = counts(model);
  const sd = C.sheetData();
  const barLen = barLength(model), kerf = +(model.params.values.CORTE_SIERRA || 3.0);
  const groups = new Map();
  for (const [k, p] of Object.entries(model.parts)) if (p.kind === "perfil") {
    const key = JSON.stringify([p.profile.code, p.material]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ ref: p.ref, label: p.name, length: p.length, qty: cnt[k] });
  }
  const cutting = [...groups.entries()].sort((a, b) => cmpTuple(JSON.parse(a[0]), JSON.parse(b[0]))).map(([key, pieces]) => {
    const [code, mat] = JSON.parse(key);
    return { ...optimizeBars(pieces, barLen, kerf), profile: code, material: mat,
      mass_per_bar_kg: pyRound((C.profile(code).massPerM(C.material(mat).density) * barLen) / 1000, 2) };
  });
  const sg = new Map();
  const push = (mat, t, item) => { const key = JSON.stringify([mat, t]); if (!sg.has(key)) sg.set(key, []); sg.get(key).push(item); };
  for (const [k, p] of Object.entries(model.parts)) {
    if (p.kind === "chapa") push(p.material, p.spec.t, { ref: p.ref, w: p.flat.width, h: p.flat.height, qty: cnt[k], area: p.flat.netArea,
      rotate: p.finish !== "INOX_SATINADO", kind: "chapa" });
    else if (p.kind === "pletina") push(p.material, p.t, { ref: p.ref, w: p.w, h: p.h, qty: cnt[k], area: plateArea(p), rotate: true, kind: "pletina" });
  }
  const las = sd.laser;
  const fmt = model.params.values.FORMATO_CHAPA;
  const fixedFmt = C.sheetFormats().filter((f) => f.code === fmt), formats = fixedFmt.length ? fixedFmt : C.sheetFormats();
  const nesting = [...sg.entries()].sort((a, b) => cmpTuple(JSON.parse(a[0]), JSON.parse(b[0]))).map(([key, parts]) => {
    const [mat, t] = JSON.parse(key);
    const r = bestFormat(parts, formats, { margin: las.sheet_margin_mm, spacing: las.part_spacing_mm, kerf: las.kerf_mm });
    return { ...r, material: mat, thickness: t,
      mass_per_sheet_kg: r.feasible ? pyRound((r.length ?? 0) * (r.width ?? 0) * t * 1e-9 * C.material(mat).density, 2) : null };
  });
  const welds = model.joints.filter((j) => j.kind === "soldadura");
  const weldLen = welds.reduce((s, j) => s + j.weld.length, 0);
  const wire = C.consumables().HILO_G3Si1, gas = C.consumables().GAS_M21;
  const deposit = welds.reduce((s, j) => s + j.weld.a ** 2 * j.weld.length, 0) * 1e-6 * wire.deposit_density_kg_dm3;
  const wireKg = deposit / wire.efficiency, arcH = deposit / gas.deposit_rate_kg_h, gasL = arcH * 60 * gas.flow_l_min;
  let painted = 0.0;
  for (const [k, p] of Object.entries(model.parts)) {
    if (!p.finish || !(C.finish(p.finish).consumable_kg_m2 > 0)) continue;
    let a;
    if (p.kind === "perfil") a = (2 * (p.profile.B + p.profile.H) - (8 - 2 * Math.PI) * p.profile.r_out) * p.length;
    else if (p.kind === "chapa") a = 2 * p.flat.netArea;
    else if (p.kind === "pletina") a = 2 * p.w * p.h + 2 * (p.w + p.h) * p.t;
    else continue;
    painted += a * cnt[k];
  }
  const fin = model.params.values.ACABADO;
  const film = +(model.params.values.ESPESOR_PINTURA || PAINT_REF_UM);      // consumo ∝ espesor de película
  const paintKg = fin ? (((painted / 1e6) * C.finish(fin).consumable_kg_m2) * film) / PAINT_REF_UM : 0.0;
  return { cutting, nesting,
    welding: { joints: welds.length, total_length_mm: pyRound(weldLen, 1), deposit_kg: pyRound(deposit, 3), wire_kg: pyRound(wireKg, 3),
      arc_time_h: pyRound(arcH, 3), gas_l: pyRound(gasL, 1), wire: wire.name, gas: gas.name },
    painting: { area_m2: pyRound(painted / 1e6, 3), powder_kg: pyRound(paintKg, 3), finish: fin },
    routing: Object.fromEntries(Object.values(model.parts).map((p) => [p.ref, routing(p)])) };
}

// ============================================================================ DFM
export function dfmCheck(model, plan = null) {
  const sd = C.sheetData();
  const pb = sd.press_brake, las = sd.laser;
  const out = [];
  const add = (level, code, element, message, proposal = "") => out.push({ level, code, element, message, proposal });
  const barLen = barLength(model);
  for (const p of Object.values(model.parts)) {
    if (p.kind === "chapa") {
      const mat = C.material(p.material);
      const s = p.spec;
      const avail = C.sheetThicknesses(p.material);
      if (!avail.includes(s.t)) {
        const near = avail.length ? avail.reduce((b, v) => (Math.abs(v - s.t) < Math.abs(b - s.t) ? v : b)) : null;
        add("error", "LAS-ESPESOR", p.ref, `Espesor ${s.t} mm no disponible en ${p.material}.`, near != null ? `Usar ${near} mm.` : "Seleccionar otro material.");
      }
      if (s.t > (las.max_thickness_mm[mat.family] ?? 10)) add("error", "LAS-ESPESOR-MAX", p.ref, `Espesor ${s.t} mm supera la capacidad del láser.`);
      const rmin = (pb.min_inner_radius_factor[mat.family] ?? 1.0) * s.t;
      if (s.r < rmin - 1e-9) add("error", "PLG-RADIO", p.ref, `Radio interior ${s.r} mm inferior al mínimo ${g(rmin)} mm para ${p.material}.`,
        `Aumentar RADIO_PLEGADO a ${g(rmin)} mm.`);
      const V = pb.v_dies_mm.find((v) => v >= pb.v_die_factor * s.t) ?? pb.v_dies_mm.at(-1);
      const bmin = V / 2 + s.r + s.t;
      for (const fl of s.flanges) {
        if (fl.height < bmin) add("error", "PLG-ALA-MIN", p.ref, `Pestaña ${fl.edge} de ${fl.height} mm inferior al mínimo ${fx(bmin, 1)} mm (matriz V${V}).`,
          `Aumentar la pestaña a ${Math.ceil(bmin)} mm.`);
        for (const [, h, d] of fl.holes) {
          const clr = h - d / 2 - s.R;
          if (clr < pb.min_hole_to_bend_factor_t * s.t) add("error", "PLG-TALADRO-PLIEGUE", p.ref, `Taladro Ø${d} a ${fx(clr, 1)} mm del pliegue `
            + `(mín. ${fx(pb.min_hole_to_bend_factor_t * s.t, 1)} mm): se deformará al plegar.`, "Alejar el taladro del pliegue o aumentar la pestaña.");
          if (fl.height - h - d / 2 < s.t) add("error", "LAS-TALADRO-BORDE", p.ref, `Taladro Ø${d} demasiado próximo al borde de la pestaña.`);
          const dmin = (las.min_hole_diameter_factor[mat.family] ?? 1.0) * s.t;
          if (d < dmin) add("error", "LAS-TALADRO-DIAM", p.ref, `Taladro Ø${d} menor que el mínimo ${g(dmin)} mm.`);
        }
      }
      for (const L of s.bendLengths()) if (L > pb.max_bend_length_mm) add("error", "PLG-LONGITUD", p.ref,
        `Longitud de pliegue ${fx(L)} mm supera la plegadora (${pb.max_bend_length_mm} mm).`, "Dividir la pieza o usar una plegadora mayor.");
      const [nx] = s.notch;
      if (nx && nx < s.R) add("error", "PLG-ESCOTADURA", p.ref, "Escotadura de esquina menor que el radio exterior de plegado.");
      add("ok", "PLG-ALIVIO", p.ref, "Esquinas abiertas con alivio de plegado ≥ radio exterior.");
    } else if (p.kind === "perfil") {
      if (p.length > barLen - 20) add("error", "PRF-LONGITUD", p.ref, `Longitud ${p.length} mm superior a la barra comercial.`, "Prever empalme soldado o barra de 12 m.");
      if (p.length < 40) add("advertencia", "PRF-CORTA", p.ref, "Pieza muy corta para la sujeción en sierra.");
      for (const [face, , off, d] of p.holes) {
        const flat = (face === "+x" || face === "-x" ? p.profile.H : p.profile.B) - 2 * p.profile.r_out;
        if (d > flat) add("error", "PRF-TALADRO", p.ref, `Taladro Ø${d} mayor que la zona plana del perfil (${fx(flat, 1)} mm).`);
        if (Math.abs(off) + d / 2 > flat / 2 + 1e-6) add("error", "PRF-TALADRO-POS", p.ref, `Taladro Ø${d} fuera de la zona plana del perfil.`);
      }
    } else if (p.kind === "pletina") {
      for (const [, , d] of p.holes) if (d < p.t) add("error", "LAS-TALADRO-DIAM", p.ref, `Taladro Ø${d} menor que el espesor ${p.t} mm.`);
    }
  }
  const seen = new Set();
  for (const j of model.joints) {
    if (j.kind !== "atornillada" || !j.data || !Object.keys(j.data).length) continue;
    const dd = j.data;
    const tray = model.instance(j.members[0]).part;
    const key = JSON.stringify([tray.ref, dd.screw, dd.rivet, dd.wall]);
    if (seen.has(key)) continue;
    seen.add(key);
    const sc = C.component(dd.screw), rnd = C.component(dd.rivet);
    const clamp = dd.t_sheet + dd.gap;
    if (!(dd.rivet_found ?? true)) add("error", "MON-REMACHABLE-AGARRE", tray.ref, `Ninguna tuerca remachable del catálogo admite pared de ${g(dd.wall)} mm.`,
      "Usar un perfil de pared ≤ 5,5 mm o fijación con tornillo pasante.");
    if (!(dd.screw_found ?? true)) add("error", "MON-TORNILLO", tray.ref, `Ningún tornillo ISO 7380 M6 del catálogo da 1·d de rosca útil con `
      + `${g(clamp)} mm de chapa + holgura sin sobrepasar la tuerca remachable.`, "Reducir holgura o espesor, o añadir longitudes de tornillo al catálogo.");
    // taladro de paso: el registrado por la familia (paneles lisos con otros taladros mayores) o el de las pestañas
    const holes = dd.hole ? [] : tray.spec.flanges.flatMap((fl) => fl.holes.map((h) => h[2]));
    const hole = dd.hole || (holes.length ? Math.max(...holes) : sc.clearance_hole);
    if (hole > sc.head_d - 2.0) add("error", "MON-APOYO-CABEZA", tray.ref, `Taladro Ø${g(hole)} demasiado grande para la cabeza Ø${g(sc.head_d)} del tornillo.`,
      "Usar arandela ancha ISO 7093 o tornillo de cabeza mayor.");
    if (rnd.head_h > dd.gap + 1e-9) add("error", "DFM-HOLGURA-REMACHABLE", tray.ref, "La cabeza de la tuerca remachable no cabe en la holgura.");
    add("ok", "MON-TORNILLERIA", tray.ref, `${sc.name} con ${rnd.name.split(",")[0]} (pared ${g(dd.wall)} mm, paquete ${g(clamp)} mm, `
      + `rosca útil ${g(sc.length - clamp)} mm).`);
  }
  const legIds = model.structure.leg_ids ?? [];
  if (legIds.length) {
    const leg = model.instance(legIds[0]).part.profile;
    const nut = Object.values(model.parts).find((p) => p.kind === "normalizado" && p.role === "tuerca_soldar");
    if (nut) {
      const ac = nut.data.s / Math.cos(Math.PI / 6);
      if (ac > leg.B - 2 * leg.t - 1) add("error", "SOL-TUERCA", nut.ref, `La tuerca de soldar (${fx(ac, 1)} mm entre vértices) no cabe en la pata.`);
    }
  }
  const thin = model.joints.filter((j) => j.kind === "soldadura" && j.weld.a < 3);
  if (thin.length) add("advertencia", "SOL-GARGANTA", "Uniones soldadas", `${thin.length} cordones con garganta < 3 mm en pared delgada: requieren WPS `
    + "cualificada y control de penetración.", "Soldar con MAG pulsado, hilo Ø0,8.");
  // compatibilidad de materiales en las uniones soldadas (la tuerca DIN 929 de acero no se suelda a aluminio)
  const weldFamily = (inst) => {
    const p = inst.part;
    if (p.kind === "normalizado") return p.data.material_family ?? "acero_carbono";
    return p.material ? C.material(p.material).family : null;
  };
  const aluSteel = [], dissimilar = [];
  for (const j of model.joints) {
    if (j.kind !== "soldadura") continue;
    const fams = new Set(j.members.map((i) => weldFamily(model.instance(i))).filter((f) => f !== null));
    if (fams.has("aluminio") && fams.size > 1) aluSteel.push(j.id);
    else if (fams.size === 2 && fams.has("acero_carbono") && fams.has("acero_inoxidable")) dissimilar.push(j.id);
  }
  if (aluSteel.length) add("error", "SOL-MATERIALES", "Uniones soldadas", `${aluSteel.length} uniones soldadas entre aluminio y acero `
    + `(p. ej. ${aluSteel[0]}): no son soldables por fusión.`, "Usar el mismo material en las piezas soldadas.");
  if (dissimilar.length) add("advertencia", "SOL-DISIMILAR", "Uniones soldadas", `${dissimilar.length} uniones soldadas entre acero al `
    + `carbono e inoxidable (p. ej. ${dissimilar[0]}): soldadura disimilar con aporte austenítico (tipo 309L) y riesgo de corrosión en ambiente húmedo.`,
    "Usar el mismo material en las piezas soldadas.");
  add("advertencia", "SOL-ENRASE", "Bastidores", "Largueros y travesaños extremos enrasados con la cara exterior de las patas: en la cara enrasada el "
    + "cordón es en ángulo exterior/borde y debe amolarse antes de pintar.");
  add("advertencia", "SOL-DEFORMACION", "Estructura soldada", "Riesgo de distorsión en bastidores de pared delgada: puntear en mesa plana con "
    + "escuadras, soldar en secuencia simétrica alterna y verificar planitud de la superficie de apoyo de la encimera (EN ISO 13920 clase F).");
  // galvanizado en caliente: los tubos cerrados por soldadura necesitan venteo y drenaje (no modelados)
  const galv = [...new Set(model.instances.filter((i) => i.part.kind === "perfil" && i.part.finish === "GALVANIZADO").map((i) => i.part.ref))].sort();
  if (galv.length) add("advertencia", "GAL-VENTEO", "Perfiles huecos", `Galvanizado en caliente (EN ISO 1461) de ${galv.length} perfiles huecos cerrados por `
    + "soldadura: necesitan taladros de venteo y drenaje en los dos extremos de cada tubo (EN ISO 14713-2), que no están modelados. Criterio orientativo: "
    + "Ø ≥ 25 % de la dimensión interior y no menos de 10 mm, en caras opuestas. Las roscas de las tuercas soldadas se repasan después del galvanizado.",
    "Añadir los taladros en los planos de taller antes de fabricar y consultarlos con el galvanizador.");
  if (plan) for (const n of plan.nesting) if (!n.feasible) add("error", "LAS-FORMATO", `Chapa ${n.material} ${n.thickness} mm`, n.reason ?? "",
    "Dividir la pieza en dos o seleccionar un formato mayor.");
  const grouped = new Map();
  for (const x of out) {
    const k = JSON.stringify([x.level, x.code, x.element]);
    if (grouped.has(k)) grouped.get(k).count += 1; else grouped.set(k, { ...x, count: 1 });
  }
  for (const x of grouped.values()) if (x.count > 1) x.message = `${x.message} (${x.count} casos)`;
  return [...grouped.values()];
}

// ============================================================================ BOM
export function buildBom(model, plan) {
  const cnt = counts(model);
  const rows = Object.values(model.parts).sort((a, b) => a.pos - b.pos).map((p) => {
    const dims = p.bomDims();
    const qty = cnt[p.key];
    const um = pyRound(p.mass, 4);
    return { pos: p.pos, ref: p.ref, description: p.name, kind: p.kind, kind_label: KIND_LABEL[p.kind],
      material: p.material || (p.kind === "normalizado" ? p.data.standard : ""), finish: p.finish ? C.finish(p.finish).name : "",
      thickness: dims.espesor ?? null, length: dims.largo ?? null, width: dims.ancho ?? null, section: dims.seccion ?? null, qty, unit_mass: um,
      total_mass: pyRound(um * qty, 4), mass_exact: p.mass * qty, process: (plan.routing[p.ref] ?? []).join(" + "),
      nominal_mass: p.kind === "perfil" ? pyRound(p.nominalMass, 3) : p.kind === "chapa" ? pyRound(p.flat.netArea * p.spec.t * 1e-9 * C.material(p.material).density, 3) : null,
      standard: p.kind === "normalizado" ? p.data.standard : p.kind === "perfil" ? p.profile.standard : null,
      code: p.kind === "normalizado" ? p.code : null, instances: model.instances.filter((i) => i.part.key === p.key).map((i) => i.id) };
  });
  const profM = {}, sheetM2 = {}, std = {};
  const acc = (o, k, v) => { o[k] = (o[k] ?? 0) + v; };
  for (const p of Object.values(model.parts)) {
    const n = cnt[p.key];
    if (p.kind === "perfil") acc(profM, `${p.profile.code} ${p.material}`, (p.length * n) / 1000);
    else if (p.kind === "chapa") acc(sheetM2, `${p.material} e=${g(p.spec.t)} mm`, (p.flat.netArea * n) / 1e6);
    else if (p.kind === "pletina") acc(sheetM2, `${p.material} e=${g(p.t)} mm`, (p.w * p.h * n) / 1e6);
    else acc(std, p.name, n);
  }
  const sortObj = (o, nd) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, nd == null ? o[k] : pyRound(o[k], nd)]));
  const totals = { components: rows.reduce((s, r) => s + r.qty, 0), distinct_parts: rows.length,
    manufactured_parts: rows.filter((r) => r.kind !== "normalizado").reduce((s, r) => s + r.qty, 0),
    standard_parts: rows.filter((r) => r.kind === "normalizado").reduce((s, r) => s + r.qty, 0),
    total_mass: pyRound(rows.reduce((s, r) => s + r.mass_exact, 0), 3), profile_meters: sortObj(profM, 3), sheet_area_m2: sortObj(sheetM2, 4),
    standard_units: sortObj(std, null) };
  const purchases = [];
  for (const c of plan.cutting) purchases.push({ type: "Perfil", description: `Barra ${c.profile} ${c.material} L=${fx(c.bar_length)} mm`, qty: c.n_bars,
    unit: "barra", mass_kg: pyRound(c.n_bars * c.mass_per_bar_kg, 2) });
  for (const n of plan.nesting) {
    if (n.feasible && n.utilization >= 0.10) purchases.push({ type: "Chapa", description: `Chapa ${n.material} e=${g(n.thickness)} mm formato ${n.format}`,
      qty: n.n_sheets, unit: "chapa", mass_kg: pyRound(n.n_sheets * n.mass_per_sheet_kg, 2) });
    else if (n.feasible) {
      const gap = n.spacing + n.kerf;
      const area = (n.sheets.reduce((s, sh) => s + sh.placements.reduce((t, p) => t + (p.w + gap) * (p.h + gap), 0), 0) * 1.15) / 1e6;
      const rho = C.material(n.material).density;
      purchases.push({ type: "Chapa (retal / corte a medida)", description: `Chapa ${n.material} e=${g(n.thickness)} mm — aprovechamiento de formato < 10 %: `
        + "pedir corte a medida o usar retal", qty: pyRound(area, 3), unit: "m²", mass_kg: pyRound(area * n.thickness * 1e-3 * rho, 2) });
    }
  }
  for (const r of rows) if (r.kind === "normalizado") purchases.push({ type: "Comercial", description: `${r.description} (${r.standard})`, qty: r.qty, unit: "ud",
    mass_kg: r.total_mass, code: r.code });
  const w = plan.welding, pnt = plan.painting;
  const consumables = [{ description: w.wire, qty: w.wire_kg, unit: "kg" }, { description: w.gas, qty: w.gas_l, unit: "l" }];
  if (pnt.powder_kg) consumables.push({ description: C.finish(pnt.finish).name, qty: pnt.powder_kg, unit: "kg", basis: `${pnt.area_m2} m² pintados` });
  const remnants = plan.cutting.flatMap((c) => c.bars.map((b) => ({ profile: c.profile, bar: b.bar, length: b.remnant, reusable: b.remnant_reusable })));
  return { rows, totals, purchases, consumables, remnants };
}
