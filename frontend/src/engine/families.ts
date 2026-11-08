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
const NUT_SUFFIX = { acero_carbono: "", acero_inoxidable: "_A2", aluminio: "_AL" };
/** Tuerca de soldar del mismo material que la estructura (acero no se suelda a aluminio; en inoxidable, corrosión). */
export const weldNutCode = (thread, mat_s) => `TUERCA_SOLDAR_M${fx(thread)}${NUT_SUFFIX[C.material(mat_s).family] ?? ""}`;
export function evenPositions(a, b, n) {
  if (n === 1) return [(a + b) / 2];
  return range(n).map((i) => a + (i * (b - a)) / (n - 1));
}
const weldA = (tmin) => (tmin >= 3 ? 3.0 : +tmin);
const pt = (p) => p.map(Number);

// ============================================================================ base común (mesa)
const FOOTREST_LOAD_N = 1000.0;     // apoyo del pie en el centro del reposapiés (criterio de ensayo habitual de 1 kN)
const FOOT_CLEARANCE = 100.0;       // hueco libre mínimo sobre el reposapiés para apoyar el pie
const CROSSBEAM_GAP = 5.0;          // hueco mínimo entre travesaños intermedios, y con las patas, para soldarlos
/** Cota de balda compatible con el reposapiés: por debajo o por encima dejando el hueco para el pie; la más próxima. */
function shelfClearOfFootrest(ctx, d, zr, fp) {
  const ts = d.z_shelf - d.z_lf, bas = d.bas, zs = d.z_shelf;
  const lo = Math.floor((zr - fp.H - 40) / 5) * 5;
  const hi = Math.ceil((zr + FOOT_CLEARANCE + Math.max(ctx.get("ALA_BALDA"), ts + bas.H)) / 5) * 5;
  const ok = [];
  if (lo >= 100 && lo - ts - bas.H >= d.z_leg0 + 20) ok.push(lo);
  if (hi <= 600 && hi <= d.z_tf - d.skirt - 150) ok.push(hi);
  if (!ok.length) return null;
  return ok.reduce((b, z) => (Math.abs(z - zs) < Math.abs(b - zs) ? z : b));
}
class MesaIndustrial {
  constructor(id = "mesa_industrial") {
    const d = FAM.families[id];
    Object.assign(this, { id, name: d.name, category: d.category, description: d.description, def: d,
      candidates: d.candidates, constructive_defaults: d.constructive_defaults, leg_param: d.leg_param,
      frame_params: d.frame_params, auto_in_construct: d.auto_in_construct, verification_inputs: d.verification_inputs,
      support_param: "PIE_NIVELADOR", support_category: "patas", support_group: ["APO", "Apoyos niveladores"],
      top_iid: "ENC.BANDEJA", top_label: "Encimera", min_clear_height: 600.0 });
  }
  specs() { return this.def.params; }
  templates() { return this.def.templates; }
  describe() { const { templates, candidates, constructive_defaults, leg_param, frame_params, auto_in_construct, ...r } = this.def; return r; }
  newParams(values = {}, sources = {}) { return newParams(this.specs(), values, sources); }

  /** ¿Lleva balda inferior? (las familias sin balda no tienen los parámetros de la balda). */
  _hasShelf(ctx) { return ctx.get("NUMERO_BALDAS") >= 1; }
  /** Perfil de las vigas que forman pórtico con las patas en la dirección X (largueros) o Y (travesaños). */
  swayBeamParam(axis) { return axis === 0 ? "PERFIL_LARGUERO" : "PERFIL_TRAVESANO"; }
  /** Retranqueo bastidor–cara exterior para una chapa plegada: espesor + holgura (igual que en la derivación). */
  sheetInset(v, tParam, gapParam) {
    const t = v[tParam];
    const fam = C.material(v.MATERIAL_CHAPA).family;
    const rmin = C.sheetData().press_brake.min_inner_radius_factor[fam] ?? 1.0;
    const r = v.RADIO_PLEGADO === AUTO ? pyRound(Math.max(t, rmin * t), 2) : v.RADIO_PLEGADO;
    const head_h = +C.component("TUERCA_REMACHABLE_M6").head_h;
    return t + (v[gapParam] === AUTO ? Math.max(r, head_h) : v[gapParam]);
  }
  /** El bastidor inferior, retranqueado para la pestaña de la balda, cabe en la sección de la pata. */
  legFits(v) {
    if (!((v.NUMERO_BALDAS ?? 0) >= 1)) return true;
    if ([this.leg_param, "PERFIL_BASTIDOR", "ESPESOR_BALDA"].some((k) => v[k] === AUTO || v[k] == null)) return true;
    return this.sheetInset(v, "ESPESOR_BALDA", "HOLGURA_ENCIMERA") + C.profile(v.PERFIL_BASTIDOR).B <= C.profile(v[this.leg_param]).B + 1e-9;
  }
  paramForRole(role) {
    return { pata: "PERFIL_PATA", larguero_sup: "PERFIL_LARGUERO", travesano_ext_sup: "PERFIL_TRAVESANO",
      travesano_int_sup: "PERFIL_TRAVESANO", larguero_inf: "PERFIL_BASTIDOR", travesano_ext_inf: "PERFIL_BASTIDOR",
      travesano_int_inf: "PERFIL_BASTIDOR", reposapies: "PERFIL_REPOSAPIES" }[role] ?? null;
  }
  verticalLoadPresent(v) { return !!(v.CARGA_TOTAL || v.CARGA_PUNTUAL); }     // la carga puntual también dimensiona
  plateTargets(v) {
    const out = [];
    if (v.CARGA_TOTAL || v.CARGA_PUNTUAL) out.push({ surface: "encimera", t_param: "ESPESOR_CHAPA", n_param: "NUMERO_TRAVESANOS",
      load_param: "CARGA_TOTAL", trv_param: "PERFIL_TRAVESANO", min_t_by_use: true });
    if (v.CARGA_BALDA && (v.NUMERO_BALDAS ?? 0) >= 1) out.push({ surface: "balda", t_param: "ESPESOR_BALDA",
      n_param: "NUMERO_TRAVESANOS_BALDA", load_param: "CARGA_BALDA", trv_param: "PERFIL_BASTIDOR", min_t_by_use: false });
    return out;
  }
  sheetDefaultsWithoutLoad(v) {
    const out = {};
    if (!(v.CARGA_TOTAL || v.CARGA_PUNTUAL)) out.ESPESOR_CHAPA = this.constructive_defaults.ESPESOR_CHAPA;
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
    model.addSub("ENC", this.top_label, { explode: [0, 0, 380], step: 4 });
    const { leg, rail, trv, bas, c, a } = d;
    const legs = {};
    const corners = { DI: [c + a / 2, c + a / 2], DD: [L - c - a / 2, c + a / 2], TI: [c + a / 2, W - c - a / 2], TD: [L - c - a / 2, W - c - a / 2] };
    const cname = { DI: "delantera izquierda", DD: "delantera derecha", TI: "trasera izquierda", TD: "trasera derecha" };
    const foot = C.component(V[this.support_param]);
    const thread = parseFloat(foot.thread.slice(1));
    const nutCode = weldNutCode(thread, mat_s);
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
          "PERFIL_TRAVESANO", "COTA_BASTIDOR_SUP", ...this._topFrameUses(), "MATERIAL_ESTRUCTURAL", "ACABADO");
        frameLevel(model, d, "SUP", d.z_tf, rail, trv, 0.0, d.n_top, legs, d.fix_top, weld, mat_s, fin);
      });
      if (d.shelf) ctx.feature("F13", "Bastidor inferior", () => {
        ctx.uses("PERFIL_BASTIDOR", "N_TRAVESANOS_BALDA", "COTA_BALDA", "ESP_BAL", "LONGITUD", "ANCHURA", "RETRANQUEO",
          "PERFIL_PATA", "PASO_FIJACIONES", "ALA_BALDA", "MATERIAL_ESTRUCTURAL");
        frameLevel(model, d, "INF", d.z_lf, bas, bas, d.e_shelf, d.n_shelf, legs, d.fix_shelf, weld, mat_s, fin);
      });
    });
    if (d.footrest) ctx.feature("F17", "Reposapiés soldado", () => {
      ctx.uses("REPOSAPIES", "ALTURA_REPOSAPIES", "PERFIL_REPOSAPIES", "LONGITUD", "RETRANQUEO", "PERFIL_PATA", "MATERIAL_ESTRUCTURAL", "ACABADO");
      const { prof: fp, z: zr } = d.footrest;
      const y = c + a / 2, zc = zr - fp.H / 2;
      const p0 = [c + a, y, zc], p1 = [L - c - a, y, zc];
      const part = profilePart("reposapies", `Reposapiés ${fp.code}`, fp.code, L - 2 * c - 2 * a, mat_s, fin);
      model.add("EST.REPOSAPIES", "Reposapiés delantero", part, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
      weld("J.EST.REPOSAPIES.0", "EST.REPOSAPIES", 0, legs.DI, fp, "Reposapiés a pata");
      weld("J.EST.REPOSAPIES.1", "EST.REPOSAPIES", 1, legs.DD, fp, "Reposapiés a pata");
    });
    ctx.feature("F40", this.support_group[1], () => {
      ctx.uses(this.support_param, "LONGITUD", "ANCHURA", "RETRANQUEO", "PERFIL_PATA");
      feet(model, d, corners, cname, V[this.support_param], foot, this.support_group[0], (k) => this._supportPart(k, V));
    });
    this._buildTop(model, ctx, d, H, mat_c, fin);
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
    if (peto > 0) levels.push(["ALTURA_ENCIMERA", this.top_iid, H], ...this._petoLevel(d, H));     // altura de trabajo y peto en la cadena
    model.dims = { LONGITUD: L, ANCHURA: W, ALTURA: H, ALTURA_BALDA: d.shelf ? d.z_shelf : null, LONGITUD_PATA: d.leg_len,
      envelope: { ids: [this.top_iid], dx: L, dy: W, zmax: H + peto, names: ["LONGITUD", "ANCHURA"] },
      levels,
      load_text: `Carga distribuida de proyecto sobre ${this.top_label.toLowerCase()}: ${V.CARGA_TOTAL ? pyStr(V.CARGA_TOTAL) + " kg" : "NO DEFINIDA"}` };
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
  /** Parámetros de la superficie de trabajo que intervienen en el bastidor superior. */
  _topFrameUses() { return ["PASO_FIJACIONES", "ALA_ENCIMERA"]; }
  /** Superficie de trabajo: encimera de chapa plegada atornillada al bastidor superior. */
  _buildTop(model, ctx, d, H, mat_c, fin) {
    ctx.feature("F20", `${this.top_label} de chapa plegada`, () => {
      ctx.uses("LONGITUD", "ANCHURA", "ALTURA", "ESP_ENC", "RADIO_ENC", "K_ENC", "ALA_ENCIMERA", "MATERIAL_CHAPA",
        "PASO_FIJACIONES", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ACABADO", "PETO_TRASERO");
      const spec = d.top_spec;
      model.add("ENC.BANDEJA", this.top_label, sheetPart("encimera", `${this.top_label} chapa ${g(spec.t)} mm`, spec, mat_c, fin), translation(0, 0, H), "ENC");
      fasteners(model, d.fix_top, "ENC");
    });
  }
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
      const trv = C.profile(ctx.get("PERFIL_TRAVESANO"));
      const bas = "PERFIL_BASTIDOR" in v ? C.profile(ctx.get("PERFIL_BASTIDOR")) : null;     // sin balda: no existe
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
      const shelf = this._hasShelf(ctx);
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
      d.skirt = ctx.get("ALA_ENCIMERA");
      if (shelf) this._deriveShelf(ctx, model, d);
      if (this.min_clear_height && H - ctx.get("ALA_ENCIMERA") < this.min_clear_height) model.note("advertencia", "ERG-ALTURA", `Altura libre bajo encimera inferior a ${g(this.min_clear_height)} mm.`);
      this._deriveFootrest(ctx, model, d);
    });
    return d;
  }

  /** Balda inferior de chapa plegada sobre su bastidor (dentro de la operación F00). */
  _deriveShelf(ctx, model, d) {
    const v = ctx.params.values;
    const L = d.Lx, W = d.Ly, { c, a, bas, z_leg0 } = d;
    const fam = C.material(v.MATERIAL_CHAPA).family;
    const rmin = C.sheetData().press_brake.min_inner_radius_factor[fam] ?? 1.0;
    const radius = (t) => (v.RADIO_PLEGADO !== AUTO ? v.RADIO_PLEGADO : pyRound(Math.max(t, rmin * t), 2));
    const kf = (r, t) => (v.FACTOR_K !== AUTO ? v.FACTOR_K : pyRound(C.din6935K(r, t), 4));
    const head_h = +C.component("TUERCA_REMACHABLE_M6").head_h;
    const rn = C.component("TUERCA_REMACHABLE_M6"), sc = C.component("TORNILLO_ISO7380_M6x12");
    const pitch = ctx.get("PASO_FIJACIONES");
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
    if (z_lf - bas.H < z_leg0 + 20) {
      const zMin = Math.ceil((z_leg0 + 20 + bas.H + ts) / 5) * 5;
      if (ctx.params.sources.ALTURA_BALDA === "defecto" && zMin <= 600 && zMin <= d.z_tf - d.skirt - 150)
        model.rule_fixes.ALTURA_BALDA = [zMin, `Balda inferior a ${g(zMin)} mm (regla de diseño): a la altura por defecto, ${g(z_s)} mm, su `
          + "bastidor no cabía sobre las placas base y los apoyos."];
      model.note("error", "GEO-BALDA-BAJA", `La balda está demasiado baja para el bastidor inferior: ALTURA_BALDA de ${g(zMin)} mm como mínimo.`);
    }
    const ala_b = ctx.get("ALA_BALDA");
    const hds = flangeHoleD(v.MATERIAL_CHAPA, ts, sc);
    const fix_sh = fixLayout(model, L - 2 * c, W - 2 * c, 0.0, a, ts, rs + ts, ala_b, bas, bas, z_s, e_sh, hds, rn, pitch * 1.5, 1,
      "balda", notch, c);
    fix_sh.gap = g_s;
    d.shelf_spec = makeSpec({ Lx: L - 2 * c, Ly: W - 2 * c, t: ts, r: rs, K: Ks, notch: [notch, notch],
      flanges: EDGES.map((e) => ({ edge: e, height: ala_b, direction: "down", holes: fix_sh.s[e].map((s) => [s, fix_sh.h[e], hds]) })) });
    Object.assign(d, { z_shelf: z_s, z_lf, e_shelf: e_sh, n_shelf: n_sh, xb: [xb0, xb1], fix_shelf: fix_sh });
    if (z_s > d.z_tf - d.skirt - 150) model.note("advertencia", "ERG-BALDA-ALTA", "Hueco libre entre balda y encimera inferior a 150 mm.");
  }
  /** Reposapiés delantero entre patas (dentro de la operación F00). */
  _deriveFootrest(ctx, model, d) {
    const v = ctx.params.values;
    const { a, z_leg0, shelf, bas } = d;
    d.footrest = null;
    if (v.REPOSAPIES) {
      const fp = C.profile(ctx.get("PERFIL_REPOSAPIES"));
      const zr = ctx.derive("COTA_REPOSAPIES", (p) => p.get("ALTURA_REPOSAPIES"), "mm", "Cota superior del reposapiés");
      d.footrest = { prof: fp, z: zr };
      if (fp.B > a) model.note("error", "DFM-REPOSAPIES-ANCHO", `El perfil del reposapiés ${fp.code} es más ancho que la pata.`);
      if (zr - fp.H < z_leg0 + 20) model.note("error", "GEO-REPOSAPIES-BAJO", `El reposapiés (${g(zr)} mm) queda demasiado bajo para soldarse a las patas por encima de la placa base.`);
      if (shelf) {
        const lo_s = d.z_shelf - Math.max(ctx.get("ALA_BALDA"), d.z_shelf - d.z_lf + bas.H);
        const above = zr - fp.H >= d.z_shelf + 40, below = zr + FOOT_CLEARANCE <= lo_s;
        if (!(above || below)) {
          const zFix = shelfClearOfFootrest(ctx, d, zr, fp);
          if (zFix !== null) model.rule_fixes.ALTURA_BALDA = [zFix, `Balda inferior a ${g(zFix)} mm (regla de diseño): a la altura por defecto, `
            + `${g(d.z_shelf)} mm, chocaba con el reposapiés a ${g(zr)} mm.`];
          model.note("error", "GEO-REPOSAPIES-BALDA", `El reposapiés (${g(zr - fp.H)}–${g(zr)} mm) choca con la balda inferior o no deja `
            + `${g(FOOT_CLEARANCE)} mm para el pie bajo ella (${g(lo_s)}–${g(d.z_shelf)} mm): cambie ALTURA_REPOSAPIES o ALTURA_BALDA.`);
        }
      }
    }
  }

  _structure(model, d, legs) {
    const ps = model.params.values;
    const surfaces = [{ id: "encimera", label: this.top_label, level: "SUP", load_param: "CARGA_TOTAL", sheet_instance: this.top_iid,
      area_mm2: ps.LONGITUD * ps.ANCHURA, ...(d.top_surface ?? {}), count_param: "NUMERO_TRAVESANOS" }];
    if (d.shelf) surfaces.push({ id: "balda", label: "Balda inferior", level: "INF", load_param: "CARGA_BALDA", sheet_instance: "BAL.BANDEJA",
      area_mm2: (ps.LONGITUD - 2 * d.c) * (ps.ANCHURA - 2 * d.c), count_param: "NUMERO_TRAVESANOS_BALDA" });
    const point_loads = d.footrest ? [{ id: "F", member: "EST.REPOSAPIES", load_N: FOOTREST_LOAD_N, label: "Apoyo del pie en el centro del reposapiés",
      hypothesis: `Reposapiés: ${g(FOOTREST_LOAD_N)} N verticales en el centro de la barra (apoyo de una persona), como acción variable.` }] : [];
    return { levels: model.structure.levels ?? {}, surfaces, supports: supportsOf(model, legs, this.support_group[0]), point_loads, horizontal_points: [legs.DI, legs.DD],
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
      description: partOf ? `${fname} roscad${fpart.role === "rueda" ? "a" : "o"} ${foot.thread} en tuerca soldada` : `Pie roscado ${foot.thread} en tuerca soldada` });
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
  // los n travesaños no se solapan entre sí ni con las patas (si llegan a su altura en Y)
  const fits = (n) => {
    const pitch = (x_r - x_l) / (n + 1);
    if (pitch - prof_end.B < CROSSBEAM_GAP - 1e-9) return false;
    return !(inset + prof_long.B < a && x_l + pitch - prof_end.B / 2 < c + a + CROSSBEAM_GAP - 1e-9);
  };
  if (n_int && !fits(n_int)) {          // antes se generaban solapados sin aviso (sólo con valores manuales)
    let nMax = 0;
    for (let n = 0; n < n_int; n++) if (fits(n)) nMax = n;
    const msg = `Los ${n_int} travesaños intermedios ${lab} de ${prof_end.code} no caben entre los travesaños extremos y las patas o montantes `
      + `(se solapan o no dejan ${g(CROSSBEAM_GAP)} mm para soldar): como máximo ${nMax}.`;
    if (!model.design_notes.some((x) => x.code === "DFM-TRAVESANOS" && x.message === msg)) model.note("error", "DFM-TRAVESANOS", msg);
  }
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
  constructor(id = "estanteria") { super(id); }
  /** Retranqueo bastidor–cara exterior (espesor de bandeja + holgura), igual que en la derivación. */
  bayInset(v) { return this.sheetInset(v, "ESPESOR_BALDA", "HOLGURA_BALDA"); }
  /** Largueros y travesaños, retranqueados para la pestaña de la bandeja, caben en el montante. */
  legFits(v) {
    if (["PERFIL_MONTANTE", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ESPESOR_BALDA"].some((k) => v[k] === AUTO || v[k] == null)) return true;
    const b = Math.max(C.profile(v.PERFIL_LARGUERO).B, C.profile(v.PERFIL_TRAVESANO).B);
    return this.bayInset(v) + b <= C.profile(v.PERFIL_MONTANTE).B + 1e-9;
  }
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
    const model = new ProductModel(this.id, this.name, `${this.def.prefix ?? "ES"}${fx(A)}-${fx(Pf)}-${fx(H)}`, ps, ctx);
    model.requested = ps;
    const d = this._deriveShelf(ctx, model);
    const mat_s = V.MATERIAL_ESTRUCTURAL, mat_c = V.MATERIAL_CHAPA, fin = V.ACABADO;
    model.addSub("EST", "Estructura soldada", { welded: true, step: 1 });
    model.addSub(this.support_group[0], this.support_group[1], { explode: [0, 0, -160], step: 2 });
    model.addSub("BAL", "Bandejas", { explode: [0, -0.9 * Pf, 0], step: 3 });
    const { leg, rail, trv, a } = d;
    const corners = { DI: [a / 2, a / 2], DD: [A - a / 2, a / 2], TI: [a / 2, Pf - a / 2], TD: [A - a / 2, Pf - a / 2] };
    const cname = { DI: "delantero izquierdo", DD: "delantero derecho", TI: "trasero izquierdo", TD: "trasero derecho" };
    const sp = this.support_param;
    const foot = C.component(V[sp]);
    const thread = parseFloat(foot.thread.slice(1));
    const nutCode = weldNutCode(thread, mat_s);
    const weld = makeWelder(model);
    const legs = {};
    ctx.feature("F10", "Estructura soldada", () => {
      ctx.feature("F11", "Montantes, placas base y tuercas", () => {
        ctx.uses("LONGITUD_MONTANTE", "PERFIL_MONTANTE", "ANCHURA", "PROFUNDIDAD", "ESPESOR_PLACA_BASE", sp,
          "MATERIAL_ESTRUCTURAL", "ACABADO");
        // montantes con taladros propios por esquina (paneles del armario) o una sola pieza común
        const legDef = d.upright_holes ? (k) => ["montante", "Montante", H, d.upright_holes[k] ?? []] : null;
        legsAndPlates(model, d, legs, corners, cname, mat_s, fin, thread, nutCode, "montante", `Montante ${leg.code}`, "EST.MONT",
          "Montante", "Placa base a montante", H, legDef);
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
    ctx.feature("F40", this.support_group[1], () => {
      ctx.uses(sp, "ANCHURA", "PROFUNDIDAD", "PERFIL_MONTANTE");
      feet(model, d, corners, cname, V[sp], foot, this.support_group[0], sp === "PIE_NIVELADOR" ? null : (k) => this._supportPart(k, V));
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
    this._extras(model, ctx, d, legs, corners);
    model.structure = this._shelfStructure(model, d, legs);
    const n = d.z_levels.length, q = V.CARGA_POR_NIVEL;
    model.dims = { ANCHURA: A, PROFUNDIDAD: Pf, ALTURA: H, LONGITUD_MONTANTE: d.leg_len,
      envelope: { ids: [...Object.values(legs), ...range(n).map((i) => `BAL.BANDEJA.${i + 1}`)], dx: A, dy: Pf, zmax: H, names: ["ANCHURA", "PROFUNDIDAD"] },
      levels: range(n).map((i) => [`NIVEL_${i + 1}`, `BAL.BANDEJA.${i + 1}`]),
      drawing_expected: Object.fromEntries(range(n).map((k) => [`DIST_NIVEL_${k + 1}`, k === 0 ? d.z_levels[0] : d.z_levels[k] - d.z_levels[k - 1]])),
      load_text: q ? `Carga distribuida por nivel de proyecto: ${g(q)} kg (${n} niveles, total ${g(n * q)} kg)` : "Carga por nivel: NO DEFINIDA" };
    this._extraDims(model, d);
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
      const sp = this.support_param;
      const foot = C.component(ctx.get(sp));
      const hn = +foot.nominal_height, tp = ctx.get("ESPESOR_PLACA_BASE");
      const A = ctx.get("ANCHURA"), Pf = ctx.get("PROFUNDIDAD"), H = ctx.get("ALTURA");
      const z_leg0 = ctx.derive("COTA_INICIO_MONTANTE", (p) => +C.component(p.get(sp)).nominal_height + p.get("ESPESOR_PLACA_BASE"),
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
      if (z1 - ts - rail.H < z_leg0 + 20) {
        const z1min = Math.ceil((z_leg0 + 20 + ts + rail.H) / 5) * 5;
        const fits = ctx.get("DISTANCIA_BALDAS") === AUTO || z1min + (n - 1) * dist <= H;
        if (ctx.params.sources.ALTURA_PRIMER_NIVEL === "defecto" && z1min <= 800 && fits)
          model.rule_fixes.ALTURA_PRIMER_NIVEL = [z1min, `Primer nivel a ${g(z1min)} mm (regla de diseño): a la altura por defecto, ${g(z1)} mm, `
            + "su bastidor no cabía sobre las placas base y los apoyos."];
        model.note("error", "GEO-NIVEL-BAJO", `El primer nivel está demasiado bajo para su bastidor: ALTURA_PRIMER_NIVEL de ${g(z1min)} mm como mínimo.`);
      }
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
    return { levels: model.structure.levels ?? {}, surfaces, supports: supportsOf(model, legs, this.support_group[0]), horizontal_points: [legs.DI, legs.DD],
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
  verticalLoadPresent(v) { return super.verticalLoadPresent(v) || !!(v.CARGA_ESTANTE && v.ESTANTE_SUPERIOR); }
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
        if (za < H + 80) model.note("error", "GEO-ASA-BAJA", `El asa (${g(za)} mm) debe quedar al menos 80 mm por encima de la ${this.top_label.toLowerCase()} (${g(H)} mm) para poder agarrarla.`);
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

// ============================================================================ armario (port de armario.py)
const DOOR_FLANGE = 20.0, DOOR_GAP = 5.0, DOOR_JOINT = 3.0, DOOR_REVEAL = 1.0, DOOR_END_GAP = 2.0, MAX_DOOR_W = 650.0, HEAD_CLEAR = 2.0;
const hingeCount = (h) => (h <= 1200 ? 2 : h <= 1800 ? 3 : 4);
const mrow = (x, y, z, rot) => [[...rot[0], x], [...rot[1], y], [...rot[2], z], [0, 0, 0, 1]];
class Armario extends Estanteria {
  constructor() { super("armario"); }
  _deriveShelf(ctx, model) {
    const d = super._deriveShelf(ctx, model);
    const v = ctx.params.values, A = v.ANCHURA;
    const { a, leg } = d;
    ctx.feature("F05", "Cerramiento: paneles y puertas", () => {
      const thin = C.sheetThicknesses(v.MATERIAL_CHAPA).filter((t) => t >= 1.0 - 1e-9);
      const tmin = thin.length ? Math.min(...thin) : 1.5;
      const tp = ctx.derive("ESP_PANEL", (p) => (p.get("ESPESOR_PANEL") === AUTO ? tmin : p.get("ESPESOR_PANEL")), "mm", "Espesor de laterales y fondo");
      const td = ctx.derive("ESP_PUERTA", (p) => (p.get("ESPESOR_PUERTA") === AUTO ? tmin : p.get("ESPESOR_PUERTA")), "mm", "Espesor de chapa de puertas");
      const selRn = C.selectRivetNut(leg.t);
      const [codeRn, rnd] = selRn ?? ["TUERCA_REMACHABLE_M6", C.component("TUERCA_REMACHABLE_M6")];
      const gp = +rnd.head_h;                    // la cabeza de la remachable queda entre panel y montante
      const Hp = ctx.derive("ALTO_PANEL", (p) => p.get("ALTURA") - p.get("COTA_INICIO_MONTANTE"), "mm", "Altura de laterales y fondo");
      ctx.derive("ANCHO_FONDO", (p) => p.get("ANCHURA") + 2 * (gp + p.get("ESP_PANEL")), "mm", "Anchura del fondo (cubre los cantos de los laterales)");
      const pitch = ctx.get("PASO_FIJACIONES");
      const nFix = Math.max(2, Math.ceil((Hp - 80) / pitch) + 1);
      const zsSide = evenPositions(40.0, Hp - 40.0, nFix);
      const step = (Hp - 80) / (nFix - 1);
      // fondo: a media separación de los laterales (las remachables de dos caras no coinciden en el montante)
      let zsBack = zsSide.slice(0, -1).map((z) => pyRound(z + step / 2, 3));
      if (zsBack.length < 2) zsBack = evenPositions(60.0, Hp - 60.0, 2);
      let n = ctx.get("NUMERO_PUERTAS");
      if (n === AUTO) n = A <= 600 ? 1 : 2;
      ctx.setDerived("N_PUERTAS", n, "ud", "Puertas batientes", ["NUMERO_PUERTAS", "ANCHURA"]);
      const Wtot = A + 2 * (gp + tp);
      const Hd = pyRound(Hp - 2 * DOOR_END_GAP, 3);
      const Wd = n ? pyRound((Wtot - 2 * DOOR_REVEAL - (n - 1) * DOOR_JOINT) / n, 3) : 0.0;
      if (n) {
        ctx.setDerived("ANCHO_PUERTA", Wd, "mm", "Anchura de cada puerta", ["ANCHURA", "NUMERO_PUERTAS"]);
        ctx.setDerived("ALTO_PUERTA", Hd, "mm", "Altura de puerta", ["ALTURA"]);
        if (Wd > MAX_DOOR_W) model.note("advertencia", "DFM-PUERTA-ANCHA", `Puerta de ${fx(Wd)} mm de anchura: más de ${g(MAX_DOOR_W)} mm por hoja tiende a descolgarse; use dos puertas.`);
      }
      ctx.setDerived("BISAGRAS_POR_PUERTA", n ? hingeCount(Hd) : 0, "ud", "Bisagras por puerta", ["ALTURA"]);
      const face = { DI: "-x", TI: "-x", DD: "+x", TD: "+x" };
      const holes = Object.fromEntries(Object.keys(face).map((k) => [k, zsSide.map((z) => [face[k], z, 0.0, rnd.hole_d])]));
      for (const k of ["TI", "TD"]) holes[k].push(...zsBack.map((z) => ["+y", z, 0.0, rnd.hole_d]));
      d.upright_holes = holes;
      Object.assign(d, { enc_tp: tp, enc_td: td, enc_gp: gp, enc_rn: [codeRn, rnd, selRn != null], enc_Hp: Hp, enc_zs_side: zsSide,
        enc_zs_back: zsBack, enc_n_doors: n, enc_Wtot: Wtot, enc_Wd: Wd, enc_Hd: Hd });
    });
    return d;
  }
  /** Cabezas de los tornillos de las bandejas que asoman por cada cara exterior: {cara: [[u, z]]}. */
  _trayScrewHeads(model, A, Pf) {
    const out = { x0: [], x1: [], y1: [] };
    for (const i of model.instances) {
      if (i.group !== "BAL" || i.part.role !== "tornillo") continue;
      const p = [i.T[0][3], i.T[1][3], i.T[2][3]], nz = [i.T[0][2], i.T[1][2], i.T[2][2]];
      if (nz[0] < -0.9 && Math.abs(p[0]) < 1.0) out.x0.push([p[1], p[2]]);
      else if (nz[0] > 0.9 && Math.abs(p[0] - A) < 1.0) out.x1.push([p[1], p[2]]);
      else if (nz[1] > 0.9 && Math.abs(p[1] - Pf) < 1.0) out.y1.push([p[0], p[2]]);
    }
    return out;
  }
  _extras(model, ctx, d, legs, corners) {
    const V = model.params.values, A = V.ANCHURA, Pf = V.PROFUNDIDAD;
    const a = d.a, z0 = d.z_leg0, wall = d.leg.t, mat_c = V.MATERIAL_CHAPA, fin = V.ACABADO;
    const tp = d.enc_tp, gp = d.enc_gp, Hp = d.enc_Hp;
    const [codeRn, rnd, rnFound] = d.enc_rn;
    const selSc = C.selectScrew(tp + gp, tp + gp + rnd.body_l);
    const codeSc = selSc ? selSc[0] : "TORNILLO_ISO7380_M6x12";
    const sc = C.component(codeSc);
    const hd = flangeHoleD(mat_c, tp, sc);
    const heads = this._trayScrewHeads(model, A, Pf);
    const traySc = model.instances.find((i) => i.group === "BAL" && i.part.role === "tornillo")?.part.data ?? sc;
    const hclear = pyRound(+traySc.head_d + HEAD_CLEAR, 2);
    model.structure.attached_masses = model.structure.attached_masses ?? [];
    const masses = model.structure.attached_masses;
    const fix = (prefix, panelId, pts, nrm) => {
      pts.forEach(([, pf], k) => {
        const n = k + 1, pr = sub(pf, scale(nrm, tp + gp));
        const rid = `${prefix}.TREM.${pad2(n)}`, sid = `${prefix}.TORN.${pad2(n)}`;
        model.add(rid, `Tuerca remachable ${n}`, standardPart("tuerca_remachable", codeRn), frameZ(pr, nrm), "PAN", { tags: { explode_extra: scale(nrm, 30) } });
        model.add(sid, `Tornillo ${n}`, standardPart("tornillo", codeSc), frameZ(pf, nrm), "PAN", { tags: { explode_extra: scale(nrm, 80) } });
        model.joint({ id: `J.${sid}`, kind: "atornillada", members: [panelId, rid], location: pf, description: `Tornillo ${sc.thread} en tuerca remachable`,
          fasteners: [sid, rid], data: { t_sheet: tp, gap: gp, wall, screw: codeSc, rivet: codeRn, rivet_found: rnFound, screw_found: selSc != null, hole: hd } });
      });
    };
    const headHoles = (pts, du = 0.0) => {
      const m = new Map();
      for (const [u, z] of pts) { const q = [pyRound(u + du, 3), pyRound(z - z0, 3)]; m.set(`${q[0]}|${q[1]}`, q); }
      return [...m.values()].sort((p, q) => p[0] - q[0] || p[1] - q[1]).map(([u, z]) => [u, z, hclear]);
    };
    const rho = C.material(mat_c).density;
    model.addSub("PAN", "Laterales y fondo", { explode: [0, 0, 0], step: 4 });
    ctx.feature("F37", "Laterales y fondo de chapa", () => {
      ctx.uses("ESP_PANEL", "ANCHURA", "PROFUNDIDAD", "ALTURA", "ALTO_PANEL", "ANCHO_FONDO", "PERFIL_MONTANTE", "PASO_FIJACIONES", "MATERIAL_CHAPA", "ACABADO");
      const zs = d.enc_zs_side;
      // lateral: X local = Y (fondo), Y local = Z, espesor según +X; el izquierdo y el derecho son la misma pieza
      const sideHoles = [...zs.map((z) => [a / 2, z, hd]), ...zs.map((z) => [Pf - a / 2, z, hd]), ...headHoles([...heads.x0, ...heads.x1])];
      const side = platePart("lateral", `Lateral chapa ${g(tp)} mm`, Pf, Hp, tp, mat_c, fin, 0, sideHoles);
      for (const [iid, x0, sgn, name, legsK] of [["PAN.LATERAL_I", -gp - tp, -1, "Lateral izquierdo", ["DI", "TI"]], ["PAN.LATERAL_D", A + gp, 1, "Lateral derecho", ["DD", "TD"]]]) {
        model.add(iid, name, side, mrow(x0, 0, z0, [[0, 0, 1], [1, 0, 0], [0, 1, 0]]), "PAN", { tags: { explode_extra: [sgn * 260.0, 0, 0] } });
        const xf = sgn < 0 ? x0 : x0 + tp;          // cara exterior del panel
        const pts = [];
        for (const k of legsK) for (const z of zs) pts.push([legs[k], [xf, model.instance(legs[k]).axis[0][1], z0 + z]]);
        fix(iid, iid, pts, [sgn, 0, 0]);
        const pm = side.mass;
        for (const k of legsK) for (const z of zs) {
          const ax = model.instance(legs[k]).axis[0];
          masses.push({ member: legs[k], point: [ax[0], ax[1], z0 + z], mass_kg: pm / pts.length, label: name });
        }
      }
      // fondo: X local = X, Y local = Z, espesor según -Y; cubre los cantos traseros de los laterales
      const zb = d.enc_zs_back, Wb = A + 2 * (gp + tp);
      const backHoles = [...zb.map((z) => [gp + tp + a / 2, z, hd]), ...zb.map((z) => [gp + tp + A - a / 2, z, hd]), ...headHoles(heads.y1, gp + tp)];
      const back = platePart("fondo", `Fondo chapa ${g(tp)} mm`, Wb, Hp, tp, mat_c, fin, 0, backHoles);
      model.add("PAN.FONDO", "Fondo", back, mrow(-gp - tp, Pf + gp + tp, z0, [[1, 0, 0], [0, 0, -1], [0, 1, 0]]), "PAN", { tags: { explode_extra: [0, 320.0, 0] } });
      const pts = [];
      for (const k of ["TI", "TD"]) for (const z of zb) pts.push([legs[k], [model.instance(legs[k]).axis[0][0], Pf + gp + tp, z0 + z]]);
      fix("PAN.FONDO", "PAN.FONDO", pts, [0, 1, 0]);
      const pm = back.mass;
      for (const k of ["TI", "TD"]) for (const z of zb) {
        const ax = model.instance(legs[k]).axis[0];
        masses.push({ member: legs[k], point: [ax[0], ax[1], z0 + z], mass_kg: pm / pts.length, label: "Fondo" });
      }
    });
    if (d.enc_n_doors) this._doors(model, ctx, d, legs, masses);
  }
  _doors(model, ctx, d, legs, masses) {
    const V = model.params.values;
    const z0 = d.z_leg0, gp = d.enc_gp, tp = d.enc_tp, n = d.enc_n_doors, Wd = d.enc_Wd, Hd = d.enc_Hd;
    const mat_c = V.MATERIAL_CHAPA, fin = V.ACABADO;
    const inox = C.material(V.MATERIAL_ESTRUCTURAL).family === "acero_inoxidable";
    const hingeCode = inox ? "BISAGRA_PERNIO_80_INOX" : "BISAGRA_PERNIO_80", lockCode = inox ? "CERRADURA_MANETA_INOX" : "CERRADURA_MANETA";
    const hinge = C.component(hingeCode), lock = C.component(lockCode);
    model.addSub("PUE", "Puertas", { explode: [0, -380, 0], step: 5 });
    ctx.feature("F38", "Puertas batientes de chapa plegada", () => {
      ctx.uses("NUMERO_PUERTAS", "N_PUERTAS", "ESP_PUERTA", "ANCHO_PUERTA", "ALTO_PUERTA", "ANCHURA", "ALTURA", "MATERIAL_CHAPA", "ACABADO");
      const t = d.enc_td;
      const fam = C.material(mat_c).family;
      const rmin = C.sheetData().press_brake.min_inner_radius_factor[fam] ?? 1.0;
      const r = V.RADIO_PLEGADO === AUTO ? pyRound(Math.max(t, rmin * t), 2) : V.RADIO_PLEGADO;
      const K = V.FACTOR_K === AUTO ? pyRound(C.din6935K(r, t), 4) : V.FACTOR_K;
      // desarrollo con la altura según X: a lo largo de la chapa (pulido vertical en el inoxidable satinado, que no se gira al anidar)
      const spec = makeSpec({ Lx: Hd, Ly: Wd, t, r, K, flanges: EDGES.map((e) => ({ edge: e, height: DOOR_FLANGE, direction: "down", holes: [] })) });
      const door = sheetPart("puerta", `Puerta chapa ${g(t)} mm`, spec, mat_c, fin);
      const yF = -(DOOR_GAP + DOOR_FLANGE), zd = z0 + DOOR_END_GAP, xLeft = -gp - tp + DOOR_REVEAL;
      const nh = hingeCount(Hd);
      const zh = evenPositions(150.0, Hd - 150.0, nh).map((z) => zd + z);
      const leaves = [[n === 2 ? "PUE.PUERTA_I" : "PUE.PUERTA", xLeft, n === 2 ? "izquierda" : "", "DI"]];
      if (n === 2) leaves.push(["PUE.PUERTA_D", xLeft + Wd + DOOR_JOINT, "derecha", "DD"]);
      const zl = Hd > 400 ? zd + Math.min(Hd / 2, 1050.0 - zd) : zd + Hd / 2;     // maneta a ~1.050 mm o a media altura
      const pm = door.mass;
      leaves.forEach(([iid, x0, side, legK], k) => {
        // X local = Z (altura), Y local = -X (anchura), Z local = -Y: pestañas hacia el armario
        model.add(iid, `Puerta ${side}`.trim(), door, mrow(x0 + Wd, yF, zd, [[0, -1, 0], [0, 0, -1], [1, 0, 0]]), "PUE");
        const hingeLeft = k === 0, xe = hingeLeft ? x0 : x0 + Wd;          // canto de giro
        zh.forEach((z, j0) => {
          const j = j0 + 1, hid = `${iid}.BISAGRA.${j}`;
          model.add(hid, `Bisagra ${j} puerta ${side}`.replace("  ", " ").trim(), standardPart("bisagra", hingeCode),
            mrow(xe, yF - hinge.dims[1] / 2, z - 40.0, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]), "PUE");
          model.joint({ id: `J.${hid}`, kind: "remachada", members: [iid, hid], location: [xe, yF, z], description: "Bisagra de pernio remachada a puerta y lateral (remaches no modelados)" });
        });
        const withLock = n === 1 || !hingeLeft;
        if (withLock) {                                                     // maneta en el canto libre
          const xl = hingeLeft ? x0 + Wd - 45.0 : x0 + 45.0, lid = `${iid}.MANETA`;
          model.add(lid, `Maneta con cerradura puerta ${side}`.trim(), standardPart("cerradura", lockCode),
            mrow(xl, yF - lock.dims[1] / 2, zl - 60.0, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]), "PUE");
          model.joint({ id: `J.${lid}`, kind: "remachada", members: [iid, lid], location: [xl, yF, zl], description: "Maneta con cerradura de cuarto de vuelta (montaje en taladro, no modelado)" });
        }
        // la puerta cuelga del montante del lado de las bisagras
        const extra = nh * +hinge.mass_kg + (withLock ? +lock.mass_kg : 0.0);
        const ax = model.instance(legs[legK]).axis[0];
        for (const z of zh) masses.push({ member: legs[legK], point: [ax[0], ax[1], z], mass_kg: (pm + extra) / nh, label: `Puerta ${side}`.trim() });
      });
    });
  }
  _shelfStructure(model, d, legs) {
    const st = super._shelfStructure(model, d, legs);
    st.attached_masses = model.structure.attached_masses ?? [];
    st.product_word = "armario";
    const n = d.enc_n_doors;
    st.assembly_texts = { ...(st.assembly_texts ?? {}),
      PAN: "Presentar los laterales contra la cara exterior de los montantes y atornillarlos a las tuercas remachables M6 (8 N·m), de abajo arriba; "
        + "después, el fondo, que cubre los cantos traseros de los laterales. Los taladros grandes de los paneles alojan las cabezas de los tornillos de las bandejas.",
      PUE: n ? (n === 1 ? "Remachar las bisagras de pernio a la puerta y al lateral, con la puerta calzada a 2 mm del suelo del armario; comprobar el cierre y "
        + "montar la maneta con cerradura en el canto libre." : "Remachar las bisagras de pernio a cada puerta y a su lateral, con las puertas calzadas a 2 mm del "
        + "suelo del armario y 3 mm de holgura entre ellas; montar la maneta con cerradura en la puerta derecha.") : "Armario abierto: sin puertas." };
    return st;
  }
  _extraDims(model, d) {
    const V = model.params.values, A = V.ANCHURA, Pf = V.PROFUNDIDAD, H = V.ALTURA;
    const gp = d.enc_gp, tp = d.enc_tp;
    const dx = pyRound(A + 2 * (gp + tp), 3);
    const yFront = d.enc_n_doors ? -(DOOR_GAP + DOOR_FLANGE) : 0.0;
    const dy = pyRound(Pf + gp + tp - yFront, 3);
    const ids = ["PAN.LATERAL_I", "PAN.LATERAL_D", "PAN.FONDO", ...model.instances.filter((i) => i.group === "PUE" && i.part.role === "puerta").map((i) => i.id)];
    if (!d.enc_n_doors) ids.push(...range(d.z_levels.length).map((i) => `BAL.BANDEJA.${i + 1}`));
    model.dims.ANCHURA_TOTAL = dx; model.dims.PROFUNDIDAD_TOTAL = dy;
    model.dims.envelope = { ids, dx, dy, zmax: H, names: ["ANCHURA_TOTAL", "PROFUNDIDAD_TOTAL"] };
  }
}

// ============================================================================ carro plataforma (port de carro_plataforma.py)
const FRAME_CLEARANCE = 20.0;          // mm libres entre el bastidor y la placa base (como el bastidor de la balda)
const PLATFORM_H_MAX = 500.0;          // altura máxima de la plataforma (ParamSpec de ALTURA)
class CarroPlataforma extends CarroTaller {
  constructor() { super("carro_plataforma"); Object.assign(this, { top_label: "Plataforma", min_clear_height: null }); }
  plateTargets(v) { return super.plateTargets(v).map((t) => ({ ...t, label: "la plataforma" })); }
  _hasShelf(ctx) { return false; }
  _derive(ctx, model) {
    const d = super._derive(ctx, model);
    const H = ctx.get("ALTURA"), hb = Math.max(d.rail.H, d.trv.H);
    if (d.z_tf - hb < d.z_leg0 + FRAME_CLEARANCE - 1e-9) {
      const zMin = Math.ceil((d.z_leg0 + FRAME_CLEARANCE + hb + d.t) / 5) * 5;
      const code = ctx.get(this.support_param);
      if (d.z_tf - d.z_leg0 < 1.0)       // pata de longitud nula o negativa: geometría imposible
        throw new ParamError(`La plataforma (${g(H)} mm) queda por debajo de la placa base de la rueda ${code} (${g(d.z_leg0)} mm desde el suelo): ALTURA de ${g(zMin)} mm como mínimo.`);
      if (ctx.params.sources.ALTURA === "defecto" && zMin <= PLATFORM_H_MAX)
        model.rule_fixes.ALTURA = [zMin, `Plataforma a ${g(zMin)} mm (regla de diseño): a la altura por defecto, ${g(H)} mm, el `
          + `bastidor de ${g(hb)} mm de canto no cabía sobre las placas base de la rueda ${code}.`];
      model.note("error", "GEO-PLATAFORMA-BAJA", `La plataforma (${g(H)} mm) está demasiado baja para la rueda ${code} (${g(d.hn)} mm) `
        + `y el bastidor de ${g(hb)} mm de canto: ALTURA de ${g(zMin)} mm como mínimo.`);
    }
    return d;
  }
  _structure(model, d, legs) {
    const st = super._structure(model, d, legs);
    const mode = d.asa_mode;
    st.product_word = mode !== "ninguna" ? "carro" : "plataforma";
    if (mode !== "ninguna") {     // se empuja por el asa (la del extremo izquierdo si hay dos)
      st.push_points = ["DI", "TI"].map((k) => ({ member: legs[k], z: d.z_asa - d.asa.H / 2 }));
      st.push_height = st.sway_height = d.z_asa;
      st.push_label = "Fuerza de maniobra en el asa (direcciones X e Y)";
      st.push_where = "en el asa";
    } else {
      st.push_label = "Empuje horizontal en el plano de la plataforma (direcciones X e Y)";
      st.push_where = "en el plano de la plataforma";
    }
    st.push_note = "hipótesis por defecto de empuje o tirón con las ruedas frenadas o bloqueadas por un obstáculo; debe confirmarse según el uso real del carro.";
    const brake = mode === "un_extremo" ? "Las ruedas con freno van en el extremo del asa." : "Las ruedas con freno van en el extremo izquierdo (X = 0).";
    const notch = { un_extremo: ", con las escotaduras alrededor de los montantes del asa,", dos_extremos: ", con las escotaduras alrededor de los montantes de las asas,", ninguna: "" }[mode];
    st.assembly_texts = {
      RUE: `Roscar las ruedas de espiga en las tuercas soldadas de las placas base hasta el tope y bloquearlas con su contratuerca. ${brake}`,
      ENC: `Colocar la plataforma sobre el bastidor${notch} y fijarla con tornillos ISO 7380 M6 (8 N·m).` };
    return st;
  }
  _extraDims(model, d) {
    super._extraDims(model, d);
    // la cota de la superficie se nombra como plataforma (la de la mesa es ALTURA_ENCIMERA)
    model.dims.levels = model.dims.levels.map((x) => (x[0] === "ALTURA_ENCIMERA" ? ["ALTURA_PLATAFORMA", ...x.slice(1)] : x));
    if ("ALTURA_ENCIMERA" in model.dims) { model.dims.ALTURA_PLATAFORMA = model.dims.ALTURA_ENCIMERA; delete model.dims.ALTURA_ENCIMERA; }
  }
}

// ============================================================================ carro estantería (port de carro_estanteria.py)
const HAND_CLEARANCE = 40.0;
/** Cota superior del asa válida más próxima a za (holgura para la mano con cada nivel, sin sobrepasar los montantes). */
function nearestHandle(zLevels, loOf, asaH, H, za) {
  const forb = zLevels.map((z) => [loOf(z) - HAND_CLEARANCE, z + HAND_CLEARANCE + asaH]);
  for (const zMin of [800.0, 600.0]) {
    const cands = new Set([Math.ceil(zMin / 5) * 5, Math.floor(H / 5) * 5]);
    for (const [a, b] of forb) { cands.add(Math.floor(a / 5) * 5); cands.add(Math.ceil(b / 5) * 5); }
    const ok = [...cands].filter((c) => zMin <= c && c <= H && !forb.some(([a, b]) => a < c && c < b)).sort((x, y) => x - y);
    if (ok.length) return ok.reduce((best, c) => (Math.abs(c - za) < Math.abs(best - za) ? c : best));
  }
  return null;
}
class CarroEstanteria extends Estanteria {
  constructor() {
    super();
    const d = FAM.families.carro_estanteria;
    Object.assign(this, { id: "carro_estanteria", name: d.name, category: d.category, description: d.description, def: d,
      candidates: d.candidates, constructive_defaults: d.constructive_defaults, leg_param: d.leg_param, frame_params: d.frame_params,
      auto_in_construct: d.auto_in_construct, verification_inputs: d.verification_inputs,
      support_param: "RUEDA", support_category: "ruedas_espiga", support_group: ["RUE", "Ruedas"] });
  }
  paramForRole(role) { return role === "asa" ? "PERFIL_ASA" : super.paramForRole(role); }
  _supportPart(corner, V) {
    const code = V.RUEDA;
    return corner === "DI" || corner === "TI" ? [standardPart("rueda", `${code}_FRENO`), "Rueda con freno"] : [standardPart("rueda", code), "Rueda giratoria"];
  }
  _deriveShelf(ctx, model) {
    const d = super._deriveShelf(ctx, model);
    const mode = ctx.get("ASA_EMPUJE");
    Object.assign(d, { asa_mode: mode, z_asa: null });
    ctx.feature("F06", "Asa de empuje y altura de maniobra", () => {
      const H = ctx.get("ALTURA");
      const asa = C.profile(ctx.get("PERFIL_ASA"));
      d.asa = asa;
      ctx.derive("ALTURA_EMPUJE", (p) => Math.min(p.get("ALTURA_ASA"), p.get("ALTURA")), "mm", "Altura de aplicación de la fuerza de maniobra (vuelco)");
      if (mode !== "ninguna") {
        const za = ctx.derive("COTA_ASA", (p) => p.get("ALTURA_ASA"), "mm", "Cota superior del asa");
        d.z_asa = za;
        if (za > H + 1e-9) model.note("error", "GEO-ASA-ALTA", `El asa (${g(za)} mm) queda por encima de los montantes (${g(H)} mm): reduzca ALTURA_ASA.`);
        if (asa.B > d.a) model.note("error", "DFM-ASA-ANCHO", `El perfil del asa ${asa.code} es más ancho que el montante.`);
        const band = d.ts + Math.max(d.rail.H, d.trv.H);
        const lo_b = za - asa.H, hi_b = za, ala = ctx.get("ALA_BALDA");
        for (let i = 0; i < d.z_levels.length; i++) {
          const z = d.z_levels[i], lo_l = z - Math.max(ala, band);
          if (!(lo_b >= z + HAND_CLEARANCE || hi_b <= lo_l - HAND_CLEARANCE)) {
            const zOk = nearestHandle(d.z_levels, (zz) => zz - Math.max(ala, band), asa.H, H, za);
            if (zOk !== null && ctx.params.sources.ALTURA_ASA === "defecto")
              model.rule_fixes.ALTURA_ASA = [zOk, `Asa a ${g(zOk)} mm (regla de diseño): a la altura por defecto, ${g(za)} mm, no dejaba `
                + `${g(HAND_CLEARANCE)} mm para la mano con el nivel ${i + 1}.`];
            model.note("error", "GEO-ASA-NIVEL", `El asa (${g(lo_b)}–${g(hi_b)} mm) no deja ${g(HAND_CLEARANCE)} mm de holgura para la mano `
              + `con el nivel ${i + 1} (${g(lo_l)}–${g(z)} mm): ` + (zOk !== null ? `ALTURA_ASA válida más próxima, ${g(zOk)} mm.`
                : "ninguna altura de asa es válida con estos niveles; cambie la distancia entre niveles."));
            break;
          }
        }
      }
      ctx.setDerived("DIAMETRO_RUEDA", C.component(ctx.get("RUEDA")).wheel_d, "mm", "Diámetro de rueda", ["RUEDA"]);
    });
    return d;
  }
  _extras(model, ctx, d, legs, corners) {
    if (d.asa_mode === "ninguna") return;
    const V = model.params.values;
    const { asa, a } = d, A = V.ANCHURA, Pf = V.PROFUNDIDAD;
    const weld = makeWelder(model);
    const two = d.asa_mode === "dos_extremos";
    const handles = [["EST.ASA", a / 2, "DI", "TI", two ? " izquierda" : ""]];
    if (two) handles.push(["EST.ASA_D", A - a / 2, "DD", "TD", " derecha"]);
    ctx.feature("F16", "Asa de empuje soldada", () => {
      ctx.uses("PERFIL_ASA", "ALTURA_ASA", "ASA_EMPUJE", "PROFUNDIDAD", "PERFIL_MONTANTE", "MATERIAL_ESTRUCTURAL", "ACABADO");
      const part = profilePart("asa", `Asa de empuje ${asa.code}`, asa.code, Pf - 2 * a, V.MATERIAL_ESTRUCTURAL, V.ACABADO);
      const zc = d.z_asa - asa.H / 2;
      for (const [iid, x, l0, l1, side] of handles) {
        const p0 = [x, a, zc], p1 = [x, Pf - a, zc];
        model.add(iid, `Asa de empuje${side}`, part, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
        weld(`J.${iid}.0`, iid, 0, legs[l0], asa, "Asa a montante");
        weld(`J.${iid}.1`, iid, 1, legs[l1], asa, "Asa a montante");
      }
    });
  }
  _shelfStructure(model, d, legs) {
    const st = super._shelfStructure(model, d, legs);
    const V = model.params.values;
    st.product_word = "carro";
    st.push_height = Math.min(V.ALTURA_ASA, V.ALTURA);        // vuelco: altura de la mano o del asa
    const { APO, ...texts } = st.assembly_texts;
    texts.RUE = "Roscar las ruedas de espiga en las tuercas soldadas de las placas base hasta el tope y bloquearlas con su contratuerca. "
      + "Las ruedas con freno van en el extremo izquierdo (X = 0).";
    st.assembly_texts = texts;
    return st;
  }
  _extraDims(model, d) { if (d.z_asa != null) model.dims.ALTURA_ASA = d.z_asa; }
}

// ============================================================================ estantería en batería (port de estanteria_bateria.py)
const BAY_GAP = 1.0;                 // junta entre bandejas de módulos contiguos
const FIX_MARGIN = 60.0;             // margen de fijaciones respecto a la cara del montante (como fixLayout)
class EstanteriaBateria extends Estanteria {
  constructor() { super("estanteria_bateria"); }
  /** Además de la regla de la estantería, los dos travesaños laterales caben en el montante común. */
  legFits(v) {
    if (!super.legFits(v)) return false;
    if (["PERFIL_MONTANTE", "PERFIL_TRAVESANO", "ESPESOR_BALDA"].some((k) => v[k] === AUTO || v[k] == null)) return true;
    const a = C.profile(v.PERFIL_MONTANTE).B;
    return BAY_GAP / 2 + this.bayInset(v) + C.profile(v.PERFIL_TRAVESANO).B <= a / 2 + 1e-9;
  }
  _deriveShelf(ctx, model) {
    const d = super._deriveShelf(ctx, model);
    const v = ctx.params.values;
    ctx.feature("F01", "Disposición en batería", () => {
      const N = ctx.get("NUMERO_MODULOS"), M = ctx.get("ANCHURA"), Pf = ctx.get("PROFUNDIDAD");
      const { a, e, trv, ts } = d;
      const A_tot = ctx.derive("ANCHURA_TOTAL", (p) => p.get("NUMERO_MODULOS") * p.get("ANCHURA") + C.profile(p.get("PERFIL_MONTANTE")).B,
        "mm", "Anchura total de la batería");
      ctx.derive("N_MONTANTES", (p) => 2 * (p.get("NUMERO_MODULOS") + 1), "ud", "Montantes");
      const xs = range(N + 1).map((k) => a / 2 + k * M);
      if (BAY_GAP / 2 + e + trv.B > a / 2 + 1e-9)
        model.note("error", "DFM-BATERIA-MONTANTE", `Los dos travesaños laterales (${trv.code}) no caben en el montante común ${d.leg.code}: `
          + `hacen falta ${fx(2 * (BAY_GAP / 2 + e + trv.B))} mm de sección. Aumente PERFIL_MONTANTE o reduzca PERFIL_TRAVESANO.`);
      if (A_tot > 3000)
        model.note("advertencia", "ERG-TRANSPORTE", `Estructura soldada de ${fx(A_tot)} mm de longitud: comprobar transporte, acceso y manipulación.`);
      const Lt = M - BAY_GAP;
      const notch = [a / 2 + ctx.get("HOLGURA_ESCOTADURA") - BAY_GAP / 2, a + ctx.get("HOLGURA_ESCOTADURA")];
      const sc = C.component("TORNILLO_ISO7380_M6x12"), rn = C.component("TUERCA_REMACHABLE_M6");
      const ala = ctx.get("ALA_BALDA");
      const rs = d.spec.r, Ks = d.spec.K;
      const hd = flangeHoleD(v.MATERIAL_CHAPA, ts, sc);
      const s0 = a / 2 - BAY_GAP / 2 + FIX_MARGIN;
      const fix = {};
      d.level_ids.forEach((lid, k) => {
        const f = fixLayout(model, Lt, Pf, 0.0, a, ts, rs + ts, ala, d.rail, trv, d.z_levels[k], e, hd, rn, ctx.get("PASO_FIJACIONES"), 1,
          `bandeja ${lid}`, 0.0, [0.0, 0.0], { y0: [s0, Lt - s0, 2], y1: [s0, Lt - s0, 2] });
        f.gap = d.fix[lid].gap;
        // pestañas laterales enfrentadas a la de la bandeja contigua (junta de 1 mm): sin tornillería
        f.s.x0 = []; f.s.x1 = [];
        fix[lid] = f;
      });
      const f0 = fix[d.level_ids[0]];
      Object.assign(d, { N, M, xs, A_tot, fix, Lt });
      d.spec = makeSpec({ Lx: Lt, Ly: Pf, t: ts, r: rs, K: Ks, notch,
        flanges: EDGES.map((ed) => ({ edge: ed, height: ala, direction: "down", holes: f0.s[ed].map((s) => [s, f0.h[ed], hd]) })) });
      d.xb = [BAY_GAP / 2 + e + trv.B / 2, M - BAY_GAP / 2 - e - trv.B / 2];
    });
    return d;
  }

  construct(ps) {
    this.checkResolved(ps);
    const ctx = new ParamContext(ps);
    const V = ps.values;
    const M = V.ANCHURA, Pf = V.PROFUNDIDAD, H = V.ALTURA, N = V.NUMERO_MODULOS;
    const model = new ProductModel(this.id, this.name, `${this.def.prefix}${N}x${fx(M)}-${fx(Pf)}-${fx(H)}`, ps, ctx);
    model.requested = ps;
    const d = this._deriveShelf(ctx, model);
    const mat_s = V.MATERIAL_ESTRUCTURAL, mat_c = V.MATERIAL_CHAPA, fin = V.ACABADO;
    model.addSub("EST", "Estructura soldada", { welded: true, step: 1 });
    model.addSub(this.support_group[0], this.support_group[1], { explode: [0, 0, -160], step: 2 });
    model.addSub("BAL", "Bandejas", { explode: [0, -0.9 * Pf, 0], step: 3 });
    const { leg, a, xs } = d;
    const corners = {}, cname = {};
    xs.forEach((x, k) => {
      corners[`D${k}`] = [x, a / 2]; cname[`D${k}`] = `delantero ${k + 1}`;
      corners[`T${k}`] = [x, Pf - a / 2]; cname[`T${k}`] = `trasero ${k + 1}`;
    });
    const sp = this.support_param;
    const foot = C.component(V[sp]);
    const thread = parseFloat(foot.thread.slice(1));
    const nutCode = weldNutCode(thread, mat_s);
    const weld = makeWelder(model);
    const legs = {};
    ctx.feature("F10", "Estructura soldada", () => {
      ctx.feature("F11", "Montantes, placas base y tuercas", () => {
        ctx.uses("LONGITUD_MONTANTE", "PERFIL_MONTANTE", "ANCHURA", "NUMERO_MODULOS", "PROFUNDIDAD", "ESPESOR_PLACA_BASE", sp,
          "MATERIAL_ESTRUCTURAL", "ACABADO");
        legsAndPlates(model, d, legs, corners, cname, mat_s, fin, thread, nutCode, "montante", `Montante ${leg.code}`, "EST.MONT",
          "Montante", "Placa base a montante", H);
      });
      d.level_ids.forEach((lid, i0) => {
        const i = i0 + 1, z = d.z_levels[i0];
        ctx.feature(`F2${i}`, `Bastidores del nivel ${i}`, () => {
          ctx.uses("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "N_TRAVESANOS_NIVEL", `COTA_NIVEL_${i}`, "ESP_BAL", "HOLGURA_BAL", "ANCHURA",
            "NUMERO_MODULOS", "PROFUNDIDAD", "PERFIL_MONTANTE", "PASO_FIJACIONES", "ALA_BALDA", "MATERIAL_ESTRUCTURAL");
          for (let j = 0; j < N; j++) this._bayFrame(model, d, lid, i, j, z - d.ts, legs, weld, mat_s, fin);
        });
      });
    });
    ctx.feature("F40", this.support_group[1], () => {
      ctx.uses(sp, "ANCHURA", "NUMERO_MODULOS", "PROFUNDIDAD", "PERFIL_MONTANTE");
      feet(model, d, corners, cname, V[sp], foot, this.support_group[0], null);
    });
    const tray = sheetPart("balda", `Bandeja chapa ${g(d.spec.t)} mm`, d.spec, mat_c, fin);
    d.level_ids.forEach((lid, i0) => {
      const i = i0 + 1, z = d.z_levels[i0];
      ctx.feature(`F3${i}`, `Bandejas del nivel ${i}`, () => {
        ctx.uses("ANCHURA", "NUMERO_MODULOS", "PROFUNDIDAD", `COTA_NIVEL_${i}`, "ESP_BAL", "ALA_BALDA", "MATERIAL_CHAPA", "PERFIL_MONTANTE",
          "HOLGURA_ESCOTADURA", "PERFIL_LARGUERO", "ACABADO");
        for (let j = 0; j < N; j++) {
          const ox = xs[j] + BAY_GAP / 2;
          const tid = j === 0 ? `BAL.BANDEJA.${i}` : `BAL.BANDEJA.${i}.M${j + 1}`;
          model.add(tid, `Bandeja nivel ${i}, módulo ${j + 1}`, tray, translation(ox, 0, z), "BAL", { tags: { explode_extra: [0, 0, 0] } });
          fasteners(model, { ...d.fix[lid], offset: [ox, 0.0] }, "BAL", `BAL.N${i}` + (j ? `M${j + 1}` : ""), tid);
        }
      });
    });
    model.structure = this._shelfStructure(model, d, legs);
    const n = d.z_levels.length, q = V.CARGA_POR_NIVEL;
    model.dims = { ANCHURA: M, ANCHURA_TOTAL: d.A_tot, PROFUNDIDAD: Pf, ALTURA: H, LONGITUD_MONTANTE: d.leg_len,
      envelope: { ids: [...Object.values(legs), ...range(n).map((i) => `BAL.BANDEJA.${i + 1}`)], dx: d.A_tot, dy: Pf, zmax: H, names: ["ANCHURA_TOTAL", "PROFUNDIDAD"] },
      levels: range(n).map((i) => [`NIVEL_${i + 1}`, `BAL.BANDEJA.${i + 1}`]),
      drawing_expected: Object.fromEntries(range(n).map((k) => [`DIST_NIVEL_${k + 1}`, k === 0 ? d.z_levels[0] : d.z_levels[k] - d.z_levels[k - 1]])),
      load_text: q ? `Carga distribuida por bandeja de proyecto: ${g(q)} kg (${N} módulos × ${n} niveles, total ${g(N * n * q)} kg)`
        : "Carga por bandeja: NO DEFINIDA" };
    model.numberParts();
    return model;
  }

  /** Bastidor de un módulo en un nivel: largueros entre montantes y travesaños dentro de su sección. */
  _bayFrame(model, d, lid, i, j, z_top, legs, weld, mat, fin) {
    const { rail, trv, a, e, n_int } = d, Pf = d.Ly;
    const xj = d.xs[j], xk = d.xs[j + 1];
    const fxl = d.fix[lid];
    const ox = xj + BAY_GAP / 2;
    const hole = C.component("TUERCA_REMACHABLE_M6").hole_d;
    const lkey = j === 0 ? lid : `${lid}_M${j + 1}`;
    const tag = ` (nivel ${i}, módulo ${j + 1})`;
    const zl = z_top - rail.H / 2;
    const y_f = e + rail.B / 2, y_b = Pf - e - rail.B / 2;
    const x0 = xj + a / 2, x1 = xk - a / 2;
    let hz = fxl.z_ref - fxl.h.y0;
    const lp = profilePart(`larguero_${lid.toLowerCase()}`, `Larguero de nivel ${rail.code}`, rail.code, x1 - x0, mat, fin,
      fxl.s.y0.map((s) => ["-x", s + ox - x0, hz - zl, hole]));
    const long_ids = [];
    for (const [k, nm, p0, p1, l0, l1] of [["D", "delantero", [x0, y_f, zl], [x1, y_f, zl], `D${j}`, `D${j + 1}`],
      ["T", "trasero", [x1, y_b, zl], [x0, y_b, zl], `T${j + 1}`, `T${j}`]]) {
      const iid = `EST.LAR_${lkey}.${k}`;
      model.add(iid, `Larguero de nivel ${nm}${tag}`, lp, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
      weld(`J.${iid}.0`, iid, 0, legs[l0], rail, `Larguero de nivel ${nm} a montante`);
      weld(`J.${iid}.1`, iid, 1, legs[l1], rail, `Larguero de nivel ${nm} a montante`);
      long_ids.push(iid);
    }
    const ze = z_top - trv.H / 2;
    const x_l = xj + BAY_GAP / 2 + e + trv.B / 2, x_r = xk - BAY_GAP / 2 - e - trv.B / 2;
    const y0 = a, y1 = Pf - a;
    hz = fxl.z_ref - fxl.h.x0;
    const ep = profilePart(`travesano_ext_${lid.toLowerCase()}`, `Travesaño extremo de nivel ${trv.code}`, trv.code, y1 - y0, mat, fin,
      fxl.s.x0.map((s) => ["+x", s - y0, hz - ze, hole]));
    const end_ids = [];
    for (const [k, nm, p0, p1, l0, l1] of [["I", "izquierdo", [x_l, y0, ze], [x_l, y1, ze], `D${j}`, `T${j}`],
      ["D", "derecho", [x_r, y1, ze], [x_r, y0, ze], `T${j + 1}`, `D${j + 1}`]]) {
      const iid = `EST.TRV_${lkey}.${k}`;
      model.add(iid, `Travesaño extremo de nivel ${nm}${tag}`, ep, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
      weld(`J.${iid}.0`, iid, 0, legs[l0], trv, `Travesaño extremo de nivel ${nm} a montante`);
      weld(`J.${iid}.1`, iid, 1, legs[l1], trv, `Travesaño extremo de nivel ${nm} a montante`);
      end_ids.push(iid);
    }
    const xs_i = range(n_int).map((q) => x_l + ((q + 1) * (x_r - x_l)) / (n_int + 1));
    const yi0 = e + rail.B, yi1 = Pf - e - rail.B;
    const int_ids = [];
    if (n_int) {
      const ip = profilePart(`travesano_int_${lid.toLowerCase()}`, `Travesaño intermedio de nivel ${trv.code}`, trv.code, yi1 - yi0, mat, fin);
      xs_i.forEach((x, q0) => {
        const q = q0 + 1, iid = `EST.TRI_${lkey}.${pad2(q)}`;
        const p0 = [x, yi0, ze], p1 = [x, yi1, ze];
        model.add(iid, `Travesaño intermedio de nivel ${q}${tag}`, ip, axisFrame(p0, p1, [0, 0, 1]), "EST", { axis: [p0, p1], up: [0, 0, 1], structural: true });
        weld(`J.${iid}.0`, iid, 0, long_ids[0], trv, "Travesaño intermedio de nivel a larguero");
        weld(`J.${iid}.1`, iid, 1, long_ids[1], trv, "Travesaño intermedio de nivel a larguero");
        int_ids.push(iid);
      });
    }
    model.structure.levels = model.structure.levels ?? {};
    model.structure.levels[lkey] = { long: long_ids, end: end_ids, int: int_ids, grid_x: [x_l, ...xs_i, x_r], grid_y: [y_f, y_b], z: z_top };
  }

  _shelfStructure(model, d, legs) {
    const { N, Lt } = d, Pf = d.Ly;
    const [nx, ny] = d.spec.notch;
    const area = Lt * Pf - 4 * nx * ny;
    const surfaces = [];
    d.level_ids.forEach((lid, i0) => {
      const i = i0 + 1;
      for (let j = 0; j < N; j++) {
        const sid = j === 0 ? lid : `${lid}_M${j + 1}`;
        surfaces.push({ id: sid, label: `Bandeja del nivel ${i}, módulo ${j + 1}`, level: sid, load_param: "CARGA_POR_NIVEL",
          sheet_instance: j === 0 ? `BAL.BANDEJA.${i}` : `BAL.BANDEJA.${i}.M${j + 1}`, area_mm2: area });
      }
    });
    const gr = this.support_group[0];
    const order = ["D0", `D${N}`, "T0", `T${N}`, ...range(N - 1).map((k) => `D${k + 1}`), ...range(N - 1).map((k) => `T${k + 1}`)];
    const supports = order.map((k) => ({ instance: `${gr}.PIE.${k}`, leg: legs[k], point: [...model.instance(legs[k]).axis[0]],
      component: model.instance(`${gr}.PIE.${k}`).part.code }));
    return { levels: model.structure.levels ?? {}, surfaces, supports, horizontal_points: [legs.D0, legs[`D${N}`]],
      worktop_height: model.params.values.ALTURA, leg_ids: order.map((k) => legs[k]), product_word: "estantería", member_roles: memberRoles(model),
      assembly_texts: {
        EST: `Recepción de la estructura soldada de ${N} módulos (montantes intermedios comunes). Insertar las tuercas remachables M6 en los `
          + "taladros Ø9,1 de largueros y travesaños de todos los niveles.",
        APO: "Roscar los pies niveladores en las tuercas soldadas. Nivelar y, si está previsto, anclar al suelo antes de cargar la estantería.",
        BAL: "Colocar las bandejas de abajo arriba y de un extremo al otro, con las escotaduras alrededor de los montantes, y fijarlas con "
          + "tornillos ISO 7380 M6x12 (8 N·m)." } };
  }
}

// ============================================================================ mesa de soldadura (port de mesa_soldadura.py)
const HOLE_SYSTEMS = { D16_P50: [16.0, 50.0], D28_P100: [28.0, 100.0], ninguno: null };
const MIN_PLATE_T = { D16_P50: 12.0, D28_P100: 15.0, ninguno: 10.0 };
const PLATE_THICKNESSES = [10.0, 12.0, 15.0, 20.0];
const PLATE_CORNER_R = 5.0, STITCH_L = 50.0, STITCH_PITCH = 250.0;
/** Retícula centrada en la placa, con al menos medio paso de borde. */
export function holeGrid(L, W, system) {
  const sd = HOLE_SYSTEMS[system];
  if (!sd) return [];
  const [dh, p] = sd;
  const nx = Math.floor((L - p) / p) + 1, ny = Math.floor((W - p) / p) + 1;
  if (nx < 1 || ny < 1) return [];
  const x0 = (L - (nx - 1) * p) / 2, y0 = (W - (ny - 1) * p) / 2;
  const out = [];
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) out.push([pyRound(x0 + i * p, 3), pyRound(y0 + j * p, 3), dh]);
  return out;
}
class MesaSoldadura extends MesaIndustrial {
  constructor(id = "mesa_soldadura") {
    super(id);
    Object.assign(this, { top_iid: "ENC.PLACA", top_label: "Placa de soldadura" });
  }
  plateTargets(v) {
    const out = [];
    if (v.CARGA_TOTAL || v.CARGA_PUNTUAL) {
      const sd = HOLE_SYSTEMS[v.SISTEMA_TALADROS];
      const avail = new Set(C.sheetThicknesses(v.MATERIAL_PLACA));
      out.push({ surface: "encimera", t_param: "ESPESOR_PLACA", n_param: "NUMERO_TRAVESANOS", load_param: "CARGA_TOTAL", trv_param: "PERFIL_TRAVESANO",
        min_t_by_use: false, mat_param: "MATERIAL_PLACA",
        t_options: PLATE_THICKNESSES.filter((t) => avail.has(t) && t >= (MIN_PLATE_T[v.SISTEMA_TALADROS] ?? 10.0)),
        t_max: sd ? Math.min(PLATE_THICKNESSES.at(-1), sd[0]) : PLATE_THICKNESSES.at(-1) });
    }
    if (v.CARGA_BALDA && (v.NUMERO_BALDAS ?? 0) >= 1) out.push({ surface: "balda", t_param: "ESPESOR_BALDA", n_param: "NUMERO_TRAVESANOS_BALDA",
      load_param: "CARGA_BALDA", trv_param: "PERFIL_BASTIDOR", min_t_by_use: false });
    return out;
  }
  sheetDefaultsWithoutLoad(v) {
    const out = {};
    if (!(v.CARGA_TOTAL || v.CARGA_PUNTUAL)) out.ESPESOR_PLACA = Math.max(this.constructive_defaults.ESPESOR_PLACA, MIN_PLATE_T[v.SISTEMA_TALADROS] ?? 10.0);
    if (!(v.CARGA_BALDA && (v.NUMERO_BALDAS ?? 0) >= 1)) out.ESPESOR_BALDA = this.constructive_defaults.ESPESOR_BALDA;
    return out;
  }
  _derive(ctx, model) {
    const v = ctx.params.values;
    const d = {};
    ctx.feature("F00", "Parámetros derivados y reglas constructivas", () => {
      const t = ctx.derive("ESP_PLACA", (p) => p.get("ESPESOR_PLACA"), "mm", "Espesor de la placa");
      const c = ctx.derive("RETRANQUEO", (p) => p.get("VUELO"), "mm", "Retranqueo de la estructura respecto al canto de la placa (vuelo)");
      const leg = C.profile(ctx.get("PERFIL_PATA")), rail = C.profile(ctx.get("PERFIL_LARGUERO"));
      const trv = C.profile(ctx.get("PERFIL_TRAVESANO")), bas = C.profile(ctx.get("PERFIL_BASTIDOR"));
      if (leg.B !== leg.H) throw new Error("Las patas deben ser de tubo cuadrado");
      const a = leg.B;
      ctx.setDerived("SECCION_PATA", `${g(leg.B)}x${g(leg.H)}`, "mm", "Sección de pata", ["PERFIL_PATA"]);
      ctx.setDerived("ESPESOR_PERFIL_PATA", leg.t, "mm", "Espesor de pata", ["PERFIL_PATA"]);
      const foot = C.component(ctx.get(this.support_param));
      const hn = +foot.nominal_height, tp = ctx.get("ESPESOR_PLACA_BASE");
      const z_tf = ctx.derive("COTA_BASTIDOR_SUP", (p) => p.get("ALTURA") - p.get("ESP_PLACA"), "mm", "Cota cara superior del bastidor (apoyo de la placa)");
      const sp = this.support_param;
      const z_leg0 = ctx.derive("COTA_INICIO_PATA", (p) => +C.component(p.get(sp)).nominal_height + p.get("ESPESOR_PLACA_BASE"), "mm", "Cota inicio de pata");
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
      ctx.setDerived("VANO_ENCIMERA", pyRound((xe1 - xe0) / (n_top + 1), 2), "mm", "Vano entre apoyos de la placa",
        ["LONGITUD", "NUMERO_TRAVESANOS", "PERFIL_TRAVESANO", "RETRANQUEO"]);
      const shelf = this._hasShelf(ctx);
      Object.assign(d, { Lx: L, Ly: W, leg, rail, trv, bas, a, c, t, hn, tp, z_tf, z_leg0, leg_len, n_top, xe: [xe0, xe1], shelf, peto: 0.0 });
      // ---- placa y retícula de amarre
      const system = v.SISTEMA_TALADROS;
      const holes = holeGrid(L, W, system);
      const sd = HOLE_SYSTEMS[system];
      const eta = sd && holes.length ? (sd[1] - sd[0]) / sd[1] : 1.0;
      ctx.setDerived("N_TALADROS_PLACA", holes.length, "ud", "Taladros de la retícula de amarre", ["SISTEMA_TALADROS", "LONGITUD", "ANCHURA"]);
      ctx.setDerived("EFICIENCIA_LIGAMENTO", pyRound(eta, 4), null, "Eficiencia de ligamento de la placa (p − d)/p", ["SISTEMA_TALADROS"]);
      d.plate = { holes, eta };
      d.top_surface = eta < 1 ? { ligament_efficiency: eta } : {};
      const t_min = MIN_PLATE_T[system];
      if (t < t_min) model.note("advertencia", "DFM-PLACA-DELGADA", `Placa de ${g(t)} mm por debajo del mínimo constructivo de ${g(t_min)} mm para el sistema `
        + `${system}: riesgo de deformación al soldar sobre ella.`);
      if (c < 30) model.note("advertencia", "ERG-VUELO", "Vuelo de la placa inferior a 30 mm: poco espacio para mordazas.");
      // sin fijaciones atornilladas: la placa se suelda al bastidor
      d.fix_top = { s: Object.fromEntries(EDGES.map((e) => [e, []])), h: Object.fromEntries(EDGES.map((e) => [e, 0.0])), z_ref: H, t, inset: 0.0, offset: 0.0,
        Lx: L, Ly: W, c, wall: Object.fromEntries(EDGES.map((e) => [e, (e === "y0" || e === "y1" ? rail : trv).t])), gap: 0.0 };
      d.skirt = rail.H;
      if (shelf) this._deriveShelf(ctx, model, d);
      this._deriveFootrest(ctx, model, d);
    });
    return d;
  }
  _topFrameUses() { return ["ESPESOR_PLACA", "VUELO"]; }
  _buildTop(model, ctx, d, H, mat_c, fin) {
    const V = model.params.values, L = V.LONGITUD, W = V.ANCHURA, t = d.t;
    ctx.feature("F20", "Placa de soldadura perforada", () => {
      ctx.uses("LONGITUD", "ANCHURA", "ALTURA", "ESP_PLACA", "SISTEMA_TALADROS", "MATERIAL_PLACA", "VUELO");
      const holes = d.plate.holes;
      const desc = holes.length ? `, ${holes.length} taladros Ø${g(holes[0][2])}` : "";
      const part = platePart("placa_soldadura", `Placa de soldadura ${g(t)} mm${desc}`, L, W, t, V.MATERIAL_PLACA, null, PLATE_CORNER_R, holes);
      model.add(this.top_iid, "Placa de soldadura", part, translation(0, 0, H - t), "ENC");
      this._stitchWelds(model, d, t, "Placa de soldadura a bastidor");
    });
  }
  /** Cordones discontinuos placa–bastidor en largueros y travesaños extremos. */
  _stitchWelds(model, d, t, desc) {
    const lv = model.structure.levels.SUP;
    for (const mid of [...lv.long, ...lv.end]) {
      const inst = model.instance(mid);
      const [p0, p1] = inst.axis;
      const Lm = Math.hypot(p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]);
      const n = Math.max(2, Math.ceil(Lm / STITCH_PITCH));
      const loc = [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2 + inst.part.profile.H / 2];
      const tmin = Math.min(t, inst.part.profile.t);
      model.joint({ id: `J.PLACA_SOLD.${mid.split(".").slice(1).join(".")}`, kind: "soldadura", members: [this.top_iid, mid], location: loc,
        description: desc, weld: { type: "fillet", a: weldA(tmin), all_around: false, process: "135 (MAG)",
          length: pyRound(n * STITCH_L, 1), note: `${n} cordones de ${g(STITCH_L)} mm cada ${g(STITCH_PITCH)} mm, alternos` } });
    }
  }
  _structure(model, d, legs) {
    const st = super._structure(model, d, legs);
    st.assembly_texts = {
      ENC: `Colocar la placa sobre el bastidor superior con el vuelo indicado y soldarla con cordones discontinuos a${g(weldA(Math.min(d.t, d.rail.t)))} de `
        + `${g(STITCH_L)} mm cada ${g(STITCH_PITCH)} mm, alternos para limitar la deformación. Proteger los taladros de las proyecciones. La placa no se `
        + "pinta: se entrega aceitada." };
    return st;
  }
}

// ============================================================================ tarima / plataforma de trabajo (port de tarima.py)
const DECK_THICKNESSES = [3.0, 4.0, 5.0, 6.0, 8.0, 10.0];
const SERVICE_LOAD_KN_M2 = 2.0, TARIMA_POINT_KG = 153.0, TARIMA_PATCH_MM = 200.0;
class Tarima extends MesaSoldadura {
  constructor() {
    super("tarima");
    Object.assign(this, { top_iid: "ENC.PLACA", top_label: "Superficie de la tarima" });
  }
  plateTargets(v) {
    if (!(v.CARGA_TOTAL || v.CARGA_PUNTUAL)) return [];
    const avail = new Set(C.sheetThicknesses(v.MATERIAL_PLACA));
    return [{ surface: "encimera", t_param: "ESPESOR_PLACA", n_param: "NUMERO_TRAVESANOS", load_param: "CARGA_TOTAL", trv_param: "PERFIL_TRAVESANO",
      min_t_by_use: false, mat_param: "MATERIAL_PLACA", t_options: DECK_THICKNESSES.filter((t) => avail.has(t)), t_max: DECK_THICKNESSES.at(-1) }];
  }
  sheetDefaultsWithoutLoad(v) { return v.CARGA_TOTAL || v.CARGA_PUNTUAL ? {} : { ESPESOR_PLACA: this.constructive_defaults.ESPESOR_PLACA }; }
  legFits() { return true; }
  _derive(ctx, model) {
    const d = {};
    ctx.feature("F00", "Parámetros derivados y reglas constructivas", () => {
      const t = ctx.derive("ESP_PLACA", (p) => p.get("ESPESOR_PLACA"), "mm", "Espesor de la chapa de la superficie");
      const c = ctx.derive("RETRANQUEO", () => 0.0, "mm", "Retranqueo de la estructura (enrasada con la chapa)");
      const leg = C.profile(ctx.get("PERFIL_PATA")), rail = C.profile(ctx.get("PERFIL_LARGUERO")), trv = C.profile(ctx.get("PERFIL_TRAVESANO"));
      if (leg.B !== leg.H) throw new Error("Las patas deben ser de tubo cuadrado");
      const a = leg.B;
      ctx.setDerived("SECCION_PATA", `${g(leg.B)}x${g(leg.H)}`, "mm", "Sección de pata", ["PERFIL_PATA"]);
      ctx.setDerived("ESPESOR_PERFIL_PATA", leg.t, "mm", "Espesor de pata", ["PERFIL_PATA"]);
      const foot = C.component(ctx.get(this.support_param));
      const hn = +foot.nominal_height, tp = ctx.get("ESPESOR_PLACA_BASE");
      const z_tf = ctx.derive("COTA_BASTIDOR_SUP", (p) => p.get("ALTURA") - p.get("ESP_PLACA"), "mm", "Cota cara superior del bastidor (apoyo de la chapa)");
      const sp = this.support_param;
      const z_leg0 = ctx.derive("COTA_INICIO_PATA", (p) => +C.component(p.get(sp)).nominal_height + p.get("ESPESOR_PLACA_BASE"), "mm", "Cota inicio de pata");
      const leg_len = ctx.derive("LONGITUD_PATA", (p) => p.get("COTA_BASTIDOR_SUP") - p.get("COTA_INICIO_PATA"), "mm", "Longitud de corte de pata");
      const L = ctx.get("LONGITUD"), W = ctx.get("ANCHURA"), H = ctx.get("ALTURA");
      ctx.derive("LONGITUD_LARGUERO", (p) => p.get("LONGITUD") - 2 * C.profile(p.get("PERFIL_PATA")).B, "mm", "Longitud de largueros");
      ctx.derive("LONGITUD_TRAVESANO_EXT", (p) => p.get("ANCHURA") - 2 * C.profile(p.get("PERFIL_PATA")).B, "mm", "Longitud de travesaños extremos");
      ctx.derive("LONGITUD_TRAVESANO_INT", (p) => p.get("ANCHURA") - 2 * C.profile(p.get("PERFIL_LARGUERO")).B, "mm", "Longitud de travesaños intermedios");
      if (rail.B > a || trv.B > a) model.note("error", "DFM-ANCHO-BASTIDOR", "El ancho de largueros/travesaños supera el de la pata: "
        + "no pueden enrasarse con la cara exterior.");
      const frameH = Math.max(rail.H, trv.H);
      if (z_tf - frameH < z_leg0 + 10) {
        const hMin = Math.ceil((z_leg0 + 10 + frameH + t) / 5) * 5;
        model.note("error", "GEO-TARIMA-BAJA", `Con el pie ${foot.name} y el bastidor de ${g(frameH)} mm de canto no cabe la tarima de ${g(H)} mm: `
          + `altura mínima ${g(hMin)} mm, o pies y perfiles más bajos.`);
      }
      const xe0 = c + trv.B / 2, xe1 = L - c - trv.B / 2;
      let n_top = ctx.get("NUMERO_TRAVESANOS");
      if (n_top === AUTO) n_top = Math.max(0, Math.ceil((xe1 - xe0) / ctx.get("SEPARACION_MAX_APOYOS")) - 1);
      ctx.setDerived("N_TRAVESANOS_INT", n_top, "ud", "Travesaños intermedios", ["NUMERO_TRAVESANOS", "SEPARACION_MAX_APOYOS", "LONGITUD"]);
      ctx.setDerived("VANO_ENCIMERA", pyRound((xe1 - xe0) / (n_top + 1), 2), "mm", "Vano entre apoyos de la chapa", ["LONGITUD", "NUMERO_TRAVESANOS", "PERFIL_TRAVESANO"]);
      const q = ctx.params.values.CARGA_TOTAL;
      if (q != null) {
        const qkn = (q * 9.81e-3) / (L * W * 1e-6);
        ctx.setDerived("CARGA_SUPERFICIAL", pyRound(qkn, 3), "kN/m²", "Carga repartida por unidad de superficie", ["CARGA_TOTAL", "LONGITUD", "ANCHURA"]);
        if (qkn < SERVICE_LOAD_KN_M2 - 1e-9) model.note("advertencia", "NORMA-14122-CARGA", `Carga repartida de ${qkn.toFixed(2)} kN/m², inferior a la `
          + `de servicio de ${g(SERVICE_LOAD_KN_M2)} kN/m² de EN ISO 14122-2 para plataformas de trabajo: use al menos `
          + `${g(Math.ceil((SERVICE_LOAD_KN_M2 * L * W * 1e-6) / 9.81e-3))} kg.`);
      }
      const P = ctx.params.values.CARGA_PUNTUAL;
      if (P != null && P < TARIMA_POINT_KG - 1e-9) model.note("advertencia", "NORMA-14122-PUNTUAL", `Carga concentrada de ${g(P)} kg, inferior a la de `
        + `1,5 kN (${g(TARIMA_POINT_KG)} kg) de EN ISO 14122-2.`);
      model.note("advertencia", "ERG-ANTIDESLIZANTE", "Superficie de chapa lisa: EN ISO 14122-2 exige una superficie de tránsito antideslizante; prever "
        + "chapa lagrimada o recubrimiento antideslizante (no modelado).");
      if (H > 250) model.note("advertencia", "ERG-ACCESO", `Altura de ${g(H)} mm: valorar un peldaño de acceso (no incluido).`);
      Object.assign(d, { Lx: L, Ly: W, leg, rail, trv, bas: null, a, c, t, hn, tp, z_tf, z_leg0, leg_len, n_top, xe: [xe0, xe1], shelf: false, peto: 0.0,
        footrest: null });
      d.plate = { holes: [], eta: 1.0 };
      d.top_surface = { patch_mm: TARIMA_PATCH_MM };
      d.fix_top = { s: Object.fromEntries(EDGES.map((e) => [e, []])), h: Object.fromEntries(EDGES.map((e) => [e, 0.0])), z_ref: H, t, inset: 0.0, offset: 0.0,
        Lx: L, Ly: W, c, wall: Object.fromEntries(EDGES.map((e) => [e, (e === "y0" || e === "y1" ? rail : trv).t])), gap: 0.0 };
      d.skirt = rail.H;
    });
    return d;
  }
  _topFrameUses() { return ["ESPESOR_PLACA"]; }
  _buildTop(model, ctx, d, H, mat_c, fin) {
    const V = model.params.values, L = V.LONGITUD, W = V.ANCHURA, t = d.t;
    ctx.feature("F20", "Chapa de la superficie de tránsito", () => {
      ctx.uses("LONGITUD", "ANCHURA", "ALTURA", "ESP_PLACA", "MATERIAL_PLACA", "ACABADO");
      const part = platePart("chapa_tarima", `Chapa de la tarima ${g(t)} mm`, L, W, t, V.MATERIAL_PLACA, fin, PLATE_CORNER_R, []);
      model.add(this.top_iid, "Superficie de la tarima", part, translation(0, 0, H - t), "ENC");
      this._stitchWelds(model, d, t, "Chapa de la tarima a bastidor");
    });
  }
  _structure(model, d, legs) {
    const st = super._structure(model, d, legs);
    st.product_word = "tarima";
    st.assembly_texts = {
      ENC: `Colocar la chapa sobre el bastidor, enrasada con él, y soldarla con cordones discontinuos a${g(weldA(Math.min(d.t, d.rail.t)))} de `
        + `${g(STITCH_L)} mm cada ${g(STITCH_PITCH)} mm, alternos para limitar la deformación. Aplicar el recubrimiento antideslizante antes del montaje.` };
    return st;
  }
}

export const REGISTRY = { mesa_industrial: new MesaIndustrial(), estanteria: new Estanteria(), puesto_trabajo: new PuestoTrabajo("puesto_trabajo"),
  carro_taller: new CarroTaller("carro_taller"), carro_estanteria: new CarroEstanteria(), mesa_soldadura: new MesaSoldadura(), estanteria_bateria: new EstanteriaBateria(),
  tarima: new Tarima(), carro_plataforma: new CarroPlataforma(), armario: new Armario() };
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
