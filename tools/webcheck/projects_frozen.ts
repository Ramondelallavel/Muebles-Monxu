// API local del navegador con la base de datos del artefacto: los documentos que entrega el runtime están congelados
// (solo lectura) y los proyectos guardados con versiones anteriores no tienen `schema`; deben migrarse al leerlos.
import { localApi } from "../../frontend/src/local/localApi";
const frozen = (o: any): any => { if (o && typeof o === "object") { Object.values(o).forEach(frozen); Object.freeze(o); } return o; };
const legacy = (code: string, status: string) => ({ code, name: "Antiguo", client: "", description: "", family: "mesa_industrial", designer: "Ingeniería", status,
  validated_by: status === "validado" ? "Ing. Antes" : null, created: "2026-11-10T15:00:00", updated: "2026-11-10T15:00:00", working_params: {}, working_sources: {},
  assistant_state: {}, changes: [], revisions: status === "en_configuracion" ? [] : [{ rev: "A", created: "2026-11-10T15:00:00", author: "x", comment: "", params: {}, sources: {},
    product_code: "MI1200-700-900", mass_kg: 100, structural: "CUMPLE", qa: { result: "ok", summary: "", blocking: 0 }, dossier: null, changes: {} }] });
const store: Record<string, any> = { "P-2026-0001": legacy("P-2026-0001", "en_configuracion"), "P-2026-0002": legacy("P-2026-0002", "validado"),
  contador: { por_anio: { a2026: 2 } } };
const writes: Record<string, any> = {};
const col = { get: async () => ({ docs: Object.entries(store).map(([id, v]) => ({ id, data: () => frozen(JSON.parse(JSON.stringify(v))) })) }),
  doc: (id: string) => ({ set: async (v: any) => { writes[id] = JSON.parse(JSON.stringify(v)); store[id] = writes[id]; }, delete: async () => { delete store[id]; } }) };
(globalThis as any).window = { claude: { use: async (n: string) => (n === "db" ? { collection: () => col } : n === "user" ? { id: async () => "u_test" } : null) } };
const out: Record<string, unknown> = {};
try {
  const list = await localApi.projects();
  out.codes = list.map((p: any) => p.code);
  out.status = Object.fromEntries(list.map((p: any) => [p.code, p.status]));
  out.migrated = Object.fromEntries(Object.entries(writes).map(([k, v]: any) => [k, v.schema]));
  const p = await localApi.project("P-2026-0002");
  out.legacy_note = writes["P-2026-0002"]?.revisions?.[0]?.approval?.legacy?.validated_by ?? null;
  out.approval_state = p.approval?.state ?? null;
  out.new_code = (await localApi.createProject({ name: "Nuevo", family: "mesa_industrial" })).code;
} catch (e) { out.error = String((e as Error).stack ?? e).slice(0, 400); }
console.log(JSON.stringify(out));
