// @ts-nocheck
// Intérprete de solicitudes en español y asistente (port de monxu/ai/interpreter.py y assistant.py).
// Determinista y trazable; opcionalmente una función externa (Claude) completa los datos que las reglas no encuentran.
import * as C from "./catalog";
import { coerce } from "./model";
import { REGISTRY } from "./families";
import { g, pyRound } from "./util";

const NUM_WORDS = { un: 1, una: 1, uno: 1, dos: 2, tres: 3, cuatro: 4, cinco: 5, seis: 6, siete: 7, ocho: 8, nueve: 9, diez: 10, once: 11, doce: 12 };
const NUM = String.raw`(\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)`;
const UNIT = String.raw`(?:(mm|milimetros?|cm|centimetros?|m|metros?)\b)`;
const FAMILY_KEYWORDS = [
  ["mesa_industrial", /\bmesas?\b|banco de (trabajo|montaje)|\bbancos?\b/],
  ["estanteria", /estanteri/],
  ["puesto_trabajo", /puesto de trabajo|estacion de trabajo|puesto ergonomico|puesto de (montaje|inspeccion)/],
  ["armario", /\barmario|\bcarro\b|carros industriales/],
];
const UNSUPPORTED = [
  ["cajones", "cajon|cajonera", "Cajones / cajonera"],
  ["panel_trasero", "panel (trasero|perforado)|panel de herramientas|panel posterior", "Panel trasero perforado"],
  ["ruedas", String.raw`\bruedas?\b|movil\b`, "Ruedas (mesa móvil)"],
  ["puertas", String.raw`\bpuertas?\b|armario inferior`, "Puertas / armario inferior"],
  ["iluminacion", String.raw`iluminacion|\bluz\b|luminaria`, "Iluminación"],
  ["tomas", "tomas? electric|enchufes|regleta", "Tomas eléctricas"],
  ["monitor", "monitor|pantalla", "Soporte para monitor"],
  ["regulable", "regulable en altura|altura regulable", "Regulación de altura"],
];
export const LABELS = { mesa_industrial: "Mesa industrial", estanteria: "Estantería industrial", puesto_trabajo: "Puesto de trabajo industrial",
  armario: "Armario / mobiliario auxiliar" };
export const STRUCTURAL_KEYS = ["PROFUNDIDAD", "NUMERO_NIVELES", "CARGA_POR_NIVEL", "ALTURA_PRIMER_NIVEL", "DISTANCIA_BALDAS", "PERFIL_MONTANTE",
  "LONGITUD", "ANCHURA", "ALTURA", "CARGA_TOTAL", "CARGA_BALDA", "CARGA_PUNTUAL", "CARGA_HORIZONTAL", "MATERIAL_ESTRUCTURAL", "MATERIAL_CHAPA",
  "ACABADO", "ESPESOR_CHAPA", "NUMERO_BALDAS", "ALTURA_BALDA", "USO", "FRECUENCIA", "ENTORNO", "ANCLAJE", "TIPO_SUELO", "TIPO_APOYO", "PERFIL_PATA"];

export const norm = (s) => s.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/×/g, "x").replace(/\*/g, "x");
export function toNumber(tok) {
  tok = tok.trim();
  if (tok in NUM_WORDS) return NUM_WORDS[tok];
  let t = tok.replace(/\s/g, "");
  if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(t)) t = t.replace(/\./g, "").replace(",", ".");
  else t = t.replace(",", ".");
  return parseFloat(t);
}
export function toMm(v, unit, def = "mm") {
  const u = unit || def;
  if (u.startsWith("m") && !u.startsWith("mm") && !u.startsWith("mil")) return v * 1000;
  if (u.startsWith("c")) return v * 10;
  return v;
}
const R = (s, f = "") => new RegExp(s, f);

class Interp {
  constructor(family = null, values = {}, accessories = []) {
    this.family = family; this.family_label = ""; this.values = { ...values }; this.evidence = {}; this.unsupported = []; this.accessories = [...accessories]; this.notes = [];
  }
  set(k, v, ev) { this.values[k] = v; this.evidence[k] = String(ev).trim(); }
  pop(k) { const v = this.values[k]; delete this.values[k]; return v; }
}

export function parse(text, pending = null) {
  let t = norm(text);
  const it = new Interp();
  for (const [fid, rx] of FAMILY_KEYWORDS) if (rx.test(t)) { it.family = fid; break; }
  for (const [w, n] of Object.entries(NUM_WORDS)) t = t.replace(R(String.raw`\b${w}\b(?=\s+(niveles|baldas|estantes|cajones|travesanos))`, "g"), String(n));
  let m = t.match(R(String.raw`${NUM}\s*${UNIT}?\s*x\s*${NUM}\s*${UNIT}?\s*x\s*${NUM}\s*${UNIT}?`));
  if (m) {
    const unit = m[6] || m[4] || m[2];
    const [a, b, c] = [1, 3, 5].map((i) => toMm(toNumber(m[i]), m[i + 1] || unit));
    it.set("LONGITUD", a, m[0]); it.set("ANCHURA", b, m[0]); it.set("ALTURA", c, m[0]);
  }
  const dimWords = { LONGITUD: String.raw`largo|longitud|long\.`, ANCHURA: "ancho|anchura|profundidad|fondo", ALTURA: "altura|alto" };
  for (const [param, words] of Object.entries(dimWords)) {
    if (param in it.values) continue;
    for (const rx of [String.raw`${NUM}\s*${UNIT}?\s*(?:de\s+)?(?:${words})`, String.raw`(?:${words})\s*(?:de|:|=)?\s*${NUM}\s*${UNIT}?`]) {
      const mm = t.match(R(rx));
      if (mm) { it.set(param, toMm(toNumber(mm[1]), mm[2]), mm[0]); break; }
    }
  }
  if (it.family === "estanteria" && "ANCHURA" in it.values) {
    const pm = t.match(R(String.raw`${NUM}\s*${UNIT}?\s*(?:de\s+)?(?:profundidad|fondo)`));
    if (pm) it.set("PROFUNDIDAD", toMm(toNumber(pm[1]), pm[2]), pm[0]);
    const am = t.match(R(String.raw`${NUM}\s*${UNIT}?\s*(?:de\s+)?(?:ancho|anchura)`));
    if (am) it.set("ANCHURA", toMm(toNumber(am[1]), am[2]), am[0]);
  }
  m = t.match(/(\d+)\s+(?:niveles|baldas|estantes)/);
  if (m) it.set("NUMERO_NIVELES", parseInt(m[1], 10), m[0]);
  for (const mm of t.matchAll(R(String.raw`${NUM}\s*(kg|kilos?|kilogramos?)\b`, "g"))) {
    const val = toNumber(mm[1]);
    const s = mm.index, e = mm.index + mm[0].length;
    const ctx = t.slice(Math.max(0, s - 60), e + 60), after = t.slice(e, e + 40), before = t.slice(Math.max(0, s - 40), s);
    if (/por nivel|cada nivel|por balda|cada balda|por estante/.test(ctx)) it.set("CARGA_POR_NIVEL", val, mm[0] + " por nivel");
    else if (/puntual|concentrada/.test(ctx)) it.set("CARGA_PUNTUAL", val, ctx);
    else if (/balda|estante inferior/.test(after) || /balda/.test(before)) it.set("CARGA_BALDA", val, ctx);
    else if (pending && ["CARGA_BALDA", "CARGA_PUNTUAL", "CARGA_TOTAL"].includes(pending[0]) && !/distribuid|encimera/.test(ctx)) it.set(pending[0], val, mm[0]);
    else {
      it.set("CARGA_TOTAL", val, ctx);
      if (/total de la mesa|en total|entre encimera y balda/.test(ctx)) it.notes.push("La carga indicada es total de la mesa: se asigna a la encimera "
        + "(hipótesis conservadora) hasta que se indique el reparto con la balda.");
    }
  }
  if (/balda (sin carga|vacia)|sin carga en la balda/.test(t)) it.set("CARGA_BALDA", 0.0, "balda sin carga");
  m = t.match(R(String.raw`${NUM}\s*(n|newton)\b`));
  if (m && /horizontal|empuje/.test(t)) it.set("CARGA_HORIZONTAL", toNumber(m[1]), m[0]);
  else if (/(sin|no hay|despreciables?) (empujes|esfuerzos horizontales)|empujes? (ligeros?|despreciables?)|empujes? horizontales? ligeros?/.test(t)) {
    it.set("CARGA_HORIZONTAL", 100.0, "empujes horizontales ligeros");
    it.notes.push("Empuje horizontal ligero: se adopta 100 N como hipótesis de uso ligero.");
  } else if (/tornillo de banco|golpe|martill/.test(t)) {
    it.set("CARGA_HORIZONTAL", 600.0, "trabajo con esfuerzos horizontales");
    it.notes.push("Trabajo con esfuerzos horizontales: se adopta 600 N como hipótesis.");
  }
  if (/inox|inoxidable|aisi\s*3(04|16)|1\.4301|1\.4404/.test(t)) {
    const code = /316|1\.4404/.test(t) ? "1.4404" : "1.4301";
    it.set("MATERIAL_ESTRUCTURAL", code, "acero inoxidable"); it.set("MATERIAL_CHAPA", code, "acero inoxidable"); it.set("ACABADO", "INOX_SATINADO", "acero inoxidable");
  } else if (/alumini/.test(t)) {
    it.set("MATERIAL_ESTRUCTURAL", "EN AW-6082 T6", "aluminio"); it.set("MATERIAL_CHAPA", "EN AW-5754 H22", "aluminio"); it.set("ACABADO", "ANODIZADO_NATURAL", "aluminio");
  } else if (/\bacero\b|chapa de acero|chapa negra|s235|s355/.test(t)) {
    it.set("MATERIAL_CHAPA", "S235JR", "acero"); it.set("MATERIAL_ESTRUCTURAL", t.includes("s355") ? "S355J2H" : "S235JRH", "acero");
  }
  if (/encimera de (madera|contrachapado|tablero|hpl|fenolic)/.test(t)) it.unsupported.push("Encimera de madera/tablero técnico (sólo chapa metálica en esta versión)");
  m = t.match(R(String.raw`chapa (?:de\s+)?${NUM}\s*mm|${NUM}\s*mm de (?:espesor|chapa)`));
  if (m) it.set("ESPESOR_CHAPA", toNumber(m[1] || m[2]), m[0]);
  for (const r of t.matchAll(/ral\s*(\d{4})/g)) {
    const code = `RAL${r[1]}_POLVO`;
    if (code in C.finishes()) it.set("ACABADO", code, `RAL ${r[1]}`);
    else it.notes.push(`Color RAL ${r[1]} no está en el catálogo de acabados: se mantiene el acabado propuesto.`);
  }
  if (/galvaniz/.test(t)) it.set("ACABADO", "GALVANIZADO", "galvanizado");
  if (/sin balda|sin estante/.test(t)) it.set("NUMERO_BALDAS", 0, "sin balda");
  else if (/balda inferior|con balda|estante inferior|bandeja inferior|una balda|1 balda/.test(t)) it.set("NUMERO_BALDAS", 1, "balda inferior");
  m = t.match(R(String.raw`balda (?:a|situada a)\s*${NUM}\s*${UNIT}?`));
  if (m) it.set("ALTURA_BALDA", toMm(toNumber(m[1]), m[2]), m[0]);
  m = t.match(/tubo (?:cuadrado )?(?:de\s+)?(\d{2,3})\s*x\s*(\d{2,3})(?:\s*x\s*(\d(?:[.,]\d)?))?/);
  if (m) {
    const a = m[1], b = m[2], tt = parseFloat((m[3] || "2").replace(",", "."));
    const code = a === b ? `SHS ${a}x${b}x${g(tt)}` : `RHS ${Math.max(+a, +b)}x${Math.min(+a, +b)}x${g(tt)}`;
    const exists = C.profiles().some((p) => p.code === code);
    if (exists && a === b) it.set("PERFIL_PATA", code, m[0]);
    else if (!exists) it.notes.push(`Perfil ${code} no disponible en el catálogo: se propondrá el más próximo.`);
  }
  if (/tubular|tubo/.test(t)) it.accessories.push("estructura tubular");
  for (const [rx, val] of [["trabajo pesado|uso intensivo pesado|heavy", "trabajo_pesado"], ["montaje ligero", "montaje_ligero"], ["inspeccion|control de calidad", "inspeccion"],
    ["laboratorio", "laboratorio"], ["embalaje|preparacion de pedidos|expedicion", "embalaje"], ["montaje|ensamblaje", "montaje"]])
    if (R(rx).test(t)) { it.set("USO", val, rx.split("|")[0]); break; }
  for (const [rx, val] of [["intensiv|tres turnos|24 ?h", "intensiva"], ["diari|a diario|cada dia", "diaria"], ["ocasional|esporadic", "ocasional"]])
    if (R(rx).test(t)) { it.set("FRECUENCIA", val, rx); break; }
  for (const [rx, val] of [["exterior|intemperie", "exterior"], ["humed", "interior_humedo"], ["alimentari|alimentos", "alimentario"], ["sala limpia", "sala_limpia"],
    ["interior|nave|taller", "interior_seco"]])
    if (R(rx).test(t)) { it.set("ENTORNO", val, rx); break; }
  if (/anclad|anclaje al suelo|atornillada al suelo|fijada al suelo/.test(t) && !/sin anclaj|no anclad/.test(t)) it.set("ANCLAJE", "al_suelo", "anclaje al suelo");
  else if (/sin anclaj|no anclad|apoyada|libre/.test(t)) it.set("ANCLAJE", "ninguno", "sin anclaje");
  if (/suelo irregular|desnivel/.test(t)) it.set("TIPO_SUELO", "irregular", "suelo irregular");
  else if (/suelo (nivelado|plano|liso)/.test(t)) it.set("TIPO_SUELO", "nivelado", "suelo nivelado");
  if (/pies? nivelador/.test(t)) it.set("TIPO_APOYO", "pie_nivelador", "pies niveladores");
  for (const [key, rx, label] of UNSUPPORTED) {
    if (R(rx).test(t) && !R(`sin (${rx})`).test(t)) {
      const mm = t.match(R(String.raw`(\d+)\s+(?:${rx})`));
      it.unsupported.push(label + (mm ? ` (${mm[1]} uds)` : ""));
      it.accessories.push(key);
    }
  }
  if (it.family === "estanteria") {
    if ("LONGITUD" in it.values) {
      const L = it.pop("LONGITUD"), ev = it.evidence.LONGITUD; delete it.evidence.LONGITUD;
      if (!("PROFUNDIDAD" in it.values) && "ANCHURA" in it.values && it.evidence.ANCHURA === ev) it.set("PROFUNDIDAD", it.values.ANCHURA, ev);
      it.set("ANCHURA", L, ev);
    }
    if ("CARGA_TOTAL" in it.values && !("CARGA_POR_NIVEL" in it.values) && it.values.NUMERO_NIVELES) {
      const n = it.values.NUMERO_NIVELES, ev = it.evidence.CARGA_TOTAL; delete it.evidence.CARGA_TOTAL;
      it.set("CARGA_POR_NIVEL", pyRound(it.pop("CARGA_TOTAL") / n, 1), ev);
      it.notes.push(`Carga total repartida por igual entre los ${n} niveles (hipótesis).`);
    }
    delete it.values.NUMERO_BALDAS;
    it.notes = it.notes.filter((n) => !n.includes("total de la mesa"));
  }
  return it;
}

const Q = (param, question, why, options = [], blocking = "verificacion", proposal = null) => ({ param, question, why, options, blocking, proposal });
export function missingData(family, values, asked = new Set()) {
  const q = [];
  if (family === "estanteria") return missingShelf(values, asked);
  if (family !== "mesa_industrial") return q;
  for (const [p, lbl, prop] of [["LONGITUD", "longitud", 1800.0], ["ANCHURA", "anchura (fondo)", 800.0], ["ALTURA", "altura de trabajo", 900.0]])
    if (!(p in values)) q.push(Q(p, `¿Qué ${lbl} necesita (mm)?`, "Dimensión principal necesaria para generar la geometría.", [], "generacion", prop));
  if (values.CARGA_TOTAL == null) q.push(Q("CARGA_TOTAL", "¿Qué carga debe soportar la encimera (kg) y está distribuida o concentrada?",
    "Sin carga no puede verificarse la estructura: el resultado quedaría PENDIENTE.", [{ label: "150 kg", value: 150 }, { label: "300 kg", value: 300 }, { label: "500 kg", value: 500 }]));
  if ((values.NUMERO_BALDAS ?? 1) >= 1 && values.CARGA_BALDA == null && !asked.has("CARGA_BALDA")) q.push(Q("CARGA_BALDA",
    "¿Qué carga soportará la balda inferior (kg)? ¿La carga indicada para la encimera incluye la de la balda?", "La balda se dimensiona y verifica de forma independiente.",
    [{ label: "Sin carga", value: 0 }, { label: "100 kg", value: 100 }, { label: "200 kg", value: 200 }]));
  if (!("MATERIAL_ESTRUCTURAL" in values) && !asked.has("MATERIAL_ESTRUCTURAL")) q.push(Q("MATERIAL_ESTRUCTURAL", "¿Material y acabado? Propuesta: acero S235 con pintura en polvo RAL 7035.",
    "Determina propiedades mecánicas, espesores comerciales y acabado.", [{ label: "Acero S235 pintado RAL 7035", value: "S235JRH" }, { label: "Acero inoxidable AISI 304", value: "1.4301" },
      { label: "Aluminio", value: "EN AW-6082 T6" }], "confirmacion", "S235JRH"));
  if (!("USO" in values) && !asked.has("USO")) q.push(Q("USO", "¿Qué uso tendrá (montaje, trabajo pesado, inspección, embalaje...)?", "Fija el espesor mínimo de encimera y la clase de ejecución.",
    [{ label: "Montaje", value: "montaje" }, { label: "Trabajo pesado", value: "trabajo_pesado" }, { label: "Inspección / ligero", value: "inspeccion" }], "confirmacion", "montaje"));
  if (!("CARGA_HORIZONTAL" in values) && !asked.has("CARGA_HORIZONTAL")) q.push(Q("CARGA_HORIZONTAL", "¿Habrá esfuerzos horizontales relevantes (empujes, tornillo de banco, golpes)? "
    + "¿Se anclará al suelo?", "Condiciona la verificación de vuelco y del desplome.", [{ label: "Empuje ligero (100 N)", value: 100 }, { label: "Uso general (300 N)", value: 300 },
      { label: "Tornillo de banco (600 N)", value: 600 }], "verificacion", 300.0));
  if (!("ENTORNO" in values) && !asked.has("ENTORNO")) q.push(Q("ENTORNO", "¿Entorno de uso (interior seco, húmedo, exterior, alimentario)?", "Afecta al material y al acabado (corrosión).",
    [{ label: "Interior seco", value: "interior_seco" }, { label: "Interior húmedo", value: "interior_humedo" }, { label: "Alimentario", value: "alimentario" }], "confirmacion", "interior_seco"));
  return q;
}
function missingShelf(values, asked) {
  const q = [];
  for (const [p, lbl, prop] of [["ANCHURA", "anchura de frente", 1500.0], ["PROFUNDIDAD", "profundidad", 600.0], ["ALTURA", "altura total", 2000.0]])
    if (!(p in values)) q.push(Q(p, `¿Qué ${lbl} necesita (mm)?`, "Dimensión principal necesaria para generar la geometría.", [], "generacion", prop));
  if (!("NUMERO_NIVELES" in values)) q.push(Q("NUMERO_NIVELES", "¿Cuántos niveles de bandejas?", "Define el número de bastidores y bandejas.",
    [{ label: "4 niveles", value: 4 }, { label: "5 niveles", value: 5 }], "generacion", 5));
  if (values.CARGA_POR_NIVEL == null) q.push(Q("CARGA_POR_NIVEL", "¿Qué carga soportará cada nivel (kg) y estará repartida (cajas) o concentrada (piezas pesadas)?",
    "Sin carga no puede verificarse la estructura: el resultado quedaría PENDIENTE.", [{ label: "80 kg", value: 80 }, { label: "150 kg", value: 150 }, { label: "250 kg", value: 250 }]));
  if (!("ANCLAJE" in values) && !asked.has("ANCLAJE")) q.push(Q("ANCLAJE", "¿Se anclará la estantería al suelo o a la pared?",
    "Una estantería alta y estrecha sin anclaje puede volcar con un empuje moderado.", [{ label: "Anclada al suelo", value: "al_suelo" }, { label: "Sin anclaje", value: "ninguno" }],
    "verificacion", "al_suelo"));
  if (!("MATERIAL_ESTRUCTURAL" in values) && !asked.has("MATERIAL_ESTRUCTURAL")) q.push(Q("MATERIAL_ESTRUCTURAL", "¿Material y acabado? Propuesta: acero S235 con pintura en polvo RAL 7035.",
    "Determina propiedades mecánicas, espesores comerciales y acabado.", [{ label: "Acero S235 pintado RAL 7035", value: "S235JRH" }, { label: "Acero inoxidable AISI 304", value: "1.4301" }],
    "confirmacion", "S235JRH"));
  if (!("ENTORNO" in values) && !asked.has("ENTORNO")) q.push(Q("ENTORNO", "¿Entorno de uso (almacén interior seco, húmedo, cámara, exterior)?", "Afecta al material y al acabado (corrosión).",
    [{ label: "Interior seco", value: "interior_seco" }, { label: "Interior húmedo", value: "interior_humedo" }], "confirmacion", "interior_seco"));
  return q;
}

export function proposalFor(family, values) {
  if (family === "estanteria") {
    const p = {};
    for (const [k, v] of [["ANCHURA", 1500.0], ["PROFUNDIDAD", 600.0], ["ALTURA", 2000.0], ["NUMERO_NIVELES", 5]]) if (!(k in values)) p[k] = v;
    for (const k of ["PERFIL_MONTANTE", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ESPESOR_BALDA"]) if (!(k in values)) p[k] = "auto";
    return p;
  }
  if (family !== "mesa_industrial") return {};
  const p = {};
  for (const [k, v] of [["LONGITUD", 1800.0], ["ANCHURA", 800.0], ["ALTURA", 900.0]]) if (!(k in values)) p[k] = v;
  if (!("NUMERO_BALDAS" in p)) p.NUMERO_BALDAS = values.NUMERO_BALDAS ?? 1;
  const haveLoad = values.CARGA_TOTAL != null;
  for (const k of ["PERFIL_PATA", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "PERFIL_BASTIDOR", "ESPESOR_CHAPA"]) if (!(k in values)) p[k] = haveLoad ? "auto" : null;
  if (values.CARGA_BALDA && !("ESPESOR_BALDA" in p)) p.ESPESOR_BALDA = "auto";
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null));
}

const thousands = (x) => pyRound(x, 0).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
export function describe(it) {
  const v = it.values;
  const out = [`Familia: ${LABELS[it.family] ?? "no identificada"}.`];
  const lab = { LONGITUD: "Longitud", ANCHURA: it.family === "estanteria" ? "Anchura (frente)" : "Anchura/fondo", PROFUNDIDAD: "Profundidad", ALTURA: "Altura" };
  for (const [k, l] of Object.entries(lab)) if (k in v) out.push(`${l}: ${thousands(v[k])} mm.`);
  if ("NUMERO_NIVELES" in v) out.push(`Niveles: ${v.NUMERO_NIVELES}.`);
  if ("CARGA_POR_NIVEL" in v && v.CARGA_POR_NIVEL != null) {
    out.push(`Carga por nivel: ${g(v.CARGA_POR_NIVEL)} kg.`);
    if ("NUMERO_NIVELES" in v) out.push(`Carga total nominal solicitada: ${g(v.CARGA_POR_NIVEL * v.NUMERO_NIVELES)} kg.`);
  }
  if ("CARGA_TOTAL" in v && v.CARGA_TOTAL != null) out.push(`Carga distribuida sobre encimera: ${g(v.CARGA_TOTAL)} kg.`);
  if ("CARGA_BALDA" in v && v.CARGA_BALDA != null) out.push(`Carga sobre balda: ${g(v.CARGA_BALDA)} kg.`);
  if ("CARGA_PUNTUAL" in v && v.CARGA_PUNTUAL != null) out.push(`Carga puntual: ${g(v.CARGA_PUNTUAL)} kg.`);
  out.push("Material: " + ("MATERIAL_ESTRUCTURAL" in v ? v.MATERIAL_ESTRUCTURAL : "pendiente de selección") + ".");
  if (it.family === "estanteria") out.push("Anclaje: " + ({ al_suelo: "al suelo", ninguno: "sin anclaje" }[v.ANCLAJE] ?? "pendiente") + ".");
  if (it.family === "mesa_industrial") {
    out.push("Balda inferior: " + (v.NUMERO_BALDAS === 1 ? "sí" : v.NUMERO_BALDAS === 0 ? "no" : "no indicada") + ".");
    out.push("Tipo de estructura: tubular soldada" + (it.accessories.includes("estructura tubular") ? " (indicada)." : " (propuesta)."));
  }
  return out;
}

export const newState = (family = null) => ({ family, values: {}, evidence: {}, asked: [], unsupported: [], notes: [], history: [], engine: "reglas" });

/** Instrucción para la extracción con Claude (capacidad 'sample' del artefacto): sólo datos, nunca geometría. */
export function llmPrompt(message, state) {
  const fam = state.family && REGISTRY[state.family];
  const specs = fam ? fam.specs().filter((s) => STRUCTURAL_KEYS.includes(s.name)) : [];
  return "Eres el intérprete técnico de una plataforma de diseño paramétrico de mobiliario industrial. Extrae de la solicitud "
    + "del usuario SOLO los datos que estén indicados explícitamente o se deduzcan sin ambigüedad. No inventes valores. "
    + "Unidades: mm, kg, N. Devuelve exclusivamente un objeto JSON {\"PARAMETRO\": valor} con parámetros de esta lista "
    + "(nombre, tipo, unidad, opciones):\n"
    + specs.map((s) => `${s.name} (${s.type}${s.unit ? ", " + s.unit : ""}${s.choices ? ", opciones: " + s.choices.join(" | ") : ""}${s.min != null ? `, ${s.min}–${s.max}` : ""}): ${s.label}`).join("\n")
    + `\n\nDatos ya conocidos: ${JSON.stringify(state.values ?? {})}\nSolicitud: «${message}»\nResponde sólo con el JSON.`;
}

/** Procesa un mensaje y/o respuestas. `llmValues` = parámetros extraídos por Claude (opcional). */
export function handle(state, message = "", answers = null, llmValues = null) {
  const st = JSON.parse(JSON.stringify(state ?? newState()));
  st.values = st.values ?? {};
  const pending = (st.last_questions ?? []).map((q) => q.param);
  const it = message ? parse(message, pending) : new Interp();
  let engine = "reglas";
  if (llmValues && typeof llmValues === "object") {
    let used = false;
    for (const [k, v] of Object.entries(llmValues)) if (!(k in it.values) && STRUCTURAL_KEYS.includes(k) && v !== null && v !== undefined) { it.set(k, v, "interpretación de Claude"); used = true; }
    if (used) engine = "claude+reglas";
  }
  if (it.family && !st.family) st.family = it.family;
  const values = { ...st.values, ...it.values };
  for (const [k, v] of Object.entries(answers ?? {})) { values[k] = v; it.evidence[k] = "respuesta del usuario"; }
  st.values = values;
  st.evidence = { ...(st.evidence ?? {}), ...it.evidence };
  st.unsupported = [...new Set([...(st.unsupported ?? []), ...it.unsupported])].sort();
  st.notes = [...new Set([...(st.notes ?? []), ...it.notes])];
  const asked = new Set(st.asked ?? []);
  const fam = st.family;
  const questions = fam ? missingData(fam, values, asked) : [];
  for (const q of questions) if (q.blocking === "confirmacion") asked.add(q.param);
  st.asked = [...asked].sort();
  st.last_questions = questions;
  st.engine = engine;
  const implemented = !!REGISTRY[fam];
  const proposal = implemented ? proposalFor(fam, values) : {};
  const reply = [];
  if (!fam) reply.push("No identifico la familia de producto. ¿Se trata de una mesa, una estantería, un puesto de trabajo o un armario?");
  else {
    reply.push("Interpretación de la solicitud:");
    reply.push(...describe(new Interp(fam, values, it.accessories)).map((s) => "• " + s));
    if (!implemented) reply.push(`La familia «${LABELS[fam] ?? fam}» está prevista en la arquitectura, pero su generador paramétrico todavía no está implementado: `
      + "no puedo generar un diseño técnico fiable para ella.");
  }
  if (st.unsupported.length) reply.push("Elementos solicitados que esta versión todavía no genera (no se incluirán en el diseño): " + st.unsupported.join("; ") + ".");
  for (const n of st.notes) reply.push("Nota: " + n);
  const genBlock = questions.filter((q) => q.blocking === "generacion");
  if (questions.length) { reply.push("Necesito confirmar estos datos:"); questions.forEach((q, i) => reply.push(`${i + 1}. ${q.question} (${q.why})`)); }
  if (implemented) {
    if (Object.keys(proposal).length) reply.push("Propuesta constructiva preliminar (pendiente de verificación por cálculo): "
      + Object.entries(proposal).map(([k, v]) => `${k} = ${v}`).join(", ") + ". 'auto' significa que el motor de cálculo dimensionará la sección.");
    reply.push(genBlock.length ? "Faltan dimensiones para generar la geometría." : "Puede generar ya un diseño preliminar; los datos pendientes quedarán marcados como tales.");
  }
  let params = { ...proposal, ...Object.fromEntries(Object.entries(values).filter(([k]) => STRUCTURAL_KEYS.includes(k))) };
  if (implemented) {
    const specs = Object.fromEntries(REGISTRY[fam].specs().map((s) => [s.name, s]));
    const clean = {};
    for (const [k, val] of Object.entries(params)) if (specs[k]) {
      try { coerce(specs[k], val); clean[k] = val; } catch { st.notes = [...new Set([...st.notes, `Valor «${val}» no admisible para ${k}: se ignora.`])]; }
    }
    params = clean;
  }
  const sources = Object.fromEntries(Object.keys(params).map((k) => [k, k in values ? "usuario" : "ia_propuesta"]));
  st.history = [...(st.history ?? []), { user: message, answers: answers ?? {} }];
  return { state: st, reply: reply.join("\n"), interpretation: { family: it.family, values: it.values, evidence: it.evidence, unsupported: it.unsupported, notes: it.notes },
    questions, proposal, parameters: params, sources, ready_to_generate: implemented && !genBlock.length, family: fam, family_implemented: implemented, engine };
}
