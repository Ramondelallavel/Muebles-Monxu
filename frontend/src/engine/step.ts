// @ts-nocheck
// STEP AP214 (ISO 10303-21) desde el navegador: estructura de producto con instancias (NAUO + transformación)
// y sólidos facetados (FACETED_BREP con caras planas acotadas por POLY_LOOP), con color por pieza.
import { colorOf, partGeometry } from "./geometry";

const R = (x) => {
  if (!Number.isFinite(x) || Math.abs(x) < 1e-12) return "0.";
  let s = x.toFixed(6).replace(/0+$/, "");
  return s;
};
const S = (s) => "'" + String(s ?? "").replace(/'/g, "''").replace(/\\/g, "\\\\").replace(/[^\x20-\x7e]/g, (c) => `\\X2\\${c.charCodeAt(0).toString(16).toUpperCase().padStart(4, "0")}\\X0\\`) + "'";
const vsub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const vdot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const vnorm = (a) => { const n = Math.hypot(...a) || 1; return a.map((v) => v / n); };

class Writer {
  constructor() { this.lines = []; this.n = 0; }
  add(body) { this.n += 1; this.lines.push(`#${this.n}=${body};`); return `#${this.n}`; }
  point(p) { return this.add(`CARTESIAN_POINT('',(${R(p[0])},${R(p[1])},${R(p[2])}))`); }
  dir(d) { return this.add(`DIRECTION('',(${R(d[0])},${R(d[1])},${R(d[2])}))`); }
  axis(o, z, x) { return this.add(`AXIS2_PLACEMENT_3D('',${this.point(o)},${this.dir(z)},${this.dir(x)})`); }
}

function header(name, author, org, desc) {
  const now = new Date().toISOString().slice(0, 19);
  return ["ISO-10303-21;", "HEADER;", `FILE_DESCRIPTION((${S(desc)}),'2;1');`, `FILE_NAME(${S(name)},${S(now)},(${S(author)}),(${S(org)}),'Monxu','Monxu motor parametrico','');`,
    "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));", "ENDSEC;", "DATA;"].join("\n");
}

function context(w) {
  const app = w.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')");
  w.add(`APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,${app})`);
  const pc = w.add(`PRODUCT_CONTEXT('',${app},'mechanical')`);
  const pdc = w.add(`PRODUCT_DEFINITION_CONTEXT('part definition',${app},'design')`);
  const mm = w.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )");
  const rad = w.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )");
  const sr = w.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )");
  const unc = w.add(`UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-03),${mm},'distance_accuracy_value','confusion accuracy')`);
  const ctx = w.add(`( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((${unc})) GLOBAL_UNIT_ASSIGNED_CONTEXT((${mm},${rad},${sr})) REPRESENTATION_CONTEXT('Context','3D') )`);
  return { pc, pdc, ctx };
}

function product(w, c, id, name) {
  const p = w.add(`PRODUCT(${S(id)},${S(name)},'',(${c.pc}))`);
  w.add(`PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(${p}))`);
  const pdf = w.add(`PRODUCT_DEFINITION_FORMATION('','',${p})`);
  const pd = w.add(`PRODUCT_DEFINITION('design','',${pdf},${c.pdc})`);
  const pds = w.add(`PRODUCT_DEFINITION_SHAPE('','',${pd})`);
  return { pd, pds };
}

/** Representación facetada de una pieza (en sus coordenadas locales). */
function partRep(w, c, part, styles) {
  const g = partGeometry(part);
  const { verts, faces } = g.brep;
  const pts = new Map();
  const P = (k) => { if (!pts.has(k)) pts.set(k, w.point(verts[k])); return pts.get(k); };
  // una capa cerrada por componente conexo (p. ej. una rueda: espiga, cabezal, horquilla y rueda son cuerpos que se tocan)
  const find = (i) => faces[i].comp ?? 0;
  const groups = new Map();
  const fs = [];
  faces.forEach((f, i) => {
    const bounds = f.loops.map((l, k) => {
      const loop = w.add(`POLY_LOOP('',(${l.map(P).join(",")}))`);
      return w.add(`${k === 0 ? "FACE_OUTER_BOUND" : "FACE_BOUND"}('',${loop},.T.)`);
    });
    const o = verts[f.loops[0][0]], q = verts[f.loops[0][1]];
    let x = vsub(q, o);
    x = vnorm(vsub(x, f.n.map((v) => v * vdot(x, f.n))));
    const plane = w.add(`PLANE('',${w.axis(o, f.n, x)})`);
    const id = w.add(`FACE_SURFACE('',(${bounds.join(",")}),${plane},.T.)`);
    fs.push(id);
    const r = find(i);
    if (!groups.has(r)) groups.set(r, []);
    groups.get(r).push(id);
  });
  const breps = [...groups.values()].map((ids, k, all) => {
    const shell = w.add(`CLOSED_SHELL('',(${ids.join(",")}))`);
    const brep = w.add(`FACETED_BREP(${S(all.length > 1 ? `${part.ref}-${k + 1}` : part.ref)},${shell})`);
    styles.push([brep, part]);
    return brep;
  });
  const origin = w.axis([0, 0, 0], [0, 0, 1], [1, 0, 0]);
  const rep = w.add(`FACETED_BREP_SHAPE_REPRESENTATION(${S(part.ref)},(${breps.join(",")},${origin}),${c.ctx})`);
  return { rep, origin, faces: faces.length, shells: breps.length };
}

function colours(w, c, styles, colorFor) {
  const items = [];
  for (const [brep, part] of styles) {
    const [r, g, b] = colorFor(part);
    const col = w.add(`COLOUR_RGB('',${R(r)},${R(g)},${R(b)})`);
    const fasc = w.add(`FILL_AREA_STYLE_COLOUR('',${col})`);
    const fas = w.add(`FILL_AREA_STYLE('',(${fasc}))`);
    const ssfa = w.add(`SURFACE_STYLE_FILL_AREA(${fas})`);
    const sss = w.add(`SURFACE_SIDE_STYLE('',(${ssfa}))`);
    const ssu = w.add(`SURFACE_STYLE_USAGE(.BOTH.,${sss})`);
    const psa = w.add(`PRESENTATION_STYLE_ASSIGNMENT((${ssu}))`);
    items.push(w.add(`STYLED_ITEM('color',(${psa}),${brep})`));
  }
  if (items.length) w.add(`MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(${items.join(",")}),${c.ctx})`);
}

const finish = (w, head) => `${head}\n${w.lines.join("\n")}\nENDSEC;\nEND-ISO-10303-21;\n`;
const partColor = (model) => { const first = {}; for (const i of model.instances) if (!first[i.part.key]) first[i.part.key] = i; return (p) => colorOf(first[p.key] ?? { part: p }); };

/** STEP del conjunto: un producto por definición de pieza y una ocurrencia (NAUO) por instancia. */
export function assemblyStep(model, info = {}) {
  const w = new Writer();
  const c = context(w);
  const root = product(w, c, model.product_code, `${model.family_name} ${model.product_code}`);
  const styles = [];
  const parts = {};
  for (const p of Object.values(model.parts)) {
    const pr = product(w, c, p.ref, p.name);
    const rep = partRep(w, c, p, styles);
    w.add(`SHAPE_DEFINITION_REPRESENTATION(${pr.pds},${rep.rep})`);
    parts[p.key] = { ...pr, ...rep };
  }
  const placements = model.instances.map((i) => {
    const T = i.T;
    return w.axis([T[0][3], T[1][3], T[2][3]], [T[0][2], T[1][2], T[2][2]], [T[0][0], T[1][0], T[2][0]]);
  });
  const rootOrigin = w.axis([0, 0, 0], [0, 0, 1], [1, 0, 0]);
  const rootRep = w.add(`SHAPE_REPRESENTATION(${S(model.product_code)},(${[rootOrigin, ...placements].join(",")}),${c.ctx})`);
  w.add(`SHAPE_DEFINITION_REPRESENTATION(${root.pds},${rootRep})`);
  model.instances.forEach((i, k) => {
    const pp = parts[i.part.key];
    const nauo = w.add(`NEXT_ASSEMBLY_USAGE_OCCURRENCE(${S(i.id)},${S(i.name)},'',${root.pd},${pp.pd},$)`);
    const pdsn = w.add(`PRODUCT_DEFINITION_SHAPE('','',${nauo})`);
    const idt = w.add(`ITEM_DEFINED_TRANSFORMATION('','',${pp.origin},${placements[k]})`);
    const rr = w.add(`( REPRESENTATION_RELATIONSHIP('','',${pp.rep},${rootRep}) REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(${idt}) SHAPE_REPRESENTATION_RELATIONSHIP() )`);
    w.add(`CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(${rr},${pdsn})`);
  });
  colours(w, c, styles, partColor(model));
  return finish(w, header(`${model.product_code}_conjunto.step`, info.designer ?? "", info.company ?? "MUEBLES MONXU",
    `Conjunto ${model.product_code}: ${model.instances.length} instancias de ${Object.keys(model.parts).length} piezas (sólidos facetados)`));
}

/** STEP de una pieza en sus coordenadas locales. */
export function partStep(model, part, info = {}) {
  const w = new Writer();
  const c = context(w);
  const pr = product(w, c, part.ref, part.name);
  const styles = [];
  const rep = partRep(w, c, part, styles);
  w.add(`SHAPE_DEFINITION_REPRESENTATION(${pr.pds},${rep.rep})`);
  colours(w, c, styles, partColor(model));
  return finish(w, header(`${part.ref}.step`, info.designer ?? "", info.company ?? "MUEBLES MONXU", `${part.ref} ${part.name}`));
}
