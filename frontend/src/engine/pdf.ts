// @ts-nocheck
// Escritor PDF 1.4 mínimo para planos (unidades de usuario en mm): líneas, polígonos, círculos, texto Helvetica
// con codificación WinAnsi y flujos de contenido comprimidos (FlateDecode) cuando el entorno ofrece CompressionStream.
import HELV from "./data/helvetica.json";
import { textBox } from "./layout";

const MM = 72 / 25.4;
const CP1252 = { 0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02c6: 0x88, 0x2030: 0x89, 0x0160: 0x8a,
  0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e, 0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97, 0x02dc: 0x98,
  0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b, 0x0153: 0x9c, 0x017e: 0x9e, 0x0178: 0x9f };
const SUBST = { "≥": ">=", "≤": "<=", "→": "->", "←": "<-", "↔": "<->", "γ": "g", "σ": "s", "τ": "t", "Δ": "D", "λ": "l", "χ": "x", "ψ": "y", "π": "pi",
  "√": "raiz", "∑": "S", "≈": "~", "≠": "!=", "′": "'", "″": '"', "✔": "OK", "✗": "x", "⁴": "4", "₀": "0", "₁": "1", "₂": "2", "ᵣ": "r", "ₑ": "e", "₍": "(", "₎": ")" };
/** Códigos WinAnsi de un texto (los caracteres sin equivalente se sustituyen). */
export function winAnsi(s) {
  const out = [];
  for (const ch of String(s)) {
    const c = ch.codePointAt(0);
    if (c >= 32 && c < 127) out.push(c);
    else if (c >= 0xa0 && c <= 0xff) out.push(c);
    else if (CP1252[c]) out.push(CP1252[c]);
    else if (SUBST[ch]) for (const k of SUBST[ch]) out.push(k.charCodeAt(0));
    else out.push(63);
  }
  return out;
}
/** Ancho de un texto en mm con altura de mayúsculas h (tamaño de cuerpo h/0,72, como en el servidor). */
export function textWidth(s, h, bold = false) {
  const W = HELV[bold ? "Helvetica-Bold" : "Helvetica"];
  let w = 0;
  for (const c of winAnsi(s)) w += W[c - 32] ?? 556;
  return (w / 1000) * (h / 0.72);
}
const num = (v) => { const r = Math.round(v * 1000) / 1000; return Object.is(r, -0) ? "0" : String(r); };
const pdfStr = (codes) => "(" + codes.map((c) => (c === 40 || c === 41 || c === 92 ? "\\" + String.fromCharCode(c) : c < 32 || c > 126 ? "\\" + c.toString(8).padStart(3, "0") : String.fromCharCode(c))).join("") + ")";

export class PDF {
  constructor(meta = {}) { this.meta = meta; this.pages = []; this.cur = null; this.W = 420; this.H = 297; }
  page(w = 420, h = 297) { this.cur = { w, h, ops: [`${num(MM)} 0 0 ${num(MM)} 0 0 cm 1 J 1 j`] }; this.pages.push(this.cur); this._lw = null; this._dash = ""; this._sc = "0 G"; this._fc = "0 g"; return this; }
  o(s) { this.cur.ops.push(s); }
  lw(w) { if (this._lw !== w) { this.o(`${num(w)} w`); this._lw = w; } return this; }
  dash(d = null) { const s = d && d.length ? `[${d.map(num).join(" ")}] 0 d` : "[] 0 d"; if (this._dash !== s) { this.o(s); this._dash = s; } return this; }
  stroke(c = [0, 0, 0]) { const s = c[0] === c[1] && c[1] === c[2] ? `${num(c[0])} G` : `${num(c[0])} ${num(c[1])} ${num(c[2])} RG`; if (this._sc !== s) { this.o(s); this._sc = s; } return this; }
  fill(c = [0, 0, 0]) { const s = c[0] === c[1] && c[1] === c[2] ? `${num(c[0])} g` : `${num(c[0])} ${num(c[1])} ${num(c[2])} rg`; if (this._fc !== s) { this.o(s); this._fc = s; } return this; }
  /** Registro opcional de lo dibujado (ocupación de la hoja para colocar textos y auditar solapes). */
  _seg(x1, y1, x2, y2) { if (this.rec) this.rec.addSeg([x1, y1, x2, y2], this.cat ?? "misc", this.gid); }
  line(x1, y1, x2, y2) { this._seg(x1, y1, x2, y2); this.o(`${num(x1)} ${num(y1)} m ${num(x2)} ${num(y2)} l S`); return this; }
  /** Varios segmentos [[x1,y1,x2,y2], ...] en un único trazado. */
  segments(segs) {
    if (!segs.length) return this;
    const parts = [];
    for (const s of segs) { this._seg(s[0], s[1], s[2], s[3]); parts.push(`${num(s[0])} ${num(s[1])} m ${num(s[2])} ${num(s[3])} l`); }
    for (let i = 0; i < parts.length; i += 400) this.o(parts.slice(i, i + 400).join(" ") + " S");
    return this;
  }
  poly(pts, close = false, mode = "S") {
    if (pts.length < 2) return this;
    if (this.rec) for (let i = 0; i < pts.length - (close ? 0 : 1); i++) { const a = pts[i], b = pts[(i + 1) % pts.length]; this._seg(a[0], a[1], b[0], b[1]); }
    this.o(pts.map((p, i) => `${num(p[0])} ${num(p[1])} ${i ? "l" : "m"}`).join(" ") + (close ? " h" : "") + ` ${mode}`);
    return this;
  }
  rect(x, y, w, h, mode = "S") {
    if (this.rec) { this._seg(x, y, x + w, y); this._seg(x + w, y, x + w, y + h); this._seg(x + w, y + h, x, y + h); this._seg(x, y + h, x, y); }
    this.o(`${num(x)} ${num(y)} ${num(w)} ${num(h)} re ${mode}`); return this; }
  circle(cx, cy, r, mode = "S") {
    const k = 0.5523 * r;
    if (this.rec) this.rec.addCircle([cx, cy], r, this.cat ?? "misc", this.gid);
    this.o(`${num(cx + r)} ${num(cy)} m ${num(cx + r)} ${num(cy + k)} ${num(cx + k)} ${num(cy + r)} ${num(cx)} ${num(cy + r)} c `
      + `${num(cx - k)} ${num(cy + r)} ${num(cx - r)} ${num(cy + k)} ${num(cx - r)} ${num(cy)} c ${num(cx - r)} ${num(cy - k)} ${num(cx - k)} ${num(cy - r)} ${num(cx)} ${num(cy - r)} c `
      + `${num(cx + k)} ${num(cy - r)} ${num(cx + r)} ${num(cy - k)} ${num(cx + r)} ${num(cy)} c h ${mode}`);
    return this;
  }
  text(x, y, s, h = 3.5, opts = {}) {
    const { align = "l", bold = false, angle = 0, color = [0, 0, 0] } = opts;
    s = String(s ?? "");
    if (!s) return this;
    const fs = h / 0.72;
    const w = textWidth(s, h, bold);
    const dx = align === "c" ? -w / 2 : align === "r" ? -w : 0;
    const a = (angle * Math.PI) / 180, c = Math.cos(a), sn = Math.sin(a);
    const tx = x + dx * c, ty = y + dx * sn;
    if (this.rec) this.rec.addText(textBox(tx, ty, w, h, angle), this.cat ?? "misc", s, this.gid);
    this.fill(color);
    this.o(`BT /${bold ? "F2" : "F1"} ${num(fs)} Tf ${num(c)} ${num(sn)} ${num(-sn)} ${num(c)} ${num(tx)} ${num(ty)} Tm ${pdfStr(winAnsi(s))} Tj ET`);
    this.fill([0, 0, 0]);
    return this;
  }
  async save() {
    const enc = new TextEncoder();
    const chunks = [];
    let off = 0;
    const offsets = [];
    const push = (b) => { const u = typeof b === "string" ? enc.encode(b) : b; chunks.push(u); off += u.length; };
    const obj = (n, body) => { offsets[n] = off; push(`${n} 0 obj\n`); push(body); push("\nendobj\n"); };
    push("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n");
    const nPages = this.pages.length;
    const pageIds = this.pages.map((_, i) => 5 + 2 * i);
    obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
    obj(2, `<< /Type /Pages /Kids [${pageIds.map((i) => `${i} 0 R`).join(" ")}] /Count ${nPages} >>`);
    obj(3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>");
    obj(4, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>");
    for (let i = 0; i < nPages; i++) {
      const p = this.pages[i];
      const content = enc.encode(p.ops.join("\n"));
      const z = await deflate(content);
      obj(pageIds[i], `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(p.w * MM)} ${num(p.h * MM)}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${pageIds[i] + 1} 0 R >>`);
      offsets[pageIds[i] + 1] = off;
      push(`${pageIds[i] + 1} 0 obj\n<< /Length ${(z ?? content).length}${z ? " /Filter /FlateDecode" : ""} >>\nstream\n`);
      push(z ?? content);
      push("\nendstream\nendobj\n");
    }
    const infoId = 5 + 2 * nPages;
    const lit = (s) => pdfStr(winAnsi(s ?? ""));
    obj(infoId, `<< /Title ${lit(this.meta.title)} /Author ${lit(this.meta.author)} /Subject ${lit(this.meta.subject)} /Creator (Monxu) /Producer (Monxu motor parametrico) >>`);
    const xref = off;
    const n = infoId + 1;
    let x = `xref\n0 ${n}\n0000000000 65535 f \n`;
    for (let i = 1; i < n; i++) x += `${String(offsets[i] ?? 0).padStart(10, "0")} 00000 n \n`;
    push(x + `trailer\n<< /Size ${n} /Root 1 0 R /Info ${infoId} 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
    const out = new Uint8Array(off);
    let p = 0;
    for (const c of chunks) { out.set(c, p); p += c.length; }
    return out;
  }
}

/** zlib (RFC 1950) con CompressionStream; null si el entorno no lo ofrece. */
export async function deflate(u8, format = "deflate") {
  if (typeof CompressionStream === "undefined") return null;
  try {
    const cs = new CompressionStream(format);
    const w = cs.writable.getWriter();
    w.write(u8); w.close();
    const parts = [];
    const r = cs.readable.getReader();
    for (;;) { const { value, done } = await r.read(); if (done) break; parts.push(value); }
    const out = new Uint8Array(parts.reduce((s, a) => s + a.length, 0));
    let o = 0;
    for (const a of parts) { out.set(a, o); o += a.length; }
    return out;
  } catch { return null; }
}
