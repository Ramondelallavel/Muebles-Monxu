// @ts-nocheck
// Parámetros, contexto de dependencias y modelo de producto (port de monxu/core).
import * as C from "./catalog";
import { pyRound } from "./util";

export const AUTO = "auto";

export class ParamError extends Error {}

export function coerce(spec, value) {
  if (value === null || value === undefined || value === "") {
    if (spec.nullable) return null;
    if (value === "" && spec.allow_auto) return AUTO;
    throw new ParamError(`${spec.name}: valor obligatorio`);
  }
  if (spec.allow_auto && typeof value === "string" && value.trim().toLowerCase() === AUTO) return AUTO;
  let v = value;
  if (spec.type === "float") {
    v = typeof value === "string" ? parseFloat(value.replace(",", ".")) : Number(value);
    if (!Number.isFinite(v)) throw new ParamError(`${spec.name}: valor no válido '${value}' (se esperaba float)`);
  } else if (spec.type === "int") {
    v = Math.trunc(Number(String(value).replace(",", ".")));
    if (!Number.isFinite(v)) throw new ParamError(`${spec.name}: valor no válido '${value}' (se esperaba int)`);
  } else if (spec.type === "bool") v = typeof value === "string" ? ["1", "true", "si", "sí", "yes"].includes(value.toLowerCase()) : !!value;
  if (spec.type === "float" || spec.type === "int") {
    if (spec.min != null && v < spec.min) throw new ParamError(`${spec.name} = ${v} ${spec.unit ?? ""} inferior al mínimo ${spec.min}`);
    if (spec.max != null && v > spec.max) throw new ParamError(`${spec.name} = ${v} ${spec.unit ?? ""} superior al máximo ${spec.max}`);
  }
  if (spec.type === "choice" && spec.choices && !spec.choices.includes(v))
    throw new ParamError(`${spec.name}: '${v}' no está entre las opciones`);
  return v;
}

export function newParams(specs, values = {}, sources = {}) {
  const ps = { specs: Object.fromEntries(specs.map((s) => [s.name, s])), values: {}, sources: {} };
  for (const s of specs) { ps.values[s.name] = s.default; ps.sources[s.name] = "defecto"; }
  const errors = [];
  for (const [k, v] of Object.entries(values)) {
    if (!ps.specs[k]) { errors.push(`Parámetro desconocido: ${k}`); continue; }
    try { ps.values[k] = coerce(ps.specs[k], v); ps.sources[k] = sources[k] ?? "usuario"; } catch (e) { errors.push(e.message); }
  }
  if (errors.length) throw new ParamError(errors.join("; "));
  return ps;
}
export const copyParams = (ps) => ({ specs: ps.specs, values: { ...ps.values }, sources: { ...ps.sources } });

export class ParamContext {
  constructor(params) { this.params = params; this.derived = {}; this.features = {}; this._stack = []; this._fstack = []; }
  get(name) {
    for (const s of this._stack) s.add(name);
    if (name in this.derived) return this.derived[name].value;
    if (name in this.params.values) return this.params.values[name];
    throw new Error(`Parámetro no definido: ${name}`);
  }
  uses(...names) { for (const n of names) this.get(n); }
  derive(name, fn, unit = null, label = "") {
    const reads = new Set();
    this._stack.push(reads);
    let value;
    try { value = fn(this); } finally { this._stack.pop(); }
    for (const s of this._stack) s.add(name);
    this.derived[name] = { name, value, unit, label: label || name, deps: reads };
    return value;
  }
  setDerived(name, value, unit = null, label = "", deps = []) {
    this.derived[name] = { name, value, unit, label: label || name, deps: new Set(deps) };
    return value;
  }
  feature(fid, label, body) {
    const rec = { id: fid, label, reads: new Set(), produces: [], parent: this._fstack.length ? this._fstack.at(-1).id : null };
    this.features[fid] = rec;
    this._stack.push(rec.reads); this._fstack.push(rec);
    try { return body(rec); } finally { this._stack.pop(); this._fstack.pop(); }
  }
  get current() { return this._fstack.length ? this._fstack.at(-1) : null; }
  baseDeps(name, seen = new Set()) {
    if (!(name in this.derived)) return new Set([name]);
    const out = new Set();
    for (const d of this.derived[name].deps) { if (seen.has(d)) continue; seen.add(d); for (const x of this.baseDeps(d, seen)) out.add(x); }
    return out;
  }
  featureDeps(fid) { const out = new Set(); for (const r of this.features[fid].reads) for (const x of this.baseDeps(r)) out.add(x); return out; }
}

// --------------------------------------------------------------------- álgebra 3D (matrices 4x4 por filas)
export const I4 = () => [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]];
export const translation = (x, y, z) => [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]];
const norm = (v) => { const n = Math.hypot(...v); return v.map((c) => c / n); };
export const sub = (a, b) => a.map((c, i) => c - b[i]);
export const add = (a, b) => a.map((c, i) => c + b[i]);
export const scale = (a, k) => a.map((c) => c * k);
export const dot = (a, b) => a.reduce((s, c, i) => s + c * b[i], 0);
export const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
function fromCols(x, y, z, o) { return [[x[0], y[0], z[0], o[0]], [x[1], y[1], z[1], o[1]], [x[2], y[2], z[2], o[2]], [0, 0, 0, 1]]; }
export function frame(o, xdir, ydir) {
  const x = norm(xdir); let y = sub(ydir, scale(x, dot(x, ydir))); y = norm(y);
  return fromCols(x, y, cross(x, y), o);
}
export function axisFrame(p0, p1, up) {
  const z = norm(sub(p1, p0)); let y = sub(up, scale(z, dot(z, up))); y = norm(y);
  return fromCols(cross(y, z), y, z, p0);
}
export function frameZ(o, zdir) {
  const z = norm(zdir); let x = Math.abs(z[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
  x = norm(sub(x, scale(z, dot(x, z))));
  return frame(o, x, cross(z, x));
}
export const tp = (T, p) => [0, 1, 2].map((i) => T[i][0] * p[0] + T[i][1] * p[1] + T[i][2] * p[2] + T[i][3]);
export function mmul(A, B) { return A.map((r) => [0, 1, 2, 3].map((j) => r.reduce((s, a, k) => s + a * B[k][j], 0))); }

// --------------------------------------------------------------------- piezas
let _hid = 0;
const KIND_ORDER = { perfil: 0, chapa: 1, pletina: 2, normalizado: 3 };
export const KIND_LABEL = { perfil: "Perfil comercial", chapa: "Pieza de chapa", pletina: "Pletina cortada", normalizado: "Elemento normalizado" };

export function profilePart(role, name, code, length, mat, fin, holes = []) {
  const p = C.profile(code);
  const L = pyRound(length, 2);
  holes = holes.map((h) => [h[0], pyRound(h[1], 3), pyRound(h[2], 3), h[3]]);
  const rho = C.material(mat).density;
  const holesVol = holes.reduce((s, h) => s + (Math.PI * h[3] * h[3]) / 4 * p.t, 0);
  return { kind: "perfil", role, name, material: mat, finish: fin, profile: p, length: L, holes,
    key: `P|${code}|${mat}|${L.toFixed(2)}|${JSON.stringify(holes)}`,
    volume: p.props.A * L - holesVol, get mass() { return this.volume * 1e-9 * rho; },
    nominalMass: p.massPerM(rho) * L / 1000,
    bomDims() { return { espesor: p.t, largo: L, ancho: null, seccion: code }; } };
}
export function sheetPart(role, name, spec, mat, fin) {
  const rho = C.material(mat).density;
  const flat = spec.flat();
  let vol = flat.netArea * spec.t;
  for (const L of spec.bendLengths()) vol += (Math.PI / 2) * spec.t * spec.t * (0.5 - spec.K) * L;
  return { kind: "chapa", role, name, material: mat, finish: fin, spec, flat, volume: vol,
    key: `S|${mat}|${spec.signature}`, get mass() { return this.volume * 1e-9 * rho; },
    bomDims() { return { espesor: spec.t, largo: Math.round(Math.max(flat.width, flat.height) * 10) / 10,
      ancho: Math.round(Math.min(flat.width, flat.height) * 10) / 10, desarrollo: true }; } };
}
export function platePart(role, name, w, h, t, mat, fin, corner_r = 0, holes = []) {
  const rho = C.material(mat).density;
  const area = w * h - (4 - Math.PI) * corner_r * corner_r - holes.reduce((s, x) => s + (Math.PI * x[2] * x[2]) / 4, 0);
  return { kind: "pletina", role, name, material: mat, finish: fin, w, h, t, corner_r, holes,
    key: `PL|${mat}|${w}|${h}|${t}|${corner_r}|${JSON.stringify(holes)}`, volume: area * t, outlineArea: w * h - (4 - Math.PI) * corner_r * corner_r,
    get mass() { return this.volume * 1e-9 * rho; }, bomDims() { return { espesor: t, largo: Math.max(w, h), ancho: Math.min(w, h) }; } };
}
export function standardPart(role, code) {
  const c = C.component(code);
  return { kind: "normalizado", role, code, data: c, name: c.name, material: null, finish: null, key: `N|${code}`,
    get mass() { return +c.mass_kg; }, bomDims() { return { espesor: null, largo: null, ancho: null, norma: c.standard }; } };
}

export class ProductModel {
  constructor(family, familyName, productCode, params, ctx) {
    Object.assign(this, { family, family_name: familyName, product_code: productCode, params, ctx });
    this.parts = {}; this.instances = []; this.subassemblies = {}; this.joints = []; this.structure = {};
    this.design_notes = []; this.dims = {}; this._ids = new Set();
  }
  addSub(id, name, opts = {}) { this.subassemblies[id] = { id, name, parent: null, explode: [0, 0, 0], step: 0, welded: false, ...opts }; }
  part(p) { if (!this.parts[p.key]) this.parts[p.key] = p; return this.parts[p.key]; }
  add(id, name, part, T, group, opts = {}) {
    if (this._ids.has(id)) throw new Error(`Identificador de instancia duplicado: ${id}`);
    this._ids.add(id);
    part = this.part(part);
    const f = this.ctx.current;
    const inst = { id, name, part, T, group, feature: f ? f.id : "", axis: null, up: null, structural: false, tags: {}, ...opts };
    if (f) f.produces.push(id);
    this.instances.push(inst);
    return inst;
  }
  joint(j) { this.joints.push({ fasteners: [], data: {}, ...j }); }
  note(level, code, message, extra = {}) { this.design_notes.push({ level, code, message, ...extra }); }
  instance(id) { const i = this.instances.find((x) => x.id === id); if (!i) throw new Error(id); return i; }
  numberParts() {
    const order = Object.fromEntries(Object.keys(this.subassemblies).map((k, i) => [k, i]));
    const first = {};
    for (const i of this.instances) if (!first[i.part.key]) first[i.part.key] = i;
    const keys = Object.keys(this.parts).sort((a, b) => {
      const pa = this.parts[a], pb = this.parts[b];
      const ka = [KIND_ORDER[pa.kind], order[first[a]?.group] ?? 99, pa.role, pa.name, a];
      const kb = [KIND_ORDER[pb.kind], order[first[b]?.group] ?? 99, pb.role, pb.name, b];
      for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
      return 0;
    });
    keys.forEach((k, n) => {
      const p = this.parts[k]; p.pos = n + 1;
      p.ref = p.kind !== "normalizado" ? `${this.product_code}-${String(n + 1).padStart(2, "0")}` : `N-${p.code}`;
    });
  }
  totalMass() { return this.instances.reduce((s, i) => s + i.part.mass, 0); }
  componentTree() {
    const node = (sid) => {
      const sa = this.subassemblies[sid];
      return { id: sid, name: sa.name, type: "subconjunto", welded: sa.welded,
        children: this.instances.filter((i) => i.group === sid).map((i) => ({ id: i.id, name: i.name, type: i.part.kind, ref: i.part.ref, part: i.part.key })) };
    };
    return { id: this.product_code, name: this.family_name, type: "conjunto", children: Object.keys(this.subassemblies).map(node) };
  }
  featureTree() {
    return Object.values(this.ctx.features).map((f) => ({ id: f.id, label: f.label, parent: f.parent,
      params: [...this.ctx.featureDeps(f.id)].sort(), produces: [...f.produces] }));
  }
  parameterTable() {
    const rows = Object.entries(this.params.specs).map(([name, s]) => ({ name, label: s.label, value: this.params.values[name], unit: s.unit,
      group: s.group, source: this.params.sources[name], derived: false }));
    for (const [name, d] of Object.entries(this.ctx.derived)) {
      let v = d.value;
      if (typeof v === "number") v = Math.round(v * 1e4) / 1e4;
      if (["number", "string", "boolean"].includes(typeof v) || v === null)
        rows.push({ name, label: d.label, value: v, unit: d.unit, group: "derivado", source: "regla_diseno", derived: true,
          depends_on: [...this.ctx.baseDeps(name)].sort() });
    }
    return rows;
  }
}
