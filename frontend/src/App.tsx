import { useEffect, useMemo, useState } from "react";
import { api, fmt, IS_LOCAL, type Dict, type FamilyInfo, type Project, type ViewerPayload } from "./api";
import { storageLabel } from "./local/localApi";

/** Tema efectivo (atributo data-theme del visor o preferencia del sistema), para el visor 3D. */
function useTheme() {
  const read = () => document.documentElement.getAttribute("data-theme") ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const [t, setT] = useState(read);
  useEffect(() => {
    const mo = new MutationObserver(() => setT(read()));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const f = () => setT(read());
    mq.addEventListener("change", f);
    return () => { mo.disconnect(); mq.removeEventListener("change", f); };
  }, []);
  return t;
}
const tick = () => new Promise((r) => setTimeout(r, 30));
import Viewer, { type ViewName } from "./Viewer";
import { AlertsPanel, BomPanel, CalcPanel, ChatPanel, FabPanel, FeaturesPanel, ParamForm, PropsPanel, TreePanel } from "./panels";

export default function App() {
  const [code, setCode] = useState<string | null>(() => (IS_LOCAL ? null : new URLSearchParams(location.search).get("p")));
  useEffect(() => {
    if (IS_LOCAL) return;          // en el artefacto la navegación vive en el estado de la página
    try { history.replaceState(null, "", code ? `?p=${code}` : location.pathname); } catch { /* marco restringido */ }
  }, [code]);
  return code ? <Workspace code={code} onBack={() => setCode(null)} /> : <Home onOpen={setCode} />;
}

// ============================================================================ PASO 1: biblioteca y proyectos
function Home({ onOpen }: { onOpen: (c: string) => void }) {
  const [lib, setLib] = useState<{ families: Dict[]; templates: Dict[] } | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const [err, setErr] = useState("");
  const [store, setStore] = useState("");
  useEffect(() => { api.library().then(setLib); api.projects().then(setProjects); if (IS_LOCAL) storageLabel().then(setStore); }, []);
  async function create(family: string, template_id?: string) {
    try {
      const p = await api.createProject({ name: name || "Nuevo proyecto", client, family, template_id, designer: "Ingeniería" });
      onOpen(p.code);
    } catch (e) { setErr((e as Error).message); }
  }
  return (
    <div className="home">
      <Header />
      <main className="home-main">
        <section>
          <h2>1 · Selección de producto</h2>
          {IS_LOCAL && <p className="home-note">Todo el motor (geometría, dimensionado, cálculo por barras y placas, fabricación, BOM y control de calidad)
            se ejecuta en este navegador. Es el mismo motor del servidor, portado y contrastado con él caso a caso. STEP, interferencias B-rep
            y planos PDF requieren el servidor.</p>}
          <div className="newp"><input id="nombre" placeholder="Nombre del proyecto" value={name} onChange={(e) => setName(e.target.value)} />
            <input id="cliente" placeholder="Cliente" value={client} onChange={(e) => setClient(e.target.value)} />{err && <span className="bad">{err}</span>}</div>
          <div className="cards">
            {lib?.families.map((f) => (
              <div key={f.id} className={`card ${f.status !== "implementada" ? "disabled" : ""}`}>
                <div className="card-icon">{icon(f.id)}</div>
                <h3>{f.name}</h3><p>{f.description}</p>
                {f.status === "implementada" ? <button className="primary" onClick={() => create(f.id)}>Nuevo diseño</button>
                  : <span className="chip pend">Generador en desarrollo</span>}
              </div>))}
          </div>
          <h3>Plantillas de producto</h3>
          <div className="cards small">
            {lib?.templates.map((t) => (
              <div key={t.id} className="card">
                <h4>{t.name}</h4>
                <p className="muted">{Object.entries(t.values).slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>
                <button onClick={() => create(t.family, t.id)}>Abrir plantilla</button>
              </div>))}
          </div>
        </section>
        <section>
          <h2>Proyectos</h2>
          {IS_LOCAL && store && <p className="home-note">Almacenamiento: {store}.</p>}
          <div className="scroll-x"><table className="grid"><thead><tr><th>Código</th><th>Nombre</th><th>Cliente</th><th>Familia</th><th>Revisión</th><th>Estado</th><th>Actualizado</th></tr></thead>
            <tbody>{projects.map((p) => (
              <tr key={p.code} className="link" onClick={() => onOpen(p.code)}><td>{p.code}</td><td>{p.name}</td><td>{p.client}</td><td>{p.family}</td>
                <td>{p.revisions.at(-1)?.rev ?? "—"}</td><td><span className="chip">{p.status_label}</span></td><td>{p.updated.replace("T", " ")}</td></tr>))}
              {projects.length === 0 && <tr><td colSpan={7} className="muted">Sin proyectos todavía. Abra una plantilla o pulse «Nuevo diseño».</td></tr>}
            </tbody></table></div>
        </section>
      </main>
    </div>
  );
}

const icon = (id: string) => ({ mesa_industrial: "▭", estanteria: "☰", puesto_trabajo: "⌂", armario: "▯" } as Dict)[id] ?? "■";

function Header({ children }: { children?: React.ReactNode }) {
  return <header className="topbar"><div className="brand"><b>MONXU</b><span>Ingeniería paramétrica de mobiliario industrial</span>
    {IS_LOCAL && <span className="engine-chip">Motor en el navegador</span>}</div>{children}</header>;
}

// ============================================================================ espacio de trabajo
const STEPS = [
  { id: "ia", label: "2 · Descripción con IA" }, { id: "dimensiones", label: "3 · Dimensiones" },
  { id: "materiales", label: "4 · Materiales" }, { id: "construccion", label: "5 · Construcción" },
  { id: "accesorios", label: "6 · Accesorios" }, { id: "cargas", label: "7 · Cargas y uso" }, { id: "generar", label: "8 · Generación" },
];
const BOTTOM = ["Alertas y validación", "Cálculo", "BOM", "Fabricación", "Operaciones", "Documentos", "Historial"];

function Workspace({ code, onBack }: { code: string; onBack: () => void }) {
  const [project, setProject] = useState<Project | null>(null);
  const [fam, setFam] = useState<FamilyInfo | null>(null);
  const [step, setStep] = useState("ia");
  const [draft, setDraft] = useState<Dict>({});
  const [design, setDesign] = useState<Dict | null>(null);
  const [viewer, setViewer] = useState<ViewerPayload | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState(BOTTOM[0]);
  const [right, setRight] = useState("Árbol");
  const [mode, setMode] = useState<"tecnico" | "comercial">("tecnico");
  const [explode, setExplode] = useState(0);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const [view, setView] = useState<{ name: ViewName; n: number }>({ name: "iso", n: 0 });
  const [stale, setStale] = useState(true);
  const theme = useTheme();

  const load = async () => { const p = await api.project(code); setProject(p); setDraft(p.working_params); return p; };
  useEffect(() => { load().then((p) => api.family(p.family).then(setFam)); /* eslint-disable-next-line */ }, [code]);

  const derived = useMemo(() => Object.fromEntries((design?.parameters ?? []).filter((p: Dict) => !p.derived).map((p: Dict) => [p.name, p.value])), [design]);

  async function generate() {
    setBusy(IS_LOCAL ? "Regenerando modelo, dimensionado y cálculo en el navegador…" : "Regenerando modelo CAD, cálculo, fabricación e interferencias…"); setError("");
    try {
      const changed = Object.fromEntries(Object.entries(draft).filter(([k, v]) => project!.working_params[k] !== v));
      if (Object.keys(changed).length) await api.setParams(code, changed);
      await tick();
      const r = await api.design(code);
      setDesign(r.design); setViewer(r.viewer); setStale(false); await load();
    } catch (e) { setError((e as Error).message); }
    setBusy("");
  }

  function change(k: string, v: any) { setDraft((d) => ({ ...d, [k]: v })); setStale(true); }

  if (!project || !fam) return <div className="loading">Cargando…</div>;
  const groupSpecs = fam.params.filter((s) => s.group === step);
  return (
    <div className="ws">
      <Header>
        <button onClick={onBack}>← Proyectos</button>
        <div className="pinfo"><b>{project.code}</b> · {project.name} <span className="chip">{project.status_label}</span>
          {project.revisions.length > 0 && <span className="chip">Rev. {project.revisions.at(-1)!.rev}</span>}</div>
        <button className="primary big" disabled={!!busy} onClick={generate}>GENERAR DISEÑO TÉCNICO</button>
      </Header>
      <div className="ws-body">
        <aside className="left">
          <nav className="steps">{STEPS.map((s) => <button key={s.id} className={step === s.id ? "on" : ""} onClick={() => setStep(s.id)}>{s.label}</button>)}</nav>
          <div className="left-content">
            {step === "ia" && <ChatPanel project={project} onApplied={async () => { await load(); setStale(true); }} />}
            {step !== "ia" && step !== "generar" && <ParamForm specs={groupSpecs} values={draft} sources={project.working_sources} derived={derived} onChange={change} />}
            {step === "generar" && <GeneratePanel project={project} design={design} stale={stale} busy={busy} onGenerate={generate} reload={load} />}
          </div>
        </aside>
        <section className="center">
          <div className="vtoolbar">
            {(["iso", "alzado", "perfil", "planta"] as ViewName[]).map((v) => <button key={v} onClick={() => setView({ name: v, n: view.n + 1 })}>{v === "iso" ? "Isométrica" : v[0].toUpperCase() + v.slice(1)}</button>)}
            <span className="sep" />
            <label>Explosionado <input type="range" min={0} max={1} step={0.01} value={explode} onChange={(e) => setExplode(+e.target.value)} /></label>
            <button className={measuring ? "on" : ""} onClick={() => setMeasuring(!measuring)}>Medir</button>
            <button onClick={() => setHidden(new Set())}>Mostrar todo</button>
            <span className="sep" />
            <button className={mode === "tecnico" ? "on" : ""} onClick={() => setMode("tecnico")}>CAD técnico</button>
            <button className={mode === "comercial" ? "on" : ""} onClick={() => setMode("comercial")}>Acabado realista</button>
            {stale && design && <span className="chip warn">Parámetros modificados: regenerar</span>}
          </div>
          <Viewer payload={viewer} mode={mode} explode={explode} hidden={hidden} selected={selected} onSelect={setSelected} measuring={measuring} view={view} theme={theme} />
          {busy && <div className="busy">{busy}</div>}
          {error && <div className="error" onClick={() => setError("")}>{error}</div>}
          <div className="bottom">
            <div className="tabs">{BOTTOM.map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}{t === "Alertas y validación" && design ? ` (${design.qa.blocking}/${design.qa.warnings})` : ""}</button>)}</div>
            <div className="tab-body">
              {!design && tab !== "Documentos" && tab !== "Historial" && <div className="hint">Genere el diseño para ver resultados.</div>}
              {design && tab === "Alertas y validación" && <AlertsPanel design={design} />}
              {design && tab === "Cálculo" && <CalcPanel eng={design.engineering} />}
              {design && tab === "BOM" && <BomPanel bom={design.bom} />}
              {design && tab === "Fabricación" && <FabPanel plan={design.manufacturing} dfm={design.dfm} />}
              {design && tab === "Operaciones" && <FeaturesPanel design={design} />}
              {tab === "Documentos" && <DocsPanel project={project} reload={load} design={design} stale={stale} />}
              {tab === "Historial" && <HistoryPanel code={code} />}
            </div>
          </div>
        </section>
        <aside className="right">
          <div className="tabs">{["Árbol", "Propiedades", "Resumen"].map((t) => <button key={t} className={right === t ? "on" : ""} onClick={() => setRight(t)}>{t}</button>)}</div>
          <div className="right-content">
            {right === "Árbol" && viewer && <TreePanel tree={viewer.tree} hidden={hidden} setHidden={setHidden} selected={selected} onSelect={(id) => { setSelected(id); setRight("Propiedades"); }} />}
            {right === "Propiedades" && design && viewer && <PropsPanel id={selected} design={design} viewer={viewer} />}
            {right === "Resumen" && design && <Summary design={design} />}
          </div>
        </aside>
      </div>
    </div>
  );
}

function Summary({ design }: { design: Dict }) {
  const t = design.bom.totals;
  const g = design.engineering.governing;
  return (
    <table className="kv"><tbody>
      <tr><th>Producto</th><td>{design.product_code}</td></tr>
      <tr><th>Masa total</th><td>{fmt(t.total_mass, 2)} kg</td></tr>
      <tr><th>Componentes</th><td>{t.components} ({t.distinct_parts} referencias)</td></tr>
      <tr><th>Geometría</th><td className={design.status.geometry_complete ? "good" : "bad"}>{design.status.geometry_complete ? "Completa" : "Con errores"}</td></tr>
      <tr><th>Cálculo</th><td>{design.status.structural_label}</td></tr>
      {g && <tr><th>Determinante</th><td>{g.description} ({fmt(g.utilization, 3)})</td></tr>}
      <tr><th>Interferencias</th><td>{design.interferences.evaluated === false ? "No evaluadas en el navegador (B-rep en servidor)" : `${design.interferences.interferences.length} (${design.interferences.pairs_checked} parejas)`}</td></tr>
      <tr><th>Tiempos (s)</th><td>{Object.entries(design.timings).map(([k, v]) => `${k} ${v}`).join(" · ")}</td></tr>
    </tbody></table>
  );
}

function GeneratePanel({ project, design, stale, busy, onGenerate, reload }: { project: Project; design: Dict | null; stale: boolean; busy: string; onGenerate: () => void; reload: () => void }) {
  return (
    <div className="gen">
      <p>{IS_LOCAL ? "La generación resuelve los parámetros «auto» por cálculo, construye todas las piezas dependientes, calcula la estructura "
        + "(barras y placas), y comprueba fabricabilidad y coherencia del BOM, todo en el navegador."
        : "La generación construye la geometría B-rep, regenera todas las piezas dependientes, calcula la estructura, comprueba interferencias, fabricabilidad y coherencia del BOM."}</p>
      <button className="primary big" disabled={!!busy} onClick={onGenerate}>GENERAR DISEÑO TÉCNICO</button>
      {design && !stale && <p className="good">Diseño regenerado: {design.product_code} · {design.qa.summary}</p>}
      <DocsPanel project={project} reload={reload} design={design} stale={stale} compact />
    </div>
  );
}

function DocsPanel({ project, reload, design, stale, compact }: { project: Project; reload: () => void; design: Dict | null; stale: boolean; compact?: boolean }) {
  const [job, setJob] = useState<Dict | null>(null);
  const [files, setFiles] = useState<Record<string, Dict[]>>({});
  const [msg, setMsg] = useState("");
  const [tech, setTech] = useState("");
  const last = project.revisions.at(-1);
  async function revision() {
    try { const r = await api.revision(project.code, "Emisión desde el configurador", project.designer || "Ingeniería"); setMsg(`Revisión ${r.rev} emitida.`); reload(); }
    catch (e) { setMsg((e as Error).message); }
  }
  async function dossier(rev: string) {
    if (IS_LOCAL) {
      setJob({ status: "running", stage: "generando DXF, CSV, SVG e informe" }); await tick();
      try { const j = await api.dossier(project.code, rev); setJob(j); setFiles((x) => ({ ...x, [rev]: j.result.files })); reload(); }
      catch (e) { setJob({ status: "error", error: (e as Error).message }); }
      return;
    }
    try {
      const j = await api.dossier(project.code, rev); setJob(j);
      const poll = async () => { const s = await api.job(j.id); setJob(s); if (s.status === "running") setTimeout(poll, 1500); else { reload(); loadFiles(rev); } };
      setTimeout(poll, 1500);
    } catch (e) { setMsg((e as Error).message); }
  }
  async function loadFiles(rev: string) { const f = await api.files(project.code, rev); setFiles((x) => ({ ...x, [rev]: f.files })); }
  async function status(s: string) {
    try { await api.status(project.code, s, "Ingeniería", tech || undefined); reload(); setMsg(""); } catch (e) { setMsg((e as Error).message); }
  }
  return (
    <div className="docs">
      <div className="row">
        <button disabled={!design || stale} onClick={revision} title="Congela los parámetros resueltos en una revisión inmutable">Emitir revisión</button>
        {last && !last.dossier && <button className="primary" disabled={job?.status === "running"} onClick={() => dossier(last.rev)}>GENERAR EXPEDIENTE DE FABRICACIÓN</button>}
        {msg && <span className="muted">{msg}</span>}
      </div>
      {IS_LOCAL && <p className="local-note">El expediente se genera aquí como ZIP (carpetas 01–06 con DXF de corte 1:1, BOM y compras en CSV, desarrollos y anidados
        en SVG, malla STL, informe de cálculo HTML y manifiesto SHA-256). STEP, planos PDF y Excel con fórmulas se generan con el servidor a partir del
        JSON paramétrico incluido.</p>}
      {job && <p className={job.status === "error" ? "bad" : ""}>Expediente: {job.status === "running" ? `en curso (${job.stage})…` : job.status === "ok" ? `generado en ${job.result.seconds} s · ${job.result.qa.summary}${job.result.saved === "rechazada" ? " · descarga cancelada" : ""}` : job.error}</p>}
      {!compact && (
        <>
          <div className="scroll-x"><table className="grid"><thead><tr><th>Rev.</th><th>Fecha</th><th>Producto</th><th>Masa</th><th>Cálculo</th><th>Control de calidad</th><th>Expediente</th></tr></thead>
            <tbody>{project.revisions.map((r) => (
              <tr key={r.rev}><td>{r.rev}</td><td>{r.created.replace("T", " ")}</td><td>{r.product_code}</td><td>{fmt(r.mass_kg, 2)} kg</td><td>{r.structural}</td>
                <td>{r.qa?.summary}</td><td>{r.dossier ? (IS_LOCAL ? <><button className="mini" onClick={() => dossier(r.rev)}>descargar ZIP</button> · <a onClick={() => loadFiles(r.rev)}>archivos</a></>
                  : <><a href={api.fileUrl(project.code, r.rev, "expediente.zip") ?? undefined}>ZIP</a> · <a onClick={() => loadFiles(r.rev)}>archivos</a></>) :
                  <button className="mini" onClick={() => dossier(r.rev)}>generar</button>}</td></tr>))}</tbody></table></div>
          {Object.entries(files).map(([rev, fl]) => (
            <div key={rev} className="filelist"><h4>Expediente revisión {rev}</h4>
              {fl.map((f) => <div key={f.path}>{IS_LOCAL ? <span>{f.path}</span> : <a href={api.fileUrl(project.code, rev, f.path) ?? undefined} target="_blank">{f.path}</a>} <span className="muted">{Math.max(1, Math.round(f.bytes / 1024))} kB · sha256 {f.sha256.slice(0, 12)}…</span></div>)}
            </div>))}
          <h4>Estado del proyecto</h4>
          <div className="row">
            <input id="tecnico" placeholder="Técnico competente que valida" value={tech} onChange={(e) => setTech(e.target.value)} />
            <button onClick={() => status("validado")}>Validar</button>
            <button onClick={() => status("preparado_fabricacion")}>Preparado para fabricación</button>
            <button onClick={() => status("fabricado")}>Fabricado</button>
            <button onClick={() => status("archivado")}>Archivar</button>
          </div>
        </>
      )}
    </div>
  );
}

function HistoryPanel({ code }: { code: string }) {
  const [p, setP] = useState<Dict | null>(null);
  useEffect(() => { api.project(code).then(setP); }, [code]);
  if (!p) return null;
  return (
    <table className="grid"><thead><tr><th>Fecha</th><th>Tipo</th><th>Autor</th><th>Detalle</th></tr></thead><tbody>
      {[...p.changes].reverse().map((c: Dict, i: number) => <tr key={i}><td>{c.timestamp.replace("T", " ")}</td><td>{c.kind}</td><td>{c.author}</td>
        <td className="small">{c.detail.changes ? Object.entries(c.detail.changes).map(([k, v]) => `${k}: ${(v as any[])[0]} → ${(v as any[])[1]}`).join("; ") : JSON.stringify(c.detail).slice(0, 200)}</td></tr>)}
    </tbody></table>
  );
}
