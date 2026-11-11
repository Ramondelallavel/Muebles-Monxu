// @ts-nocheck
// Optimización de corte y anidado, plan de fabricación, DFM y BOM (port de monxu/manufacturing y monxu/docs/bom.py).
import * as C from "./catalog";
import { KIND_LABEL } from "./model";
import { instanceBBox } from "./geometry";
import { f as fx, g, pyRound } from "./util";

const cmpTuple = (a, b) => { for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1; return 0; };

// ============================================================================ 1D
/** Balance físico de una barra: L = despunte inicial + Σ piezas + ancho de sierra + despunte final + retal. */
function barBalance(n, b, kerf, trim, trim_end, reusable_min) {
  const L = b.length;
  const used = b.cuts.reduce((s, c) => s + c.length, 0);
  const npc = b.cuts.length;
  const free = L - trim - trim_end - used - npc * kerf;
  let remnant, kerf_total, n_cuts;
  if (free >= 0) { remnant = free; kerf_total = npc * kerf; n_cuts = 1 + npc; }
  else { const last = kerf + free; remnant = 0.0; kerf_total = (npc - 1) * kerf + Math.max(0.0, last); n_cuts = 1 + npc - (last > 1e-9 ? 0 : 1); }
  const reusable = remnant >= reusable_min;
  const status = reusable ? "reutilizable" : remnant > 1e-9 ? "chatarra" : "sin retal";
  const bal = L - (trim + used + kerf_total + trim_end + remnant);
  return { bar: n, source: b.source ?? "comercial", stock_id: b.stock_id ?? null, length: L, cuts: b.cuts, n_pieces: npc, n_cuts,
    used: pyRound(used, 1), trim_start: trim, trim_end, kerf_total: pyRound(kerf_total, 1), kerf_loss: pyRound(kerf_total + trim + trim_end, 1),
    remnant: pyRound(remnant, 1), remnant_reusable: reusable, remnant_status: status, balance_mm: pyRound(bal, 6) };
}

export function optimizeBars(pieces, bar_length = 6000.0, kerf = 3.0, trim = 10.0, reusable_min = 500.0, trim_end = 0.0, stock = null) {
  let items = [];
  for (const p of pieces) {
    if (p.length + trim + trim_end + kerf > bar_length) throw new Error(`La pieza ${p.ref} (${p.length} mm) supera la longitud de barra ${bar_length} mm`);
    for (let i = 0; i < p.qty; i++) items.push({ ...p });
  }
  items = items.map((p, i) => ({ p, i })).sort((a, b) => b.p.length - a.p.length || a.i - b.i).map((x) => x.p);   // orden estable
  const avail = (stock ?? []).filter((s) => s.length - trim - trim_end > 0).map((s) => ({ ...s }))
    .sort((a, b) => a.length - b.length || (String(a.id) < String(b.id) ? -1 : String(a.id) > String(b.id) ? 1 : 0));
  let bars = [];
  for (const it of items) {
    const need = it.length + kerf;
    let best = null, bestRem = null;
    for (const b of bars) {
      const rem = b.free - need;
      if (rem >= -kerf + 1e-9 && (bestRem === null || rem < bestRem)) { best = b; bestRem = rem; }
    }
    if (!best) {
      const k = avail.findIndex((s) => s.length - trim - trim_end - need >= -kerf + 1e-9);
      if (k >= 0) { const s = avail.splice(k, 1)[0]; best = { cuts: [], free: s.length - trim - trim_end, length: s.length, source: "retal", stock_id: s.id }; }
      else best = { cuts: [], free: bar_length - trim - trim_end, length: bar_length, source: "comercial" };
      bars.push(best);
    }
    best.cuts.push({ ref: it.ref, label: it.label ?? "", length: it.length });
    best.free -= need;
  }
  const cap = bar_length - trim - trim_end + kerf;
  let neu = bars.filter((b) => b.source === "comercial");
  const fromStock = bars.filter((b) => b.source === "retal");
  const newItems = neu.flatMap((b) => b.cuts);
  // cota inferior válida: cada barra admite hasta un ancho de sierra más (la última pieza puede apurarla)
  const lb0 = newItems.length ? Math.ceil(newItems.reduce((s, p) => s + p.length + kerf, 0) / cap - 1e-9) : 0;
  if (neu.length > lb0 && newItems.length <= 60) {
    for (let k = lb0; k < neu.length; k++) {
      const exact = exactPack(newItems, cap, kerf, k);
      if (exact) { neu = exact.map((b) => ({ cuts: b.map((it) => ({ ref: it.ref, label: it.label ?? "", length: it.length })), length: bar_length, source: "comercial" })); break; }
    }
  }
  bars = [...fromStock, ...neu];
  const out = bars.map((b, n) => barBalance(n + 1, b, kerf, trim, trim_end, reusable_min));
  const nb = neu.length;
  const total = items.reduce((s, p) => s + p.length, 0);
  const stockLen = out.filter((b) => b.source === "retal").reduce((s, b) => s + b.length, 0);
  const purchased = nb * bar_length;
  const kerfTot = out.reduce((s, b) => s + b.kerf_total, 0);
  const trims = out.reduce((s, b) => s + (b.trim_start + b.trim_end), 0);
  const reus = out.filter((b) => b.remnant_reusable).reduce((s, b) => s + b.remnant, 0);
  const scrapRem = out.filter((b) => !b.remnant_reusable).reduce((s, b) => s + b.remnant, 0);
  const waste = kerfTot + trims + scrapRem;
  return { bar_length, kerf, trim, trim_start: trim, trim_end, reusable_min, bars: out, n_bars: nb, n_stock_used: fromStock.length,
    stock_used: out.filter((b) => b.source === "retal").map((b) => b.stock_id), lower_bound: lb0, optimal: nb === lb0, pieces: items.length,
    pieces_length: pyRound(total, 1), n_cuts: out.reduce((s, b) => s + b.n_cuts, 0), purchased_length: pyRound(purchased, 1),
    stock_length: pyRound(stockLen, 1), kerf_total: pyRound(kerfTot, 1), trim_total: pyRound(trims, 1), scrap_remnant_length: pyRound(scrapRem, 1),
    reusable_length: pyRound(reus, 1), waste_length: pyRound(waste, 1),
    balance_mm: pyRound(purchased + stockLen - (total + kerfTot + trims + scrapRem + reus), 6),
    utilization: purchased + stockLen ? pyRound(total / (purchased + stockLen), 4) : 0.0,
    reusable_remnants: out.filter((b) => b.remnant_reusable).map((b) => b.remnant), scrap: pyRound(waste, 1) };
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

export function nestSheets(parts, sheet_l, sheet_w, margin = 10.0, spacing = 8.0, kerf = 0.3, stock = null) {
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
  const bins = [], meta = [];
  const st = (stock ?? []).map((s, i) => ({ s, i })).sort((a, b) => a.s.length * a.s.width - b.s.length * b.s.width
    || (String(a.s.id) < String(b.s.id) ? -1 : String(a.s.id) > String(b.s.id) ? 1 : 0) || a.i - b.i).map((x) => x.s);
  for (const s of st) {
    const sw = s.length - 2 * margin + gap, sh = s.width - 2 * margin + gap;
    if (sw > gap && sh > gap) { bins.push(new Bin(sw, sh)); meta.push({ source: "retal", stock_id: s.id, length: s.length, width: s.width }); }
  }
  const put = (b, p, fnd) => {
    b.place(fnd[1]);
    b.used.push({ ref: p.ref, x: fnd[1].x + margin, y: fnd[1].y + margin, rot: fnd[2], w: fnd[2] ? p.h : p.w, h: fnd[2] ? p.w : p.h, area: p.area });
  };
  for (const p of items) {
    let placed = false;
    for (const b of bins) { const fnd = b.find(p.w + gap, p.h + gap, p.rotate ?? true); if (fnd) { put(b, p, fnd); placed = true; break; } }
    if (!placed) {
      const b = new Bin(UW, UH); put(b, p, b.find(p.w + gap, p.h + gap, p.rotate ?? true)); bins.push(b);
      meta.push({ source: "comercial", stock_id: null, length: sheet_l, width: sheet_w });
    }
  }
  const sheets = [];
  let n = 0;
  bins.forEach((b, k) => {
    if (!b.used.length) return;
    n += 1;
    const m = meta[k];
    const used = b.used.reduce((s, u) => s + u.area, 0);
    const ext = [Math.max(...b.used.map((u) => u.x + u.w)), Math.max(...b.used.map((u) => u.y + u.h))];
    sheets.push({ sheet: n, ...m, placements: b.used, parts_area_mm2: pyRound(used, 1), extent: [pyRound(ext[0], 3), pyRound(ext[1], 3)],
      utilization: pyRound(used / (m.length * m.width), 4) });
  });
  const com = sheets.filter((x) => x.source === "comercial");
  const tot = sheets.reduce((s, x) => s + x.parts_area_mm2, 0);
  const sheetArea = sheet_l * sheet_w;
  const allArea = sheets.reduce((s, x) => s + x.length * x.width, 0);
  return { feasible: true, format: `${fx(sheet_l)}x${fx(sheet_w)}`, length: sheet_l, width: sheet_w, margin, spacing, kerf, sheets,
    n_sheets: com.length, n_stock_used: sheets.length - com.length, stock_used: sheets.filter((x) => x.source === "retal").map((x) => x.stock_id),
    parts_area_m2: pyRound(tot / 1e6, 4), sheet_area_m2: pyRound((com.length * sheetArea) / 1e6, 4),
    utilization: sheets.length ? pyRound(tot / allArea, 4) : 0, waste_m2: pyRound((allArea - tot) / 1e6, 4) };
}

export function bestFormat(parts, formats, kw, purchase = null) {
  const results = formats.map((f) => {
    const r = { ...nestSheets(parts, f.length, f.width, kw.margin, kw.spacing, kw.kerf, kw.stock ?? null), format_code: f.code };
    if (r.feasible && purchase) sheetPurchase(r, parts, purchase.min_utilization, purchase.remnant_min, purchase.round_to);
    return r;
  });
  const feasible = results.filter((r) => r.feasible);
  if (!feasible.length) return { feasible: false, alternatives: results, reason: "Ninguna pieza cabe en los formatos comerciales configurados",
    parts_area_m2: pyRound(parts.reduce((s, p) => s + p.area * p.qty, 0) / 1e6, 4) };
  const key = (r) => purchase ? [r.purchase.purchased_area_m2, r.n_sheets] : [r.sheet_area_m2, r.n_sheets];
  let best = feasible[0];
  for (const r of feasible) if (cmpTuple(key(r), key(best)) < 0) best = r;
  return { ...best, alternatives: results.map((r) => ({ format: r.format_code, feasible: r.feasible, n_sheets: r.n_sheets ?? null,
    utilization: r.utilization ?? null, reason: r.reason ?? null, purchased_area_m2: r.purchase?.purchased_area_m2 ?? null })) };
}

function compactBlank(items, L, W, margin, spacing, kerf, roundTo) {
  const lim = Math.max(...items.map((p) => ((p.rotate ?? true) ? Math.min(p.w, p.h) : p.h))) + 2 * margin;
  let best = null;
  for (let i = 0; i < 21; i++) {
    const wc = lim + ((W - lim) * i) / 20;
    const n = nestSheets(items, L, wc, margin, spacing, kerf);
    if (!n.feasible || n.n_sheets !== 1) continue;
    const [ux, uy] = n.sheets[0].extent;
    const bl = Math.min(L, Math.ceil((ux + margin) / roundTo - 1e-9) * roundTo);
    const bw = Math.min(W, Math.ceil((uy + margin) / roundTo - 1e-9) * roundTo);
    if (best === null || bl * bw < best[0] - 1e-6) best = [bl * bw, bl, bw, n.sheets[0]];
  }
  return best;
}

/** Compra real de chapa a partir del anidado (port de optimization.sheet_purchase; modifica ``nest``). */
export function sheetPurchase(nest, parts, min_utilization = 0.10, remnant_min = 300.0, round_to = 10.0) {
  const margin = nest.margin, spacing = nest.spacing;
  const last = nest.sheets.length ? nest.sheets[nest.sheets.length - 1] : null;
  if (last && last.source === "comercial" && last.utilization < min_utilization) {
    const cnt = {};
    for (const u of last.placements) cnt[u.ref] = (cnt[u.ref] ?? 0) + 1;
    const items = parts.filter((p) => p.ref in cnt).map((p) => ({ ...p, qty: cnt[p.ref] }));
    const cb = compactBlank(items, last.length, last.width, margin, spacing, nest.kerf, round_to);
    if (cb) {
      const [, bl, bw, sh] = cb;
      Object.assign(last, { source: "corte_medida", length: bl, width: bw, placements: sh.placements, extent: sh.extent,
        utilization: pyRound(last.parts_area_mm2 / (bl * bw), 4) });
    }
  }
  const lines = [];
  for (const s of nest.sheets) {
    const L = s.length, W = s.width;
    const [ux, uy] = s.extent;
    const mode = s.source === "comercial" ? "formato" : s.source;
    s.mode = mode;
    let rem = null;
    if (mode !== "corte_medida") {
      const cand = [[L - ux - spacing, W, "x", ux + spacing], [L, W - uy - spacing, "y", uy + spacing]].filter((c) => Math.min(c[0], c[1]) >= remnant_min);
      if (cand.length) {
        let c = cand[0];
        for (const x of cand) if (x[0] * x[1] > c[0] * c[1]) c = x;
        rem = { length: pyRound(c[0], 1), width: pyRound(c[1], 1), axis: c[2], at: pyRound(c[3], 1), area_mm2: pyRound(c[0] * c[1], 1) };
      }
    }
    s.remnant = rem;
    lines.push({ sheet: s.sheet, mode, stock_id: s.stock_id ?? null, length: L, width: W, area_mm2: pyRound(L * W, 1), parts_area_mm2: s.parts_area_mm2,
      remnant: rem, utilization: pyRound(s.parts_area_mm2 / (L * W), 4) });
  }
  const purchased = lines.filter((x) => x.mode !== "retal").reduce((t, x) => t + x.area_mm2, 0);
  const stockArea = lines.filter((x) => x.mode === "retal").reduce((t, x) => t + x.area_mm2, 0);
  const partsA = lines.reduce((t, x) => t + x.parts_area_mm2, 0);
  const reus = lines.filter((x) => x.remnant).reduce((t, x) => t + x.remnant.area_mm2, 0);
  const out = { sheets: lines, n_full: lines.filter((x) => x.mode === "formato").length, n_custom: lines.filter((x) => x.mode === "corte_medida").length,
    n_stock: lines.filter((x) => x.mode === "retal").length, purchased_area_m2: pyRound(purchased / 1e6, 6), stock_area_m2: pyRound(stockArea / 1e6, 6),
    parts_area_m2: pyRound(partsA / 1e6, 6), reusable_area_m2: pyRound(reus / 1e6, 6),
    waste_area_m2: pyRound((purchased + stockArea - partsA - reus) / 1e6, 6),
    utilization: purchased + stockArea ? pyRound(partsA / (purchased + stockArea), 4) : 0.0, min_utilization, remnant_min };
  nest.purchase = out;
  nest.utilization = out.utilization;
  nest.waste_m2 = pyRound((purchased + stockArea - partsA) / 1e6, 4);
  return out;
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

/** Lote de fabricación del proyecto: el plan de corte, el anidado y la lista de compras cubren el lote completo. */
export const lotSize = (model) => Math.max(1, Math.trunc(+(model.params.values.LOTE_FABRICACION || 1)));

export function cuttingParams(model) {
  const cm = C.profileMeta().cutting ?? {};
  return { bar_length: barLength(model), kerf: +(model.params.values.CORTE_SIERRA || 3.0), trim: +(cm.trim_start_mm ?? 10.0),
    trim_end: +(cm.trim_end_mm ?? 0.0), reusable_min: +(cm.reusable_min_mm ?? 500.0) };
}

const stockFor = (stock, kind, key) => (stock ?? []).filter((s) => s.kind === kind && Object.entries(key).every(([k, v]) => s[k] === v)
  && (s.status ?? "disponible") === "disponible");

/** Plan de corte, anidado y balance de material de ``lot`` unidades, con los retales compatibles del inventario. */
export function materialPurchase(model, lot = 1, stock = null) {
  const cnt = counts(model);
  const sd = C.sheetData();
  const cp = cuttingParams(model);
  const groups = new Map();
  for (const [k, p] of Object.entries(model.parts)) if (p.kind === "perfil") {
    const key = JSON.stringify([p.profile.code, p.material]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ ref: p.ref, label: p.name, length: p.length, qty: cnt[k] * lot });
  }
  const cutting = [...groups.entries()].sort((a, b) => cmpTuple(JSON.parse(a[0]), JSON.parse(b[0]))).map(([key, pieces]) => {
    const [code, mat] = JSON.parse(key);
    const st = stockFor(stock, "barra", { profile: code, material: mat }).map((s) => ({ id: s.id, length: s.length }));
    const r = optimizeBars(pieces, cp.bar_length, cp.kerf, cp.trim, cp.reusable_min, cp.trim_end, st);
    const kgm = C.profile(code).massPerM(C.material(mat).density);
    return { ...r, profile: code, material: mat, kg_per_m: pyRound(kgm, 4), mass_per_bar_kg: pyRound((kgm * cp.bar_length) / 1000, 2) };
  });
  const sg = new Map();
  const push = (mat, t, item) => { const key = JSON.stringify([mat, t]); if (!sg.has(key)) sg.set(key, []); sg.get(key).push(item); };
  for (const [k, p] of Object.entries(model.parts)) {
    if (p.kind === "chapa") push(p.material, p.spec.t, { ref: p.ref, w: p.flat.width, h: p.flat.height, qty: cnt[k] * lot, area: p.flat.netArea,
      rotate: p.finish !== "INOX_SATINADO", kind: "chapa" });
    else if (p.kind === "pletina") push(p.material, p.t, { ref: p.ref, w: p.w, h: p.h, qty: cnt[k] * lot, area: plateArea(p), rotate: true, kind: "pletina" });
  }
  const las = sd.laser, pur = sd.purchase ?? {};
  const fmt = model.params.values.FORMATO_CHAPA;
  const fixedFmt = C.sheetFormats().filter((f) => f.code === fmt), formats = fixedFmt.length ? fixedFmt : C.sheetFormats();
  const nesting = [...sg.entries()].sort((a, b) => cmpTuple(JSON.parse(a[0]), JSON.parse(b[0]))).map(([key, parts]) => {
    const [mat, t] = JSON.parse(key);
    const st = stockFor(stock, "chapa", { material: mat, thickness: t }).map((s) => ({ id: s.id, length: s.length, width: s.width }));
    const r = bestFormat(parts, formats, { margin: las.sheet_margin_mm, spacing: las.part_spacing_mm, kerf: las.kerf_mm, stock: st },
      { min_utilization: pur.custom_cut_min_utilization ?? 0.10, remnant_min: pur.remnant_min_mm ?? 300.0, round_to: pur.custom_cut_round_mm ?? 10.0 });
    const rho = C.material(mat).density;
    return { ...r, material: mat, thickness: t, kg_per_m2: pyRound(t * 1e-3 * rho, 4),
      mass_per_sheet_kg: r.feasible ? pyRound((r.length ?? 0) * (r.width ?? 0) * t * 1e-9 * rho, 2) : null };
  });
  return { lot, cutting, nesting, balance: materialBalance(cutting, nesting), cutting_params: cp };
}

const BAL_KEYS = ["purchased_kg", "from_stock_kg", "net_kg", "waste_kg", "reusable_kg"];
/** Balance de material: comprado + retales de inventario = neto en piezas + desperdicio + retales reutilizables. */
export function materialBalance(cutting, nesting) {
  const rows = [];
  for (const c of cutting) {
    const k = c.kg_per_m / 1000;
    rows.push({ kind: "perfil", group: `${c.profile} ${c.material}`, unit: "mm", purchased: c.purchased_length, from_stock: c.stock_length,
      net: c.pieces_length, waste: c.waste_length, reusable: c.reusable_length, purchased_kg: c.purchased_length * k, from_stock_kg: c.stock_length * k,
      net_kg: c.pieces_length * k, waste_kg: c.waste_length * k, reusable_kg: c.reusable_length * k, balance: c.balance_mm });
  }
  for (const n of nesting) {
    const grp = `${n.material} e=${g(n.thickness)} mm`;
    if (!n.feasible) {
      rows.push({ kind: "chapa", group: grp, unit: "m2", purchased: null, from_stock: 0.0, net: n.parts_area_m2, waste: null, reusable: 0.0,
        purchased_kg: null, from_stock_kg: 0.0, net_kg: null, waste_kg: null, reusable_kg: 0.0, balance: null, infeasible: true });
      continue;
    }
    const pu = n.purchase, k = n.kg_per_m2;
    rows.push({ kind: "chapa", group: grp, unit: "m2", purchased: pu.purchased_area_m2, from_stock: pu.stock_area_m2, net: pu.parts_area_m2,
      waste: pu.waste_area_m2, reusable: pu.reusable_area_m2, purchased_kg: pu.purchased_area_m2 * k, from_stock_kg: pu.stock_area_m2 * k,
      net_kg: pu.parts_area_m2 * k, waste_kg: pu.waste_area_m2 * k, reusable_kg: pu.reusable_area_m2 * k,
      balance: pyRound(pu.purchased_area_m2 + pu.stock_area_m2 - pu.parts_area_m2 - pu.waste_area_m2 - pu.reusable_area_m2, 6) });
  }
  const totals = {};
  for (const key of BAL_KEYS) totals[key] = pyRound(rows.reduce((t, r) => t + (r[key] ?? 0.0), 0), 3);
  for (const r of rows) for (const key of BAL_KEYS) if (r[key] !== null) r[key] = pyRound(r[key], 3);
  return { rows, totals };
}

/** Norma del componente comercial, o la indicación de que no hay norma de producto aplicable. */
export const stdLabel = (c) => c.standard || "sin norma de producto, según fabricante";

/** Lista de compras del lote: barras y chapas del plan de corte y del anidado, componentes del modelo y consumibles. */
export function purchases(model, mp, welding, painting) {
  const lot = mp.lot;
  const out = [];
  for (const c of mp.cutting) {
    if (c.n_bars) out.push({ type: "Perfil", description: `Barra ${c.profile} ${c.material} L=${fx(c.bar_length)} mm`, qty: c.n_bars, unit: "barra",
      mass_kg: pyRound((c.purchased_length * c.kg_per_m) / 1000, 2), basis: "plan de corte", group: `${c.profile} ${c.material}` });
    if (c.n_stock_used) out.push({ type: "Perfil (retal de inventario)", description: `Retales ${c.profile} ${c.material}: ` + c.stock_used.map(String).join(", "),
      qty: c.n_stock_used, unit: "retal", mass_kg: pyRound((c.stock_length * c.kg_per_m) / 1000, 2), basis: "inventario de retales",
      group: `${c.profile} ${c.material}`, purchase: false });
  }
  for (const n of mp.nesting) {
    const grp = `${n.material} e=${g(n.thickness)} mm`;
    if (!n.feasible) {
      out.push({ type: "Chapa", description: `Chapa ${n.material} e=${g(n.thickness)} mm — sin formato comercial válido (pieza mayor que los formatos)`,
        qty: null, unit: "chapa", mass_kg: null, basis: "anidado", group: grp, blocking: true });
      continue;
    }
    const pu = n.purchase;
    if (pu.n_full) out.push({ type: "Chapa", description: `Chapa ${n.material} e=${g(n.thickness)} mm formato ${n.format}`, qty: pu.n_full, unit: "chapa",
      mass_kg: pyRound(pu.n_full * n.length * n.width * 1e-6 * n.kg_per_m2, 2), basis: "anidado", group: grp });
    for (const x of pu.sheets) {
      if (x.mode === "corte_medida") out.push({ type: "Chapa (corte a medida)", description: `Chapa ${n.material} e=${g(n.thickness)} mm cortada a medida `
        + `${fx(x.length)}x${fx(x.width)} mm (hoja ${x.sheet} del anidado)`, qty: 1, unit: "ud", mass_kg: pyRound(x.area_mm2 * 1e-6 * n.kg_per_m2, 2),
        basis: "anidado", group: grp });
      else if (x.mode === "retal") out.push({ type: "Chapa (retal de inventario)", description: `Retal ${x.stock_id} ${n.material} e=${g(n.thickness)} mm `
        + `${fx(x.length)}x${fx(x.width)} mm`, qty: 1, unit: "retal", mass_kg: pyRound(x.area_mm2 * 1e-6 * n.kg_per_m2, 2), basis: "inventario de retales",
        group: grp, purchase: false });
    }
  }
  const std = {};
  for (const i of model.instances) if (i.part.kind === "normalizado") std[i.part.code] = (std[i.part.code] ?? 0) + 1;
  for (const code of Object.keys(std).sort()) {
    const c = C.component(code);
    out.push({ type: "Comercial", description: `${c.name} (${stdLabel(c)})`, qty: std[code] * lot, unit: "ud", mass_kg: pyRound(c.mass_kg * std[code] * lot, 4),
      code, ref: `N-${code}`, basis: "BOM", validation: c.validation?.status ?? "pendiente_validacion" });
  }
  const consumables = welding.joints ? [
    { description: welding.wire, qty: pyRound(welding.wire_kg * lot, 3), unit: "kg", basis: "cordones del modelo" },
    { description: welding.gas, qty: pyRound(welding.gas_l * lot, 1), unit: "l", basis: "tiempo de arco" }] : [];
  if (painting.powder_kg) consumables.push({ description: C.finish(painting.finish).name, qty: pyRound(painting.powder_kg * lot, 3), unit: "kg",
    basis: `${painting.area_m2} m² pintados por unidad` });
  const remnants = [];
  for (const c of mp.cutting) for (const b of c.bars) if (b.remnant > 0) remnants.push({ kind: "barra", profile: c.profile, material: c.material, bar: b.bar,
    length: b.remnant, reusable: b.remnant_reusable, status: b.remnant_status });
  for (const n of mp.nesting) for (const x of n.purchase?.sheets ?? []) if (x.remnant) remnants.push({ kind: "chapa", material: n.material, thickness: n.thickness,
    sheet: x.sheet, length: x.remnant.length, width: x.remnant.width, reusable: true, status: "reutilizable" });
  return { lot, items: out, consumables, remnants };
}

export function manufacturingPlan(model, stock = null) {
  const cnt = counts(model);
  const lot = lotSize(model);
  const mp = materialPurchase(model, lot, stock);
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
  const welding = { joints: welds.length, total_length_mm: pyRound(weldLen, 1), deposit_kg: pyRound(deposit, 3), wire_kg: pyRound(wireKg, 3),
    arc_time_h: pyRound(arcH, 3), gas_l: pyRound(gasL, 1), wire: wire.name, gas: gas.name };
  const painting = { area_m2: pyRound(painted / 1e6, 3), powder_kg: pyRound(paintKg, 3), finish: fin };
  return { lot, cutting: mp.cutting, nesting: mp.nesting, balance: mp.balance, cutting_params: mp.cutting_params, welding, painting,
    purchases: purchases(model, mp, welding, painting), stock_offered: (stock ?? []).length,
    routing: Object.fromEntries(Object.values(model.parts).map((p) => [p.ref, routing(p)])) };
}

// ============================================================================ DFM
/** Posición de las caras laterales de cada barra soldada a tope sobre otra, desde la geometría (= plan.weld_face_conditions):
 *  flush = una cara enrasada con la de la barra de apoyo; corner = una cara a menos del radio de esquina, sin enrasar. */
export function weldFaceConditions(model, tol = 0.05) {
  let flush = 0, corner = 0, dmin = null, rmin = null;
  const axisOf = (i) => { let m = 0; for (let k = 1; k < 3; k++) if (Math.abs(i.axis[1][k] - i.axis[0][k]) > Math.abs(i.axis[1][m] - i.axis[0][m])) m = k; return m; };
  for (const j of model.joints) {
    const fem = j.kind === "soldadura" ? j.weld?.fem : null;
    if (!fem) continue;
    const a = model.instance(fem.member), b = model.instance(fem.onto);
    if (a.part.kind !== "perfil" || b.part.kind !== "perfil") continue;
    const [alo, ahi] = instanceBBox(a), [blo, bhi] = instanceBBox(b);
    const r = b.part.profile.r_out, axA = axisOf(a), axB = axisOf(b);
    let state = null, dC = null;
    for (let k = 0; k < 3; k++) {
      if (k === axA || k === axB || !(alo[k] >= blo[k] - tol && ahi[k] <= bhi[k] + tol)) continue;
      const d = Math.min(alo[k] - blo[k], bhi[k] - ahi[k]);
      if (d <= tol) state = "flush";
      else if (d < r - tol && state !== "flush") { state = "corner"; dC = dC === null ? d : Math.min(dC, d); }
    }
    if (state === "flush") flush++;
    else if (state === "corner") { corner++; if (dmin === null || dC < dmin) { dmin = dC; rmin = r; } }
  }
  return { flush, corner, corner_min: dmin === null ? null : pyRound(dmin, 2), corner_r: rmin === null ? null : pyRound(rmin, 2) };
}
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
    // compatibilidad tornillo – tuerca remachable – pared (datos de la base de componentes)
    if (sc.thread !== rnd.thread) add("error", "MON-ROSCA", tray.ref, `Rosca del tornillo ${sc.thread} distinta de la de la tuerca remachable ${rnd.thread}.`,
      "Usar tornillo y tuerca de la misma métrica.");
    const engaged = sc.length - clamp, need = Math.min(sc.d, rnd.thread_len ?? sc.d);
    if (engaged < need - 1e-9) add("error", "MON-ROSCA-UTIL", tray.ref, `Rosca útil ${g(engaged)} mm menor que la mínima ${g(need)} mm en la tuerca remachable.`,
      "Usar un tornillo más largo.");
    if (sc.length > clamp + rnd.body_l + 1e-9) add("error", "MON-PROFUNDIDAD", tray.ref, `El tornillo (${g(sc.length)} mm) sobrepasa el cuerpo de la tuerca remachable `
      + `(${g(clamp + rnd.body_l)} mm desde la cabeza).`, "Usar un tornillo más corto.");
    const tq = [sc.tightening_torque_Nm, rnd.max_torque_Nm].filter((v) => v !== undefined && v !== null);
    const pend = rnd.validation?.status !== "definido_por_norma";
    add("ok", "MON-TORNILLERIA", tray.ref, `${sc.name} con ${rnd.name.split(",")[0]} (pared ${g(dd.wall)} mm, paquete ${g(clamp)} mm, `
      + `rosca útil ${g(engaged)} mm, par ${g(Math.min(...tq))} N·m${pend ? " orientativo" : ""}, ${sc.tool ?? "herramienta según ficha"}).`);
  }
  const legIds = model.structure.leg_ids ?? [];
  if (legIds.length && (model.structure.nuts_inside_legs ?? true)) {     // tuerca dentro del tubo de la pata
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
  // advertencias de soldeo propias de la familia o, por defecto, las de los bastidores con encimera
  // caras enrasadas o dentro del radio de esquina de la barra de apoyo: siempre desde la geometría (no supuesto)
  const wf = weldFaceConditions(model);
  if (wf.flush) add("advertencia", "SOL-ENRASE", "Uniones soldadas", `${wf.flush} uniones con una cara enrasada con la de la barra a la que se sueldan `
    + "(misma cara exterior o mismo canto): en esa cara el cordón cae sobre el radio de esquina (ángulo exterior o borde).",
  "Amolar esos cordones donde apoye una chapa y antes de pintar.");
  if (wf.corner) add("advertencia", "SOL-RADIO-ESQUINA", "Uniones soldadas", `${wf.corner} uniones con una cara lateral a ${g(wf.corner_min)} mm de la cara de la barra de apoyo, `
    + `dentro de su radio de esquina (${g(wf.corner_r)} mm): en ese lado el cordón es en bisel abocinado sobre el radio, con garganta efectiva reducida.`,
  "Recogerlo en la WPS o separar la barra de la cara al menos el radio de esquina.");
  const weldNotes = model.structure.dfm_weld_notes ?? [["SOL-DEFORMACION", "Estructura soldada", "Riesgo de distorsión en bastidores de pared delgada: puntear en mesa plana "
    + "con escuadras, soldar en secuencia simétrica alterna y verificar la planitud de las superficies de apoyo de las chapas (EN ISO 13920 clase F)."]];
  for (const [code, elem, msg] of weldNotes) add("advertencia", code, elem, msg);
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
    const std = p.kind === "normalizado";
    return { pos: p.pos, ref: p.ref, description: p.name, kind: p.kind, kind_label: KIND_LABEL[p.kind],
      material: p.material || (std ? p.data.material || "" : ""), finish: p.finish ? C.finish(p.finish).name : "",
      thickness: dims.espesor ?? null, length: dims.largo ?? null, width: dims.ancho ?? null, section: dims.seccion ?? null, qty, unit_mass: um,
      total_mass: pyRound(um * qty, 4), mass_exact: p.mass * qty, process: (plan.routing[p.ref] ?? []).join(" + "),
      nominal_mass: p.kind === "perfil" ? pyRound(p.nominalMass, 3) : p.kind === "chapa" ? pyRound(p.flat.netArea * p.spec.t * 1e-9 * C.material(p.material).density, 3) : null,
      standard: std ? stdLabel(p.data) : p.kind === "perfil" ? p.profile.standard : null,
      validation: std ? (p.data.validation?.status ?? "pendiente_validacion") : null,
      code: std ? p.code : null, instances: model.instances.filter((i) => i.part.key === p.key).map((i) => i.id) };
  });
  const profM = {}, sheetM2 = {}, stdU = {};
  const acc = (o, k, v) => { o[k] = (o[k] ?? 0) + v; };
  for (const p of Object.values(model.parts)) {
    const n = cnt[p.key];
    if (p.kind === "perfil") acc(profM, `${p.profile.code} ${p.material}`, (p.length * n) / 1000);
    else if (p.kind === "chapa") acc(sheetM2, `${p.material} e=${g(p.spec.t)} mm`, (p.flat.netArea * n) / 1e6);
    else if (p.kind === "pletina") acc(sheetM2, `${p.material} e=${g(p.t)} mm`, (plateArea(p) * n) / 1e6);
    else acc(stdU, p.name, n);
  }
  const sortObj = (o, nd) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, nd == null ? o[k] : pyRound(o[k], nd)]));
  const man = rows.filter((r) => r.kind !== "normalizado").reduce((t, r) => t + r.mass_exact, 0);
  const com = rows.filter((r) => r.kind === "normalizado").reduce((t, r) => t + r.mass_exact, 0);
  const bal = plan.balance.totals;
  const lot = plan.lot ?? 1;
  const totals = { components: rows.reduce((s, r) => s + r.qty, 0), distinct_parts: rows.length,
    manufactured_parts: rows.filter((r) => r.kind !== "normalizado").reduce((s, r) => s + r.qty, 0),
    standard_parts: rows.filter((r) => r.kind === "normalizado").reduce((s, r) => s + r.qty, 0),
    total_mass: pyRound(man + com, 3), mass_manufactured_kg: pyRound(man, 3), mass_commercial_kg: pyRound(com, 3), mass_product_kg: pyRound(man + com, 3),
    material_lot: lot, mass_purchased_kg: bal.purchased_kg, mass_from_stock_kg: bal.from_stock_kg, mass_raw_net_kg: bal.net_kg,
    mass_waste_kg: bal.waste_kg, mass_reusable_kg: bal.reusable_kg,
    profile_meters: sortObj(profM, 3), sheet_area_m2: sortObj(sheetM2, 4), standard_units: sortObj(stdU, null) };
  const pu = plan.purchases;
  return { rows, totals, purchases: pu.items.map((it) => ({ ...it })), consumables: pu.consumables, remnants: pu.remnants, lot };
}
