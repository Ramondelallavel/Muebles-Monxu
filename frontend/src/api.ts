import { localApi } from "./local/localApi";

export type Dict = Record<string, any>;

export interface ParamSpec {
  name: string; label: string; type: string; default: any; unit: string | null; group: string;
  min: number | null; max: number | null; choices: any[] | null; allow_auto: boolean; nullable: boolean;
  help: string; advanced: boolean;
}

export interface FamilyInfo {
  id: string; name: string; description: string; status: string; configurations: string[];
  groups: { id: string; label: string }[]; params: ParamSpec[]; verification_inputs: string[];
}

export interface Revision {
  rev: string; created: string; comment: string; author: string; product_code: string; mass_kg: number;
  structural: string; qa: Dict; dossier: boolean; changes: Dict;
}

export interface Project {
  code: string; name: string; client: string; description: string; family: string; designer: string;
  status: string; status_label: string; created: string; updated: string; validated_by: string | null; approval?: Dict | null;
  working_params: Dict; working_sources: Dict; revisions: Revision[]; changes?: Dict[]; assistant_state?: Dict;
}

export interface ViewerInstance {
  id: string; name: string; part: string; ref: string; group: string; kind: string; matrix: number[];
  color: number[]; explode: number[]; bbox: number[][]; feature: string;
}

export interface ViewerPayload {
  // mallas de `parts`: base64 (servidor) o arrays tipados (navegador)
  product_code: string; parts: Record<string, Dict>; instances: ViewerInstance[]; bbox: number[][];
  subassemblies: Dict[]; tree: Dict;
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method, headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : j.detail?.message ?? JSON.stringify(j.detail);
    } catch { /* sin cuerpo JSON */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

const serverApi = {
  mode: "servidor" as "servidor" | "local",
  library: () => req<{ families: Dict[]; templates: Dict[] }>("GET", "/api/library"),
  family: (id: string) => req<FamilyInfo>("GET", `/api/families/${id}`),
  projects: () => req<Project[]>("GET", "/api/projects"),
  project: (code: string) => req<Project & { assistant_state: Dict }>("GET", `/api/projects/${code}`),
  createProject: (b: Dict) => req<Project>("POST", "/api/projects", b),
  deleteProject: (code: string) => req<Dict>("DELETE", `/api/projects/${code}`),
  setParams: (code: string, values: Dict, sources?: Dict, replace = false) =>
    req<{ changes: Dict; project: Project }>("PUT", `/api/projects/${code}/params`, { values, sources, replace }),
  design: (code: string) => req<{ design: Dict; viewer: ViewerPayload }>("POST", `/api/projects/${code}/design`),
  assistant: (code: string, message: string, answers?: Dict, apply = false) =>
    req<Dict>("POST", `/api/projects/${code}/assistant`, { message, answers, apply }),
  revision: (code: string, comment: string, author: string) =>
    req<{ rev: string; project: Project }>("POST", `/api/projects/${code}/revisions`, { comment, author }),
  dossier: (code: string, rev: string) => req<Dict>("POST", `/api/projects/${code}/revisions/${rev}/dossier`),
  job: (id: string) => req<Dict>("GET", `/api/jobs/${id}`),
  files: (code: string, rev: string) => req<{ files: Dict[] }>("GET", `/api/projects/${code}/revisions/${rev}/files`),
  status: (code: string, status: string, user: string, validated_by?: string) =>
    req<Project>("POST", `/api/projects/${code}/status`, { status, user, validated_by }),
  statuses: () => req<{ id: string; label: string }[]>("GET", "/api/statuses"),
  approval: (code: string, rev?: string | null) => req<Dict>("GET", `/api/projects/${code}/approval${rev ? `?rev=${rev}` : ""}`),
  validate: (code: string, item: string, by: string, reference: string, comment = "", rev?: string | null) =>
    req<Dict>("POST", `/api/projects/${code}/validations`, { code: item, by, reference, comment, rev: rev ?? null }),
  signoff: (code: string, stage: string, by: string, comment = "", rev?: string | null) =>
    req<Dict>("POST", `/api/projects/${code}/signoff`, { stage, by, comment, rev: rev ?? null }),
  remnants: (status: string | null = "disponible") => req<Dict[]>("GET", `/api/remnants${status ? `?status=${status}` : "?status="}`),
  addRemnant: (b: Dict) => req<Dict>("POST", "/api/remnants", b),
  fileUrl: (code: string, rev: string, path: string): string | null => `/api/projects/${code}/revisions/${rev}/files/${path}`,
};

/** En la versión artefacto (VITE_LOCAL=1) todo el motor se ejecuta en el navegador con la misma interfaz. */
export const IS_LOCAL = import.meta.env.VITE_LOCAL === "1";
type Api = typeof serverApi & {
  assistantPrompt?: (code: string, message: string) => Promise<string>;
  design: (code: string, onProgress?: (s: string) => void) => Promise<{ design: Dict; viewer: ViewerPayload }>;
  assistant: (code: string, message: string, answers?: Dict, apply?: boolean, llm?: Dict | null) => Promise<Dict>;
  dossier: (code: string, rev: string, onProgress?: (s: string) => void) => Promise<Dict>;
};
export const api: Api = IS_LOCAL ? (localApi as unknown as Api) : (serverApi as Api);

export const fmt = (v: any, d = 1) =>
  typeof v === "number" ? (Math.abs(v - Math.round(v)) < 1e-9 ? String(Math.round(v)) : v.toFixed(d).replace(".", ",")) : v ?? "—";

export const SOURCE_LABEL: Record<string, string> = {
  usuario: "Usuario", defecto: "Por defecto", plantilla: "Plantilla", ia_propuesta: "Propuesta IA",
  regla_diseno: "Regla de diseño", calculo: "Dimensionado por cálculo", por_uso: "Por defecto según el uso", correccion: "Corrección automática",
};
