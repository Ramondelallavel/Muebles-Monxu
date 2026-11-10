// @ts-nocheck
// API local: misma interfaz que la API del servidor, ejecutada íntegramente en el navegador.
// Persistencia: base de datos privada del artefacto (capacidad 'db', por usuario) o memoria si no está disponible.
import { REGISTRY, family, library, allTemplates } from "../engine/families";
import { regenerate } from "../engine/pipeline";
import { viewerPayload } from "../engine/geometry";
import { ParamError } from "../engine/model";
import * as A from "../engine/assistant";
import { buildDossier } from "./dossier";
import * as AP from "../engine/approval";
import { affectedDocuments } from "../engine/dependencies";

export const STATUSES = ["en_configuracion", "en_diseno", "pendiente_validacion", "validado", "preparado_fabricacion", "fabricado", "archivado"];
export const STATUS_LABELS = { en_configuracion: "En configuración", en_diseno: "En diseño", pendiente_validacion: "Pendiente de validación", validado: "Aprobado técnicamente",
  preparado_fabricacion: "Liberado para fabricación", fabricado: "Fabricado", archivado: "Archivado" };
/** Versión del formato de proyecto: las migraciones se aplican al leer y se guardan (= storage/db.py, SCHEMA_VERSION). */
const SCHEMA_VERSION = 2;
const now = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 19);

// ---------------------------------------------------------------------------- almacenamiento
const cap = (name) => (typeof window !== "undefined" && window.claude?.use ? window.claude.use(name).catch(() => null) : Promise.resolve(null));
let storeP = null;
function getStore() {
  if (storeP) return storeP;
  storeP = (async () => {
    const mem = new Map();
    const [db, user] = await Promise.all([cap("db"), cap("user")]);
    let uid = null;
    try { uid = user ? await user.id() : null; } catch { uid = null; }
    const memSeq = {};
    let memInv = [];
    if (!db || !uid) return { kind: "memoria", list: async () => [...mem.values()], put: async (p) => { mem.set(p.code, p); }, del: async (code) => { mem.delete(code); },
      seq: async (year) => memSeq[year] ?? 0, setSeq: async (year, n) => { memSeq[year] = Math.max(memSeq[year] ?? 0, n); },
      inv: async () => memInv.map((x) => ({ ...x })), setInv: async (items) => { memInv = items.map((x) => ({ ...x })); }, label: "Memoria del navegador (se pierde al cerrar)" };
    const col = db.collection("data/users/" + uid);
    const cache = new Map();
    let loaded = false, seq = {}, invItems = [];
    const load = async () => {
      if (loaded) return;
      const t = new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 10000));
      const snap = await Promise.race([col.get(), t]);
      snap.docs.forEach((d) => { const v = d.data(); if (d.id === SEQ_DOC) seq = v?.por_anio ?? {}; else if (d.id === INV_DOC) invItems = v?.items ?? []; else if (v?.code) cache.set(v.code, v); });
      loaded = true;
    };
    return { kind: "db", label: "Base de datos privada del artefacto (sólo usted)", list: async () => { try { await load(); } catch { /* sin conexión: caché */ } return [...cache.values()]; },
      put: async (p) => { cache.set(p.code, p); await col.doc(p.code).set(JSON.parse(JSON.stringify(p))); },
      del: async (code) => { await col.doc(code).delete(); cache.delete(code); },
      // claves «a2026»: nombres de campo no numéricos
      seq: async (year) => { try { await load(); } catch { /* caché */ } return Number(seq[`a${year}`]) || 0; },
      setSeq: async (year, n) => { seq = { ...seq, [`a${year}`]: Math.max(Number(seq[`a${year}`]) || 0, n) }; await col.doc(SEQ_DOC).set({ por_anio: seq }); },
      inv: async () => { try { await load(); } catch { /* caché */ } return invItems.map((x) => ({ ...x })); },
      setInv: async (items) => { invItems = items.map((x) => ({ ...x })); await col.doc(INV_DOC).set({ items: JSON.parse(JSON.stringify(invItems)) }); } };
  })();
  return storeP;
}
export const storageLabel = async () => (await getStore()).label;
const SEQ_DOC = "contador";
const INV_DOC = "inventario_retales";   // inventario de retales reutilizables (barras y chapas)            // último número de proyecto emitido: los códigos no se reutilizan al borrar
const CODE_RX = /^P-(\d{4})-(\d{4,})$/;
/** Siguiente código del año: mayor que cualquiera emitido (existente o borrado). */
async function nextCode() {
  const st = await getStore(), year = new Date().getFullYear();
  const used = (await all()).map((p) => CODE_RX.exec(p.code)).filter((m) => m && +m[1] === year).map((m) => +m[2]);
  const n = Math.max(await st.seq(year), ...used) + 1;
  await st.setSeq(year, n);
  return `P-${year}-${String(n).padStart(4, "0")}`;
}

/** v2: la validación anterior a la auditoría no cubre las comprobaciones nuevas: se conserva como antecedente en la última
 *  revisión y el proyecto vuelve a «pendiente de validación» (salvo lo ya fabricado). */
function migrate(p) {
  if ((p.schema ?? 1) >= SCHEMA_VERSION) return false;
  if (["validado", "preparado_fabricacion", "fabricado"].includes(p.status) && (p.revisions ?? []).length) {
    const last = p.revisions.at(-1);
    last.approval = { ...(last.approval ?? {}), legacy: { status: p.status, validated_by: p.validated_by ?? null, migrated: now(),
      note: "Validación anterior a la auditoría de 2026-11: no incluye las nuevas comprobaciones; debe repetirse con el flujo de aprobación." } };
    const old = p.status;
    if (p.status !== "fabricado") p.status = "pendiente_validacion";
    log(p, "migracion", { schema: SCHEMA_VERSION, from: old, to: p.status, validated_by: p.validated_by ?? null }, "sistema");
  }
  p.schema = SCHEMA_VERSION;
  return true;
}
async function all() {
  const st = await getStore();
  const list = await st.list();
  for (const p of list) if (migrate(p)) { try { await st.put(JSON.parse(JSON.stringify(p))); } catch { /* se guarda en la próxima escritura */ } }
  return list.sort((a, b) => (a.code < b.code ? 1 : -1));
}
/** QA compacto que se guarda con la revisión: las comprobaciones no satisfactorias (código, nivel, bloqueo de liberación). */
const compactQa = (q) => ({ result: q.result, summary: q.summary, blocking: q.blocking, release_blockers: q.release_blockers ?? [],
  items: q.items.filter((i) => i.level !== "ok").map((i) => ({ code: i.code, level: i.level, severity: i.severity, release_block: !!i.release_block, message: i.message.slice(0, 400) })) });
/** Estado de aprobación de una revisión (= Store._evaluate del servidor). */
const availableStock = async () => (await (await getStore()).inv()).filter((x) => x.status === "disponible");
/** Retales que usa el plan y retales reutilizables que produce (= release_movements del servidor). */
function releaseMovements(plan) {
  const used = [...plan.cutting.flatMap((c) => c.stock_used ?? []), ...plan.nesting.filter((n) => n.feasible).flatMap((n) => n.stock_used ?? [])];
  const produced = [...plan.purchases.remnants.filter((x) => x.kind === "barra" && x.reusable).map((x) => ({ kind: "barra", profile: x.profile, material: x.material, length: x.length })),
    ...plan.purchases.remnants.filter((x) => x.kind === "chapa").map((x) => ({ kind: "chapa", material: x.material, thickness: x.thickness, length: x.length, width: x.width }))];
  return { used, produced };
}
const evaluateRev = (r) => AP.evaluate(r.qa, r.structural, r.dossier ? { qa: r.dossier.qa, state: r.dossier.state ?? null } : null, r.approval ?? {});
const approvalOf = (p, rev = null) => {
  const r = rev ? p.revisions.find((x) => x.rev === rev) : p.revisions.at(-1);
  if (!r) return { state: null, label: "Sin revisión", gates: [], open_validations: [], release_blockers: [], records: {} };
  return { ...evaluateRev(r), revision: r.rev, records: r.approval ?? {} };
};
async function get(code) { const p = (await all()).find((x) => x.code === code); if (!p) throw new Error(`Proyecto no encontrado: ${code}`); return JSON.parse(JSON.stringify(p)); }
async function put(p) {
  p.updated = now();
  p.changes = (p.changes ?? []).slice(-200);
  if (p.assistant_state?.history) p.assistant_state.history = p.assistant_state.history.slice(-30);
  if (p.assistant_state?.chat) p.assistant_state.chat = p.assistant_state.chat.slice(-CHAT_MAX);
  // cada documento de la base de datos admite 256 KiB: se recorta lo más antiguo (historial y conversación) si hace falta
  while (JSON.stringify(p).length > 230000 && (p.changes.length > 20 || (p.assistant_state?.chat?.length ?? 0) > 6)) {
    if (p.changes.length > 20) p.changes = p.changes.slice(Math.ceil(p.changes.length / 4));
    else p.assistant_state.chat = p.assistant_state.chat.slice(Math.ceil(p.assistant_state.chat.length / 3));
  }
  try { await (await getStore()).put(p); }
  catch (e) { throw new Error(`No se ha podido guardar el proyecto (${e?.code ?? e?.message ?? "error de almacenamiento"}). Vuelva a intentarlo.`); }
}
const log = (p, kind, detail, author = "") => (p.changes ??= []).push({ timestamp: now(), kind, author, detail });
const CHAT_MAX = 40;          // mensajes de la conversación que se guardan con el proyecto

/** Aplica parámetros al proyecto (validados con las reglas de la familia; lanza ParamError) y devuelve los cambios. */
function applyParams(p, values, sources = null, replace = false, author = "") {
  const checked = family(p.family).newParams({ ...(replace ? {} : p.working_params), ...values });     // valida (lanza ParamError)
  // se guardan los valores ya convertidos (números, no los textos del formulario): historial y revisiones limpios
  values = Object.fromEntries(Object.keys(values).map((k) => [k, k in checked.values ? checked.values[k] : values[k]]));
  const old = { ...p.working_params };
  const nw = replace ? { ...values } : { ...old, ...values };
  const changes = {};
  for (const k of new Set([...Object.keys(old), ...Object.keys(nw)])) if (JSON.stringify(old[k]) !== JSON.stringify(nw[k])) changes[k] = [old[k] ?? null, nw[k] ?? null];
  p.working_params = nw;
  p.working_sources = { ...p.working_sources, ...(sources ?? Object.fromEntries(Object.keys(values).map((k) => [k, "usuario"]))) };
  if (p.status === "en_configuracion") p.status = "en_diseno";
  if (Object.keys(changes).length) log(p, "parametros", { changes }, author);
  return changes;
}
/** Mensaje del asistente tal como se guarda: texto y botones de opción. */
const chatEntry = (r) => ({ who: "ia", text: r.reply,
  questions: (r.questions ?? []).filter((q) => q.options?.length).map((q) => ({ param: q.param, label: q.label ?? q.param, options: q.options })) });
const projectDict = (p) => ({ ...p, status_label: STATUS_LABELS[p.status], approval: (p.revisions ?? []).length ? approvalOf(p) : null,
  revisions: (p.revisions ?? []).map((r) => ({ rev: r.rev, created: r.created, comment: r.comment, author: r.author, product_code: r.product_code, mass_kg: r.mass_kg,
    structural: r.structural, qa: r.qa, dossier: !!r.dossier, changes: r.changes, affected_documents: r.approval?.affected_documents ?? [] })) });

const jobs = new Map();
const designCache = new Map();
async function designFor(fam, values, sources, onProgress, stock = null) {
  const key = JSON.stringify([fam, values, sources, (stock ?? []).map((x) => x.id).sort()]);
  if (designCache.has(key)) return designCache.get(key);
  try {
    const r = regenerate(fam, values, sources, onProgress, stock);
    if (designCache.size > 6) designCache.delete(designCache.keys().next().value);
    designCache.set(key, r);
    return r;
  } catch (e) {
    if (e instanceof ParamError || /Parámetro|superan|valor/.test(e.message)) throw new Error(e.message);
    throw new Error(`La regeneración ha fallado: ${e.message}`);
  }
}

// ---------------------------------------------------------------------------- API
export const localApi = {
  mode: "local",
  library: async () => ({ families: library(), templates: allTemplates().map((t) => ({ ...t, builtin: true })) }),
  family: async (id) => family(id).describe(),
  projects: async () => (await all()).map(projectDict),
  project: async (code) => { const p = await get(code); return { ...projectDict(p), assistant_state: p.assistant_state ?? {}, changes: p.changes ?? [] }; },
  createProject: async (b) => {
    family(b.family);
    let values = { ...(b.values ?? {}) }, sources = {};
    if (b.template_id) {
      const t = allTemplates().find((x) => x.id === b.template_id);
      if (!t) throw new Error(`Plantilla no encontrada: ${b.template_id}`);
      values = { ...t.values, ...values };
      sources = Object.fromEntries(Object.keys(t.values).map((k) => [k, "plantilla"]));
    }
    for (const k of Object.keys(b.values ?? {})) sources[k] = "usuario";
    const p = { code: await nextCode(), name: b.name || "Nuevo proyecto", client: b.client ?? "", description: b.description ?? "", family: b.family,
      designer: b.designer ?? "", status: "en_configuracion", created: now(), updated: now(), validated_by: null, working_params: values, working_sources: sources,
      assistant_state: {}, revisions: [], changes: [] };
    log(p, "creacion", { values }, b.designer ?? "");
    await put(p);
    return projectDict(p);
  },
  /** Borra el proyecto con sus revisiones e historial (irreversible). Los expedientes ya descargados no se tocan. */
  deleteProject: async (code) => {
    const p = await get(code);
    try { await (await getStore()).del(code); }
    catch (e) { throw new Error(`No se ha podido borrar el proyecto (${e?.code ?? e?.message ?? "error de almacenamiento"}). Vuelva a intentarlo.`); }
    return { code: p.code, name: p.name, status: p.status, revisions: (p.revisions ?? []).map((r) => r.rev),
      dossiers: (p.revisions ?? []).filter((r) => r.dossier).length, files_removed: false };
  },
  setParams: async (code, values, sources = null, replace = false, author = "") => {
    const p = await get(code);
    const changes = applyParams(p, values, sources, replace, author);
    await put(p);
    return { changes, project: projectDict(p) };
  },
  design: async (code, onProgress) => {
    const p = await get(code);
    const { model, summary } = await designFor(p.family, p.working_params, p.working_sources, onProgress, await availableStock());
    return { design: summary, viewer: viewerPayload(model) };
  },
  /** Interpreta el mensaje, adopta lo no indicado y, con `apply`, aplica al proyecto lo que cambia en este turno. La conversación se
   * guarda con el proyecto (assistant_state.chat): no se pierde al cambiar de apartado ni al salir del proyecto. */
  assistant: async (code, message, answers, apply = false, llmValues = null) => {
    const p = await get(code);
    const st = p.assistant_state && Object.keys(p.assistant_state).length ? p.assistant_state : A.newState(p.family);
    st.family ??= p.family;
    const chat = [...(st.chat ?? [])];
    let r = A.handle(st, message, answers, llmValues, { values: p.working_params, sources: p.working_sources });
    let switched = null;
    const want = r.interpretation?.family;
    if (want && want !== p.family) {
      if (!(p.revisions ?? []).length && REGISTRY[want]) {
        // proyecto todavía sin revisiones: se cambia de familia y se interpreta de nuevo con la nueva
        switched = { from: p.family, to: want };
        log(p, "familia", switched, "asistente");
        const [keep, keepSrc] = A.carryParams(p.family, want, p.working_params ?? {}, p.working_sources ?? {}, family(want).specs());
        Object.assign(p, { family: want, working_params: keep, working_sources: keepSrc });
        r = A.handle(A.newState(want), message, answers, llmValues, { values: keep, sources: keepSrc });
        r.reply = `He cambiado el proyecto a «${A.LABELS[want] ?? want}» (todavía no tenía revisiones).\n` + r.reply;
      } else {
        r.reply += `\nAtención: la solicitud corresponde a «${A.LABELS[want] ?? want}», pero el proyecto ya tiene revisiones de la familia «${A.LABELS[p.family] ?? p.family}». `
          + "Cree un proyecto nuevo para esa familia.";
        r.ready_to_generate = false;
      }
    }
    let applied = null;
    if (apply && r.ready_to_generate) {
      try {
        applied = applyParams(p, r.to_apply, Object.fromEntries(Object.keys(r.to_apply).map((k) => [k, r.sources[k]])), false, "asistente");
        r.reply += "\n✔ Datos aplicados al proyecto: se genera y verifica el diseño.";
      } catch (e) { r.reply += `\nNo se han podido aplicar los datos: ${e.message}`; }
    }
    if (message || (answers && Object.keys(answers).length)) {
      const labels = Object.fromEntries(family(p.family).specs().map((sp) => [sp.name, sp.label]));
      chat.push({ who: "usuario", text: message || Object.entries(answers).map(([k, v]) => `${labels[k] ?? k}: ${v}`).join(" · ") });
    }
    chat.push(chatEntry(r));
    r.state.chat = chat.slice(-CHAT_MAX);
    p.assistant_state = r.state;
    log(p, "asistente", { message, answers: answers ?? {}, parameters: r.to_apply, engine: r.engine });
    await put(p);
    const { state, ...rest } = r;
    return { ...rest, applied, switched, chat: state.chat };
  },
  assistantPrompt: async (code, message) => { const p = await get(code); const st = p.assistant_state?.family ? p.assistant_state : A.newState(p.family); return A.llmPrompt(message, st); },
  revision: async (code, comment, author) => {
    const p = await get(code);
    const stock = await availableStock();
    const { model, summary } = await designFor(p.family, p.working_params, p.working_sources, null, stock);
    if (summary.qa.blocking) throw new Error("El diseño tiene errores bloqueantes: no puede emitirse revisión.");
    const prev = p.revisions.at(-1);
    const letter = prev ? String.fromCharCode(prev.rev.charCodeAt(0) + 1) : "A";
    const resolved = { ...model.params.values };
    const diff = prev ? Object.fromEntries(Object.entries(resolved).filter(([k, v]) => JSON.stringify(prev.params[k]) !== JSON.stringify(v)).map(([k, v]) => [k, [prev.params[k] ?? null, v]])) : {};
    p.revisions.push({ rev: letter, created: now(), comment, author, params: resolved, sources: { ...model.params.sources }, product_code: model.product_code,
      mass_kg: summary.bom.totals.total_mass, structural: summary.engineering.status,
      qa: compactQa(summary.qa), dossier: null, changes: diff, approval: { affected_documents: prev ? affectedDocuments(summary.dependencies, Object.keys(diff)) : [], stock } });
    log(p, "revision", { rev: letter, comment, changes: diff }, author);
    await put(p);
    return { rev: letter, project: projectDict(p) };
  },
  /** Genera el expediente de una revisión congelada y lo entrega como ZIP (capacidad 'downloads' o descarga del navegador). */
  dossier: async (code, rev, onProgress) => {
    const p = await get(code);
    const r = p.revisions.find((x) => x.rev === rev);
    if (!r) throw new Error(`Revisión ${rev} no encontrada`);
    const id = `job-${Date.now()}`;
    const t0 = performance.now();
    onProgress?.("regenerando la revisión congelada");
    await new Promise((res) => setTimeout(res, 0));
    const { model, summary } = regenerate(p.family, r.params, r.sources, null, r.approval?.stock ?? []);
    const ev = approvalOf(p, rev);
    const out = await buildDossier({ ...p, approval_eval: ev }, r, model, summary, onProgress);
    if (out.qa.blocking) throw new Error("La verificación de los archivos exportados ha fallado: no se publica el expediente. " + out.qa.items.filter((i) => i.level === "bloqueante").map((i) => i.message).join(" "));
    const saved = await deliver(out.name + ".zip", out.zip);
    // se guarda la primera vez y, como nueva edición, cuando la revisión se ha aprobado o liberado después de generarlo
    const advanced = r.dossier && AP.STATES.indexOf(ev.state) > AP.STATES.indexOf(r.dossier.state ?? "diseno_generado")
      && ["aprobado_tecnicamente", "liberado_fabricacion"].includes(ev.state);
    if (!r.dossier || advanced) {
      if (r.dossier) (r.approval ??= {}).editions = [...(r.approval.editions ?? []), { name: r.dossier.name, created: r.dossier.created, state: r.dossier.state ?? null }];
      r.dossier = { name: out.name, created: now(), files: out.files, qa: compactQa(out.qa), state: ev.state };
      r.qa = r.dossier.qa;
      log(p, "expediente", { rev, name: out.name, files: out.files.length, state: ev.state, edition: !!advanced });
      if (["en_configuracion", "en_diseno"].includes(p.status)) p.status = "pendiente_validacion";
      await put(p);
    }
    const job = { id, status: "ok", stage: "fin", result: { name: out.name, seconds: Math.round((performance.now() - t0) / 100) / 10, qa: out.qa, files: out.files, saved } };
    jobs.set(id, job);
    return job;
  },
  job: async (id) => jobs.get(id),
  files: async (code, rev) => { const p = await get(code); return { files: p.revisions.find((x) => x.rev === rev)?.dossier?.files ?? [] }; },
  status: async (code, status, user, validated_by) => {
    if (!STATUSES.includes(status)) throw new Error(`Estado no válido: ${status}`);
    const p = await get(code);
    const last = p.revisions.at(-1);
    if (["validado", "preparado_fabricacion", "fabricado"].includes(status)) {
      if (!last || !last.dossier) throw new Error("Se requiere una revisión con expediente generado.");
      const ev = evaluateRev(last), need = status === "validado" ? "aprobado_tecnicamente" : "liberado_fabricacion";
      if (AP.STATES.indexOf(ev.state) < AP.STATES.indexOf(need)) {
        const gt = ev.gates.find((x) => !x.ok);
        throw new Error(`La revisión ${last.rev} está en «${ev.label}»: se requiere «${AP.LABELS[need]}»` + (gt ? ` (${gt.label}: ${gt.reasons.join("; ")})` : "") + ".");
      }
    }
    if (status === "validado" && validated_by) p.validated_by = validated_by;
    const old = p.status;
    p.status = status;
    log(p, "estado", { from: old, to: status, validated_by: validated_by ?? null }, user);
    await put(p);
    return projectDict(p);
  },
  statuses: async () => STATUSES.map((s) => ({ id: s, label: STATUS_LABELS[s] })),
  approval: async (code, rev = null) => approvalOf(await get(code), rev),
  remnants: async (status = "disponible") => (await (await getStore()).inv()).filter((x) => !status || x.status === status),
  addRemnant: async (b) => {
    const { kind, material, length, profile = null, thickness = null, width = null } = b;
    if (!["barra", "chapa"].includes(kind) || !(length > 0) || (kind === "chapa" && !(width && thickness)) || (kind === "barra" && !profile))
      throw new Error("Retal no válido: barra con perfil y longitud, o chapa con espesor, largo y ancho.");
    const st = await getStore(), items = await st.inv();
    const n = items.reduce((m, it) => Math.max(m, +String(it.id).slice(2) || 0), 0) + 1;
    const it = { id: `R-${String(n).padStart(5, "0")}`, kind, profile, material, thickness: thickness == null ? null : +thickness, length: +length, width: width == null ? null : +width,
      origin: "manual", status: "disponible", created: now(), consumed_by: null };
    await st.setInv([...items, it]);
    return it;
  },
  /** Registra la validación de una comprobación PENDIENTE de la revisión con el documento que la justifica. */
  validate: async (code, item, by, reference, comment = "", rev = null) => {
    if (!by?.trim() || !reference?.trim()) throw new Error("La validación requiere el técnico y la referencia del documento que la justifica.");
    const p = await get(code);
    const r = rev ? p.revisions.find((x) => x.rev === rev) : p.revisions.at(-1);
    if (!r) throw new Error("El proyecto no tiene revisiones.");
    const pend = new Set([...(r.qa?.items ?? []), ...(r.dossier?.qa?.items ?? [])].filter((i) => i.level === "pendiente").map((i) => i.code));
    if (!pend.has(item)) throw new Error(`${item} no es una validación pendiente de la revisión ${r.rev}.`);
    r.approval ??= {};
    (r.approval.validations ??= {})[item] = { by: by.trim(), reference: reference.trim(), comment, date: now().slice(0, 10) };
    log(p, "validacion", { rev: r.rev, code: item, reference }, by);
    await put(p);
    return approvalOf(p, r.rev);
  },
  /** Firma de una etapa (fabricabilidad, cálculo, aprobación, liberación) si se cumplen las anteriores. */
  signoff: async (code, stage, by, comment = "", rev = null) => {
    if (!(stage in AP.SIGNOFFS)) throw new Error(`Etapa de firma no válida: ${stage}`);
    if (!by?.trim()) throw new Error("La firma requiere el nombre del técnico.");
    const p = await get(code);
    const r = rev ? p.revisions.find((x) => x.rev === rev) : p.revisions.at(-1);
    if (!r) throw new Error("El proyecto no tiene revisiones.");
    const [ok, why] = AP.canSign(evaluateRev(r), stage);
    if (!ok) throw new Error(`No puede firmarse «${AP.LABELS[AP.SIGNOFFS[stage]]}»: ${why}`);
    let inv = null;
    if (stage === "liberacion") {         // retales que consume y produce el plan de la revisión (instantánea de stock)
      const { summary } = regenerate(p.family, r.params, r.sources, null, r.approval?.stock ?? []);
      inv = releaseMovements(summary.manufacturing);
      const avail = new Set((await availableStock()).map((x) => x.id));
      const missing = inv.used.filter((i) => !avail.has(i));
      if (missing.length) throw new Error(`Retales del plan ya no disponibles: ${missing.join(", ")}. Emita una revisión nueva.`);
    }
    r.approval ??= {};
    (r.approval.signoffs ??= {})[stage] = { by: by.trim(), comment, date: now().slice(0, 10) };
    const ev = evaluateRev(r), old = p.status;
    if (stage === "aprobacion" && ["aprobado_tecnicamente", "liberado_fabricacion"].includes(ev.state)) { p.status = "validado"; p.validated_by = by.trim(); }
    if (stage === "liberacion" && ev.state === "liberado_fabricacion") p.status = "preparado_fabricacion";
    log(p, "firma", { rev: r.rev, stage, from: old, to: p.status, state: ev.state }, by);
    let inventory = null;
    if (inv && ev.state === "liberado_fabricacion") {
      const st = await getStore(), items = await st.inv();
      for (const it of items) if (inv.used.includes(it.id)) { it.status = "consumido"; it.consumed_by = `${p.code} Rev.${r.rev}`; }
      let n = items.reduce((m, it) => Math.max(m, +String(it.id).slice(2) || 0), 0);
      const added = inv.produced.map((x) => ({ id: `R-${String(++n).padStart(5, "0")}`, ...x, origin: `${p.code} Rev.${r.rev}`, status: "disponible", created: now(), consumed_by: null }));
      await st.setInv([...items, ...added]);
      inventory = { consumed: inv.used, added };
      log(p, "inventario", { rev: r.rev, consumidos: inv.used, nuevos: added.map((x) => x.id) }, by);
    }
    await put(p);
    return { ...approvalOf(p, r.rev), inventory };
  },
  fileUrl: () => null,
};

async function deliver(filename, bytes) {
  const dl = await cap("downloads");
  if (dl) {
    try { await dl.save({ filename, data: bytes }); return "downloads"; }
    catch (e) { if (e?.code === "declined" || e?.code === "cancelled") return "rechazada"; }
  }
  try {
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
    const a = document.createElement("a");
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    return "navegador";
  } catch { return "no_disponible"; }
}
