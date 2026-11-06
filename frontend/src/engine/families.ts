// @ts-nocheck
// Familias de producto (port exacto de monxu/families/mesa_industrial.py y estanteria.py).
import * as C from "./catalog";
import { AUTO, ParamContext, ParamError, ProductModel, axisFrame, frameZ, newParams, platePart, profilePart, sheetPart,
  standardPart, translation, sub, scale } from "./model";
import { EDGES, bendDeduction, makeSpec, perforationGrid } from "./sheet";
import { f as fx, g, pad2, pyRound, range } from "./util";
import FAM from "./data/families.json";

export const library = () => FAM.library;
export const familyDefs = FAM.families;

export function flangeHoleD(matCode, t, screw) {
  const fam = C.material(matCode).family;
  const dmin = (C.sheetData().laser.min_hole_diameter_factor[fam] ?? 1.0) * t;
  return pyRound(Math.max(screw.clearance_hole, Math.ceil(dmin * 10) / 10), 1);
}
const roundedPerimeter = (B, H, r) => 2 * (B + H) - (8 - 2 * Math.PI) * r;
export function evenPositions(a, b, n) {
  if (n === 1) return [(a + b) / 2];
  return range(n).map((i) => a + (i * (b - a)) / (n - 1));
}
const weldA = (tmin) => (tmin >= 3 ? 3.0 : +tmin);
const pt = (p) => p.map(Number);

// ============================================================================ base común (mesa)
class MesaIndustrial {
  constructor(id = "mesa_industrial") {
    const d = FAM.families[id];
    Object.assign(this, { id, name: d.name, category: d.category, description: d.description, def: d,
      candidates: d.candidates, constructive_defaults: d.constructive_defaults, leg_param: d.leg_param,
      frame_params: d.frame_params, auto_in_construct: d.auto_in_construct, verification_inputs: d.verification_inputs,
      support_param: "PIE_NIVELADOR", support_category: "patas", support_group: ["APO", "Apoyos niveladores"] });
  }
  specs() { return this.def.params; }
  templates() { return this.def.templates; }
  describe() { const { templates, candidates, constructive_defaults, leg_param, frame_params, auto_in_construct, ...r } = this.def; return r; }
  newParams(values = {}, sources = {}) { return newParams(this.specs(), values, sources); }

  paramForRole(role) {
    return { pata: "PERFIL_PATA", larguero_sup: "PERFIL_LARGUERO", travesano_ext_sup: "PERFIL_TRAVESANO",
      travesano_int_sup: "PERFIL_TRAVESANO", larguero_inf: "PERFIL_BASTIDOR", travesano_ext_inf: "PERFIL_BASTIDOR",
      travesano_int_inf: "PERFIL_BASTIDOR" }[role] ?? null;
  }
  verticalLoadPresent(v) { return !!v.CARGA_TOTAL; }
  plateTargets(v) {
    const out = [];
    if (v.CARGA_TOTAL) out.push({ surface: "encimera", t_param: "ESPESOR_CHAPA", n_param: "NUMERO_TRAVESANOS",
      load_param: "CARGA_TOTAL", trv_param: "PERFIL_TRAVESANO", min_t_by_use: true });
    if (v.CARGA_BALDA && (v.NUMERO_BALDAS ?? 0) >= 1) out.push({ surface: "balda", t_param: "ESPESOR_BALDA",
      n_param: "NUMERO_TRAVESANOS_BALDA", load_param: "CARGA_BALDA", trv_param: "PERFIL_BASTIDOR", min_t_by_use: false });
    return out;
  }
  sheetDefaultsWithoutLoad(v) {
    const out = {};
    if (!v.CARGA_TOTAL) out.ESPESOR_CHAPA = this.constructive_defaults.ESPESOR_CHAPA;
    if (!(v.CARGA_BALDA && (v.NUMERO_BALDAS ?? 0) >= 1)) out.ESPESOR_BALDA = this.constructive_defaults.ESPESOR_BALDA;
    return out;
  }
  checkResolved(ps) {
    for (const [k, v] of Object.entries(ps.values))
      if (v === AUTO && !this.auto_in_construct.includes(k)) throw new Error(`Parámetro sin resolver: ${k}`);
  }

  // ------------------------------------------------------------------ construcción
  construct(ps) {
    this.checkResolved(ps);
    const ctx = new ParamContext(ps);
    const V = ps.values;
    const L = V.LONGITUD, W = V.ANCHURA, H = V.ALTURA;
    const model = new ProductModel(this.id, this.name, `${this.def.prefix ?? "MI"}${fx(L)}-${fx(W)}-${fx(H)}`, ps, ctx);
    model.requested = ps;
    const d = this._derive(ctx, model);
    const mat_s = V.MATERIAL_ESTRUCTURAL, mat_c = V.MATERIAL_CHAPA, fin = V.ACABADO;
    model.addSub("EST", "Estructura soldada", { welded: true, step: 1 });
    model.addSub(this.support_group[0], this.support_group[1], { explode: [0, 0, -160], step: 2 });
    if (d.shelf) model.addSub("BAL", "Balda inferior", { explode: [0, 0, 90], step: 3 });
    model.addSub("ENC", "Encimera", { explode: [0, 0, 380], step: 4 });
    const { leg, rail, trv, bas, c, a } = d;
    const legs = {};
    const corners = { DI: [c + a / 2, c + a / 2], DD: [L - c - a / 2, c + a / 2], TI: [c + a / 2, W - c - a / 2], TD: [L - c - a / 2, W - c - a / 2] };
    const cname = { DI: "delantera izquierda", DD: "delantera derecha", TI: "trasera izquierda", TD: "trasera derecha" };
    const foot = C.component(V[this.support_param]);
    const thread = parseFloat(foot.thread.slice(1));
    const nutCode = `TUERCA_SOLDAR_M${fx(thread)}`;
    const rn = C.component("TUERCA_REMACHABLE_M6");
    const sc = C.component("TORNILLO_ISO7380_M6x12");
    const weld = makeWelder(model);

    ctx.feature("F10", "Estructura soldada", () => {
      ctx.feature("F11", "Patas, placas base y tuercas", () => {
        ctx.uses("LONGITUD_PATA", "PERFIL_PATA", "RETRANQUEO", "LONGITUD", "ANCHURA", "ESPESOR_PLACA_BASE", this.support_param,
          "MATERIAL_ESTRUCTURAL", "ACABADO", ...this._legUses());
        legsAndPlates(model, d, legs, corners, cname, mat_s, fin, thread, nutCode, "pata", `Pata ${leg.code}`, "EST.PATA",
          "Pata", "Placa base a pata", d.z_tf, (k) => this._legDef(k, d, leg));
      });
      ctx.feature("F12", "Bastidor superior", () => {
        ctx.uses("LONGITUD_LARGUERO", "LONGITUD_TRAVESANO_EXT", "LONGITUD_TRAVESANO_INT", "N_TRAVESANOS_INT", "PERFIL_LARGUERO",
          "PERFIL_TRAVESANO", "COTA_BASTIDOR_SUP", "PASO_FIJACIONES", "ALA_ENCIMERA", "MATERIAL_ESTRUCTURAL", "ACABADO");
        frameLevel(model, d, "SUP", d.z_tf, rail, trv, 0.0, d.n_top, legs, d.fix_top, weld, mat_s, fin);
      });
      if (d.shelf) ctx.feature("F13", "Bastidor inferior", () => {
        ctx.uses("PERFIL_BASTIDOR", "N_TRAVESANOS_BALDA", "COTA_BALDA", "ESP_BAL", "LONGITUD", "ANCHURA", "RETRANQUEO",
          "PERFIL_PATA", "PASO_FIJACIONES", "ALA_BALDA", "MATERIAL_ESTRUCTURAL");
        frameLevel(model, d, "INF", d.z_lf, bas, bas, d.e_shelf, d.n_shelf, legs, d.fix_shelf, weld, mat_s, fin);
      });
    });
    ctx.feature("F40", this.support_group[1], () => {
      ctx.uses(this.support_param, "LONGITUD", "ANCHURA", "RETRANQUEO", "PERFIL_PATA");
      feet(model, d, corners, cname, V[this.support_param], foot, this.support_group[0], (k) => this._supportPart(k, V));
    });
    ctx.feature("F20", "Encimera de chapa plegada", () => {
      ctx.uses("LONGITUD", "ANCHURA", "ALTURA", "ESP_ENC", "RADIO_ENC", "K_ENC", "ALA_ENCIMERA", "MATERIAL_CHAPA",
        "PASO_FIJACIONES", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ACABADO", "PETO_TRASERO");
      const spec = d.top_spec;
      model.add("ENC.BANDEJA", "Encimera", sheetPart("encimera", `Encimera chapa ${g(spec.t)} mm`, spec, mat_c, fin), translation(0, 0, H), "ENC");
      fasteners(model, d.fix_top, "ENC");
    });
    if (d.shelf) ctx.feature("F30", "Balda inferior de chapa plegada", () => {
      ctx.uses("LONGITUD", "ANCHURA", "COTA_BALDA", "ESP_BAL", "ALA_BALDA", "MATERIAL_CHAPA", "PERFIL_PATA",
        "HOLGURA_ESCOTADURA", "PERFIL_BASTIDOR", "ACABADO");
      const spec = d.shelf_spec;
      model.add("BAL.BANDEJA", "Balda inferior", sheetPart("balda", `Balda chapa ${g(spec.t)} mm`, spec, mat_c, fin), translation(c, c, d.z_shelf), "BAL");
      fasteners(model, d.fix_shelf, "BAL");
    });
    this._extras(model, ctx, d, legs, corners);
    model.structure = this._structure(model, d, legs);
    const peto = d.peto;
    const levels = d.shelf ? [["ALTURA_BALDA", "BAL.BANDEJA"]] : [];
    if (peto > 0) levels.push(["ALTURA_ENCIMERA", "ENC.BANDEJA", H], ...this._petoLevel(d, H));     // altura de trabajo y peto en la cadena
    model.dims = { LONGITUD: L, ANCHURA: W, ALTURA: H, ALTURA_BALDA: d.shelf ? d.z_shelf : null, LONGITUD_PATA: d.leg_len,
      envelope: { ids: ["ENC.BANDEJA"], dx: L, dy: W, zmax: H + peto, names: ["LONGITUD", "ANCHURA"] },
      levels,
      load_text: `Carga distribuida de proyecto sobre encimera: ${V.CARGA_TOTAL ? pyStr(V.CARGA_TOTAL) + " kg" : "NO DEFINIDA"}` };
    if (peto > 0) {
      const zs = [0.0, ...(d.shelf ? [d.z_shelf] : []), H, H + peto];
      model.dims.ALTURA_ENCIMERA = H;
      model.dims.drawing_expected = Object.fromEntries(levels.map((_, k) => [`DIST_NIVEL_${k + 1}`, zs[k + 1] - zs[k]]));
    }
    this._extraDims(model, d);
    model.numberParts();
    return model;
  }

  // ------------------------------------------------------------------ ganchos para familias derivadas
  _legUses() { return []; }
  /** [rol, nombre, cota superior, taladros] de la pata de cada esquina. */
  _legDef(corner, d, leg) { return ["pata", "Pata", d.z_tf, []]; }
  _supportPart(corner, V) { return [standardPart("pie_nivelador", V[this.support_param]), "Pie nivelador"]; }
  /** Escotaduras de la encimera: [[nx, ny], esquinas] o null. */
  _topNotch(ctx, d) { return null; }
  _extras(model, ctx, d, legs, corners) {}
  _extraDims(model, d) {}
  /** Nivel de cota de la cara superior del peto trasero (vacío si no hay peto). */
  _petoLevel(d, H) { return d.peto > 0 ? [["COTA_PETO", "ENC.BANDEJA", H + d.peto]] : []; }

  _derive(ctx, model) {
    const v = ctx.params.values;
    const d = {};
    ctx.feature("F00", "Parámetros derivados y reglas constructivas", () => {
      const fam = C.material(v.MATERIAL_CHAPA).family;
      const rmin = C.sheetData().press_brake.min_inner_radius_factor[fam] ?? 1.0;
      const radius = (t) => (v.RADIO_PLEGADO !== AUTO ? v.RADIO_PLEGADO : pyRound(Math.max(t, rmin * t), 2));
      const kf = (r, t) => (v.FACTOR_K !== AUTO ? v.FACTOR_K : pyRound(C.din6935K(r, t), 4));
      const t = ctx.derive("ESP_ENC", (p) => p.get("ESPESOR_CHAPA"), "mm", "Espesor encimera");
      const r = ctx.derive("RADIO_ENC", (p) => (p.get("RADIO_PLEGADO") === AUTO ? radius(p.get("ESP_ENC")) : p.get("RADIO_PLEGADO")),
        "mm", "Radio interior de plegado (encimera)");
      const K = ctx.derive("K_ENC", (p) => (p.get("FACTOR_K") === AUTO ? kf(p.get("RADIO_ENC"), p.get("ESP_ENC")) : p.get("FACTOR_K")),
        null, "Factor K (encimera)");
      ctx.derive("DEDUCCION_PLEGADO_ENC", (p) => pyRound(bendDeduction(p.get("ESP_ENC"), p.get("RADIO_ENC"), p.get("K_ENC")), 4),
        "mm", "Deducción de plegado 90° (encimera)");
      const head_h = +C.component("TUERCA_REMACHABLE_M6").head_h;
      const gg = ctx.derive("HOLGURA_ENC", (p) => (p.get("HOLGURA_ENCIMERA") === AUTO ? Math.max(p.get("RADIO_ENC"), head_h)
        : p.get("HOLGURA_ENCIMERA")), "mm", "Holgura estructura–pestaña (encimera)");
      if (gg < r - 1e-9) model.note("error", "GEO-HOLGURA-RADIO", `Holgura ${pyStr(gg)} mm menor que el radio interior de plegado `
        + `${pyStr(r)} mm: las aristas del bastidor interfieren con el pliegue de la encimera.`);
      const c = ctx.derive("RETRANQUEO", (p) => p.get("ESP_ENC") + p.get("HOLGURA_ENC"), "mm", "Retranqueo de la estructura respecto al canto exterior");
      const leg = C.profile(ctx.get("PERFIL_PATA")), rail = C.profile(ctx.get("PERFIL_LARGUERO"));
      const trv = C.profile(ctx.get("PERFIL_TRAVESANO")), bas = C.profile(ctx.get("PERFIL_BASTIDOR"));
      if (leg.B !== leg.H) throw new Error("Las patas deben ser de tubo cuadrado");
      const a = leg.B;
      ctx.setDerived("SECCION_PATA", `${g(leg.B)}x${g(leg.H)}`, "mm", "Sección de pata", ["PERFIL_PATA"]);
      ctx.setDerived("ESPESOR_PERFIL_PATA", leg.t, "mm", "Espesor de pata", ["PERFIL_PATA"]);
      const foot = C.component(ctx.get(this.support_param));
      const hn = +foot.nominal_height;
      const tp = ctx.get("ESPESOR_PLACA_BASE");
      const z_tf = ctx.derive("COTA_BASTIDOR_SUP", (p) => p.get("ALTURA") - p.get("ESP_ENC"), "mm", "Cota cara superior del bastidor");
      const sp = this.support_param;
      const z_leg0 = ctx.derive("COTA_INICIO_PATA", (p) => +C.component(p.get(sp)).nominal_height + p.get("ESPESOR_PLACA_BASE"),
        "mm", "Cota inicio de pata");
      const leg_len = ctx.derive("LONGITUD_PATA", (p) => p.get("COTA_BASTIDOR_SUP") - p.get("COTA_INICIO_PATA"), "mm", "Longitud de corte de pata");
      const L = ctx.get("LONGITUD"), W = ctx.get("ANCHURA"), H = ctx.get("ALTURA");
      ctx.derive("LONGITUD_LARGUERO", (p) => p.get("LONGITUD") - 2 * p.get("RETRANQUEO") - 2 * C.profile(p.get("PERFIL_PATA")).B, "mm", "Longitud de largueros");
      ctx.derive("LONGITUD_TRAVESANO_EXT", (p) => p.get("ANCHURA") - 2 * p.get("RETRANQUEO") - 2 * C.profile(p.get("PERFIL_PATA")).B, "mm",
        "Longitud de travesaños extremos");
      ctx.derive("LONGITUD_TRAVESANO_INT", (p) => p.get("ANCHURA") - 2 * p.get("RETRANQUEO") - 2 * C.profile(p.get("PERFIL_LARGUERO")).B, "mm",
        "Longitud de travesaños intermedios");
      if (rail.B > a || trv.B > a) model.note("error", "DFM-ANCHO-BASTIDOR", "El ancho de largueros/travesaños supera el de la pata: "
        + "no pueden enrasarse con la cara exterior.");
      const xe0 = c + trv.B / 2, xe1 = L - c - trv.B / 2;
      let n_top = ctx.get("NUMERO_TRAVESANOS");
      if (n_top === AUTO) n_top = Math.max(0, Math.ceil((xe1 - xe0) / ctx.get("SEPARACION_MAX_APOYOS")) - 1);
      ctx.setDerived("N_TRAVESANOS_INT", n_top, "ud", "Travesaños intermedios", ["NUMERO_TRAVESANOS", "SEPARACION_MAX_APOYOS", "LONGITUD"]);
      ctx.setDerived("VANO_ENCIMERA", pyRound((xe1 - xe0) / (n_top + 1), 2), "mm", "Vano entre apoyos de encimera",
        ["LONGITUD", "NUMERO_TRAVESANOS", "PERFIL_TRAVESANO", "RETRANQUEO"]);
      const shelf = ctx.get("NUMERO_BALDAS") >= 1;
      Object.assign(d, { Lx: L, Ly: W, leg, rail, trv, bas, a, c, t, r, K, hn, tp, z_tf, z_leg0, leg_len, n_top, xe: [xe0, xe1], shelf });
      const rn = C.component("TUERCA_REMACHABLE_M6");
      const sc = C.component("TORNILLO_ISO7380_M6x12");
      if (rn.head_h > gg + 1e-9) model.note("error", "DFM-HOLGURA-REMACHABLE", `La cabeza de la tuerca remachable (${pyStr(rn.head_h)} mm) `
        + `no cabe en la holgura de ${pyStr(gg)} mm.`);
      const ala = ctx.get("ALA_ENCIMERA"), pitch = ctx.get("PASO_FIJACIONES");
      const hd = flangeHoleD(v.MATERIAL_CHAPA, t, sc);
      const fix_top = fixLayout(model, L, W, c, a, t, r + t, ala, rail, trv, H, 0.0, hd, rn, pitch, 2, "encimera");
      fix_top.gap = gg;
      const peto = v.PETO_TRASERO || 0.0;
      if (peto > 0) {     // peto trasero: pestaña hacia arriba, sin fijaciones en ese borde
        fix_top.s.y1 = [];
        ctx.derive("COTA_PETO", (p) => p.get("ALTURA") + p.get("PETO_TRASERO"), "mm", "Cota superior del peto trasero");
      }
      d.peto = peto;
      const tn = this._topNotch(ctx, d);
      d.top_spec = makeSpec({ Lx: L, Ly: W, t, r, K, flanges: EDGES.map((e) => (e === "y1" && peto > 0
        ? { edge: e, height: peto + t, direction: "up", holes: [] }
        : { edge: e, height: ala, direction: "down", holes: fix_top.s[e].map((s) => [s, fix_top.h[e], hd]) })),
      ...(tn ? { notch: tn[0], notchCorners: tn[1] } : {}) });
      d.fix_top = fix_top;
      if (shelf) {
        const ts = ctx.derive("ESP_BAL", (p) => p.get("ESPESOR_BALDA"), "mm", "Espesor balda");
        const rs = radius(ts), Ks = kf(rs, ts);
        const z_s = ctx.derive("COTA_BALDA", (p) => p.get("ALTURA_BALDA"), "mm", "Cota cara superior de balda");
        const g_s = ctx.derive("HOLGURA_BAL", (p) => (p.get("HOLGURA_ENCIMERA") === AUTO ? Math.max(rs, head_h) : p.get("HOLGURA_ENCIMERA")),
          "mm", "Holgura bastidor–pestaña (balda)");
        if (g_s < rs - 1e-9) model.note("error", "GEO-HOLGURA-RADIO-BAL", "Holgura menor que el radio de plegado de la balda.");
        const e_sh = ts + g_s, z_lf = z_s - ts;
        const notch = a + ctx.get("HOLGURA_ESCOTADURA");
        const xb0 = c + e_sh + bas.B / 2, xb1 = L - c - e_sh - bas.B / 2;
        let n_sh = ctx.get("NUMERO_TRAVESANOS_BALDA");
        if (n_sh === AUTO) n_sh = Math.max(0, Math.ceil((xb1 - xb0) / ctx.get("SEPARACION_MAX_APOYOS")) - 1);
        ctx.setDerived("N_TRAVESANOS_BALDA", n_sh, "ud", "Travesaños bajo balda", ["NUMERO_TRAVESANOS_BALDA", "LONGITUD"]);
        if (e_sh + bas.B > a) model.note("error", "DFM-BASTIDOR-INF", "El bastidor inferior retranqueado no cabe en la sección de la pata.");
        if (z_lf - bas.H < z_leg0 + 20) model.note("error", "GEO-BALDA-BAJA", "La balda está demasiado baja para el bastidor inferior.");
        const ala_b = ctx.get("ALA_BALDA");
        const hds = flangeHoleD(v.MATERIAL_CHAPA, ts, sc);
        const fix_sh = fixLayout(model, L - 2 * c, W - 2 * c, 0.0, a, ts, rs + ts, ala_b, bas, bas, z_s, e_sh, hds, rn, pitch * 1.5, 1,
          "balda", notch, c);
        fix_sh.gap = g_s;
        d.shelf_spec = makeSpec({ Lx: L - 2 * c, Ly: W - 2 * c, t: ts, r: rs, K: Ks, notch: [notch, notch],
          flanges: EDGES.map((e) => ({ edge: e, height: ala_b, direction: "down", holes: fix_sh.s[e].map((s) => [s, fix_sh.h[e], hds]) })) });
        Object.assign(d, { z_shelf: z_s, z_lf, e_shelf: e_sh, n_shelf: n_sh, xb: [xb0, xb1], fix_shelf: fix_sh });
        if (z_s > d.z_tf - ctx.get("ALA_ENCIMERA") - 150) model.note("advertencia", "ERG-BALDA-ALTA", "Hueco libre entre balda y encimera inferior a 150 mm.");
      }
      if (H - ctx.get("ALA_ENCIMERA") < 600) model.note("advertencia", "ERG-ALTURA", "Altura libre bajo encimera inferior a 600 mm.");
    });
    return d;
  }

  _structure(model, d, legs) {
    const ps = model.params.values;
    const surfaces = [{ id: "encimera", label: "Encimera", level: "SUP", load_param: "CARGA_TOTAL", sheet_instance: "ENC.BANDEJA",
      area_mm2: ps.LONGITUD * ps.ANCHURA, count_param: "NUMERO_TRAVESANOS" }];
    if (d.shelf) surfaces.push({ id: "balda", label: "Balda inferior", level: "INF", load_param: "CARGA_BALDA", sheet_instance: "BAL.BANDEJA",
      area_mm2: (ps.LONGITUD - 2 * d.c) * (ps.ANCHURA - 2 * d.c), count_param: "NUMERO_TRAVESANOS_BALDA" });
    return { levels: model.structure.levels ?? {}, surfaces, supports: supportsOf(model, legs, this.support_group[0]), horizontal_points: [legs.DI, legs.DD],
      worktop_height: ps.ALTURA, leg_ids: Object.values(legs), member_roles: memberRoles(model) };
  }
}

const pyStr = (x) => (Number.isInteger(x) ? `${x}.0` : String(x));   // str(float) de Python
const supportsOf = (model, legs, g = "APO") => ["DI", "DD", "TI", "TD"].map((k) => ({ instance: `${g}.PIE.${k}`, leg: legs[k],
  point: [...model.instance(legs[k]).axis[0]], component: model.instance(`${g}.PIE.${k}`).part.code }));
const memberRoles = (model) => Object.fromEntries(model.instances.filter((i) => i.structural).map((i) => [i.id, i.role]));

function legsAndPlates(model, d, legs, corners, cname, mat_s, fin, thread, nutCode, role, partName, idPrefix, word, weldDesc, zTop, legDef = null) {
  const { leg, a, tp, hn } = d;
  const legPart = legDef ? null : profilePart(role, partName, leg.code, d.leg_len, mat_s, fin);
  const legParts = new Map();
  const plateMat = C.material(mat_s).family === "acero_carbono" ? "S235JR" : mat_s;
  const plate = platePart("placa_base", `Placa base ${fx(a)}x${fx(a)}x${fx(tp)}`, a, a, tp, plateMat, fin, Math.min(3.0, a / 10),
    [[a / 2, a / 2, thread + 1.0]]);
  const nut = standardPart("tuerca_soldar", nutCode);
  for (const [k, [x, y]] of Object.entries(corners)) {
    const iid = `${idPrefix}.${k}`;
    let part = legPart, top = zTop, w = word;
    if (legDef) {
      const [rl, pname, zt, holes] = legDef(k);
      const pk = JSON.stringify([rl, pyRound(zt, 4), holes]);
      if (!legParts.has(pk)) legParts.set(pk, profilePart(rl, `${pname} ${leg.code}`, leg.code, zt - d.z_leg0, mat_s, fin, holes));
      part = legParts.get(pk); top = zt; w = pname;
    }
    const p0 = [x, y, d.z_leg0], p1 = [x, y, top];
    model.add(iid, `${w} ${cname[k]}`, part, axisFrame(p0, p1, [0, 1, 0]), "EST", { axis: [p0, p1], up: [0, 1, 0], structural: true });
    legs[k] = iid;
    model.add(`EST.PLACA.${k}`, `Placa base ${cname[k]}`, plate, translation(x - a / 2, y - a / 2, hn), "EST");
    model.add(`EST.TUERCA.${k}`, `Tuerca soldada ${cname[k]}`, nut, translation(x, y, hn + tp), "EST");
    model.joint({ id: `J.PLACA.${k}`, kind: "soldadura", members: [iid, `EST.PLACA.${k}`], location: [x, y, d.z_leg0], description: weldDesc,
      weld: { type: "fillet", a: weldA(Math.min(leg.t, tp)), all_around: true, process: "135 (MAG)",
        length: pyRound(roundedPerimeter(a, a, leg.r_out), 1) } });
    const s = +C.component(nutCode).s;
    model.joint({ id: `J.TUERCA.${k}`, kind: "soldadura", members: [`EST.TUERCA.${k}`, `EST.PLACA.${k}`], location: [x, y, hn + tp],
      description: "Tuerca de soldar a placa base", weld: { type: "fillet", a: 2.0, all_around: false, process: "135 (MAG)",
        length: pyRound((3 * s) / Math.sqrt(3), 1), note: "3 cordones en caras alternas de la tuerca" } });
  }
}

function feet(model, d, corners, cname, code, foot, g = "APO", partOf = null) {
  const shared = partOf ? null : standardPart("pie_nivelador", code);
  for (const [k, [x, y]] of Object.entries(corners)) {
    const [fpart, fname] = partOf ? partOf(k) : [shared, "Pie nivelador"];
    model.add(`${g}.PIE.${k}`, `${fname} ${cname[k]}`, fpart, translation(x, y, 0.0), g);
    model.joint({ id: `J.PIE.${k}`, kind: "roscada", members: [`${g}.PIE.${k}`, `EST.TUERCA.${k}`], location: [x, y, d.hn],
      description: partOf ? `${fname} roscado ${foot.thread} en tuerca soldada` : `Pie roscado ${foot.thread} en tuerca soldada` });
  }
}

function makeWelder(model) {
  return (jid, a_id, end, b_id, prof, desc) => {
    const tmin = Math.min(model.instance(a_id).part.profile.t, model.instance(b_id).part.profile.t);
    const loc = model.instance(a_id).axis[end];
    model.joint({ id: jid, kind: "soldadura", members: [a_id, b_id], location: pt(loc), description: desc,
      weld: { type: "fillet", a: weldA(tmin), all_around: true, length: pyRound(roundedPerimeter(prof.B, prof.H, prof.r_out), 1),
        process: "135 (MAG)", fem: { member: a_id, end, onto: b_id } } });
  };
}

function fixLayout(model, Lx, Ly, c, a, t, R, ala, prof_long, prof_end, z_ref, inset, hole_d, rn, pitch, short_min, tag, notch = 0.0, offset = 0.0, ranges = null, profs = null) {
  const margin = 60.0;
  const long_rng = [c + a + margin, Lx - c - a - margin];
  const short_rng = [c + a + margin / 2, Ly - c - a - margin / 2];
  const count = (span, nmin) => Math.max(nmin, Math.ceil(span / pitch) + 1);
  const n_long = count(long_rng[1] - long_rng[0], 2);
  const n_short = count(short_rng[1] - short_rng[0], short_min);
  const s = { y0: evenPositions(...long_rng, n_long), y1: evenPositions(...long_rng, n_long),
    x0: evenPositions(...short_rng, n_short), x1: evenPositions(...short_rng, n_short) };
  for (const [e, [s0, s1, nmin]] of Object.entries(ranges ?? {})) s[e] = evenPositions(s0, s1, count(s1 - s0, nmin));
  const h = {};
  const word = tag.split(/\s+/)[0];
  const profOf = (e) => profs?.[e] ?? (e === "y0" || e === "y1" ? prof_long : prof_end);
  for (const e of EDGES) {
    const prof = profOf(e);
    const fl_lo = R + 2 * t + hole_d / 2, fl_hi = ala - Math.max(t, 3.0) - hole_d / 2;
    const depth0 = t;
    const rail_lo = depth0 + prof.r_out + rn.hole_d / 2;
    const rail_hi = depth0 + prof.H - prof.r_out - rn.hole_d / 2;
    const lo = Math.max(fl_lo, rail_lo), hi = Math.min(fl_hi, rail_hi);
    if (lo > hi) {
      const ala_min = Math.max(fl_lo, rail_lo) + Math.max(t, 3.0) + hole_d / 2;
      const fix = rail_hi >= fl_lo ? `Aumentar la pestaña a ${fx(ala_min)} mm como mínimo`
        : `El perfil ${prof.code} es demasiado bajo para el taladro: usar un perfil de mayor canto`;
      const code = `DFM-FIJ-${word.toUpperCase()}`;
      if (!model.design_notes.some((n) => n.code === code))
        model.note("error", code, `No hay zona válida para el taladro de fijación de ${word}: pestaña de ${g(ala)} mm, chapa de ${g(t)} mm `
          + `(Ri+t = ${g(R)} mm) y perfil ${prof.code}. ${fix}.`, { min_flange: pyRound(ala_min, 1) });
      h[e] = pyRound((rail_lo + rail_hi) / 2, 1);
    } else h[e] = pyRound((lo + hi) / 2, 1);
  }
  const wall = Object.fromEntries(EDGES.map((e) => [e, profOf(e).t]));
  return { s, h, z_ref, t, inset, offset, Lx, Ly, c, wall };
}

function frameLevel(model, d, level, z_top, prof_long, prof_end, inset, n_int, legs, fixings, weld, mat, fin, label = null) {
  const L = d.Lx, W = d.Ly, c = d.c, a = d.a;
  const lab = label || (level === "SUP" ? "superior" : "inferior");
  const holeD = C.component("TUERCA_REMACHABLE_M6").hole_d;
  const zl = z_top - prof_long.H / 2;
  const y_f = c + inset + prof_long.B / 2, y_b = W - c - inset - prof_long.B / 2;
  const x0 = c + a, x1 = L - c - a;
  let hz = fixings.z_ref - fixings.h.y0;
  const offs = fixings.offset;
  const holes_long = fixings.s.y0.map((s) => ["-x", s + offs - x0, hz - zl, holeD]);
  const lp = profilePart(`larguero_${level.toLowerCase()}`, `Larguero ${lab} ${prof_long.code}`, prof_long.code, x1 - x0, mat, fin, holes_long);
  let lpRear = lp;
  const sameS = fixings.s.y1.length === fixings.s.y0.length && fixings.s.y1.every((s, i) => s === fixings.s.y0[i]);
  if (!sameS || fixings.h.y1 !== fixings.h.y0) {
    // fijaciones traseras distintas de las delanteras (p. ej. peto trasero sin fijaciones): pieza propia
    const hzb = fixings.z_ref - fixings.h.y1;
    const holesRear = [...fixings.s.y1].reverse().map((s) => ["-x", x1 - (s + offs), hzb - zl, holeD]);
    lpRear = profilePart(`larguero_${level.toLowerCase()}`, `Larguero ${lab} trasero ${prof_long.code}`, prof_long.code, x1 - x0, mat, fin, holesRear);
  }
  const long_ids = [];
  for (const [k, nm, p0, p1, l0, l1, part] of [["D", "delantero", [x0, y_f, zl], [x1, y_f, zl], "DI", "DD", lp],
    ["T", "trasero", [x1, y_b, zl], [x0, y_b, zl], "TD", "TI", lpRear]]) {
    const iid = `EST.LAR_${level}.${k}`;
    model.add(iid, `Larguero ${lab} ${nm}`, part, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
    weld(`J.${iid}.0`, iid, 0, legs[l0], prof_long, `Larguero ${lab} ${nm} a pata`);
    weld(`J.${iid}.1`, iid, 1, legs[l1], prof_long, `Larguero ${lab} ${nm} a pata`);
    long_ids.push(iid);
  }
  const ze = z_top - prof_end.H / 2;
  const x_l = c + inset + prof_end.B / 2, x_r = L - c - inset - prof_end.B / 2;
  const y0 = c + a, y1 = W - c - a;
  hz = fixings.z_ref - fixings.h.x0;
  const holes_end = fixings.s.x0.map((s) => ["+x", s + offs - y0, hz - ze, holeD]);
  const ep = profilePart(`travesano_ext_${level.toLowerCase()}`, `Travesaño extremo ${lab} ${prof_end.code}`, prof_end.code, y1 - y0, mat, fin, holes_end);
  const end_ids = [];
  for (const [k, nm, p0, p1, l0, l1] of [["I", "izquierdo", [x_l, y0, ze], [x_l, y1, ze], "DI", "TI"],
    ["D", "derecho", [x_r, y1, ze], [x_r, y0, ze], "TD", "DD"]]) {
    const iid = `EST.TRV_${level}.${k}`;
    model.add(iid, `Travesaño extremo ${lab} ${nm}`, ep, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
    weld(`J.${iid}.0`, iid, 0, legs[l0], prof_end, `Travesaño extremo ${lab} ${nm} a pata`);
    weld(`J.${iid}.1`, iid, 1, legs[l1], prof_end, `Travesaño extremo ${lab} ${nm} a pata`);
    end_ids.push(iid);
  }
  const xs = range(n_int).map((i) => x_l + ((i + 1) * (x_r - x_l)) / (n_int + 1));
  const yi0 = c + inset + prof_long.B, yi1 = W - c - inset - prof_long.B;
  const int_ids = [];
  if (n_int) {
    const ip = profilePart(`travesano_int_${level.toLowerCase()}`, `Travesaño intermedio ${lab} ${prof_end.code}`, prof_end.code, yi1 - yi0, mat, fin);
    xs.forEach((x, n0) => {
      const n = n0 + 1;
      const iid = `EST.TRI_${level}.${pad2(n)}`;
      const p0 = [x, yi0, ze], p1 = [x, yi1, ze];
      model.add(iid, `Travesaño intermedio ${lab} ${n}`, ip, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
      weld(`J.${iid}.0`, iid, 0, long_ids[0], prof_end, `Travesaño intermedio ${lab} a larguero`);
      weld(`J.${iid}.1`, iid, 1, long_ids[1], prof_end, `Travesaño intermedio ${lab} a larguero`);
      int_ids.push(iid);
    });
  }
  model.structure.levels = model.structure.levels ?? {};
  model.structure.levels[level] = { long: long_ids, end: end_ids, int: int_ids, grid_x: [x_l, ...xs, x_r], grid_y: [y_f, y_b], z: z_top };
}

function fasteners(model, fix, group, prefix = null, tray_id = null) {
  const { t, offset: off, Lx, Ly, gap } = fix;
  const [ox, oy] = Array.isArray(off) ? off : [off, off];
  let n = 0;
  for (const e of EDGES) {
    const wall = fix.wall?.[e] ?? 2.0;
    const sel_rn = C.selectRivetNut(wall);
    const [code_rn, rnd] = sel_rn ?? ["TUERCA_REMACHABLE_M6", C.component("TUERCA_REMACHABLE_M6")];
    const sel_sc = C.selectScrew(t + gap, t + gap + rnd.body_l);
    const code_sc = sel_sc ? sel_sc[0] : "TORNILLO_ISO7380_M6x12";
    const rn_part = standardPart("tuerca_remachable", code_rn);
    const sc_part = standardPart("tornillo", code_sc);
    for (const s of fix.s[e]) {
      n += 1;
      const z = fix.z_ref - fix.h[e];
      const [pf, nrm] = { y0: [[ox + s, oy, z], [0, -1, 0]], y1: [[ox + s, oy + Ly, z], [0, 1, 0]],
        x0: [[ox, oy + s, z], [-1, 0, 0]], x1: [[ox + Lx, oy + s, z], [1, 0, 0]] }[e];
      const pr = sub(pf, scale(nrm, t + gap));
      const pre = prefix || group;
      const sid = `${pre}.TORN.${pad2(n)}`, rid = `${pre}.TREM.${pad2(n)}`;
      model.add(rid, `Tuerca remachable ${n}`, rn_part, frameZ(pr, nrm), group, { tags: { explode_extra: scale(nrm, 30) } });
      model.add(sid, `Tornillo ${n}`, sc_part, frameZ(pf, nrm), group, { tags: { explode_extra: scale(nrm, 80) } });
      model.joint({ id: `J.${sid}`, kind: "atornillada", members: [tray_id || `${group}.BANDEJA`, rid], location: pf,
        description: `Tornillo ${sc_part.data.thread} en tuerca remachable`, fasteners: [sid, rid],
        data: { t_sheet: t, gap, wall, screw: code_sc, rivet: code_rn, rivet_found: sel_rn != null, screw_found: sel_sc != null } });
    }
  }
}

// ============================================================================ estantería
class Estanteria extends MesaIndustrial {
  constructor() { super("estanteria"); }
  paramForRole(role) {
    if (role === "montante") return "PERFIL_MONTANTE";
    if (role.startsWith("larguero")) return "PERFIL_LARGUERO";
    if (role.startsWith("travesano")) return "PERFIL_TRAVESANO";
    return null;
  }
  verticalLoadPresent(v) { return !!v.CARGA_POR_NIVEL; }
  plateTargets(v) {
    if (!v.CARGA_POR_NIVEL) return [];
    return [{ surface: "N1", t_param: "ESPESOR_BALDA", n_param: "NUMERO_TRAVESANOS_BALDA", load_param: "CARGA_POR_NIVEL",
      trv_param: "PERFIL_TRAVESANO", min_t_by_use: false }];
  }
  sheetDefaultsWithoutLoad(v) { return v.CARGA_POR_NIVEL ? {} : { ESPESOR_BALDA: this.constructive_defaults.ESPESOR_BALDA }; }

  construct(ps) {
    this.checkResolved(ps);
    const ctx = new ParamContext(ps);
    const V = ps.values;
    const A = V.ANCHURA, Pf = V.PROFUNDIDAD, H = V.ALTURA;
    const model = new ProductModel(this.id, this.name, `ES${fx(A)}-${fx(Pf)}-${fx(H)}`, ps, ctx);
    model.requested = ps;
    const d = this._deriveShelf(ctx, model);
    const mat_s = V.MATERIAL_ESTRUCTURAL, mat_c = V.MATERIAL_CHAPA, fin = V.ACABADO;
    model.addSub("EST", "Estructura soldada", { welded: true, step: 1 });
    model.addSub("APO", "Apoyos niveladores", { explode: [0, 0, -160], step: 2 });
    model.addSub("BAL", "Bandejas", { explode: [0, -0.9 * Pf, 0], step: 3 });
    const { leg, rail, trv, a } = d;
    const corners = { DI: [a / 2, a / 2], DD: [A - a / 2, a / 2], TI: [a / 2, Pf - a / 2], TD: [A - a / 2, Pf - a / 2] };
    const cname = { DI: "delantero izquierdo", DD: "delantero derecho", TI: "trasero izquierdo", TD: "trasero derecho" };
    const foot = C.component(V.PIE_NIVELADOR);
    const thread = parseFloat(foot.thread.slice(1));
    const nutCode = `TUERCA_SOLDAR_M${fx(thread)}`;
    const weld = makeWelder(model);
    const legs = {};
    ctx.feature("F10", "Estructura soldada", () => {
      ctx.feature("F11", "Montantes, placas base y tuercas", () => {
        ctx.uses("LONGITUD_MONTANTE", "PERFIL_MONTANTE", "ANCHURA", "PROFUNDIDAD", "ESPESOR_PLACA_BASE", "PIE_NIVELADOR",
          "MATERIAL_ESTRUCTURAL", "ACABADO");
        legsAndPlates(model, d, legs, corners, cname, mat_s, fin, thread, nutCode, "montante", `Montante ${leg.code}`, "EST.MONT",
          "Montante", "Placa base a montante", H);
      });
      d.level_ids.forEach((lid, i0) => {
        const i = i0 + 1, z = d.z_levels[i0];
        ctx.feature(`F2${i}`, `Bastidor del nivel ${i}`, () => {
          ctx.uses("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "N_TRAVESANOS_NIVEL", `COTA_NIVEL_${i}`, "ESP_BAL", "HOLGURA_BAL", "ANCHURA",
            "PROFUNDIDAD", "PERFIL_MONTANTE", "PASO_FIJACIONES", "ALA_BALDA", "MATERIAL_ESTRUCTURAL");
          const before = model.instances.length;
          frameLevel(model, d, lid, z - d.ts, rail, trv, d.e, d.n_int, legs, d.fix[lid], weld, mat_s, fin, "de nivel");
          for (const inst of model.instances.slice(before)) inst.name += ` (nivel ${i})`;
        });
      });
    });
    ctx.feature("F40", "Apoyos niveladores", () => {
      ctx.uses("PIE_NIVELADOR", "ANCHURA", "PROFUNDIDAD", "PERFIL_MONTANTE");
      feet(model, d, corners, cname, V.PIE_NIVELADOR, foot);
    });
    const tray = sheetPart("balda", `Bandeja chapa ${g(d.spec.t)} mm`, d.spec, mat_c, fin);
    d.level_ids.forEach((lid, i0) => {
      const i = i0 + 1, z = d.z_levels[i0];
      ctx.feature(`F3${i}`, `Bandeja del nivel ${i}`, () => {
        ctx.uses("ANCHURA", "PROFUNDIDAD", `COTA_NIVEL_${i}`, "ESP_BAL", "ALA_BALDA", "MATERIAL_CHAPA", "PERFIL_MONTANTE",
          "HOLGURA_ESCOTADURA", "PERFIL_LARGUERO", "ACABADO");
        const tid = `BAL.BANDEJA.${i}`;
        model.add(tid, `Bandeja nivel ${i}`, tray, translation(0, 0, z), "BAL", { tags: { explode_extra: [0, 0, 0] } });
        fasteners(model, d.fix[lid], "BAL", `BAL.N${i}`, tid);
      });
    });
    model.structure = this._shelfStructure(model, d, legs);
    const n = d.z_levels.length, q = V.CARGA_POR_NIVEL;
    model.dims = { ANCHURA: A, PROFUNDIDAD: Pf, ALTURA: H, LONGITUD_MONTANTE: d.leg_len,
      envelope: { ids: [...Object.values(legs), ...range(n).map((i) => `BAL.BANDEJA.${i + 1}`)], dx: A, dy: Pf, zmax: H, names: ["ANCHURA", "PROFUNDIDAD"] },
      levels: range(n).map((i) => [`NIVEL_${i + 1}`, `BAL.BANDEJA.${i + 1}`]),
      drawing_expected: Object.fromEntries(range(n).map((k) => [`DIST_NIVEL_${k + 1}`, k === 0 ? d.z_levels[0] : d.z_levels[k] - d.z_levels[k - 1]])),
      load_text: q ? `Carga distribuida por nivel de proyecto: ${g(q)} kg (${n} niveles, total ${g(n * q)} kg)` : "Carga por nivel: NO DEFINIDA" };
    model.numberParts();
    return model;
  }

  _deriveShelf(ctx, model) {
    const v = ctx.params.values;
    const d = {};
    ctx.feature("F00", "Parámetros derivados y reglas constructivas", () => {
      const fam = C.material(v.MATERIAL_CHAPA).family;
      const rmin = C.sheetData().press_brake.min_inner_radius_factor[fam] ?? 1.0;
      const ts = ctx.derive("ESP_BAL", (p) => p.get("ESPESOR_BALDA"), "mm", "Espesor de bandeja");
      const rs = ctx.derive("RADIO_BAL", (p) => (p.get("RADIO_PLEGADO") === AUTO ? pyRound(Math.max(p.get("ESP_BAL"), rmin * p.get("ESP_BAL")), 2)
        : p.get("RADIO_PLEGADO")), "mm", "Radio interior de plegado");
      const Ks = ctx.derive("K_BAL", (p) => (p.get("FACTOR_K") === AUTO ? pyRound(C.din6935K(p.get("RADIO_BAL"), p.get("ESP_BAL")), 4)
        : p.get("FACTOR_K")), null, "Factor K");
      ctx.derive("DEDUCCION_PLEGADO_BAL", (p) => pyRound(bendDeduction(p.get("ESP_BAL"), p.get("RADIO_BAL"), p.get("K_BAL")), 4), "mm", "Deducción de plegado 90°");
      const leg = C.profile(ctx.get("PERFIL_MONTANTE")), rail = C.profile(ctx.get("PERFIL_LARGUERO")), trv = C.profile(ctx.get("PERFIL_TRAVESANO"));
      if (leg.B !== leg.H) throw new Error("Los montantes deben ser de tubo cuadrado");
      const a = leg.B;
      const foot = C.component(ctx.get("PIE_NIVELADOR"));
      const hn = +foot.nominal_height, tp = ctx.get("ESPESOR_PLACA_BASE");
      const A = ctx.get("ANCHURA"), Pf = ctx.get("PROFUNDIDAD"), H = ctx.get("ALTURA");
      const z_leg0 = ctx.derive("COTA_INICIO_MONTANTE", (p) => +C.component(p.get("PIE_NIVELADOR")).nominal_height + p.get("ESPESOR_PLACA_BASE"),
        "mm", "Cota inicio de montante");
      const leg_len = ctx.derive("LONGITUD_MONTANTE", (p) => p.get("ALTURA") - p.get("COTA_INICIO_MONTANTE"), "mm", "Longitud de corte de montante");
      const head_h = +C.component("TUERCA_REMACHABLE_M6").head_h;
      const gg = ctx.derive("HOLGURA_BAL", (p) => (p.get("HOLGURA_BALDA") === AUTO ? Math.max(p.get("RADIO_BAL"), head_h) : p.get("HOLGURA_BALDA")),
        "mm", "Holgura bastidor–pestaña");
      if (gg < rs - 1e-9) model.note("error", "GEO-HOLGURA-RADIO", `Holgura ${pyStr(gg)} mm menor que el radio de plegado ${pyStr(rs)} mm.`);
      if (head_h > gg + 1e-9) model.note("error", "DFM-HOLGURA-REMACHABLE", "La cabeza de la tuerca remachable no cabe en la holgura.");
      const e = ts + gg;
      if (e + Math.max(rail.B, trv.B) > a) model.note("error", "DFM-BASTIDOR", "El bastidor retranqueado no cabe en la sección del montante.");
      const n = ctx.get("NUMERO_NIVELES"), z1 = ctx.get("ALTURA_PRIMER_NIVEL");
      const dist = ctx.derive("DISTANCIA_NIVELES", (p) => (p.get("DISTANCIA_BALDAS") === AUTO
        ? (p.get("ALTURA") - p.get("ALTURA_PRIMER_NIVEL")) / (p.get("NUMERO_NIVELES") - 1) : p.get("DISTANCIA_BALDAS")), "mm", "Distancia entre niveles");
      const zs = range(n).map((i) => ctx.derive(`COTA_NIVEL_${i + 1}`, (p) => p.get("ALTURA_PRIMER_NIVEL") + i * p.get("DISTANCIA_NIVELES"),
        "mm", `Cota cara superior del nivel ${i + 1}`));
      if (zs.at(-1) > H + 1e-6 * H)
        throw new ParamError(`Los ${n} niveles a ${g(dist)} mm superan la altura total de ${g(H)} mm: reduzca `
          + `DISTANCIA_BALDAS a ${fx((H - z1) / Math.max(n - 1, 1))} mm o menos, o use 'auto'.`);
      if (z1 - ts - rail.H < z_leg0 + 20) model.note("error", "GEO-NIVEL-BAJO", "El primer nivel está demasiado bajo para su bastidor.");
      const libre = dist - ts - Math.max(rail.H, trv.H);
      ctx.setDerived("HUECO_LIBRE", pyRound(libre, 1), "mm", "Altura libre entre niveles", ["DISTANCIA_BALDAS", "ALTURA", "NUMERO_NIVELES", "PERFIL_LARGUERO"]);
      if (libre < 150) model.note("advertencia", "ERG-HUECO", `Altura libre entre niveles de ${fx(libre)} mm (< 150 mm).`);
      const xb0 = e + trv.B / 2, xb1 = A - e - trv.B / 2;
      let n_int = ctx.get("NUMERO_TRAVESANOS_BALDA");
      if (n_int === AUTO) n_int = Math.max(0, Math.ceil((xb1 - xb0) / ctx.get("SEPARACION_MAX_APOYOS")) - 1);
      ctx.setDerived("N_TRAVESANOS_NIVEL", n_int, "ud", "Travesaños intermedios por nivel", ["NUMERO_TRAVESANOS_BALDA", "SEPARACION_MAX_APOYOS", "ANCHURA"]);
      const notch = a + ctx.get("HOLGURA_ESCOTADURA");
      const ala = ctx.get("ALA_BALDA");
      const rn = C.component("TUERCA_REMACHABLE_M6"), sc = C.component("TORNILLO_ISO7380_M6x12");
      const level_ids = [...range(n - 1).map((i) => `N${i + 1}`), "SUP"];
      Object.assign(d, { Lx: A, Ly: Pf, c: 0.0, a, leg, rail, trv, hn, tp, z_leg0, leg_len, ts, e, n_int, z_levels: zs, level_ids });
      const hd = flangeHoleD(v.MATERIAL_CHAPA, ts, sc);
      d.fix = {};
      level_ids.forEach((lid, k) => {
        const f = fixLayout(model, A, Pf, 0.0, a, ts, rs + ts, ala, rail, trv, zs[k], e, hd, rn, ctx.get("PASO_FIJACIONES"), 1,
          `bandeja ${lid}`, notch, 0.0);
        f.gap = gg;
        d.fix[lid] = f;
      });
      const f0 = d.fix[level_ids[0]];
      d.spec = makeSpec({ Lx: A, Ly: Pf, t: ts, r: rs, K: Ks, notch: [notch, notch],
        flanges: EDGES.map((ed) => ({ edge: ed, height: ala, direction: "down", holes: f0.s[ed].map((s) => [s, f0.h[ed], hd]) })) });
    });
    return d;
  }

  _shelfStructure(model, d, legs) {
    const notch = d.spec.notch[0];
    const area = d.Lx * d.Ly - 4 * notch * notch;
    const surfaces = d.level_ids.map((lid, i) => ({ id: lid, label: `Bandeja del nivel ${i + 1}`, level: lid, load_param: "CARGA_POR_NIVEL",
      sheet_instance: `BAL.BANDEJA.${i + 1}`, area_mm2: area }));
    return { levels: model.structure.levels ?? {}, surfaces, supports: supportsOf(model, legs), horizontal_points: [legs.DI, legs.DD],
      worktop_height: model.params.values.ALTURA, leg_ids: Object.values(legs), product_word: "estantería", member_roles: memberRoles(model),
      assembly_texts: {
        EST: "Recepción de la estructura soldada y pintada. Insertar las tuercas remachables M6 en los taladros Ø9,1 de largueros y "
          + "travesaños de todos los niveles.",
        APO: "Roscar los pies niveladores en las tuercas soldadas. Nivelar y, si está previsto, anclar al suelo antes de cargar la estantería.",
        BAL: "Colocar las bandejas de abajo arriba sobre cada bastidor, con las escotaduras alrededor de los montantes, y fijarlas con "
          + "tornillos ISO 7380 M6x12 (8 N·m)." } };
  }
}


// ============================================================================ puesto de trabajo (port de puesto_trabajo.py)
const PANEL_HOLE = 10.0, PANEL_PITCH = 38.0;
class PuestoTrabajo extends MesaIndustrial {
  paramForRole(role) {
    if (role === "montante") return "PERFIL_PATA";
    if (["travesano_alto", "larguero_est", "brazo_est", "travesano_int_est"].includes(role)) return "PERFIL_ALTILLO";
    return super.paramForRole(role);
  }
  verticalLoadPresent(v) { return !!v.CARGA_TOTAL || !!(v.CARGA_ESTANTE && v.ESTANTE_SUPERIOR); }
  plateTargets(v) {
    const out = super.plateTargets(v);
    if (v.ESTANTE_SUPERIOR && v.CARGA_ESTANTE) out.push({ surface: "estante", t_param: "ESPESOR_ESTANTE", n_param: "NUMERO_TRAVESANOS_ESTANTE",
      load_param: "CARGA_ESTANTE", trv_param: "PERFIL_ALTILLO", min_t_by_use: false });
    return out;
  }
  sheetDefaultsWithoutLoad(v) {
    const out = super.sheetDefaultsWithoutLoad(v);
    if (!(v.ESTANTE_SUPERIOR && v.CARGA_ESTANTE)) out.ESPESOR_ESTANTE = this.constructive_defaults.ESPESOR_ESTANTE;
    return out;
  }
  _legUses() { return ["ALTURA_TOTAL", "PANEL_HERRAMIENTAS"]; }
  _legDef(corner, d, leg) { return corner === "TI" || corner === "TD" ? ["montante", "Montante trasero", d.z_top_alt, d.leg_holes] : ["pata", "Pata", d.z_tf, []]; }
  _topNotch(ctx, d) { const n = d.c + d.a + ctx.get("HOLGURA_ESCOTADURA"); return [[n, n], ["x0y1", "x1y1"]]; }

  _derive(ctx, model) {
    const d = super._derive(ctx, model);
    const v = ctx.params.values;
    ctx.feature("F05", "Superestructura: montantes, estante y panel", () => {
      const { a, c } = d, L = ctx.get("LONGITUD"), W = ctx.get("ANCHURA"), H = ctx.get("ALTURA");
      const alt = C.profile(ctx.get("PERFIL_ALTILLO"));
      const zt = ctx.derive("COTA_SUPERIOR_MONTANTE", (p) => p.get("ALTURA_TOTAL"), "mm", "Cota superior de montantes");
      ctx.derive("LONGITUD_MONTANTE", (p) => p.get("ALTURA_TOTAL") - p.get("COTA_INICIO_PATA"), "mm", "Longitud de corte de montante trasero");
      Object.assign(d, { alt, z_top_alt: zt, leg_holes: [] });
      if (zt < H + 300) model.note("error", "GEO-ALTURA-TOTAL", `Altura de montantes ${g(zt)} mm insuficiente: debe superar la encimera (${g(H)} mm) en al menos 300 mm.`);
      if (alt.B > a) model.note("error", "DFM-ALTILLO-ANCHO", `El perfil ${alt.code} es más ancho que el montante: no puede enrasarse con él.`);
      const rn = C.component("TUERCA_REMACHABLE_M6"), sc = C.component("TORNILLO_ISO7380_M6x12");
      const head_h = +rn.head_h;
      d.shelf_top = !!ctx.get("ESTANTE_SUPERIOR");
      if (d.shelf_top) {
        const fam = C.material(v.MATERIAL_CHAPA).family;
        const rmin = C.sheetData().press_brake.min_inner_radius_factor[fam] ?? 1.0;
        const ts = ctx.derive("ESP_EST", (p) => p.get("ESPESOR_ESTANTE"), "mm", "Espesor del estante superior");
        const rs = ctx.derive("RADIO_EST", (p) => (p.get("RADIO_PLEGADO") === AUTO ? pyRound(Math.max(p.get("ESP_EST"), rmin * p.get("ESP_EST")), 2) : p.get("RADIO_PLEGADO")),
          "mm", "Radio de plegado (estante)");
        const Ks = ctx.derive("K_EST", (p) => (p.get("FACTOR_K") === AUTO ? pyRound(C.din6935K(p.get("RADIO_EST"), p.get("ESP_EST")), 4) : p.get("FACTOR_K")),
          null, "Factor K (estante)");
        ctx.derive("DEDUCCION_PLEGADO_EST", (p) => pyRound(bendDeduction(p.get("ESP_EST"), p.get("RADIO_EST"), p.get("K_EST")), 4), "mm", "Deducción de plegado 90° (estante)");
        const gg = ctx.derive("HOLGURA_EST", (p) => (p.get("HOLGURA_ENCIMERA") === AUTO ? Math.max(p.get("RADIO_EST"), head_h) : p.get("HOLGURA_ENCIMERA")),
          "mm", "Holgura bastidor–pestaña (estante)");
        const e = ts + gg;
        const D = ctx.get("PROFUNDIDAD_ESTANTE"), zs = ctx.get("ALTURA_ESTANTE");
        const notch = a + ctx.get("HOLGURA_ESCOTADURA");
        const Lx = L - 2 * c;
        if (e + alt.B > a) model.note("error", "DFM-BASTIDOR-ESTANTE", "El bastidor retranqueado del estante no cabe en la sección del montante.");
        if (D - a - e - alt.B < 40) model.note("error", "GEO-ESTANTE-CORTO", `Fondo de estante ${g(D)} mm insuficiente para el montante y el bastidor (mínimo ${fx(a + e + alt.B + 40)} mm).`);
        if (zs > zt - 100 + 1e-9) model.note("error", "GEO-ESTANTE-ALTO", `El estante superior (${g(zs)} mm) debe quedar al menos 100 mm por debajo de la cota superior de los montantes (${g(zt)} mm).`);
        if (zs < H + 300) model.note("error", "GEO-ESTANTE-BAJO", `El estante superior (${g(zs)} mm) debe quedar al menos 300 mm por encima de la encimera (${g(H)} mm).`);
        const xa0 = c + e + alt.B / 2, xa1 = L - c - e - alt.B / 2;
        let n_int = ctx.get("NUMERO_TRAVESANOS_ESTANTE");
        if (n_int === AUTO) n_int = Math.max(0, Math.ceil((xa1 - xa0) / ctx.get("SEPARACION_MAX_APOYOS")) - 1);
        ctx.setDerived("N_TRAVESANOS_ESTANTE", n_int, "ud", "Travesaños intermedios bajo el estante", ["NUMERO_TRAVESANOS_ESTANTE", "SEPARACION_MAX_APOYOS", "LONGITUD"]);
        const ala = ctx.get("ALA_ESTANTE");
        const hd = flangeHoleD(v.MATERIAL_CHAPA, ts, sc);
        const m = 40.0;
        const ranges = { y0: [e + alt.B + m, Lx - e - alt.B - m, 2], y1: [notch + 30, Lx - notch - 30, 2],
          x0: [e + alt.B + 30, D - notch - 20, 1], x1: [e + alt.B + 30, D - notch - 20, 1] };
        const fix = fixLayout(model, Lx, D, 0.0, a, ts, rs + ts, ala, alt, alt, zs, e, hd, rn, ctx.get("PASO_FIJACIONES"), 1, "estante", 0.0, [c, W - c - D], ranges);
        fix.gap = gg;
        d.est_spec = makeSpec({ Lx, Ly: D, t: ts, r: rs, K: Ks, notch: [notch, notch], notchCorners: ["x0y1", "x1y1"],
          flanges: EDGES.map((ed) => ({ edge: ed, height: ala, direction: "down", holes: fix.s[ed].map((s) => [s, fix.h[ed], hd]) })) });
        Object.assign(d, { est_t: ts, est_e: e, est_D: D, est_z: zs, est_notch: notch, est_n_int: n_int, fix_est: fix, est_xa: [xa0, xa1] });
      }
      d.panel = !!ctx.get("PANEL_HERRAMIENTAS");
      if (d.panel) {
        const tp = ctx.get("ESPESOR_PANEL");
        const z0 = H + 40.0;
        const z1 = d.shelf_top ? ctx.get("ALTURA_ESTANTE") - d.est_t - alt.H - 30.0 : zt - alt.H - 30.0;
        const Hp = pyRound(z1 - z0, 3);
        if (Hp < 200) {
          model.note("advertencia", "GEO-PANEL-SIN-HUECO", `No queda hueco para el panel portaherramientas (${fx(Hp)} mm entre encimera y estante): se omite.`);
          d.panel = false;
        } else {
          const fam = C.material(v.MATERIAL_CHAPA).family;
          const rmin = C.sheetData().press_brake.min_inner_radius_factor[fam] ?? 1.0;
          const rp = v.RADIO_PLEGADO === AUTO ? pyRound(Math.max(tp, rmin * tp), 2) : v.RADIO_PLEGADO;
          const Kp = v.FACTOR_K === AUTO ? pyRound(C.din6935K(rp, tp), 4) : v.FACTOR_K;
          const Rp = rp + tp, Lp = L - 2 * c, gp = head_h;
          const hd = flangeHoleD(v.MATERIAL_CHAPA, tp, sc);
          const n_fix = Math.max(2, Math.ceil((Hp - 2 * Rp - 50) / ctx.get("PASO_FIJACIONES")) + 1);
          const ys = evenPositions(Rp + 25, Hp - Rp - 25, n_fix);
          const holes = [...ys.map((y) => ["round", a / 2, y, hd]), ...ys.map((y) => ["round", Lp - a / 2, y, hd]),
            ...perforationGrid(a + 15, Rp + 2 * tp + 12, Lp - a - 15, Hp - Rp - 2 * tp - 12, PANEL_PITCH, PANEL_HOLE)];
          d.panel_spec = makeSpec({ Lx: Lp, Ly: Hp, t: tp, r: rp, K: Kp, notch: [a + 3, Rp], holes,
            flanges: [{ edge: "y0", height: 15.0, direction: "down", holes: [] }, { edge: "y1", height: 15.0, direction: "down", holes: [] }] });
          Object.assign(d, { panel_z: [z0, z1], panel_y: W - c - a - gp - tp, panel_gap: gp, panel_t: tp, panel_fix_z: ys.map((y) => z0 + y) });
          ctx.setDerived("ALTO_PANEL", Hp, "mm", "Altura del panel perforado", ["ALTURA", "ALTURA_ESTANTE", "ALTURA_TOTAL", "PANEL_HERRAMIENTAS"]);
          d.leg_holes = d.panel_fix_z.map((z) => ["-y", pyRound(z - d.z_leg0, 3), 0.0, rn.hole_d]);
        }
      }
    });
    return d;
  }

  _extras(model, ctx, d, legs, corners) {
    const V = model.params.values;
    const mat_s = V.MATERIAL_ESTRUCTURAL, mat_c = V.MATERIAL_CHAPA, fin = V.ACABADO;
    const { a, c, alt } = d, L = V.LONGITUD, W = V.ANCHURA;
    const weld = makeWelder(model);
    const yR = W - c - a / 2;
    ctx.feature("F14", "Travesaño alto entre montantes", () => {
      ctx.uses("PERFIL_ALTILLO", "ALTURA_TOTAL", "LONGITUD", "RETRANQUEO", "PERFIL_PATA", "MATERIAL_ESTRUCTURAL");
      const zc = d.z_top_alt - alt.H / 2;
      const p0 = [c + a, yR, zc], p1 = [L - c - a, yR, zc];
      const part = profilePart("travesano_alto", `Travesaño alto ${alt.code}`, alt.code, L - 2 * c - 2 * a, mat_s, fin);
      model.add("EST.TRV_ALTO", "Travesaño alto entre montantes", part, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
      weld("J.EST.TRV_ALTO.0", "EST.TRV_ALTO", 0, legs.TI, alt, "Travesaño alto a montante");
      weld("J.EST.TRV_ALTO.1", "EST.TRV_ALTO", 1, legs.TD, alt, "Travesaño alto a montante");
    });
    if (d.shelf_top) this._shelfTop(model, ctx, d, legs, weld, mat_s, mat_c, fin);
    if (d.panel) this._panel(model, ctx, d, mat_c, fin);
  }

  _shelfTop(model, ctx, d, legs, weld, mat_s, mat_c, fin) {
    const V = model.params.values;
    const { a, c, alt } = d, L = V.LONGITUD, W = V.ANCHURA;
    const e = d.est_e, D = d.est_D, zs = d.est_z, ts = d.est_t, fix = d.fix_est;
    model.addSub("ALT", "Estante superior", { explode: [0, -0.6 * D, 120], step: 5 });
    const holeRn = C.component("TUERCA_REMACHABLE_M6").hole_d;
    const yFt = W - c - D, zTop = zs - ts, zc = zTop - alt.H / 2;
    const hz = (edge) => fix.z_ref - fix.h[edge] - zc;
    ctx.feature("F15", "Bastidor del estante superior", () => {
      ctx.uses("PERFIL_ALTILLO", "ALTURA_ESTANTE", "PROFUNDIDAD_ESTANTE", "ESP_EST", "HOLGURA_EST", "N_TRAVESANOS_ESTANTE", "PASO_FIJACIONES", "ALA_ESTANTE", "MATERIAL_ESTRUCTURAL");
      const yF = yFt + e + alt.B / 2, x0 = c + e, x1 = L - c - e;
      let holes = fix.s.y0.map((s) => ["-x", pyRound(c + s - x0, 3), pyRound(hz("y0"), 3), holeRn]);
      const pF = profilePart("larguero_est", `Larguero delantero de estante ${alt.code}`, alt.code, x1 - x0, mat_s, fin, holes);
      let p0 = [x0, yF, zc], p1 = [x1, yF, zc];
      model.add("EST.EST_LAR.D", "Larguero delantero del estante", pF, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
      const yB = W - c - e - alt.B / 2, xb0 = L - c - a, xb1 = c + a;
      holes = fix.s.y1.map((s) => ["-x", pyRound(xb0 - (c + s), 3), pyRound(hz("y1"), 3), holeRn]);
      const pB = profilePart("larguero_est", `Larguero trasero de estante ${alt.code}`, alt.code, xb0 - xb1, mat_s, fin, holes);
      p0 = [xb0, yB, zc]; p1 = [xb1, yB, zc];
      model.add("EST.EST_LAR.T", "Larguero trasero del estante", pB, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
      weld("J.EST.EST_LAR.T.0", "EST.EST_LAR.T", 0, legs.TD, alt, "Larguero trasero de estante a montante");
      weld("J.EST.EST_LAR.T.1", "EST.EST_LAR.T", 1, legs.TI, alt, "Larguero trasero de estante a montante");
      const ya0 = W - c - a, ya1 = yF + alt.B / 2;
      const arms = [];
      for (const [k, nm, x, face, edge, leg] of [["I", "izquierdo", c + e + alt.B / 2, "-x", "x0", "TI"], ["D", "derecho", L - c - e - alt.B / 2, "+x", "x1", "TD"]]) {
        const hh = fix.s[edge].map((s) => [face, pyRound(ya0 - (yFt + s), 3), pyRound(hz(edge), 3), holeRn]);
        const pA = profilePart("brazo_est", `Brazo ${nm} de estante ${alt.code}`, alt.code, ya0 - ya1, mat_s, fin, hh);
        const iid = `EST.EST_BRZ.${k}`;
        const q0 = [x, ya0, zc], q1 = [x, ya1, zc];
        model.add(iid, `Brazo ${nm} del estante`, pA, axisFrame(q0, q1, [0, 0, 1]), "EST", { axis: [q0, q1], up: [0, 0, 1], structural: true });
        weld(`J.${iid}.0`, iid, 0, legs[leg], alt, "Brazo de estante a montante");
        weld(`J.${iid}.1`, iid, 1, "EST.EST_LAR.D", alt, "Brazo de estante a larguero delantero");
        arms.push(iid);
      }
      const [xa0, xa1] = d.est_xa, n_int = d.est_n_int;
      const xs = range(n_int).map((i) => xa0 + ((i + 1) * (xa1 - xa0)) / (n_int + 1));
      const ints = [];
      if (n_int) {
        const yi0 = yF + alt.B / 2, yi1 = yB - alt.B / 2;
        const pI = profilePart("travesano_int_est", `Travesaño intermedio de estante ${alt.code}`, alt.code, yi1 - yi0, mat_s, fin);
        xs.forEach((x, n0) => {
          const iid = `EST.EST_TRI.${pad2(n0 + 1)}`;
          const q0 = [x, yi0, zc], q1 = [x, yi1, zc];
          model.add(iid, `Travesaño intermedio del estante ${n0 + 1}`, pI, axisFrame(q0, q1, [0, 0, 1]), "EST", { axis: [q0, q1], up: [0, 0, 1], structural: true });
          weld(`J.${iid}.0`, iid, 0, "EST.EST_LAR.D", alt, "Travesaño intermedio de estante a larguero");
          weld(`J.${iid}.1`, iid, 1, "EST.EST_LAR.T", alt, "Travesaño intermedio de estante a larguero");
          ints.push(iid);
        });
      }
      model.structure.levels = model.structure.levels ?? {};
      model.structure.levels.ALTO = { long: ["EST.EST_LAR.D", "EST.EST_LAR.T"], end: arms, int: ints, grid_x: [xa0, ...xs, xa1], grid_y: [yF, yB], z: zTop };
    });
    ctx.feature("F35", "Estante superior de chapa plegada", () => {
      ctx.uses("LONGITUD", "PROFUNDIDAD_ESTANTE", "ALTURA_ESTANTE", "ESP_EST", "ALA_ESTANTE", "MATERIAL_CHAPA", "PERFIL_PATA", "HOLGURA_ESCOTADURA", "PERFIL_ALTILLO", "ACABADO");
      const tray = sheetPart("estante", `Estante superior chapa ${g(ts)} mm`, d.est_spec, mat_c, fin);
      model.add("ALT.BANDEJA", "Estante superior", tray, translation(c, yFt, zs), "ALT");
      fasteners(model, fix, "ALT", null, "ALT.BANDEJA");
    });
  }

  _panel(model, ctx, d, mat_c, fin) {
    const V = model.params.values;
    const { a, c } = d, L = V.LONGITUD, spec = d.panel_spec;
    model.addSub("PAN", "Panel portaherramientas", { explode: [0, -220, 0], step: 6 });
    ctx.feature("F36", "Panel perforado portaherramientas", () => {
      ctx.uses("PANEL_HERRAMIENTAS", "ESPESOR_PANEL", "LONGITUD", "ALTURA", "ALTURA_ESTANTE", "ALTURA_TOTAL", "MATERIAL_CHAPA", "PERFIL_PATA", "ACABADO");
      const z0 = d.panel_z[0], yF = d.panel_y;
      const T = [[1, 0, 0, c], [0, 0, -1, yF], [0, 1, 0, z0], [0, 0, 0, 1]];
      const part = sheetPart("panel", `Panel perforado chapa ${g(spec.t)} mm`, spec, mat_c, fin);
      model.add("PAN.PANEL", "Panel portaherramientas", part, T, "PAN");
      const tp = d.panel_t, gp = d.panel_gap, wall = d.leg.t;
      const sel_rn = C.selectRivetNut(wall);
      const [code_rn, rnd] = sel_rn ?? ["TUERCA_REMACHABLE_M6", C.component("TUERCA_REMACHABLE_M6")];
      const sel_sc = C.selectScrew(tp + gp, tp + gp + rnd.body_l);
      const code_sc = sel_sc ? sel_sc[0] : "TORNILLO_ISO7380_M6x12";
      const nrm = [0, -1, 0];
      let n = 0;
      for (const x of [c + a / 2, L - c - a / 2]) for (const z of d.panel_fix_z) {
        n += 1;
        const pf = [x, yF, z], pr = sub(pf, scale(nrm, tp + gp));
        const rid = `PAN.TREM.${pad2(n)}`, sid = `PAN.TORN.${pad2(n)}`;
        model.add(rid, `Tuerca remachable ${n}`, standardPart("tuerca_remachable", code_rn), frameZ(pr, nrm), "PAN", { tags: { explode_extra: scale(nrm, 30) } });
        model.add(sid, `Tornillo ${n}`, standardPart("tornillo", code_sc), frameZ(pf, nrm), "PAN", { tags: { explode_extra: scale(nrm, 80) } });
        model.joint({ id: `J.${sid}`, kind: "atornillada", members: ["PAN.PANEL", rid], location: pf,
          description: `Tornillo ${C.component(code_sc).thread} en tuerca remachable`, fasteners: [sid, rid],
          data: { t_sheet: tp, gap: gp, wall, screw: code_sc, rivet: code_rn, rivet_found: sel_rn != null, screw_found: sel_sc != null } });
      }
      const pm = part.mass;
      const pts = [];
      for (const mid of ["EST.PATA.TI", "EST.PATA.TD"]) for (const z of d.panel_fix_z) pts.push([mid, z]);
      model.structure.attached_masses = [...(model.structure.attached_masses ?? []), ...pts.map(([mid, z]) => ({ member: mid,
        point: [model.instance(mid).axis[0][0], model.instance(mid).axis[0][1], z], mass_kg: pm / pts.length, label: "Panel portaherramientas" }))];
    });
  }

  _structure(model, d, legs) {
    const st = super._structure(model, d, legs);
    if (d.shelf_top) {
      const V = model.params.values, notch = d.est_notch;
      st.surfaces.push({ id: "estante", label: "Estante superior", level: "ALTO", load_param: "CARGA_ESTANTE", sheet_instance: "ALT.BANDEJA",
        area_mm2: (V.LONGITUD - 2 * d.c) * d.est_D - 2 * notch * notch, count_param: "NUMERO_TRAVESANOS_ESTANTE" });
    }
    st.attached_masses = model.structure.attached_masses ?? [];
    st.product_word = "puesto";
    st.assembly_texts = {
      ALT: "Colocar el estante superior sobre su bastidor, con las escotaduras traseras alrededor de los montantes, y fijarlo con tornillos ISO 7380 M6 (8 N·m).",
      PAN: "Presentar el panel perforado contra la cara delantera de los montantes y atornillarlo a las tuercas remachables M6 (8 N·m), de abajo arriba." };
    return st;
  }

  _extraDims(model, d) {
    const V = model.params.values;
    const levels = [];
    if (d.shelf) levels.push(["ALTURA_BALDA", "BAL.BANDEJA"]);
    levels.push(["ALTURA_ENCIMERA", "ENC.BANDEJA", V.ALTURA], ...this._petoLevel(d, V.ALTURA));
    if (d.shelf_top) levels.push(["ALTURA_ESTANTE", "ALT.BANDEJA"]);
    const zOf = { ALTURA_BALDA: d.z_shelf, ALTURA_ENCIMERA: V.ALTURA, ALTURA_ESTANTE: d.est_z, COTA_PETO: V.ALTURA + d.peto };
    const zs = [0.0, ...levels.map(([n]) => zOf[n])];
    Object.assign(model.dims, { ALTURA_ENCIMERA: V.ALTURA,
      ALTURA_TOTAL: d.z_top_alt,
      envelope: { ids: ["ENC.BANDEJA", "EST.PATA.TI", "EST.PATA.TD"], dx: V.LONGITUD, dy: V.ANCHURA, zmax: Math.max(d.z_top_alt, V.ALTURA + d.peto), names: ["LONGITUD", "ANCHURA"] },
      levels,
      drawing_expected: Object.fromEntries(levels.map((_, k) => [`DIST_NIVEL_${k + 1}`, zs[k + 1] - zs[k]])),
      load_text: `Cargas de proyecto: encimera ${V.CARGA_TOTAL ? pyStr(V.CARGA_TOTAL) : "NO DEFINIDA"} kg` + (d.shelf ? `, balda ${V.CARGA_BALDA ? pyStr(V.CARGA_BALDA) : "NO DEFINIDA"} kg` : "")
        + (d.shelf_top ? `, estante superior ${V.CARGA_ESTANTE ? pyStr(V.CARGA_ESTANTE) : "NO DEFINIDA"} kg` : ""),
    });
  }
}

// ============================================================================ carro de taller (port de carro_taller.py)
// esquinas cuyas patas se prolongan como montantes del asa y esquinas de la encimera con escotadura
const HANDLE_CORNERS = { un_extremo: ["DI", "TI"], dos_extremos: ["DI", "TI", "DD", "TD"], ninguna: [] };
const NOTCH_CORNERS = { un_extremo: ["x0y0", "x0y1"], dos_extremos: ["x0y0", "x0y1", "x1y0", "x1y1"], ninguna: [] };
class CarroTaller extends MesaIndustrial {
  constructor(id) { super(id); Object.assign(this, { support_param: "RUEDA", support_category: "ruedas_espiga", support_group: ["RUE", "Ruedas"] }); }
  paramForRole(role) {
    if (role === "montante") return "PERFIL_PATA";
    if (role === "asa") return "PERFIL_ASA";
    return super.paramForRole(role);
  }
  _legUses() { return ["ALTURA_ASA", "ASA_EMPUJE"]; }
  _legDef(corner, d, leg) { return d.asa_corners.includes(corner) ? ["montante", "Montante del asa", d.z_asa, []] : ["pata", "Pata", d.z_tf, []]; }
  _supportPart(corner, V) {
    const code = V.RUEDA;
    return corner === "DI" || corner === "TI" ? [standardPart("rueda", `${code}_FRENO`), "Rueda con freno"] : [standardPart("rueda", code), "Rueda giratoria"];
  }
  _topNotch(ctx, d) {
    const corners = NOTCH_CORNERS[ctx.get("ASA_EMPUJE")];
    if (!corners.length) return null;
    const n = d.c + d.a + ctx.get("HOLGURA_ESCOTADURA");
    return [[n, n], corners];
  }
  _derive(ctx, model) {
    const d = super._derive(ctx, model);
    const mode = ctx.get("ASA_EMPUJE");
    Object.assign(d, { asa_mode: mode, asa_corners: HANDLE_CORNERS[mode], z_asa: null });
    ctx.feature("F06", "Asa de empuje", () => {
      const H = ctx.get("ALTURA");
      const asa = C.profile(ctx.get("PERFIL_ASA"));
      d.asa = asa;
      if (mode !== "ninguna") {
        const za = ctx.derive("COTA_ASA", (p) => p.get("ALTURA_ASA"), "mm", "Cota superior del asa");
        ctx.derive("LONGITUD_MONTANTE_ASA", (p) => p.get("ALTURA_ASA") - p.get("COTA_INICIO_PATA"), "mm", "Longitud de corte de los montantes del asa");
        d.z_asa = za;
        if (za < H + 80) model.note("error", "GEO-ASA-BAJA", `El asa (${g(za)} mm) debe quedar al menos 80 mm por encima de la encimera (${g(H)} mm) para poder agarrarla.`);
        if (asa.B > d.a) model.note("error", "DFM-ASA-ANCHO", `El perfil del asa ${asa.code} es más ancho que el montante.`);
      }
      ctx.setDerived("DIAMETRO_RUEDA", C.component(ctx.get("RUEDA")).wheel_d, "mm", "Diámetro de rueda", ["RUEDA"]);
    });
    return d;
  }
  _extras(model, ctx, d, legs, corners) {
    if (d.asa_mode === "ninguna") return;
    const V = model.params.values;
    const { asa, a, c } = d, L = V.LONGITUD, W = V.ANCHURA;
    const weld = makeWelder(model);
    const two = d.asa_mode === "dos_extremos";
    const handles = [["EST.ASA", c + a / 2, "DI", "TI", two ? " izquierda" : ""]];
    if (two) handles.push(["EST.ASA_D", L - c - a / 2, "DD", "TD", " derecha"]);
    ctx.feature("F16", "Asa de empuje soldada", () => {
      ctx.uses("PERFIL_ASA", "ALTURA_ASA", "ASA_EMPUJE", "ANCHURA", "RETRANQUEO", "PERFIL_PATA", "MATERIAL_ESTRUCTURAL", "ACABADO");
      const part = profilePart("asa", `Asa de empuje ${asa.code}`, asa.code, W - 2 * c - 2 * a, V.MATERIAL_ESTRUCTURAL, V.ACABADO);
      const zc = d.z_asa - asa.H / 2;
      for (const [iid, x, l0, l1, side] of handles) {
        const p0 = [x, c + a, zc], p1 = [x, W - c - a, zc];
        model.add(iid, `Asa de empuje${side}`, part, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
        weld(`J.${iid}.0`, iid, 0, legs[l0], asa, "Asa a montante");
        weld(`J.${iid}.1`, iid, 1, legs[l1], asa, "Asa a montante");
      }
    });
  }
  _structure(model, d, legs) {
    const st = super._structure(model, d, legs);
    const mode = d.asa_mode;
    st.product_word = mode !== "ninguna" ? "carro" : "mesa";
    const brake = mode === "un_extremo" ? "Las ruedas con freno van en el extremo del asa." : "Las ruedas con freno van en el extremo izquierdo (X = 0).";
    const notch = { un_extremo: ", con las escotaduras alrededor de los montantes del asa,", dos_extremos: ", con las escotaduras alrededor de los montantes de las asas,", ninguna: "" }[mode];
    st.assembly_texts = {
      RUE: `Roscar las ruedas de espiga en las tuercas soldadas de las placas base hasta el tope y bloquearlas con su contratuerca. ${brake}`,
      BAL: "Colocar la balda sobre el bastidor inferior, con las escotaduras alrededor de las patas, y fijarla con tornillos ISO 7380 M6 (8 N·m).",
      ENC: `Colocar la encimera sobre el bastidor superior${notch} y fijarla con tornillos ISO 7380 M6 (8 N·m).` };
    return st;
  }
  _extraDims(model, d) {
    const V = model.params.values, H = V.ALTURA;
    const zmax = Math.max(d.z_asa ?? 0.0, H + d.peto);
    const levels = d.shelf ? [["ALTURA_BALDA", "BAL.BANDEJA"]] : [];
    if (zmax > H + 1e-9) levels.push(["ALTURA_ENCIMERA", "ENC.BANDEJA", H]);     // el asa o el peto sobresalen
    levels.push(...this._petoLevel(d, H));
    const zs = [0.0, ...(d.shelf ? [d.z_shelf] : []), H, ...(d.peto > 0 ? [H + d.peto] : [])];
    model.dims.ALTURA_ENCIMERA = H;
    if (d.z_asa != null) model.dims.ALTURA_ASA = d.z_asa;
    Object.assign(model.dims, {
      envelope: { ids: ["ENC.BANDEJA", ...d.asa_corners.map((k) => `EST.PATA.${k}`)], dx: V.LONGITUD, dy: V.ANCHURA, zmax, names: ["LONGITUD", "ANCHURA"] },
      levels, drawing_expected: Object.fromEntries(levels.map((_, k) => [`DIST_NIVEL_${k + 1}`, zs[k + 1] - zs[k]])) });
  }
}

export const REGISTRY = { mesa_industrial: new MesaIndustrial(), estanteria: new Estanteria(), puesto_trabajo: new PuestoTrabajo("puesto_trabajo"),
  carro_taller: new CarroTaller("carro_taller") };
export function family(fid) {
  const f = REGISTRY[fid];
  if (!f) {
    const p = FAM.library.find((x) => x.id === fid);
    if (p) throw new Error(`La familia '${p.name}' está prevista pero su generador paramétrico todavía no está implementado.`);
    throw new Error(`Familia desconocida: ${fid}`);
  }
  return f;
}
export const allTemplates = () => Object.values(REGISTRY).flatMap((f) => f.templates());
