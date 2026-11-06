// @ts-nocheck
// Familias de producto (port exacto de monxu/families/mesa_industrial.py y estanteria.py).
import * as C from "./catalog";
import { AUTO, ParamContext, ParamError, ProductModel, axisFrame, frameZ, newParams, platePart, profilePart, sheetPart,
  standardPart, translation, sub, scale } from "./model";
import { EDGES, bendDeduction, makeSpec } from "./sheet";
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
      frame_params: d.frame_params, auto_in_construct: d.auto_in_construct, verification_inputs: d.verification_inputs });
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
    const model = new ProductModel(this.id, this.name, `MI${fx(L)}-${fx(W)}-${fx(H)}`, ps, ctx);
    model.requested = ps;
    const d = this._derive(ctx, model);
    const mat_s = V.MATERIAL_ESTRUCTURAL, mat_c = V.MATERIAL_CHAPA, fin = V.ACABADO;
    model.addSub("EST", "Estructura soldada", { welded: true, step: 1 });
    model.addSub("APO", "Apoyos niveladores", { explode: [0, 0, -160], step: 2 });
    if (d.shelf) model.addSub("BAL", "Balda inferior", { explode: [0, 0, 90], step: 3 });
    model.addSub("ENC", "Encimera", { explode: [0, 0, 380], step: 4 });
    const { leg, rail, trv, bas, c, a } = d;
    const legs = {};
    const corners = { DI: [c + a / 2, c + a / 2], DD: [L - c - a / 2, c + a / 2], TI: [c + a / 2, W - c - a / 2], TD: [L - c - a / 2, W - c - a / 2] };
    const cname = { DI: "delantera izquierda", DD: "delantera derecha", TI: "trasera izquierda", TD: "trasera derecha" };
    const foot = C.component(V.PIE_NIVELADOR);
    const thread = parseFloat(foot.thread.slice(1));
    const nutCode = `TUERCA_SOLDAR_M${fx(thread)}`;
    const rn = C.component("TUERCA_REMACHABLE_M6");
    const sc = C.component("TORNILLO_ISO7380_M6x12");
    const weld = makeWelder(model);

    ctx.feature("F10", "Estructura soldada", () => {
      ctx.feature("F11", "Patas, placas base y tuercas", () => {
        ctx.uses("LONGITUD_PATA", "PERFIL_PATA", "RETRANQUEO", "LONGITUD", "ANCHURA", "ESPESOR_PLACA_BASE", "PIE_NIVELADOR",
          "MATERIAL_ESTRUCTURAL", "ACABADO");
        legsAndPlates(model, d, legs, corners, cname, mat_s, fin, thread, nutCode, "pata", `Pata ${leg.code}`, "EST.PATA",
          "Pata", "Placa base a pata", d.z_tf, (k) => cname[k]);
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
    ctx.feature("F40", "Apoyos niveladores", () => {
      ctx.uses("PIE_NIVELADOR", "LONGITUD", "ANCHURA", "RETRANQUEO", "PERFIL_PATA");
      feet(model, d, corners, cname, V.PIE_NIVELADOR, foot);
    });
    ctx.feature("F20", "Encimera de chapa plegada", () => {
      ctx.uses("LONGITUD", "ANCHURA", "ALTURA", "ESP_ENC", "RADIO_ENC", "K_ENC", "ALA_ENCIMERA", "MATERIAL_CHAPA",
        "PASO_FIJACIONES", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ACABADO");
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
    model.structure = this._structure(model, d, legs);
    model.dims = { LONGITUD: L, ANCHURA: W, ALTURA: H, ALTURA_BALDA: d.shelf ? d.z_shelf : null, LONGITUD_PATA: d.leg_len,
      envelope: { ids: ["ENC.BANDEJA"], dx: L, dy: W, zmax: H, names: ["LONGITUD", "ANCHURA"] },
      levels: d.shelf ? [["ALTURA_BALDA", "BAL.BANDEJA"]] : [],
      load_text: `Carga distribuida de proyecto sobre encimera: ${V.CARGA_TOTAL ? pyStr(V.CARGA_TOTAL) + " kg" : "NO DEFINIDA"}` };
    model.numberParts();
    return model;
  }

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
      const foot = C.component(ctx.get("PIE_NIVELADOR"));
      const hn = +foot.nominal_height;
      const tp = ctx.get("ESPESOR_PLACA_BASE");
      const z_tf = ctx.derive("COTA_BASTIDOR_SUP", (p) => p.get("ALTURA") - p.get("ESP_ENC"), "mm", "Cota cara superior del bastidor");
      const z_leg0 = ctx.derive("COTA_INICIO_PATA", (p) => +C.component(p.get("PIE_NIVELADOR")).nominal_height + p.get("ESPESOR_PLACA_BASE"),
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
      d.top_spec = makeSpec({ Lx: L, Ly: W, t, r, K, flanges: EDGES.map((e) => ({ edge: e, height: ala, direction: "down",
        holes: fix_top.s[e].map((s) => [s, fix_top.h[e], hd]) })) });
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
    return { levels: model.structure.levels ?? {}, surfaces, supports: supportsOf(model, legs), horizontal_points: [legs.DI, legs.DD],
      worktop_height: ps.ALTURA, leg_ids: Object.values(legs), member_roles: memberRoles(model) };
  }
}

const pyStr = (x) => (Number.isInteger(x) ? `${x}.0` : String(x));   // str(float) de Python
const supportsOf = (model, legs) => ["DI", "DD", "TI", "TD"].map((k) => ({ instance: `APO.PIE.${k}`, leg: legs[k],
  point: [...model.instance(legs[k]).axis[0]], component: model.params.values.PIE_NIVELADOR }));
const memberRoles = (model) => Object.fromEntries(model.instances.filter((i) => i.structural).map((i) => [i.id, i.part.role]));

function legsAndPlates(model, d, legs, corners, cname, mat_s, fin, thread, nutCode, role, partName, idPrefix, word, weldDesc, zTop) {
  const { leg, a, tp, hn } = d;
  const legPart = profilePart(role, partName, leg.code, d.leg_len, mat_s, fin);
  const plateMat = C.material(mat_s).family === "acero_carbono" ? "S235JR" : mat_s;
  const plate = platePart("placa_base", `Placa base ${fx(a)}x${fx(a)}x${fx(tp)}`, a, a, tp, plateMat, fin, Math.min(3.0, a / 10),
    [[a / 2, a / 2, thread + 1.0]]);
  const nut = standardPart("tuerca_soldar", nutCode);
  for (const [k, [x, y]] of Object.entries(corners)) {
    const iid = `${idPrefix}.${k}`;
    const p0 = [x, y, d.z_leg0], p1 = [x, y, zTop];
    model.add(iid, `${word} ${cname[k]}`, legPart, axisFrame(p0, p1, [0, 1, 0]), "EST", { axis: [p0, p1], up: [0, 1, 0], structural: true });
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

function feet(model, d, corners, cname, code, foot) {
  const fpart = standardPart("pie_nivelador", code);
  for (const [k, [x, y]] of Object.entries(corners)) {
    model.add(`APO.PIE.${k}`, `Pie nivelador ${cname[k]}`, fpart, translation(x, y, 0.0), "APO");
    model.joint({ id: `J.PIE.${k}`, kind: "roscada", members: [`APO.PIE.${k}`, `EST.TUERCA.${k}`], location: [x, y, d.hn],
      description: `Pie roscado ${foot.thread} en tuerca soldada` });
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

function fixLayout(model, Lx, Ly, c, a, t, R, ala, prof_long, prof_end, z_ref, inset, hole_d, rn, pitch, short_min, tag, notch = 0.0, offset = 0.0) {
  const margin = 60.0;
  const long_rng = [c + a + margin, Lx - c - a - margin];
  const short_rng = [c + a + margin / 2, Ly - c - a - margin / 2];
  const count = (span, nmin) => Math.max(nmin, Math.ceil(span / pitch) + 1);
  const n_long = count(long_rng[1] - long_rng[0], 2);
  const n_short = count(short_rng[1] - short_rng[0], short_min);
  const s = { y0: evenPositions(...long_rng, n_long), y1: evenPositions(...long_rng, n_long),
    x0: evenPositions(...short_rng, n_short), x1: evenPositions(...short_rng, n_short) };
  const h = {};
  const word = tag.split(/\s+/)[0];
  for (const e of EDGES) {
    const prof = e === "y0" || e === "y1" ? prof_long : prof_end;
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
  const wall = Object.fromEntries(EDGES.map((e) => [e, (e === "y0" || e === "y1" ? prof_long : prof_end).t]));
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
  const long_ids = [];
  for (const [k, nm, p0, p1, l0, l1] of [["D", "delantero", [x0, y_f, zl], [x1, y_f, zl], "DI", "DD"],
    ["T", "trasero", [x1, y_b, zl], [x0, y_b, zl], "TD", "TI"]]) {
    const iid = `EST.LAR_${level}.${k}`;
    model.add(iid, `Larguero ${lab} ${nm}`, lp, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
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
      const [pf, nrm] = { y0: [[off + s, off, z], [0, -1, 0]], y1: [[off + s, off + Ly, z], [0, 1, 0]],
        x0: [[off, off + s, z], [-1, 0, 0]], x1: [[off + Lx, off + s, z], [1, 0, 0]] }[e];
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

export const REGISTRY = { mesa_industrial: new MesaIndustrial(), estanteria: new Estanteria() };
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
