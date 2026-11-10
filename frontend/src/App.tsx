import { useEffect, useMemo, useRef, useState } from "react";
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
import { AlertsPanel, BomPanel, CalcPanel, ChatPanel, CostPanel, FabPanel, FeaturesPanel, FixBox, ParamForm, PropsPanel, TreePanel } from "./panels";

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
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [delMsg, setDelMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.library().then(setLib).catch((e) => setErr((e as Error).message));
    api.projects().then(setProjects).catch((e) => setErr((e as Error).message));
    if (IS_LOCAL) storageLabel().then(setStore);
  }, []);
  const famName: Dict = Object.fromEntries((lib?.families ?? []).map((f) => [f.id, f.name]));
  async function remove(p: Project) {
    setBusy(true);
    try {
      await api.deleteProject(p.code);
      setProjects(await api.projects());
      setDelMsg({ ok: true, text: `Proyecto ${p.code} «${p.name}» borrado.` });
      setConfirmDel(null);
    } catch (e) { setDelMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  }
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
            se ejecuta en este navegador. Es el mismo motor del servidor, portado y contrastado con él caso a caso. Cada revisión se descarga como un expediente ZIP
            con STEP, planos PDF, instrucciones de montaje, DXF de corte, BOM en Excel y CSV, plan de corte, anidado e informe de cálculo.</p>}
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
          {delMsg && <p className={delMsg.ok ? "good" : "bad"} role="status">{delMsg.text}</p>}
          <div className="scroll-x"><table className="grid"><thead><tr><th>Código</th><th>Nombre / cliente</th><th>Familia</th><th>Rev.</th><th>Estado</th><th>Actualizado</th><th></th></tr></thead>
            <tbody>{projects.flatMap((p) => {
              const nRev = p.revisions.length, nDos = p.revisions.filter((r) => r.dossier).length;
              const official = ["validado", "preparado_fabricacion", "fabricado"].includes(p.status);
              const row = (
                <tr key={p.code} className="link" onClick={() => onOpen(p.code)}><td className="nowrap">{p.code}</td>
                  <td>{p.name}{p.client && <div className="muted small">{p.client}</div>}</td><td>{famName[p.family] ?? p.family}</td>
                  <td>{p.revisions.at(-1)?.rev ?? "—"}</td><td><span className="chip">{p.status_label}</span></td>
                  <td className="nowrap" title={p.updated.replace("T", " ")}>{p.updated.slice(0, 10)}</td>
                  <td><button className="mini danger" aria-label={`Borrar el proyecto ${p.code}`} disabled={busy}
                    onClick={(e) => { e.stopPropagation(); setDelMsg(null); setConfirmDel(confirmDel === p.code ? null : p.code); }}>Borrar</button></td></tr>);
              if (confirmDel !== p.code) return [row];
              return [row, (
                <tr key={p.code + "-confirm"} className="confirm-row"><td colSpan={7}>
                  <b>¿Borrar definitivamente {p.code} «{p.name}»?</b> Se eliminan {nRev ? `sus ${nRev} revisiones` : "sus parámetros"}
                  {nDos ? (IS_LOCAL ? ", el registro de sus expedientes (los ZIP ya descargados no se tocan)" : ` y sus ${nDos} expedientes guardados en el servidor`) : ""} y el historial de cambios. No se puede deshacer.
                  {official && <> <b className="bad">El proyecto está {p.status_label.toLowerCase()}: se perderá su registro técnico de validación.</b></>}
                  <div className="actions">
                    <button className="danger solid" disabled={busy} onClick={() => remove(p)}>{busy ? "Borrando…" : "Borrar definitivamente"}</button>
                    <button disabled={busy} onClick={() => setConfirmDel(null)}>Cancelar</button>
                  </div></td></tr>)];
            })}
              {projects.length === 0 && <tr><td colSpan={7} className="muted">Sin proyectos todavía. Abra una plantilla o pulse «Nuevo diseño».</td></tr>}
            </tbody></table></div>
        </section>
      </main>
    </div>
  );
}

const icon = (id: string) => ({ mesa_industrial: "▭", estanteria: "☰", puesto_trabajo: "⌂", carro_taller: "⛟", carro_estanteria: "▤", mesa_soldadura: "⊞", estanteria_bateria: "▥", tarima: "▬", carro_plataforma: "▂", armario: "▯", cantilever: "⊢", escalon: "⌸" } as Dict)[id] ?? "■";

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
const BOTTOM = ["Alertas y validación", "Cálculo", "BOM", "Fabricación", "Presupuesto", "Operaciones", "Documentos", "Historial"];

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

  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const projRef = useRef<Project | null>(null);
  projRef.current = project;

  const load = async () => { const p = await api.project(code); setProject(p); setDraft(p.working_params); return p; };
  // al entrar en el proyecto se recupera el diseño guardado: se regenera solo a partir de sus parámetros
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const p = await load();
        const f = await api.family(p.family);
        if (!alive) return;
        setFam(f);
        await regenerate(IS_LOCAL ? "Recuperando el diseño guardado (dimensionado y cálculo en el navegador)…" : "Recuperando el diseño guardado…");
      } catch (e) { if (alive) setError((e as Error).message); }
    })();
    return () => { alive = false; };
    /* eslint-disable-next-line */
  }, [code]);

  const derived = useMemo(() => Object.fromEntries((design?.parameters ?? []).filter((p: Dict) => !p.derived).map((p: Dict) => [p.name, p.value])), [design]);

  /** Regenera el diseño con los parámetros guardados del proyecto. */
  async function regenerate(label?: string) {
    setBusy(label ?? (IS_LOCAL ? "Regenerando modelo, dimensionado y cálculo en el navegador…" : "Regenerando modelo CAD, cálculo, fabricación e interferencias…"));
    setError("");
    try {
      await tick();
      const r = await api.design(code);
      setDesign(r.design); setViewer(r.viewer); setStale(false);
    } catch (e) { setError((e as Error).message); }
    setBusy("");
  }

  /** Guarda el borrador del formulario (si hay cambios) y regenera. */
  async function generate() {
    setError("");
    try {
      const p = projRef.current!;
      const changed = Object.fromEntries(Object.entries(draft).filter(([k, v]) => !same(p.working_params[k], v)));
      if (Object.keys(changed).length) { const r = await api.setParams(code, changed); setProject((o) => (o ? { ...o, ...r.project, assistant_state: o.assistant_state } : r.project)); }
    } catch (e) { setError((e as Error).message); return; }
    await regenerate();
  }

  // el borrador del formulario se guarda solo (no se pierde al cambiar de apartado ni al salir del proyecto)
  useEffect(() => {
    const p = projRef.current;
    if (!p) return;
    const changed = Object.fromEntries(Object.entries(draft).filter(([k, v]) => !same(p.working_params[k], v)));
    if (!Object.keys(changed).length) return;
    const t = setTimeout(async () => {
      try {
        const r = await api.setParams(code, changed);
        setProject((o) => (o ? { ...o, ...r.project, assistant_state: o.assistant_state } : r.project));
        setSaveMsg({ ok: true, text: "Cambios guardados" });
      } catch (e) { setSaveMsg({ ok: false, text: `Sin guardar: ${(e as Error).message}` }); }
    }, 800);
    return () => clearTimeout(t);
    /* eslint-disable-next-line */
  }, [draft]);

  function change(k: string, v: any) { setDraft((d) => ({ ...d, [k]: v })); setStale(true); setSaveMsg(null); }

  /** Respuesta del asistente: recarga el proyecto (familia incluida si ha cambiado) y regenera si se aplicaron datos. */
  async function onAssistant(r: Dict) {
    const p = await load();
    if (r.switched) setFam(await api.family(p.family));
    if (r.applied && (Object.keys(r.applied).length || !design || stale))
      await regenerate("Aplicando los datos del asistente: dimensionado, cálculo y verificación…");
  }

  /** Aplica la corrección automática comprobada y regenera. */
  async function applyFix(fix: Dict) {
    try {
      await api.setParams(code, fix.params, Object.fromEntries(Object.keys(fix.params).map((k) => [k, "correccion"])));
      await load();
    } catch (e) { setError((e as Error).message); return; }
    await regenerate("Aplicando la corrección y verificando de nuevo…");
  }

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
            {step === "ia" && <ChatPanel project={project} onResult={onAssistant} />}
            {step !== "ia" && step !== "generar" && <>
              <ParamForm specs={groupSpecs} values={draft} sources={{ ...designSources(design), ...project.working_sources }} derived={derived} onChange={change} />
              {saveMsg && <div className={`savestate ${saveMsg.ok ? "" : "bad"}`} role="status">{saveMsg.text}</div>}</>}
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
          {!busy && design?.fix && tab !== "Alertas y validación" && <div className="fixbox-float"><FixBox fix={design.fix} onApply={applyFix} busy={!!busy} /></div>}
          {error && <div className="error" onClick={() => setError("")}>{error}</div>}
          <div className="bottom">
            <div className="tabs">{BOTTOM.map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}{t === "Alertas y validación" && design ? ` (${design.qa.blocking}/${design.qa.warnings})` : ""}</button>)}</div>
            <div className="tab-body">
              {!design && tab !== "Documentos" && tab !== "Historial" && <div className="hint">Genere el diseño para ver resultados.</div>}
              {design && tab === "Alertas y validación" && <AlertsPanel design={design} project={project} onApplyFix={applyFix} busy={!!busy} />}
              {design && tab === "Cálculo" && <CalcPanel eng={design.engineering} />}
              {design && tab === "BOM" && <BomPanel bom={design.bom} />}
              {design && tab === "Fabricación" && <FabPanel plan={design.manufacturing} dfm={design.dfm} />}
              {design && tab === "Presupuesto" && <CostPanel cost={design.cost} />}
              {design && tab === "Operaciones" && <FeaturesPanel design={design} />}
              {tab === "Documentos" && <DocsPanel project={project} reload={load} design={design} stale={stale} />}
              {tab === "Historial" && <HistoryPanel code={code} updated={project.updated} />}
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

/** Igualdad entre el valor del formulario (texto) y el guardado (número, booleano o nulo). */
const same = (a: any, b: any) => String(a ?? "") === String(b ?? "");
/** Origen de cada valor según el diseño generado (cargas por uso, reglas, cálculo) para lo que el proyecto no fija. */
const designSources = (design: Dict | null): Dict => Object.fromEntries((design?.parameters ?? []).filter((p: Dict) => !p.derived && p.source).map((p: Dict) => [p.name, p.source]));

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
      <p>{IS_LOCAL ? "La generación resuelve los parámetros «auto» por cálculo, construye los sólidos de todas las piezas, calcula la estructura "
        + "(barras y placas) y comprueba interferencias, fabricabilidad y coherencia del BOM, todo en el navegador."
        : "La generación construye la geometría B-rep, regenera todas las piezas dependientes, calcula la estructura, comprueba interferencias, fabricabilidad y coherencia del BOM."}</p>
      <button className="primary big" disabled={!!busy} onClick={onGenerate}>GENERAR DISEÑO TÉCNICO</button>
      {design && !stale && <p className="good">Diseño regenerado: {design.product_code} · {design.qa.summary}</p>}
      <DocsPanel project={project} reload={reload} design={design} stale={stale} compact />
    </div>
  );
}

/** Aprobación técnica de la última revisión: nueve estados encadenados, validaciones pendientes con su documento de referencia
 *  y firmas de fabricabilidad, cálculo, aprobación y liberación (cada firma exige las etapas anteriores). */
function ApprovalPanel({ project, reload }: { project: Project; reload: () => void }) {
  const ap = project.approval;
  const [who, setWho] = useState("");
  const [refs, setRefs] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  if (!ap || !ap.gates?.length) return <p className="muted">Aprobación técnica: emita una revisión para iniciar el flujo de aprobación.</p>;
  const sign = async (stage: string) => { try { await api.signoff(project.code, stage, who); setMsg(""); reload(); } catch (e) { setMsg((e as Error).message); } };
  const validate = async (code: string) => { try { await api.validate(project.code, code, who, refs[code] ?? ""); setMsg(""); reload(); } catch (e) { setMsg((e as Error).message); } };
  const STAGES: [string, string, string][] = [["fabricabilidad", "Firmar revisión de fabricabilidad", "fabricabilidad_revisada"], ["calculo", "Firmar validación del cálculo", "calculo_validado"],
    ["aprobacion", "Aprobar técnicamente", "aprobado_tecnicamente"], ["liberacion", "Liberar para fabricación", "liberado_fabricacion"]];
  const sig = ap.records?.signoffs ?? {};
  return (
    <div className="approval">
      <h4>Aprobación técnica · revisión {ap.revision}: <span className={ap.state === "liberado_fabricacion" ? "good" : "warn"}>{ap.label}</span></h4>
      <ol className="gates">{ap.gates.map((g: Dict) => <li key={g.id} className={g.ok ? "good" : "pend"}><b>{g.ok ? "✓" : "○"} {g.label}</b>
        {g.signoff ? <span className="muted"> · {g.signoff.by} ({g.signoff.date})</span> : null}
        {!g.ok && g.reasons?.length ? <span className="muted"> — {g.reasons.join("; ")}</span> : null}</li>)}</ol>
      {ap.records?.legacy && <p className="muted">Antecedente migrado: {ap.records.legacy.status} ({ap.records.legacy.validated_by ?? "—"}). {ap.records.legacy.note}</p>}
      <div className="row"><input placeholder="Técnico que valida o firma" value={who} onChange={(e) => setWho(e.target.value)} /></div>
      {ap.open_validations?.length ? <>
        <p className="muted">Validaciones pendientes (cada una exige la referencia del documento que la justifica: ficha técnica, ETA, WPS, certificado, anejo nacional):</p>
        <table className="grid"><tbody>{ap.open_validations.map((c: string) => <tr key={c}><td>{c}</td>
          <td><input placeholder="Referencia del documento" value={refs[c] ?? ""} onChange={(e) => setRefs((x) => ({ ...x, [c]: e.target.value }))} /></td>
          <td><button className="mini" onClick={() => validate(c)}>Registrar validación</button></td></tr>)}</tbody></table></> : null}
      {Object.keys(ap.records?.validations ?? {}).length ? <p className="muted">Validaciones registradas: {Object.entries(ap.records.validations).map(([c, v]: [string, any]) =>
        `${c} (${v.reference}, ${v.by})`).join(" · ")}</p> : null}
      <div className="row">{STAGES.map(([st, label, gate]) => <button key={st} disabled={!!sig[st] || !who.trim()} onClick={() => sign(st)}
        title={ap.gates.find((g: Dict) => g.id === gate)?.reasons?.join("; ")}>{sig[st] ? `${label} ✓` : label}</button>)}</div>
      {ap.release_blockers?.length ? <p className="bad">Bloqueos de liberación abiertos: {ap.release_blockers.join(", ")}</p> : null}
      {msg && <p className="bad">{msg}</p>}
    </div>
  );
}

/** Inventario de retales reutilizables: los compatibles se ofrecen al plan de corte y al anidado; al liberar una revisión se
 *  consumen los usados y se dan de alta los nuevos. */
function InventoryPanel() {
  const [items, setItems] = useState<Dict[] | null>(null);
  const [f, setF] = useState<Dict>({ kind: "barra", profile: "", material: "", thickness: "", length: "", width: "" });
  const [msg, setMsg] = useState("");
  const load = async () => { try { setItems(await api.remnants("disponible")); } catch (e) { setMsg((e as Error).message); } };
  useEffect(() => { load(); }, []);
  const add = async () => {
    try {
      await api.addRemnant({ kind: f.kind, material: f.material, length: +f.length, profile: f.kind === "barra" ? f.profile : null,
        thickness: f.kind === "chapa" ? +f.thickness : null, width: f.kind === "chapa" ? +f.width : null });
      setMsg(""); load();
    } catch (e) { setMsg((e as Error).message); }
  };
  return (
    <div className="inventory">
      <h4>Inventario de retales reutilizables</h4>
      {items && !items.length ? <p className="muted">Sin retales disponibles. Se dan de alta al liberar una revisión para fabricación o manualmente.</p> : null}
      {items?.length ? <table className="grid"><thead><tr><th>Retal</th><th>Tipo</th><th>Perfil / espesor</th><th>Material</th><th>Dimensiones mm</th><th>Origen</th></tr></thead>
        <tbody>{items.map((r) => <tr key={r.id}><td>{r.id}</td><td>{r.kind}</td><td>{r.kind === "barra" ? r.profile : `e=${fmt(r.thickness)} mm`}</td><td>{r.material}</td>
          <td>{r.kind === "barra" ? fmt(r.length, 0) : `${fmt(r.length, 0)} × ${fmt(r.width, 0)}`}</td><td>{r.origin}</td></tr>)}</tbody></table> : null}
      <div className="row">
        <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="barra">barra</option><option value="chapa">chapa</option></select>
        {f.kind === "barra" ? <input placeholder="Perfil (p. ej. RHS 40x20x2)" value={f.profile} onChange={(e) => setF({ ...f, profile: e.target.value })} />
          : <input placeholder="Espesor mm" value={f.thickness} onChange={(e) => setF({ ...f, thickness: e.target.value })} />}
        <input placeholder="Material (p. ej. S235JRH)" value={f.material} onChange={(e) => setF({ ...f, material: e.target.value })} />
        <input placeholder="Longitud mm" value={f.length} onChange={(e) => setF({ ...f, length: e.target.value })} />
        {f.kind === "chapa" ? <input placeholder="Anchura mm" value={f.width} onChange={(e) => setF({ ...f, width: e.target.value })} /> : null}
        <button className="mini" onClick={add}>Añadir retal</button>
      </div>
      {msg && <p className="bad">{msg}</p>}
    </div>
  );
}

function DocsPanel({ project, reload, design, stale, compact }: { project: Project; reload: () => void; design: Dict | null; stale: boolean; compact?: boolean }) {
  const [job, setJob] = useState<Dict | null>(null);
  const [files, setFiles] = useState<Record<string, Dict[]>>({});
  const [msg, setMsg] = useState("");
  const last = project.revisions.at(-1);
  async function revision() {
    try { const r = await api.revision(project.code, "Emisión desde el configurador", project.designer || "Ingeniería"); setMsg(`Revisión ${r.rev} emitida.`); reload(); }
    catch (e) { setMsg((e as Error).message); }
  }
  async function dossier(rev: string) {
    if (IS_LOCAL) {
      setJob({ status: "running", stage: "regenerando la revisión" }); await tick();
      try { const j = await api.dossier(project.code, rev, (stage: string) => setJob({ status: "running", stage })); setJob(j); setFiles((x) => ({ ...x, [rev]: j.result.files })); reload(); }
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
    try { await api.status(project.code, s, "Ingeniería"); reload(); setMsg(""); } catch (e) { setMsg((e as Error).message); }
  }
  return (
    <div className="docs">
      <div className="row">
        <button disabled={!design || stale} onClick={revision} title="Congela los parámetros resueltos en una revisión inmutable">Emitir revisión</button>
        {last && !last.dossier && <button className="primary" disabled={job?.status === "running"} onClick={() => dossier(last.rev)}>GENERAR EXPEDIENTE DE FABRICACIÓN</button>}
        {last && last.dossier && project.approval?.gates?.some((g: Dict) => g.id === "liberado_fabricacion" && g.reasons?.some((r: string) => r.includes("regenerarse")))
          && ["aprobado_tecnicamente", "liberado_fabricacion"].includes(project.approval?.state)
          && <button className="primary" disabled={job?.status === "running"} onClick={() => dossier(last.rev)}>Nueva edición del expediente (aprobado)</button>}
        {msg && <span className="muted">{msg}</span>}
      </div>
      {IS_LOCAL && <p className="local-note">El expediente se genera aquí y se descarga como un único ZIP: 01 STEP del conjunto y de cada pieza, STL y JSON
        paramétrico · 02 planos PDF A3 (conjunto, estructura, perfiles, chapas, desarrollos, pletinas, soldaduras, explosionado, montaje y despiece) · 03 DXF de
        corte 1:1 y anidados · 04 BOM en Excel con fórmulas y CSV · 05 plan de corte y anidado · 06 instrucciones de montaje, informe de cálculo e historial,
        con manifiesto SHA-256. Cada archivo se verifica antes de empaquetar.</p>}
      {job && <p className={job.status === "error" ? "bad" : ""}>Expediente: {job.status === "running" ? `en curso (${job.stage})…` : job.status === "ok" ? `generado en ${job.result.seconds} s · ${job.result.qa.summary}${job.result.saved === "rechazada" ? " · descarga cancelada" : ""}` : job.error}</p>}
      {!compact && (
        <>
          <div className="scroll-x"><table className="grid"><thead><tr><th>Rev.</th><th>Fecha</th><th>Producto</th><th>Masa</th><th>Cálculo</th><th>Control de calidad</th><th>Expediente</th></tr></thead>
            <tbody>{project.revisions.map((r) => (
              <tr key={r.rev}><td>{r.rev}</td><td>{r.created.replace("T", " ")}</td><td>{r.product_code}</td><td>{fmt(r.mass_kg, 2)} kg</td><td>{r.structural}</td>
                <td>{r.qa?.summary}{(r as Dict).affected_documents?.length ? <div className="muted small">Documentos afectados por los cambios: {(r as Dict).affected_documents.join(", ")}</div> : null}</td><td>{r.dossier ? (IS_LOCAL ? <><button className="mini" onClick={() => dossier(r.rev)}>descargar ZIP</button> · <a onClick={() => loadFiles(r.rev)}>archivos</a></>
                  : <><a href={api.fileUrl(project.code, r.rev, "expediente.zip") ?? undefined}>ZIP</a> · <a onClick={() => loadFiles(r.rev)}>archivos</a></>) :
                  <button className="mini" onClick={() => dossier(r.rev)}>generar</button>}</td></tr>))}</tbody></table></div>
          {Object.entries(files).map(([rev, fl]) => (
            <div key={rev} className="filelist"><h4>Expediente revisión {rev}</h4>
              {fl.map((f) => <div key={f.path}>{IS_LOCAL ? <span>{f.path}</span> : <a href={api.fileUrl(project.code, rev, f.path) ?? undefined} target="_blank">{f.path}</a>} <span className="muted">{Math.max(1, Math.round(f.bytes / 1024))} kB · sha256 {f.sha256.slice(0, 12)}…</span></div>)}
            </div>))}
          <ApprovalPanel project={project} reload={reload} />
          <InventoryPanel />
          <h4>Estado del proyecto</h4>
          <p className="muted">«Aprobado técnicamente» y «Liberado para fabricación» se alcanzan con las firmas de la aprobación técnica.</p>
          <div className="row">
            <button onClick={() => status("fabricado")}>Fabricado</button>
            <button onClick={() => status("archivado")}>Archivar</button>
          </div>
        </>
      )}
    </div>
  );
}

function HistoryPanel({ code, updated }: { code: string; updated?: string }) {
  const [p, setP] = useState<Dict | null>(null);
  useEffect(() => { api.project(code).then(setP); }, [code, updated]);
  if (!p) return null;
  return (
    <table className="grid"><thead><tr><th>Fecha</th><th>Tipo</th><th>Autor</th><th>Detalle</th></tr></thead><tbody>
      {[...p.changes].reverse().map((c: Dict, i: number) => <tr key={i}><td>{c.timestamp.replace("T", " ")}</td><td>{c.kind}</td><td>{c.author}</td>
        <td className="small">{c.detail.changes ? Object.entries(c.detail.changes).map(([k, v]) => `${k}: ${(v as any[])[0]} → ${(v as any[])[1]}`).join("; ") : JSON.stringify(c.detail).slice(0, 200)}</td></tr>)}
    </tbody></table>
  );
}
