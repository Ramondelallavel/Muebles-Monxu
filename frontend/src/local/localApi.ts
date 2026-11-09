// @ts-nocheck
// API local: misma interfaz que la API del servidor, ejecutada íntegramente en el navegador.
// Persistencia: base de datos privada del artefacto (capacidad 'db', por usuario) o memoria si no está disponible.
import { REGISTRY, family, library, allTemplates } from "../engine/families";
import { regenerate } from "../engine/pipeline";
import { viewerPayload } from "../engine/geometry";
import { ParamError } from "../engine/model";
import * as A from "../engine/assistant";
import { buildDossier } from "./dossier";

export const STATUSES = ["en_configuracion", "en_diseno", "pendiente_validacion", "validado", "preparado_fabricacion", "fabricado", "archivado"];
export const STATUS_LABELS = { en_configuracion: "En configuración", en_diseno: "En diseño", pendiente_validacion: "Pendiente de validación", validado: "Validado",
  preparado_fabricacion: "Preparado para fabricación", fabricado: "Fabricado", archivado: "Archivado" };
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
    if (!db || !uid) return { kind: "memoria", list: async () => [...mem.values()], put: async (p) => { mem.set(p.code, p); }, del: async (code) => { mem.delete(code); },
      seq: async (year) => memSeq[year] ?? 0, setSeq: async (year, n) => { memSeq[year] = Math.max(memSeq[year] ?? 0, n); }, label: "Memoria del navegador (se pierde al cerrar)" };
    const col = db.collection("data/users/" + uid);
    const cache = new Map();
    let loaded = false, seq = {};
    const load = async () => {
      if (loaded) return;
      const t = new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 10000));
      const snap = await Promise.race([col.get(), t]);
      snap.docs.forEach((d) => { const v = d.data(); if (d.id === SEQ_DOC) seq = v?.por_anio ?? {}; else if (v?.code) cache.set(v.code, v); });
      loaded = true;
    };
    return { kind: "db", label: "Base de datos privada del artefacto (sólo usted)", list: async () => { try { await load(); } catch { /* sin conexión: caché */ } return [...cache.values()]; },
      put: async (p) => { cache.set(p.code, p); await col.doc(p.code).set(JSON.parse(JSON.stringify(p))); },
      del: async (code) => { await col.doc(code).delete(); cache.delete(code); },
      // claves «a2026»: nombres de campo no numéricos
      seq: async (year) => { try { await load(); } catch { /* caché */ } return Number(seq[`a${year}`]) || 0; },
      setSeq: async (year, n) => { seq = { ...seq, [`a${year}`]: Math.max(Number(seq[`a${year}`]) || 0, n) }; await col.doc(SEQ_DOC).set({ por_anio: seq }); } };
  })();
  return storeP;
}
export const storageLabel = async () => (await getStore()).label;
const SEQ_DOC = "contador";            // último número de proyecto emitido: los códigos no se reutilizan al borrar
const CODE_RX = /^P-(\d{4})-(\d{4,})$/;
/** Siguiente código del año: mayor que cualquiera emitido (existente o borrado). */
async function nextCode() {
  const st = await getStore(), year = new Date().getFullYear();
  const used = (await all()).map((p) => CODE_RX.exec(p.code)).filter((m) => m && +m[1] === year).map((m) => +m[2]);
  const n = Math.max(await st.seq(year), ...used) + 1;
  await st.setSeq(year, n);
  return `P-${year}-${String(n).padStart(4, "0")}`;
}

async function all() { return (await (await getStore()).list()).sort((a, b) => (a.code < b.code ? 1 : -1)); }
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
const projectDict = (p) => ({ ...p, status_label: STATUS_LABELS[p.status],
  revisions: (p.revisions ?? []).map((r) => ({ rev: r.rev, created: r.created, comment: r.comment, author: r.author, product_code: r.product_code, mass_kg: r.mass_kg,
    structural: r.structural, qa: r.qa, dossier: !!r.dossier, changes: r.changes })) });

const jobs = new Map();
const designCache = new Map();
async function designFor(fam, values, sources, onProgress) {
  const key = JSON.stringify([fam, values, sources]);
  if (designCache.has(key)) return designCache.get(key);
  try {
    const r = regenerate(fam, values, sources, onProgress);
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
    const { model, summary } = await designFor(p.family, p.working_params, p.working_sources, onProgress);
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
    const { model, summary } = await designFor(p.family, p.working_params, p.working_sources);
    if (summary.qa.blocking) throw new Error("El diseño tiene errores bloqueantes: no puede emitirse revisión.");
    const prev = p.revisions.at(-1);
    const letter = prev ? String.fromCharCode(prev.rev.charCodeAt(0) + 1) : "A";
    const resolved = { ...model.params.values };
    const diff = prev ? Object.fromEntries(Object.entries(resolved).filter(([k, v]) => JSON.stringify(prev.params[k]) !== JSON.stringify(v)).map(([k, v]) => [k, [prev.params[k] ?? null, v]])) : {};
    p.revisions.push({ rev: letter, created: now(), comment, author, params: resolved, sources: { ...model.params.sources }, product_code: model.product_code,
      mass_kg: summary.bom.totals.total_mass, structural: summary.engineering.status,
      qa: { result: summary.qa.result, summary: summary.qa.summary, blocking: summary.qa.blocking }, dossier: null, changes: diff });
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
    const { model, summary } = regenerate(p.family, r.params, r.sources);
    const out = await buildDossier(p, r, model, summary, onProgress);
    if (out.qa.blocking) throw new Error("La verificación de los archivos exportados ha fallado: no se publica el expediente. " + out.qa.items.filter((i) => i.level === "bloqueante").map((i) => i.message).join(" "));
    const saved = await deliver(out.name + ".zip", out.zip);
    if (!r.dossier) {
      r.dossier = { name: out.name, created: now(), files: out.files, qa: { result: out.qa.result, summary: out.qa.summary, blocking: out.qa.blocking } };
      r.qa = r.dossier.qa;
      log(p, "expediente", { rev, name: out.name, files: out.files.length });
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
      if (last.structural !== "CUMPLE") throw new Error("La verificación estructural de la revisión no es CUMPLE: no puede validarse.");
      if (last.qa?.blocking) throw new Error("La revisión tiene errores bloqueantes de control de calidad.");
    }
    if (status === "validado") { if (!validated_by) throw new Error("La validación requiere el nombre del técnico competente."); p.validated_by = validated_by; }
    if (["preparado_fabricacion", "fabricado"].includes(status) && !p.validated_by) throw new Error("El proyecto debe estar validado por un técnico competente.");
    const old = p.status;
    p.status = status;
    log(p, "estado", { from: old, to: status, validated_by: validated_by ?? null }, user);
    await put(p);
    return projectDict(p);
  },
  statuses: async () => STATUSES.map((s) => ({ id: s, label: STATUS_LABELS[s] })),
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
