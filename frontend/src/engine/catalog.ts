// @ts-nocheck
// Catálogo técnico: los mismos ficheros JSON que usa el servidor (fuente única de datos).
import materialsJ from "../../../monxu/catalog/data/materials.json";
import profilesJ from "../../../monxu/catalog/data/profiles.json";
import sheetsJ from "../../../monxu/catalog/data/sheets.json";
import componentsJ from "../../../monxu/catalog/data/components.json";
import standardsJ from "../../../monxu/catalog/data/standards.json";
import criteriaJ from "../../../monxu/catalog/data/criteria.json";

export const versions = {
  materials: materialsJ._meta.version, profiles: profilesJ._meta.version, sheets: sheetsJ._meta.version,
  components: componentsJ._meta.version, standards: standardsJ._meta.version, criteria: criteriaJ._meta.version,
};

const matCache = {};
export function material(code) {
  if (matCache[code]) return matCache[code];
  const d = materialsJ.materials[code];
  if (!d) throw new Error(`Material desconocido: ${code}`);
  const m = {
    code, name: d.name, family: d.family, standard: d.standard, density: d.density, E: d.E ?? null, G: d.G ?? null,
    nu: d.nu ?? null, fy: d.fy ?? null, fu: d.fu ?? null, fy_guaranteed: !!d.fy_guaranteed, gamma_M0: d.gamma_M0 ?? 1.0,
    gamma_M1: d.gamma_M1 ?? 1.0, gamma_M2: d.gamma_M2 ?? 1.25, beta_w: d.beta_w ?? 1.0, design_code: d.design_code ?? null,
    weldable: !!d.weldable, render_color: d.render_color ?? [0.5, 0.5, 0.5], haz_reduction_required: !!d.haz_reduction_required,
    note: d.note ?? "", forms: d.forms ?? [],
  };
  m.structural = m.E != null && m.fy != null;
  matCache[code] = m;
  return m;
}
export const materials = () => Object.keys(materialsJ.materials).map(material);
export const finishes = () => materialsJ.finishes;
export function finish(code) {
  const f = materialsJ.finishes[code];
  if (!f) throw new Error(`Acabado desconocido: ${code}`);
  return f;
}

// --------------------------------------------------------------------- perfiles (EN 10219-2, Anexo B)
function outline(p, inner, seg = 24) {
  const [b, h, r] = inner ? [p.B - 2 * p.t, p.H - 2 * p.t, p.r_in] : [p.B, p.H, p.r_out];
  const pts = [];
  const corners = [[b / 2 - r, h / 2 - r, 0], [-b / 2 + r, h / 2 - r, 90], [-b / 2 + r, -h / 2 + r, 180], [b / 2 - r, -h / 2 + r, 270]];
  for (const [cx, cy, a0] of corners)
    for (let i = 0; i <= seg; i++) {
      const a = ((a0 + (90 * i) / seg) * Math.PI) / 180;
      pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
    }
  return pts;
}
function polyMoments(pts) {
  let A = 0, Ix = 0, Iy = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length];
    const c = x0 * y1 - x1 * y0;
    A += c; Ix += (y0 * y0 + y0 * y1 + y1 * y1) * c; Iy += (x0 * x0 + x0 * x1 + x1 * x1) * c;
  }
  return [A / 2, Ix / 12, Iy / 12];
}
function clipHalf(pts, axis) {
  const out = [];
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i], q = pts[(i + 1) % pts.length];
    const pin = p[axis] >= 0, qin = q[axis] >= 0;
    if (pin) out.push(p);
    if (pin !== qin) {
      const s = p[axis] / (p[axis] - q[axis]);
      out.push([p[0] + s * (q[0] - p[0]), p[1] + s * (q[1] - p[1])]);
    }
  }
  return out;
}
function firstMoment(pts, axis) {
  let S = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % pts.length];
    const c = x0 * y1 - x1 * y0;
    S += (axis === 1 ? y0 + y1 : x0 + x1) * c;
  }
  return S / 6;
}
const profCache = {};
export function profile(code) {
  if (profCache[code]) return profCache[code];
  const d = profilesJ.profiles[code];
  if (!d) throw new Error(`Perfil desconocido: ${code}`);
  const p = { code, type: d.type, B: +d.B, H: +d.H, t: +d.t, standard: d.standard };
  p.r_out = 2 * p.t; p.r_in = p.t;
  const out = outline(p, false), inn = outline(p, true);
  const [Ao, Ixo, Iyo] = polyMoments(out), [Ai, Ixi, Iyi] = polyMoments(inn);
  const A = Ao - Ai, Iy = Ixo - Ixi, Iz = Iyo - Iyi;
  const Wpl_y = 2 * (firstMoment(clipHalf(out, 1), 1) - firstMoment(clipHalf(inn, 1), 1));
  const Wpl_z = 2 * (firstMoment(clipHalf(out, 0), 0) - firstMoment(clipHalf(inn, 0), 0));
  const bm = p.B - p.t, hm = p.H - p.t, rm = (p.r_out + p.r_in) / 2;
  const Am = bm * hm - (4 - Math.PI) * rm * rm, pm = 2 * (bm + hm) - 2 * (4 - Math.PI) * rm;
  p.props = { A, Iy, Iz, Wel_y: Iy / (p.H / 2), Wel_z: Iz / (p.B / 2), Wpl_y, Wpl_z, iy: Math.sqrt(Iy / A),
    iz: Math.sqrt(Iz / A), It: (4 * Am * Am * p.t) / pm, Av_z: (A * p.H) / (p.B + p.H), Av_y: (A * p.B) / (p.B + p.H) };
  p.massPerM = (rho) => p.props.A * 1e-6 * rho;
  profCache[code] = p;
  return p;
}
export const profiles = () => Object.keys(profilesJ.profiles).map(profile);
export const profileMeta = () => profilesJ._meta;

// --------------------------------------------------------------------- chapa, componentes, normas
export const sheetData = () => sheetsJ;
export const sheetThicknesses = (code) => sheetsJ.thicknesses_mm[code] ?? [];
export const sheetFormats = () => sheetsJ.formats_mm;
export function din6935K(r, t) {
  const ratio = r / t;
  if (ratio >= 5) return 0.5;
  const k = 0.65 + 0.5 * Math.log10(ratio);
  return Math.max(0.2, Math.min(0.5, k / 2));
}
export const components = () => componentsJ.components;
export function component(code) {
  const c = componentsJ.components[code];
  if (!c) throw new Error(`Componente desconocido: ${code}`);
  return c;
}
export function series(name) {
  return Object.entries(componentsJ.components).filter(([, v]) => v.series === name)
    .sort((a, b) => (a[1].length ?? 0) - (b[1].length ?? 0) || (a[1].grip_max ?? 0) - (b[1].grip_max ?? 0));
}
export function selectRivetNut(wall, name = "REMACHABLE_M6") {
  for (const [code, c] of series(name)) if ((c.grip_min ?? 0) - 1e-9 <= wall && wall <= c.grip_max + 1e-9) return [code, c];
  return null;
}
export function selectScrew(clamp, reach, name = "ISO7380_M6") {
  for (const [code, c] of series(name)) if (c.length >= clamp + c.d - 1e-9 && c.length <= reach + 1e-9) return [code, c];
  return null;
}
export const consumables = () => componentsJ.consumables;
export const criteria = () => criteriaJ;
export function standards(family) {
  return standardsJ.standards.filter((s) => s.families.includes("*") || s.families.includes(family))
    .filter((s) => s.markets.includes("*") || s.markets.includes("EU"));
}
