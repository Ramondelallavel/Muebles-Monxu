import { useEffect, useState } from "react";
import { api, fmt, IS_LOCAL, SOURCE_LABEL, type Dict, type ParamSpec, type Project } from "./api";

type SampleJson = { json: (input: string, opts?: Dict) => Promise<unknown> };
/** Capacidad 'sample' del artefacto (Claude con la cuenta del usuario); null fuera de un visor de Claude. */
function useSample() {
  const [s, setS] = useState<SampleJson | null>(null);
  useEffect(() => {
    const w = window as unknown as { claude?: { use?: (n: string) => Promise<unknown> } };
    if (!IS_LOCAL || !w.claude?.use) return;
    let alive = true;
    w.claude.use("sample").then((x) => { if (alive && x) setS(x as SampleJson); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);
  return [s, setS] as const;
}

// ============================================================================ formulario de parámetros
export function ParamForm({ specs, values, sources, derived, onChange }: {
  specs: ParamSpec[]; values: Dict; sources: Dict; derived: Dict; onChange: (k: string, v: any) => void;
}) {
  const [adv, setAdv] = useState(false);
  const shown = specs.filter((s) => adv || !s.advanced);
  return (
    <div className="form">
      {shown.map((s) => {
        const v = values[s.name] ?? s.default;
        const resolved = derived[s.name];
        return (
          <label key={s.name} className="field" title={s.help}>
            <span className="field-label">{s.label}{s.unit && <em> [{s.unit}]</em>}</span>
            <div className="field-row">
              {s.type === "choice" ? (
                <select value={String(v)} onChange={(e) => onChange(s.name, e.target.value)}>
                  {s.allow_auto && <option value="auto">auto (dimensionar)</option>}
                  {s.choices!.map((c) => <option key={String(c)} value={String(c)}>{String(c)}</option>)}
                </select>
              ) : s.type === "bool" ? (
                <input type="checkbox" checked={!!v} onChange={(e) => onChange(s.name, e.target.checked)} />
              ) : (
                <input value={v === null || v === undefined ? "" : String(v)} placeholder={s.nullable ? "sin definir" : ""}
                  onChange={(e) => onChange(s.name, e.target.value === "" && s.nullable ? null : e.target.value)} />
              )}
              {s.allow_auto && s.type !== "choice" && (
                <button className="mini" onClick={(e) => { e.preventDefault(); onChange(s.name, "auto"); }}>auto</button>
              )}
            </div>
            <span className="field-meta">
              {SOURCE_LABEL[sources[s.name]] ?? "Por defecto"}
              {resolved !== undefined && String(resolved) !== String(v) && <> · resuelto: <b>{String(resolved)}</b></>}
              {s.min !== null && s.max !== null && <> · {s.min}–{s.max}</>}
            </span>
          </label>
        );
      })}
      <label className="adv"><input type="checkbox" checked={adv} onChange={(e) => setAdv(e.target.checked)} /> Mostrar parámetros avanzados</label>
    </div>
  );
}

// ============================================================================ asistente
export function ChatPanel({ project, onApplied }: { project: Project; onApplied: () => void }) {
  const [log, setLog] = useState<{ who: string; text: string; data?: Dict }[]>([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<Dict | null>(null);
  const [sample, setSample] = useSample();
  const [useLlm, setUseLlm] = useState(true);
  async function send(text: string, answers?: Dict, apply = false) {
    setBusy(true);
    if (text) setLog((l) => [...l, { who: "usuario", text }]);
    try {
      let llm: Dict | null = null, llmNote = "";
      if (text && sample && useLlm && api.assistantPrompt) {
        try {
          const out = await sample.json(await api.assistantPrompt(project.code, text), { modelTier: "quick" });
          if (out && typeof out === "object" && !Array.isArray(out)) llm = out as Dict;
        } catch (e) {
          const code = (e as { code?: string }).code;
          if (code === "not_granted") { setSample(null); llmNote = "\n\n(Claude no autorizado en esta vista: se usa sólo el intérprete de reglas.)"; }
          else llmNote = `\n\n(Claude no disponible ahora${code ? `: ${code}` : ""}; se usa el intérprete de reglas.)`;
        }
      }
      const r = await api.assistant(project.code, text, answers, apply, llm);
      setLast(r);
      setLog((l) => [...l, { who: "ia", text: r.reply + (r.applied ? "\n\n✔ Parámetros aplicados al proyecto." : "") + llmNote
        + (r.engine === "claude+reglas" ? "\n\nInterpretación: reglas deterministas + Claude (las reglas prevalecen; cada dato queda trazado)." : ""), data: r }]);
      if (r.applied) onApplied();
    } catch (e) { setLog((l) => [...l, { who: "ia", text: "Error: " + (e as Error).message }]); }
    setBusy(false);
    setMsg("");
  }
  return (
    <div className="chat">
      <div className="chat-log">
        {log.length === 0 && <div className="hint">Describa el producto que necesita. Ejemplo: «Quiero una mesa industrial de
          2.000 × 800 × 900 mm, con estructura tubular, encimera de chapa, una balda inferior y carga distribuida de 400 kg».</div>}
        {log.map((m, i) => (
          <div key={i} className={`bubble ${m.who}`}>
            <pre>{m.text}</pre>
            {m.data?.questions?.map((q: Dict) => q.options?.length ? (
              <div key={q.param} className="q-opts"><span>{q.param}:</span>
                {q.options.map((o: Dict) => <button key={String(o.value)} className="mini" disabled={busy}
                  onClick={() => send("", { [q.param]: o.value })}>{o.label}</button>)}
              </div>) : null)}
          </div>
        ))}
      </div>
      <div className="chat-input">
        <textarea id="mensaje" value={msg} rows={3} placeholder="Escriba su solicitud o respuesta…" onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && msg.trim()) { e.preventDefault(); send(msg); } }} />
        <div className="row">
          <button disabled={busy || !msg.trim()} onClick={() => send(msg)}>Enviar</button>
          <button className="primary" disabled={busy || !last?.ready_to_generate} onClick={() => send("", {}, true)}>
            Aplicar parámetros al diseño</button>
        </div>
        {sample && <label className="llm-toggle"><input id="usar-claude" type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          Completar la interpretación con Claude (usa su cuenta; las reglas prevalecen)</label>}
      </div>
    </div>
  );
}

// ============================================================================ árbol de componentes
export function TreePanel({ tree, hidden, setHidden, selected, onSelect }: {
  tree: Dict; hidden: Set<string>; setHidden: (s: Set<string>) => void; selected: string | null; onSelect: (id: string) => void;
}) {
  const leaves = (n: Dict): string[] => n.children ? n.children.flatMap(leaves) : [n.id];
  const toggle = (n: Dict) => {
    const ids = leaves(n);
    const s = new Set(hidden);
    const allHidden = ids.every((i) => s.has(i));
    ids.forEach((i) => (allHidden ? s.delete(i) : s.add(i)));
    setHidden(s);
  };
  const Node = ({ n, depth }: { n: Dict; depth: number }) => {
    const [open, setOpen] = useState(depth < 1);
    const ids = leaves(n);
    const vis = !ids.every((i) => hidden.has(i));
    return (
      <div className="tnode">
        <div className={`trow ${selected === n.id ? "sel" : ""}`} style={{ paddingLeft: depth * 12 }}>
          {n.children ? <span className="caret" onClick={() => setOpen(!open)}>{open ? "▾" : "▸"}</span> : <span className="caret" />}
          <input type="checkbox" checked={vis} onChange={() => toggle(n)} />
          <span className={`tname k-${n.type}`} onClick={() => !n.children && onSelect(n.id)}>{n.name}</span>
          {n.ref && <span className="tref">{n.ref.split("-").slice(-1)[0]}</span>}
        </div>
        {open && n.children?.map((c: Dict) => <Node key={c.id} n={c} depth={depth + 1} />)}
      </div>
    );
  };
  return <div className="tree"><Node n={tree} depth={0} /></div>;
}

export function PropsPanel({ id, design, viewer }: { id: string | null; design: Dict; viewer: Dict }) {
  if (!id) return <div className="hint">Doble clic sobre una pieza del visor o selección en el árbol.</div>;
  const inst = viewer.instances.find((i: Dict) => i.id === id);
  if (!inst) return null;
  const part = viewer.parts[inst.part];
  const row = design.bom.rows.find((r: Dict) => r.ref === inst.ref);
  const [lo, hi] = inst.bbox;
  const util = design.engineering.member_utilization?.[id];
  return (
    <table className="kv"><tbody>
      <tr><th>Identificador</th><td>{inst.id}</td></tr>
      <tr><th>Nombre</th><td>{inst.name}</td></tr>
      <tr><th>Referencia</th><td>{inst.ref} (pos. {row?.pos})</td></tr>
      <tr><th>Tipo</th><td>{row?.kind_label}</td></tr>
      <tr><th>Descripción</th><td>{part.name}</td></tr>
      <tr><th>Material</th><td>{row?.material}</td></tr>
      <tr><th>Masa (sólido)</th><td>{fmt(part.mass, 3)} kg</td></tr>
      {part.dims?.seccion && <tr><th>Sección</th><td>{part.dims.seccion}</td></tr>}
      {part.dims?.largo && <tr><th>Largo / ancho</th><td>{fmt(part.dims.largo)} / {fmt(part.dims.ancho)} mm</td></tr>}
      <tr><th>Envolvente</th><td>{fmt(hi[0] - lo[0])} × {fmt(hi[1] - lo[1])} × {fmt(hi[2] - lo[2])} mm</td></tr>
      <tr><th>Subconjunto</th><td>{inst.group}</td></tr>
      <tr><th>Operación</th><td>{inst.feature}</td></tr>
      <tr><th>Proceso</th><td>{row?.process}</td></tr>
      {util !== undefined && <tr><th>Aprovechamiento</th><td className={util > 1 ? "bad" : "good"}>{fmt(util, 3)}</td></tr>}
    </tbody></table>
  );
}

// ============================================================================ alertas y validación
const LV: Record<string, string> = { bloqueante: "bad", error: "bad", NO_CUMPLE: "bad", advertencia: "warn", ADVERTENCIA: "warn",
  pendiente: "pend", PENDIENTE: "pend", ok: "good", CUMPLE: "good", propuesta: "info", info: "info" };

export function AlertsPanel({ design }: { design: Dict }) {
  const q = design.qa;
  return (
    <div className="alerts">
      <div className="status-row">
        <span className={`chip ${design.status.geometry_complete ? "good" : "bad"}`}>
          {design.status.geometry_complete ? "Geometría completa y coherente" : "Errores bloqueantes"}</span>
        <span className={`chip ${LV[design.status.structural]}`}>{design.status.structural_label}</span>
        <span className="chip pend">Validación definitiva por técnico competente: pendiente</span>
      </div>
      <p className="muted">{q.summary}</p>
      <div className="scroll-x"><table className="grid"><thead><tr><th>Nivel</th><th>Código</th><th>Descripción</th></tr></thead><tbody>
        {[...design.design_notes.map((n: Dict) => ({ level: n.level, code: n.code, message: n.message })),
          ...q.items.filter((i: Dict) => i.level !== "ok"), ...q.items.filter((i: Dict) => i.level === "ok")].map((i: Dict, k: number) => (
          <tr key={k}><td><span className={`dot ${LV[i.level]}`} />{i.level}</td><td>{i.code}</td><td>{i.message}</td></tr>))}
      </tbody></table></div>
    </div>
  );
}

export function CalcPanel({ eng }: { eng: Dict }) {
  return (
    <div>
      <p><span className={`chip ${LV[eng.status]}`}>{eng.status_label}</span> <span className="muted">{eng.validation_note}</span></p>
      <p className="muted">Modelo de barras: {eng.fem.nodes} nodos · {eng.fem.elements} elementos · {eng.fem.dof} GDL.
        Combinaciones: {Object.keys(eng.combinations.ELU).concat(Object.keys(eng.combinations.ELS)).join(", ")}</p>
      {eng.pending.length > 0 && <ul className="pending">{eng.pending.map((p: string) => <li key={p}>PENDIENTE: {p}</li>)}</ul>}
      <div className="scroll-x"><table className="grid"><thead><tr><th>Comprobación</th><th>Referencia</th><th>Comb.</th><th>Valor</th><th>Límite</th><th>Aprov.</th><th>Estado</th></tr></thead>
        <tbody>{eng.checks.map((c: Dict) => (
          <tr key={c.id}><td>{c.description}</td><td className="muted">{c.standard}</td><td>{c.combination}</td>
            <td>{c.value === null ? "—" : `${fmt(c.value, 2)} ${c.unit}`}</td><td>{c.limit === null ? "—" : `${fmt(c.limit, 2)} ${c.unit}`}</td>
            <td><Bar u={c.utilization} /></td><td><span className={`dot ${LV[c.status]}`} />{c.status}</td></tr>))}
        </tbody></table></div>
      <h4>Hipótesis</h4><ul>{eng.hypotheses.map((h: string) => <li key={h}>{h}</li>)}</ul>
      <h4>Limitaciones</h4><ul>{eng.limitations.map((h: string) => <li key={h}>{h}</li>)}</ul>
    </div>
  );
}

function Bar({ u }: { u: number | null }) {
  if (u === null || u === undefined) return <span className="muted">—</span>;
  return <div className="ubar"><div style={{ width: `${Math.min(100, u * 100)}%` }} className={u > 1 ? "bad" : u > 0.85 ? "warn" : "good"} /><span>{fmt(u, 3)}</span></div>;
}

export function BomPanel({ bom }: { bom: Dict }) {
  const t = bom.totals;
  return (
    <div>
      <div className="scroll-x"><table className="grid"><thead><tr><th>Pos.</th><th>Referencia</th><th>Descripción</th><th>Material</th><th>Espesor</th><th>Largo</th>
        <th>Ancho</th><th>Cant.</th><th>Peso unit.</th><th>Peso total</th></tr></thead>
        <tbody>{bom.rows.map((r: Dict) => (
          <tr key={r.ref}><td>{r.pos}</td><td>{r.ref}</td><td>{r.description}</td><td>{r.material}</td><td>{fmt(r.thickness)}</td>
            <td>{fmt(r.length)}</td><td>{fmt(r.width)}</td><td>{r.qty}</td><td>{fmt(r.unit_mass, 3)}</td><td>{fmt(r.total_mass, 3)}</td></tr>))}
          <tr className="total"><td colSpan={7}>Totales: {t.components} componentes ({t.manufactured_parts} fabricados, {t.standard_parts} normalizados)</td>
            <td>{t.components}</td><td /><td>{fmt(t.total_mass, 2)} kg</td></tr>
        </tbody></table></div>
      <div className="cols">
        <div><h4>Metros de perfil</h4><ul>{Object.entries(t.profile_meters).map(([k, v]) => <li key={k}>{k}: {fmt(v as number, 3)} m</li>)}</ul></div>
        <div><h4>Superficie de chapa</h4><ul>{Object.entries(t.sheet_area_m2).map(([k, v]) => <li key={k}>{k}: {fmt(v as number, 4)} m²</li>)}</ul></div>
        <div><h4>Compras</h4><ul>{bom.purchases.map((p: Dict, i: number) => <li key={i}>{p.qty} {p.unit} · {p.description}</li>)}</ul></div>
        <div><h4>Consumibles</h4><ul>{bom.consumables.map((p: Dict, i: number) => <li key={i}>{fmt(p.qty, 3)} {p.unit} · {p.description}</li>)}</ul></div>
      </div>
    </div>
  );
}

export function FabPanel({ plan, dfm }: { plan: Dict; dfm: Dict[] }) {
  return (
    <div>
      <h4>Plan de corte de perfiles</h4>
      {plan.cutting.map((c: Dict) => (
        <div key={c.profile + c.material} className="cut">
          <div className="muted">{c.profile} {c.material} · {c.n_bars} barras de {c.bar_length} mm (cota inferior {c.lower_bound}{c.optimal ? ", óptimo" : ""})
            · aprovechamiento {(c.utilization * 100).toFixed(1)} % · sierra {c.kerf} mm</div>
          {c.bars.map((b: Dict) => (
            <svg key={b.bar} viewBox={`0 0 ${c.bar_length} 120`} className="barsvg" preserveAspectRatio="none">
              <rect x={0} y={10} width={c.bar_length} height={100} className="bar-bg" />
              {(() => { let x = c.trim; return b.cuts.map((ct: Dict, i: number) => {
                const el = <g key={i}><rect x={x} y={10} width={ct.length} height={100} className="bar-cut" />
                  <text x={x + ct.length / 2} y={75} className="bar-txt">{ct.ref.split("-").slice(-1)[0]} · {ct.length}</text></g>;
                x += ct.length + c.kerf; return el; }); })()}
            </svg>))}
        </div>))}
      <h4>Anidado de chapa</h4>
      <div className="nests">
        {plan.nesting.map((n: Dict) => n.feasible ? n.sheets.map((s: Dict) => (
          <figure key={n.material + n.thickness + s.sheet}>
            <svg viewBox={`0 0 ${n.length} ${n.width}`} className="nestsvg">
              <rect x={0} y={0} width={n.length} height={n.width} className="sheet" />
              {s.placements.map((p: Dict, i: number) => <g key={i}><rect x={p.x} y={n.width - p.y - p.h} width={p.w} height={p.h} className="part" />
                <text x={p.x + p.w / 2} y={n.width - p.y - p.h / 2} className="nest-txt">{p.ref.split("-").slice(-1)[0]}</text></g>)}
            </svg>
            <figcaption>{n.material} e={n.thickness} mm · {n.format} · hoja {s.sheet}/{n.n_sheets} · {(s.utilization * 100).toFixed(1)} %</figcaption>
          </figure>)) : <p key={n.material + n.thickness} className="bad">{n.material} {n.thickness}: {n.reason}</p>)}
      </div>
      <h4>Soldadura y pintura</h4>
      <p>{plan.welding.joints} uniones · {fmt(plan.welding.total_length_mm / 1000, 2)} m de cordón · hilo {fmt(plan.welding.wire_kg, 3)} kg ·
        gas {fmt(plan.welding.gas_l, 0)} l · pintura {fmt(plan.painting.area_m2, 2)} m² ({fmt(plan.painting.powder_kg, 2)} kg)</p>
      <h4>Diseño para fabricación</h4>
      <table className="grid"><tbody>{dfm.map((d, i) => <tr key={i}><td><span className={`dot ${LV[d.level]}`} />{d.level}</td><td>{d.code}</td>
        <td>{d.element}</td><td>{d.message} {d.proposal && <em>→ {d.proposal}</em>}</td></tr>)}</tbody></table>
    </div>
  );
}

export function FeaturesPanel({ design }: { design: Dict }) {
  const params = design.parameters.filter((p: Dict) => p.derived);
  return (
    <div>
      <h4>Árbol de operaciones</h4>
      <table className="grid"><thead><tr><th>Id</th><th>Operación</th><th>Instancias</th><th>Depende de</th></tr></thead><tbody>
        {design.feature_tree.map((f: Dict) => <tr key={f.id}><td>{f.id}</td><td style={{ paddingLeft: f.parent ? 18 : 4 }}>{f.label}</td>
          <td>{f.produces.length}</td><td className="muted small">{f.params.join(", ")}</td></tr>)}
      </tbody></table>
      <h4>Parámetros derivados (reglas constructivas)</h4>
      <table className="grid"><tbody>{params.map((p: Dict) => <tr key={p.name}><td>{p.name}</td><td>{p.label}</td>
        <td><b>{String(p.value)}</b> {p.unit}</td><td className="muted small">{(p.depends_on || []).join(", ")}</td></tr>)}</tbody></table>
    </div>
  );
}
