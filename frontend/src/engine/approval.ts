// @ts-nocheck
// Estados de aprobación de una revisión (port exacto de monxu/validation/approval.py): nueve estados encadenados,
// validaciones registradas por código de QA y firmas de fabricabilidad, cálculo, aprobación y liberación.
export const STATES = ["diseno_generado", "geometria_validada", "bom_validado", "fabricabilidad_revisada", "calculo_validado", "documentacion_generada",
  "revision_tecnica_pendiente", "aprobado_tecnicamente", "liberado_fabricacion"];
export const LABELS = { diseno_generado: "Diseño generado", geometria_validada: "Geometría validada", bom_validado: "BOM validado",
  fabricabilidad_revisada: "Fabricabilidad revisada", calculo_validado: "Cálculo estructural validado", documentacion_generada: "Documentación generada",
  revision_tecnica_pendiente: "Revisión técnica pendiente", aprobado_tecnicamente: "Aprobado técnicamente", liberado_fabricacion: "Liberado para fabricación" };
export const SIGNOFFS = { fabricabilidad: "fabricabilidad_revisada", calculo: "calculo_validado", aprobacion: "aprobado_tecnicamente", liberacion: "liberado_fabricacion" };
const GEO = ["GEO-", "UNI-", "CHAPA-"], BOM = ["BOM-", "XDOC-", "COMP-"], DFM = ["LAS-", "PLG-", "PRF-", "MON-", "DFM-", "SOL-", "GAL-", "ERG-"], CALC = ["CALC"];
const sw = (code, ps) => ps.some((p) => code.startsWith(p));
const blocking = (items, ps) => items.filter((i) => i.level === "bloqueante" && sw(i.code, ps)).map((i) => i.code);
const open = (items, ps, val) => items.filter((i) => i.level === "pendiente" && sw(i.code, ps) && !(i.code in val)).map((i) => i.code);

export function evaluate(designQa, structural, dossier, record) {
  record = record ?? {};
  const val = record.validations ?? {}, sig = record.signoffs ?? {};
  const items = designQa?.items ?? [];
  const dItems = dossier?.qa?.items?.length ? dossier.qa.items : items;
  const gates = [];
  const gate = (state, ok, reasons, signer = null) => gates.push({ id: state, label: LABELS[state], ok: !!ok, reasons: reasons.filter(Boolean), signoff: signer ?? null });
  gate("diseno_generado", true, []);
  // una revisión anterior a la auditoría no tiene los controles cruzados ni las validaciones pendientes en su QA
  const legacy = !(designQa && "release_blockers" in designQa);
  let b = blocking(items, GEO);
  gate("geometria_validada", !b.length && !legacy, [b.length ? `errores de geometría: ${b.join(", ")}` : "",
    legacy ? "revisión anterior a la auditoría (QA sin controles cruzados): emita una revisión nueva" : ""]);
  b = blocking(items, BOM); let o = open(items, BOM, val);
  gate("bom_validado", !b.length && !o.length, [b.length ? `errores: ${b.join(", ")}` : "", o.length ? `validaciones sin registrar: ${o.join(", ")}` : ""]);
  b = blocking(items, DFM); o = open(items, DFM, val); let s = sig.fabricabilidad;
  gate("fabricabilidad_revisada", !b.length && !o.length && s, [b.length ? `errores de fabricación: ${b.join(", ")}` : "", o.length ? `validaciones sin registrar: ${o.join(", ")}` : "",
    !s ? "falta la firma de revisión de fabricabilidad" : ""], s);
  o = open(items, CALC, val); s = sig.calculo;
  gate("calculo_validado", structural === "CUMPLE" && !o.length && s, [structural !== "CUMPLE" ? `cálculo ${structural}` : "",
    o.length ? `validaciones sin registrar: ${o.join(", ")}` : "", !s ? "falta la firma del técnico que valida el cálculo" : ""], s);
  const dq = dossier?.qa ?? {};
  gate("documentacion_generada", !!dossier && !dq.blocking, [!dossier ? "expediente no generado" : "", dossier && dq.blocking ? `${dq.blocking} errores bloqueantes en el expediente` : ""]);
  gate("revision_tecnica_pendiente", true, []);
  const blockers = dItems.filter((i) => i.release_block && !(i.level === "pendiente" && i.code in val)).map((i) => i.code);
  for (const i of items) if (i.release_block && !(i.level === "pendiente" && i.code in val) && !blockers.includes(i.code)) blockers.push(i.code);
  s = sig.aprobacion;
  gate("aprobado_tecnicamente", s && !blockers.length, [!s ? "falta la firma de aprobación técnica" : "", blockers.length ? `bloqueos de liberación abiertos: ${blockers.join(", ")}` : ""], s);
  s = sig.liberacion;
  const after = ["aprobado_tecnicamente", "liberado_fabricacion"].includes(dossier?.state);
  gate("liberado_fabricacion", s && after && !blockers.length, [!s ? "falta la firma de liberación para fabricación" : "",
    !after ? "el expediente debe regenerarse después de la aprobación" : ""], s);
  let state = "diseno_generado";
  for (const g of gates) { if (!g.ok) break; state = g.id; }
  const openAll = [...new Set([...items, ...dItems].filter((i) => i.level === "pendiente" && !(i.code in val)).map((i) => i.code))].sort();
  return { state, label: LABELS[state], index: STATES.indexOf(state), gates, open_validations: openAll, release_blockers: blockers, stamp: stamp(state, structural, sig) };
}

/** Sello de los documentos según el estado de aprobación (nunca «verificado» sin firmas). */
export function stamp(state, structural, sig) {
  const who = (k) => { const s = sig?.[k] ?? {}; return `${s.by ?? ""} (${s.date ?? ""})`.trim(); };
  if (structural === "NO_CUMPLE") return { text: "NO APTO PARA FABRICACIÓN — verificación estructural no superada", level: "error" };
  if (state === "liberado_fabricacion") return { text: `LIBERADO PARA FABRICACIÓN — ${who("liberacion")}`, level: "info" };
  if (state === "aprobado_tecnicamente") return { text: `APROBADO TÉCNICAMENTE — ${who("aprobacion")} · NO LIBERADO PARA FABRICACIÓN`, level: "info" };
  if (structural === "PENDIENTE") return { text: "PRELIMINAR — verificación estructural pendiente de datos · NO APTO PARA FABRICACIÓN", level: "warn" };
  return { text: `${LABELS[state].toUpperCase()} — SIN APROBACIÓN TÉCNICA · NO APTO PARA FABRICACIÓN`, level: "warn" };
}

/** Una firma solo puede registrarse si los estados anteriores al suyo se cumplen. */
export function canSign(ev, stage) {
  const k = STATES.indexOf(SIGNOFFS[stage]);
  for (const g of ev.gates.slice(0, k)) if (!g.ok) return [false, `${g.label}: ${g.reasons.join("; ") || "no cumplido"}`];
  const own = ev.gates[k], other = own.reasons.filter((r) => !r.startsWith("falta la firma"));
  return other.length ? [false, `${own.label}: ${other.join("; ")}`] : [true, ""];
}
