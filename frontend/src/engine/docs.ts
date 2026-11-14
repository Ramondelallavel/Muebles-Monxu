// @ts-nocheck
// Documentación de fabricación generada en el navegador: DXF (R12, mm, capas de corte/plegado), CSV, SVG de
// desarrollos y anidados, STL de la malla, informe HTML y expediente ZIP con manifiesto SHA-256.
import * as C from "./catalog";
import { partGeometry } from "./geometry";
import { deflate } from "./pdf";
import { f as fx, g } from "./util";

// ============================================================================ DXF R12
const LAYERS = { CORTE_EXTERIOR: [7, "CONTINUOUS"], CORTE_INTERIOR: [1, "CONTINUOUS"], PLEGADO_ABAJO: [3, "DASHDOT"],
  PLEGADO_ARRIBA: [4, "DASHDOT"], GRABADO: [2, "CONTINUOUS"], INFO: [8, "CONTINUOUS"], FORMATO: [9, "CONTINUOUS"],
  RETAL: [5, "DASHED"] };
const n6 = (v) => (Math.abs(v) < 5e-7 ? "0.0" : (+v.toFixed(6)).toString());

class DXF {
  constructor() { this.e = []; this.lo = [Infinity, Infinity]; this.hi = [-Infinity, -Infinity]; this.cut = { lo: [Infinity, Infinity], hi: [-Infinity, -Infinity] }; }
  _ext(x, y, layer) {
    this.lo = [Math.min(this.lo[0], x), Math.min(this.lo[1], y)]; this.hi = [Math.max(this.hi[0], x), Math.max(this.hi[1], y)];
    if (layer.startsWith("CORTE")) { this.cut.lo = [Math.min(this.cut.lo[0], x), Math.min(this.cut.lo[1], y)]; this.cut.hi = [Math.max(this.cut.hi[0], x), Math.max(this.cut.hi[1], y)]; }
  }
  /** pts: [x, y, bulge?] */
  poly(pts, layer, closed = true) {
    this.e.push("0", "POLYLINE", "8", layer, "66", "1", "10", "0.0", "20", "0.0", "30", "0.0", "70", closed ? "1" : "0");
    for (const [x, y, b] of pts) {
      this.e.push("0", "VERTEX", "8", layer, "10", n6(x), "20", n6(y), "30", "0.0");
      if (b) this.e.push("42", n6(b));
      this._ext(x, y, layer);
    }
    this.e.push("0", "SEQEND", "8", layer);
  }
  circle(x, y, r, layer) { this.e.push("0", "CIRCLE", "8", layer, "10", n6(x), "20", n6(y), "30", "0.0", "40", n6(r)); this._ext(x - r, y - r, layer); this._ext(x + r, y + r, layer); }
  line(p, q, layer) { this.e.push("0", "LINE", "8", layer, "10", n6(p[0]), "20", n6(p[1]), "30", "0.0", "11", n6(q[0]), "21", n6(q[1]), "31", "0.0"); }
  text(x, y, h, s, layer, rot = 0, center = false) {
    const t = String(s).replace(/[\r\n]+/g, " ");
    this.e.push("0", "TEXT", "8", layer, "10", n6(x), "20", n6(y), "30", "0.0", "40", n6(h), "1", t);
    if (rot) this.e.push("50", n6(rot));
    if (center) this.e.push("72", "1", "73", "2", "11", n6(x), "21", n6(y), "31", "0.0");
  }
  toString() {
    const H = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4", "9", "$MEASUREMENT", "70", "1",
      "9", "$EXTMIN", "10", n6(this.lo[0]), "20", n6(this.lo[1]), "30", "0.0", "9", "$EXTMAX", "10", n6(this.hi[0]), "20", n6(this.hi[1]), "30", "0.0", "0", "ENDSEC"];
    const T = ["0", "SECTION", "2", "TABLES",
      "0", "TABLE", "2", "LTYPE", "70", "3",
      "0", "LTYPE", "2", "CONTINUOUS", "70", "0", "3", "Solid line", "72", "65", "73", "0", "40", "0.0",
      "0", "LTYPE", "2", "DASHDOT", "70", "0", "3", "Dash dot __ . __ . __", "72", "65", "73", "4", "40", "25.4", "49", "12.7", "49", "-6.35", "49", "0.0", "49", "-6.35",
      "0", "LTYPE", "2", "DASHED", "70", "0", "3", "Dashed __ __ __", "72", "65", "73", "2", "40", "19.05", "49", "12.7", "49", "-6.35",
      "0", "ENDTAB",
      "0", "TABLE", "2", "LAYER", "70", String(Object.keys(LAYERS).length + 1),
      "0", "LAYER", "2", "0", "70", "0", "62", "7", "6", "CONTINUOUS",
      ...Object.entries(LAYERS).flatMap(([n, [c, lt]]) => ["0", "LAYER", "2", n, "70", "0", "62", String(c), "6", lt]),
      "0", "ENDTAB", "0", "ENDSEC"];
    return [...H, ...T, "0", "SECTION", "2", "ENTITIES", ...this.e, "0", "ENDSEC", "0", "EOF"].join("\r\n") + "\r\n";
  }
}

function addPart(dx, part, tr = [0, 0, false], label = null, info = true) {
  // tr = [dx, dy, rot90]: x' = H - y, y' = x (giro de 90° como en el servidor)
  let w, h, refH;
  const T = (x, y) => { let X = x, Y = y; if (tr[2]) { X = refH - y; Y = x; } return [X + tr[0], Y + tr[1]]; };
  if (part.kind === "chapa") {
    const fp = part.flat.normalized();
    refH = fp.height;
    dx.poly(fp.outline.map(([x, y]) => T(x, y)), "CORTE_EXTERIOR");
    for (const ho of fp.holes) {
      const [cx, cy] = T(ho.x, ho.y);
      if (ho.kind === "round") dx.circle(cx, cy, ho.d / 2, "CORTE_INTERIOR");
      else { const [ww, hh] = tr[2] ? [ho.h, ho.w] : [ho.w, ho.h]; dx.poly([[cx - ww / 2, cy - hh / 2], [cx + ww / 2, cy - hh / 2], [cx + ww / 2, cy + hh / 2], [cx - ww / 2, cy + hh / 2]], "CORTE_INTERIOR"); }
    }
    for (const b of fp.bends) {
      const p0 = T(...b.p0), p1 = T(...b.p1);
      dx.line(p0, p1, b.direction === "ABAJO" ? "PLEGADO_ABAJO" : "PLEGADO_ARRIBA");
      if (info) {
        let ang = (Math.atan2(p1[1] - p0[1], p1[0] - p0[0]) * 180) / Math.PI;
        if (ang > 90 || ang < -90) ang += 180;
        dx.text((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, 4, `${b.direction} 90° Ri${g(b.radius)}`, "INFO", ang);
      }
    }
    [w, h] = tr[2] ? [fp.height, fp.width] : [fp.width, fp.height];
  } else if (part.kind === "pletina") {
    refH = part.h;
    const r = part.corner_r, W = part.w, Hh = part.h, b = Math.tan(Math.PI / 8);
    const pts = r > 0 ? [[r, 0, 0], [W - r, 0, b], [W, r, 0], [W, Hh - r, b], [W - r, Hh, 0], [r, Hh, b], [0, Hh - r, 0], [0, r, b]] : [[0, 0, 0], [W, 0, 0], [W, Hh, 0], [0, Hh, 0]];
    dx.poly(pts.map(([x, y, bb]) => [...T(x, y), bb]), "CORTE_EXTERIOR");
    for (const [x, y, d] of part.holes) { const [cx, cy] = T(x, y); dx.circle(cx, cy, d / 2, "CORTE_INTERIOR"); }
    [w, h] = tr[2] ? [part.h, part.w] : [part.w, part.h];
  } else throw new Error("Sólo piezas de chapa y pletinas generan DXF de corte");
  if (label) dx.text(tr[0] + w / 2, tr[1] + h / 2, Math.max(3.0, Math.min(8.0, Math.min(w, h) / 12)), label, "GRABADO", 0, true);
  return [w, h];
}

export function partDxf(part, project = null) {
  const dx = new DXF();
  addPart(dx, part, [0, 0, false], part.ref);
  const t = part.kind === "chapa" ? part.spec.t : part.t;
  let note = `${part.ref} | ${part.name} | ${part.material} e=${g(t)} mm | Escala 1:1 | mm`;
  if (project) note += ` | ${project.code ?? ""} Rev.${project.revision ?? ""}`;
  dx.text(0, -15, 4, note, "INFO");
  const cutW = dx.cut.hi[0] - dx.cut.lo[0], cutH = dx.cut.hi[1] - dx.cut.lo[1];
  return { text: dx.toString(), width: Math.round(cutW * 1000) / 1000, height: Math.round(cutH * 1000) / 1000 };
}
/** Rótulo de la chapa comprada: formato comercial, corte a medida o retal del inventario. */
export function sheetLabel(nest, sh) {
  const mode = sh.mode ?? (sh.source === "comercial" || !sh.source ? "formato" : sh.source);
  const L = sh.length ?? nest.length, W = sh.width ?? nest.width;
  if (mode === "corte_medida") return `corte a medida ${fx(L)}x${fx(W)}`;
  if (mode === "retal") return `retal ${sh.stock_id} ${fx(L)}x${fx(W)}`;
  return `formato ${nest.format}`;
}
export function nestingDxf(nest, partsByRef) {
  const total = nest.sheets.length;
  return nest.sheets.map((sh) => {
    const dx = new DXF();
    const L = sh.length ?? nest.length, W = sh.width ?? nest.width;
    dx.poly([[0, 0], [L, 0], [L, W], [0, W]], "FORMATO");
    for (const pl of sh.placements) addPart(dx, partsByRef[pl.ref], [pl.x, pl.y, pl.rot], pl.ref, false);
    const rem = sh.remnant;
    if (rem) {
      const [x0, y0] = rem.axis === "x" ? [rem.at, 0.0] : [0.0, rem.at];
      dx.poly([[x0, y0], [x0 + rem.length, y0], [x0 + rem.length, y0 + rem.width], [x0, y0 + rem.width]], "RETAL");
    }
    dx.text(0, -25, 10, `Chapa ${nest.material} e=${g(nest.thickness)} mm  ${sheetLabel(nest, sh)}  hoja ${sh.sheet}/${total}  aprovechamiento ${(sh.utilization * 100).toFixed(1)} %`, "INFO");
    return { sheet: sh.sheet, text: dx.toString() };
  });
}

// ============================================================================ SVG
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const svgDoc = (w, h, body) => `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${fx(w, 1)} ${fx(h, 1)}" width="${fx(w / 2, 1)}mm" height="${fx(h / 2, 1)}mm" font-family="Arial, sans-serif">\n<rect width="100%" height="100%" fill="#fff"/>\n${body}\n</svg>\n`;

/** Plano de desarrollo de una pieza de chapa: contorno, taladros, líneas de plegado y cotas generales. */
export function flatSvg(part, info) {
  const fp = part.flat.normalized();
  const m = 60, W = fp.width + 2 * m + 40, H = fp.height + 2 * m + 70;
  const Y = (y) => m + fp.height - y;
  const X = (x) => m + x;
  const out = [];
  out.push(`<path d="M ${fp.outline.map(([x, y]) => `${X(x).toFixed(2)} ${Y(y).toFixed(2)}`).join(" L ")} Z" fill="#f1f4f7" stroke="#111" stroke-width="1.2"/>`);
  for (const ho of fp.holes) out.push(ho.kind === "round" ? `<circle cx="${X(ho.x).toFixed(2)}" cy="${Y(ho.y).toFixed(2)}" r="${(ho.d / 2).toFixed(2)}" fill="#fff" stroke="#c1121f" stroke-width="0.8"/>`
    : `<rect x="${X(ho.x - ho.w / 2).toFixed(2)}" y="${Y(ho.y + ho.h / 2).toFixed(2)}" width="${ho.w}" height="${ho.h}" fill="#fff" stroke="#c1121f" stroke-width="0.8"/>`);
  for (const b of fp.bends) out.push(`<line x1="${X(b.p0[0]).toFixed(2)}" y1="${Y(b.p0[1]).toFixed(2)}" x2="${X(b.p1[0]).toFixed(2)}" y2="${Y(b.p1[1]).toFixed(2)}" stroke="#2a9d8f" stroke-width="1" stroke-dasharray="14 4 2 4"/>`);
  const dim = (x0, y0, x1, y1, txt, horiz) => {
    const s = `stroke="#333" stroke-width="0.6"`;
    if (horiz) return `<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" ${s} marker-start="url(#a)" marker-end="url(#a)"/><text x="${(x0 + x1) / 2}" y="${y0 - 6}" font-size="16" text-anchor="middle">${txt}</text>`;
    return `<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" ${s} marker-start="url(#a)" marker-end="url(#a)"/><text x="${x0 - 8}" y="${(y0 + y1) / 2}" font-size="16" text-anchor="middle" transform="rotate(-90 ${x0 - 8} ${(y0 + y1) / 2})">${txt}</text>`;
  };
  out.push(`<defs><marker id="a" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 2 L10 5 L0 8 z" fill="#333"/></marker></defs>`);
  out.push(dim(X(0), m - 25, X(fp.width), m - 25, fx(fp.width, 2).replace(".", ","), true));
  out.push(dim(m - 25, Y(fp.height), m - 25, Y(0), fx(fp.height, 2).replace(".", ","), false));
  const s = part.spec;
  const txt = [`${part.ref} · ${part.name}`, `${part.material} e=${g(s.t)} mm · Ri ${g(s.r)} mm · K ${g(s.K)} · deducción 90° ${fx(s.BD, 3)} mm`,
    `Desarrollo ${fx(fp.width, 2)} × ${fx(fp.height, 2)} mm · ${fp.bends.length} pliegues · ${fp.holes.length} taladros · corte ${fx(fp.cutLength / 1000, 2)} m`,
    `${info.project ?? ""} ${info.revision ? "Rev. " + info.revision : ""} · Escala 1:1 en el DXF · Tolerancias ${info.tolerances ?? "ISO 2768-mK"} · ${info.stamp ?? ""}`];
  txt.forEach((t, i) => out.push(`<text x="${m}" y="${H - 52 + i * 15}" font-size="12">${esc(t)}</text>`));
  return svgDoc(W, H, out.join("\n"));
}

export function nestingSvg(nest, sh) {
  const L = sh.length ?? nest.length, Wd = sh.width ?? nest.width, m = 20;
  const out = [`<rect x="${m}" y="${m}" width="${L}" height="${Wd}" fill="#fafafa" stroke="#111" stroke-width="2"/>`];
  for (const p of sh.placements) {
    out.push(`<rect x="${m + p.x}" y="${m + Wd - p.y - p.h}" width="${p.w}" height="${p.h}" fill="#dbe7f3" stroke="#1d3557" stroke-width="1.5"/>`);
    out.push(`<text x="${m + p.x + p.w / 2}" y="${m + Wd - p.y - p.h / 2}" font-size="${Math.max(14, Math.min(40, Math.min(p.w, p.h) / 6))}" text-anchor="middle" dominant-baseline="middle">${esc(p.ref)}</text>`);
  }
  const rem = sh.remnant;
  if (rem) {
    const [x0, y0] = rem.axis === "x" ? [rem.at, 0.0] : [0.0, rem.at];
    out.push(`<rect x="${m + x0}" y="${m + Wd - y0 - rem.width}" width="${rem.length}" height="${rem.width}" fill="none" stroke="#2a9d8f" stroke-width="2" stroke-dasharray="16 8"/>`);
    out.push(`<text x="${m + x0 + rem.length / 2}" y="${m + Wd - y0 - rem.width / 2}" font-size="22" text-anchor="middle" fill="#2a9d8f">${esc(`retal ${fx(rem.length)}×${fx(rem.width)}`)}</text>`);
  }
  out.push(`<text x="${m}" y="${Wd + m + 34}" font-size="24">${esc(`${nest.material} e=${g(nest.thickness)} mm · ${sheetLabel(nest, sh)} · hoja ${sh.sheet}/${nest.sheets.length} · ${(sh.utilization * 100).toFixed(1)} %`)}</text>`);
  return svgDoc(L + 2 * m, Wd + 2 * m + 50, out.join("\n"));
}

// ============================================================================ STL binario de la malla
export function stlBinary(model) {
  let ntri = 0;
  for (const i of model.instances) ntri += partGeometry(i.part).indices.length / 3;
  const buf = new ArrayBuffer(84 + 50 * ntri);
  const dv = new DataView(buf);
  const head = `Monxu ${model.product_code} malla de visualizacion (mm)`;
  for (let k = 0; k < Math.min(80, head.length); k++) dv.setUint8(k, head.charCodeAt(k));
  dv.setUint32(80, ntri, true);
  let o = 84;
  for (const inst of model.instances) {
    const geo = partGeometry(inst.part), P = geo.positions, I = geo.indices, T = inst.T;
    const tp = (k) => [0, 1, 2].map((r) => T[r][0] * P[3 * k] + T[r][1] * P[3 * k + 1] + T[r][2] * P[3 * k + 2] + T[r][3]);
    for (let t = 0; t < I.length; t += 3) {
      const a = tp(I[t]), b = tp(I[t + 1]), c = tp(I[t + 2]);
      const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
      const nn = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
      const L = Math.hypot(...nn) || 1;
      for (const x of [...nn.map((q) => q / L), ...a, ...b, ...c]) { dv.setFloat32(o, x, true); o += 4; }
      dv.setUint16(o, 0, true); o += 2;
    }
  }
  return new Uint8Array(buf);
}

// ============================================================================ CSV
export const csv = (header, rows) => "﻿" + [header, ...rows].map((r) => r.map((c) => {
  // número: notación fija (nunca «1e-6») y sin ruido de coma flotante, como pipeline.csv_cell (hasta 9 decimales)
  const num = (x) => { if (Number.isInteger(x)) return String(x); const t = x.toFixed(9).replace(/0+$/, "").replace(/\.$/, ""); return (t === "-0" || t === "" ? "0" : t).replace(".", ","); };
  const s = c === null || c === undefined ? "" : typeof c === "number" ? num(c) : String(c);
  return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}).join(";")).join("\r\n") + "\r\n";

// ============================================================================ ZIP (método STORE, CRC-32)
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (u8) => { let c = 0xffffffff; for (let i = 0; i < u8.length; i++) c = CRC[(c ^ u8[i]) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const enc = new TextEncoder();
export function zip(files) { return zipBuild(files.map((f) => { const data = typeof f.data === "string" ? enc.encode(f.data) : f.data; return { path: f.path, raw: data, payload: data, method: 0 }; })); }
/** ZIP con compresión deflate (CompressionStream 'deflate-raw') cuando el entorno la ofrece; si no, almacenado. */
export async function zipAsync(files) {
  const out = [];
  for (const f of files) {
    const raw = typeof f.data === "string" ? enc.encode(f.data) : f.data;
    let payload = raw, method = 0;
    if (raw.length > 256) { const z = await deflate(raw, "deflate-raw"); if (z && z.length < raw.length) { payload = z; method = 8; } }
    out.push({ path: f.path, raw, payload, method });
  }
  return zipBuild(out);
}
function zipBuild(entries) {
  const parts = [], central = [];
  let off = 0;
  const d = new Date();
  const dosT = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1), dosD = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
  for (const e of entries) {
    const name = enc.encode(e.path), crc = crc32(e.raw), data = e.payload;
    const lh = new DataView(new ArrayBuffer(30));
    lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true); lh.setUint16(8, e.method, true);
    lh.setUint16(10, dosT, true); lh.setUint16(12, dosD, true); lh.setUint32(14, crc, true); lh.setUint32(18, data.length, true); lh.setUint32(22, e.raw.length, true);
    lh.setUint16(26, name.length, true); lh.setUint16(28, 0, true);
    parts.push(new Uint8Array(lh.buffer), name, data);
    const ch = new DataView(new ArrayBuffer(46));
    ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint16(8, 0x0800, true); ch.setUint16(10, e.method, true);
    ch.setUint16(12, dosT, true); ch.setUint16(14, dosD, true); ch.setUint32(16, crc, true); ch.setUint32(20, data.length, true); ch.setUint32(24, e.raw.length, true);
    ch.setUint16(28, name.length, true); ch.setUint32(42, off, true);
    central.push(new Uint8Array(ch.buffer), name);
    off += 30 + name.length + data.length;
  }
  const cdSize = central.reduce((s, a) => s + a.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, entries.length, true); end.setUint16(10, entries.length, true); end.setUint32(12, cdSize, true); end.setUint32(16, off, true);
  const all = [...parts, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(all.reduce((s, a) => s + a.length, 0));
  let p = 0;
  for (const a of all) { out.set(a, p); p += a.length; }
  return out;
}

export async function sha256(u8) {
  const h = await crypto.subtle.digest("SHA-256", u8);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ============================================================================ informe HTML
export function reportHtml(summary, info) {
  const e = summary.engineering, q = summary.qa, b = summary.bom;
  const row = (cells, tag = "td") => `<tr>${cells.map((c) => `<${tag}>${esc(c ?? "—")}</${tag}>`).join("")}</tr>`;
  const num = (v, d = 3) => (v === null || v === undefined ? "—" : typeof v === "number" ? v.toFixed(d).replace(".", ",") : v);
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Informe ${esc(summary.product_code)}</title>
<style>body{font:13px/1.45 system-ui,Arial,sans-serif;color:#111;margin:24px;max-width:1100px}h1{font-size:20px}h2{font-size:16px;margin-top:28px;border-bottom:1px solid #999}
table{border-collapse:collapse;width:100%;margin:8px 0}td,th{border:1px solid #bbb;padding:3px 6px;text-align:left;vertical-align:top}th{background:#eef1f4}
.CUMPLE,.ok{color:#11622f}.NO_CUMPLE,.bloqueante{color:#a10f1f;font-weight:600}.PENDIENTE,.pendiente{color:#7a5a00}.stamp{border:2px solid #333;padding:6px 10px;display:inline-block;margin:6px 0}</style></head><body>
<h1>Informe de cálculo y verificaciones · ${esc(info.product_name)}</h1>
<div class="stamp">${esc(info.status_stamp)}</div>
<p>Proyecto ${esc(info.project_code)} · Revisión ${esc(info.revision)} · ${esc(info.date)} · Diseñado: ${esc(info.designer)} · Cliente: ${esc(info.client)}<br>
Motor: cálculo ejecutado en el navegador (port validado del motor de referencia del servidor). ${esc(e.validation_note)}</p>
<h2>1. Resultado</h2><p class="${e.status}">${esc(e.status_label)}</p>
${e.governing ? `<p>Comprobación determinante: ${esc(e.governing.description)} — aprovechamiento ${num(e.governing.utilization)}</p>` : ""}
${e.pending.length ? `<ul>${e.pending.map((p) => `<li class="PENDIENTE">PENDIENTE: ${esc(p)}</li>`).join("")}</ul>` : ""}
<h2>2. Parámetros resueltos</h2><table>${row(["Parámetro", "Descripción", "Valor", "Unidad", "Origen"], "th")}${summary.parameters.filter((p) => !p.derived).map((p) => row([p.name, p.label, String(p.value), p.unit, p.source])).join("")}</table>
<h2>3. Materiales y secciones</h2><table>${row(["Código", "Nombre", "Norma", "E MPa", "fy MPa", "fu MPa", "ρ kg/m³"], "th")}${e.materials.map((m) => row([m.code, m.name, m.standard, m.E, m.fy, m.fu, m.density])).join("")}</table>
<table>${row(["Perfil", "A mm²", "Iy cm⁴", "Iz cm⁴", "Wpl,y cm³", "Wpl,z cm³"], "th")}${e.sections.map((s) => row(s)).join("")}</table>
<h2>4. Casos de carga y combinaciones</h2><table>${row(["Caso", "Descripción", "Valor", "Total N"], "th")}${e.load_cases.map((c) => row([c.id, c.label, c.value, c.total_N])).join("")}</table>
<p>ELU: ${esc(Object.entries(e.combinations.ELU).map(([k, v]) => `${k} = ${Object.entries(v).map(([a, f]) => `${f.toFixed(2)}·${a}`).join(" + ")}`).join("; "))}<br>
ELS: ${esc(Object.entries(e.combinations.ELS).map(([k, v]) => `${k} = ${Object.entries(v).map(([a, f]) => `${f.toFixed(2)}·${a}`).join(" + ")}`).join("; "))}</p>
<p>Modelo de barras: ${e.fem.nodes} nodos, ${e.fem.elements} elementos, ${e.fem.dof} grados de libertad.</p>
<h2>5. Comprobaciones</h2><table>${row(["Id", "Descripción", "Norma / criterio", "Comb.", "Valor", "Límite", "Aprov.", "Estado"], "th")}
${e.checks.map((c) => `<tr><td>${esc(c.id)}</td><td>${esc(c.description)}</td><td>${esc(c.standard)}</td><td>${esc(c.combination)}</td><td>${num(c.value, 3)} ${esc(c.unit)}</td><td>${num(c.limit, 3)} ${esc(c.unit)}</td><td>${num(c.utilization, 3)}</td><td class="${c.status}">${c.status}</td></tr>`).join("")}</table>
<h2>6. Reacciones</h2><table>${row(["Combinación", "Apoyo", "Rx N", "Ry N", "Rz N"], "th")}${e.reactions.map((r) => row([r.combination, r.support, r.Rx_N, r.Ry_N, r.Rz_N])).join("")}</table>
<h2>7. Hipótesis</h2><ul>${e.hypotheses.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>
<h2>8. Limitaciones</h2><ul>${e.limitations.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>
<h2>9. Fabricabilidad (DFM)</h2><table>${row(["Nivel", "Código", "Elemento", "Mensaje"], "th")}${summary.dfm.map((d) => row([d.level, d.code, d.element, d.message + (d.proposal ? " → " + d.proposal : "")])).join("")}</table>
<h2>10. Control de calidad</h2><p>${esc(q.summary)}</p><table>${row(["Nivel", "Código", "Descripción"], "th")}${q.items.map((i) => `<tr><td class="${i.level}">${esc(i.level)}</td><td>${esc(i.code)}</td><td>${esc(i.message)}</td></tr>`).join("")}</table>
<h2>11. Lista de materiales</h2><table>${row(["Pos.", "Referencia", "Descripción", "Material", "Esp.", "Largo", "Ancho", "Cant.", "Peso unit. kg", "Peso total kg"], "th")}${b.rows.map((r) => row([r.pos, r.ref, r.description, r.material, r.thickness, r.length, r.width, r.qty, num(r.unit_mass, 4), num(r.total_mass, 4)])).join("")}
<tr><th colspan="7">Total</th><th>${b.totals.components}</th><th></th><th>${num(b.totals.total_mass, 2)}</th></tr></table>
<h2>12. Normas de referencia</h2><ul>${(summary.engineering.applicable_standards ?? C.standards(summary.family)).map((s) => `<li>${esc(s.code)}:${esc(s.version)} — ${esc(s.title)}${s.applicability ? " (" + esc(s.applicability) + ")" : ""}</li>`).join("")}</ul>
<p><em>La identificación de normas aplicables es orientativa; el responsable técnico del fabricante la confirma al firmar el expediente.</em></p>
</body></html>`;
}

// ============================================================================ tablas del expediente (= pipeline.py)
export const CUT_PLAN_HEADER = ["Perfil", "Material", "Barra", "Origen", "Long. barra mm", "Despunte inicial mm", "Piezas (ref:long)", "Nº piezas", "Nº cortes",
  "Ancho sierra mm", "Sierra total mm", "Σ piezas mm", "Despunte final mm", "Retal final mm", "Estado del retal", "Balance mm"];
export const BALANCE_HEADER = ["Tipo", "Grupo", "Unidad", "Comprado", "De inventario", "Neto en piezas", "Desperdicio no recuperable", "Retal reutilizable", "Comprado kg",
  "De inventario kg", "Neto kg", "Desperdicio kg", "Retal kg", "Balance"];
/** Plan de corte barra a barra: L = despunte inicial + Σ piezas + sierra + despunte final + retal. */
export const cutPlanRows = (plan) => plan.cutting.flatMap((c) => c.bars.map((b) => [c.profile, c.material, b.bar, b.source === "retal" ? `retal ${b.stock_id}` : "comercial",
  b.length, b.trim_start, b.cuts.map((x) => `${x.ref}:${g(x.length)}`).join(" + "), b.n_pieces, b.n_cuts, c.kerf, b.kerf_total, b.used, b.trim_end, b.remnant,
  b.remnant_status, b.balance_mm]));
export function balanceRows(plan) {
  const t = plan.balance.totals;
  return [...plan.balance.rows.map((r) => [r.kind, r.group, r.unit, r.purchased, r.from_stock, r.net, r.waste, r.reusable, r.purchased_kg, r.from_stock_kg, r.net_kg,
    r.waste_kg, r.reusable_kg, r.balance]), ["total", `lote de ${plan.lot ?? 1}`, "kg", "", "", "", "", "", t.purchased_kg, t.from_stock_kg, t.net_kg, t.waste_kg, t.reusable_kg, ""]];
}
/** Masas separadas: producto (por unidad) y material en bruto del lote; nunca se suman entre sí. */
export function weightSummaryRows(bom) {
  const t = bom.totals, lot = t.material_lot ?? 1;
  return [["", "", "Masa neta de piezas fabricadas (por unidad)", "", "", "", t.mass_manufactured_kg],
    ["", "", "Masa de componentes comerciales (por unidad)", "", "", "", t.mass_commercial_kg],
    ["", "", "Masa total del producto (por unidad)", "", "", "", t.mass_product_kg],
    ["", "", `Material en bruto comprado (lote de ${lot})`, "", "", "", t.mass_purchased_kg],
    ["", "", `Material de retales del inventario (lote de ${lot})`, "", "", "", t.mass_from_stock_kg],
    ["", "", `Desperdicio no recuperable (lote de ${lot})`, "", "", "", t.mass_waste_kg],
    ["", "", `Retales reutilizables al inventario (lote de ${lot})`, "", "", "", t.mass_reusable_kg]];
}
const PK = ["profile", "material", "n_bars", "n_stock_used", "stock_used", "lower_bound", "pieces", "n_cuts", "pieces_length", "purchased_length", "stock_length", "kerf_total",
  "trim_total", "scrap_remnant_length", "reusable_length", "waste_length", "balance_mm", "utilization", "reusable_remnants"];
export const optimizationSummary = (plan) => ({ lote: plan.lot ?? 1, parametros_corte: plan.cutting_params ?? null,
  perfiles: plan.cutting.map((c) => Object.fromEntries(PK.map((k) => [k, c[k]]))),
  chapa: plan.nesting.map((n) => ({ material: n.material, thickness: n.thickness, format: n.format ?? null, n_sheets: n.n_sheets ?? null, utilization: n.utilization ?? null,
    waste_m2: n.waste_m2 ?? null, compra: n.purchase ?? null })), balance: plan.balance });
export const purchaseRows = (bom, lot) => [...bom.purchases.map((p) => [p.type, p.description, p.ref ?? "", p.qty, p.unit, p.mass_kg, p.basis ?? "", p.validation ?? "", lot]),
  ...bom.consumables.map((c) => ["Consumible", c.description, "", c.qty, c.unit, "", c.basis ?? "", "", lot])];
export const PURCHASE_HEADER = ["Tipo", "Descripción", "Referencia", "Cantidad", "Unidad", "Masa kg", "Origen", "Validación", "Lote"];

// ============================================================================ verificación de archivos exportados
/** Relee un STL binario: triángulos, volumen (teorema de la divergencia) y envolvente, para compararlos con el modelo. */
export function verifyStl(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  const n = dv.getUint32(80, true);
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  let vol = 0, o = 84;
  for (let t = 0; t < n; t++) {
    const p = [];
    for (let k = 0; k < 3; k++) { const v = [0, 1, 2].map((j) => dv.getFloat32(o + 12 + 12 * k + 4 * j, true)); p.push(v); for (let j = 0; j < 3; j++) { lo[j] = Math.min(lo[j], v[j]); hi[j] = Math.max(hi[j], v[j]); } }
    const [a, b, c] = p;
    vol += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6;
    o += 50;
  }
  return { triangles: n, bytes_ok: u8.length === 84 + 50 * n, volume: vol, bbox: [lo, hi] };
}
/** Cuenta en un DXF R12 los contornos exteriores de corte y lee el contorno del formato (capa FORMATO). */
export function verifyNestingDxf(text) {
  const L = text.split("\r\n");
  let cut = 0, fmt = null;
  for (let i = 0; i + 3 < L.length; i++) {
    if (L[i] === "0" && L[i + 1] === "POLYLINE" && L[i + 2] === "8") {
      if (L[i + 3] === "CORTE_EXTERIOR") cut++;
      if (L[i + 3] === "FORMATO" && !fmt) {
        const xs = [], ys = [];
        for (let j = i + 4; j < L.length && L[j + 1] !== "SEQEND"; j++) if (L[j] === "VERTEX") { xs.push(+L[j + 4]); ys.push(+L[j + 6]); }
        fmt = [Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)];
      }
    }
  }
  return { cut_contours: cut, format: fmt };
}
