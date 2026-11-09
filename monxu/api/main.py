"""API REST de la plataforma (FastAPI). Sirve también la interfaz compilada (``frontend/dist``)."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import catalog
from ..ai import assistant
from ..ai import interpreter as I
from ..cad.export import viewer_payload
from ..core.params import ParamError
from ..families import REGISTRY, family, library
from ..pipeline import Design, DossierError, generate_dossier, regenerate
from ..storage.db import STATUS_LABELS, STATUSES, Store

app = FastAPI(title="Monxu — Plataforma de ingeniería de mobiliario industrial", version="0.1.0")
STORE: Store | None = None
CAD = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cad")
DOSSIER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="expediente")
_cache: "OrderedDict[str, tuple[Design, dict | None]]" = OrderedDict()
_cache_lock = threading.Lock()
JOBS: dict[str, dict[str, Any]] = {}


@app.exception_handler(KeyError)
async def _not_found(request: Request, exc: KeyError):
    """Proyecto, revisión, plantilla o familia inexistente: 404 con el motivo (no un error 500)."""
    msg = exc.args[0] if exc.args else "No encontrado"
    return JSONResponse(status_code=404, content={"detail": str(msg)})


_store_lock = threading.Lock()


def store() -> Store:
    """Almacén único, creado una sola vez aunque lleguen varias peticiones a la vez (antes, dos peticiones
    simultáneas con la base de datos vacía creaban las tablas dos veces: «table already exists», error 500)."""
    global STORE
    if STORE is None:
        with _store_lock:
            if STORE is None:
                STORE = Store()
    return STORE


def set_store(s: Store) -> None:
    global STORE
    STORE = s
    _cache.clear()


def _jsonable(o):
    return json.loads(json.dumps(o, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x)))


def _key(fam, values, sources):
    return json.dumps([fam, values, sources], sort_keys=True, default=str)


def design_for(fam: str, values: dict, sources: dict | None = None, viewer: bool = False) -> tuple[Design, dict | None]:
    k = _key(fam, values, sources or {})
    with _cache_lock:
        cached = _cache.get(k)
        if cached:
            _cache.move_to_end(k)
            if cached[1] is not None or not viewer:
                return cached
    d = cached[0] if cached else regenerate(fam, values, sources)
    v = viewer_payload(d.model) if viewer else (cached[1] if cached else None)
    with _cache_lock:
        _cache[k] = (d, v)
        while len(_cache) > 6:
            _cache.popitem(last=False)
    return d, v


async def in_cad(fn, *a):
    return await asyncio.get_running_loop().run_in_executor(CAD, fn, *a)


def project_dict(p) -> dict:
    return {"code": p.code, "name": p.name, "client": p.client, "description": p.description, "family": p.family,
            "designer": p.designer, "status": p.status, "status_label": STATUS_LABELS[p.status],
            "created": p.created.isoformat(), "updated": p.updated.isoformat(), "validated_by": p.validated_by,
            "working_params": p.working_params, "working_sources": p.working_sources,
            "revisions": [{"rev": r.rev, "created": r.created.isoformat(), "comment": r.comment, "author": r.author,
                           "product_code": r.product_code, "mass_kg": r.mass_kg, "structural": r.structural_status,
                           "qa": {k: (r.qa_summary or {}).get(k) for k in ("result", "summary", "blocking")},
                           "dossier": bool(r.dossier_path), "changes": r.changes_from_previous} for r in p.revisions]}


# ============================================================================ esquemas de petición
class ProjectIn(BaseModel):
    name: str
    family: str = "mesa_industrial"
    client: str = ""
    description: str = ""
    designer: str = ""
    template_id: str | None = None
    values: dict[str, Any] | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    client: str | None = None
    description: str | None = None
    designer: str | None = None


class ParamsIn(BaseModel):
    values: dict[str, Any]
    source: str = "usuario"
    sources: dict[str, str] | None = None
    author: str = ""
    replace: bool = False


class AssistantIn(BaseModel):
    message: str = ""
    answers: dict[str, Any] | None = None
    apply: bool = False


class RevisionIn(BaseModel):
    comment: str = ""
    author: str = ""


class StatusIn(BaseModel):
    status: str
    user: str = ""
    validated_by: str | None = None


class ComponentIn(BaseModel):
    code: str
    data: dict[str, Any]


class TemplateIn(BaseModel):
    id: str
    name: str


# ============================================================================ catálogo y familias
@app.get("/api/health")
def health():
    return {"ok": True, "families": list(REGISTRY), "catalog_versions": catalog.catalog_versions()}


@app.get("/api/library")
def get_library():
    return {"families": library(), "templates": [{"id": t.id, "family": t.family, "name": t.name, "values": t.values,
                                                   "builtin": t.builtin} for t in store().templates()]}


@app.get("/api/families/{fid}")
def get_family(fid: str):
    try:
        return family(fid).describe()
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/catalog")
def get_catalog():
    return _jsonable({
        "materials": {c: m.__dict__ for c, m in catalog.materials().items()},
        "finishes": catalog.finishes(),
        "profiles": {c: {**p.__dict__, "A": p.props.A, "mass_kg_m_steel": p.mass_per_m(7850)}
                     for c, p in catalog.profiles().items()},
        "sheets": catalog.sheet_data(), "components": catalog.components(),
        "standards": catalog.standards(), "standards_meta": catalog.standards_meta(), "criteria": catalog.criteria(),
        "versions": catalog.catalog_versions()})


@app.post("/api/catalog/components")
def add_component(c: ComponentIn):
    try:
        store().add_component(c.code, c.data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "code": c.code}


# ============================================================================ proyectos
@app.get("/api/projects")
def list_projects():
    return [project_dict(p) for p in store().list_projects()]


@app.post("/api/projects")
def create_project(pin: ProjectIn):
    try:
        family(pin.family)
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))
    values, sources = dict(pin.values or {}), {}
    if pin.template_id:
        t = store().template(pin.template_id)
        values = {**t.values, **values}
        sources = {k: "plantilla" for k in t.values}
    sources.update({k: "usuario" for k in (pin.values or {})})
    p = store().create_project(pin.name, pin.family, pin.client, pin.description, pin.designer, values, sources)
    return project_dict(store().get(p.code))


@app.get("/api/projects/{code}")
def get_project(code: str):
    try:
        p = store().get(code)
    except KeyError as e:
        raise HTTPException(404, str(e))
    d = project_dict(p)
    d["assistant_state"] = p.assistant_state
    d["changes"] = [{"timestamp": c.timestamp.isoformat(), "kind": c.kind, "author": c.author, "detail": c.detail}
                    for c in p.changes]
    return d


@app.delete("/api/projects/{code}")
def delete_project(code: str):
    """Borra el proyecto, sus revisiones, su historial y sus expedientes (irreversible)."""
    if any(j.get("project") == code and j.get("status") == "running" for j in JOBS.values()):
        raise HTTPException(409, "Se está generando un expediente de este proyecto: espere a que termine para borrarlo.")
    return store().delete_project(code)


@app.patch("/api/projects/{code}")
def patch_project(code: str, body: ProjectPatch):
    store().update_project(code, **{k: v for k, v in body.model_dump().items() if v is not None})
    return project_dict(store().get(code))


@app.put("/api/projects/{code}/params")
def put_params(code: str, body: ParamsIn):
    p = store().get(code)
    fam = family(p.family)
    trial = fam.new_params()
    try:
        trial.update({**(p.working_params if not body.replace else {}), **body.values})
    except ParamError as e:
        raise HTTPException(422, str(e))
    sources = body.sources or {k: body.source for k in body.values}
    changes = store().set_params(code, body.values, sources, body.author, body.replace)
    return {"changes": changes, "project": project_dict(store().get(code))}


@app.post("/api/projects/{code}/design")
async def post_design(code: str, viewer: bool = True):
    p = store().get(code)
    try:
        d, v = await in_cad(design_for, p.family, p.working_params, p.working_sources, viewer)
    except ValueError as e:          # incluye ParamError: datos incompatibles con las reglas constructivas
        raise HTTPException(422, str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"La regeneración ha fallado: {e}")
    return JSONResponse(_jsonable({"design": d.summary(), "viewer": v}))


@app.post("/api/preview")
async def preview(body: dict):
    """Regeneración sin proyecto (configurador rápido)."""
    fam = body.get("family", "mesa_industrial")
    try:
        d, v = await in_cad(design_for, fam, body.get("values", {}), body.get("sources") or {}, True)
    except ParamError as e:
        raise HTTPException(422, str(e))
    return JSONResponse(_jsonable({"design": d.summary(), "viewer": v}))


CHAT_MAX = 40          # mensajes de la conversación que se guardan con el proyecto


def _chat_entry(r: dict) -> dict:
    """Mensaje del asistente tal como se guarda: texto y botones de opción (sin el resto de la respuesta)."""
    return {"who": "ia", "text": r["reply"],
            "questions": [{"param": q["param"], "label": q.get("label", q["param"]), "options": q["options"]}
                          for q in r["questions"] if q.get("options")]}


@app.post("/api/projects/{code}/assistant")
def post_assistant(code: str, body: AssistantIn):
    """Interpreta el mensaje, adopta lo no indicado y, con ``apply``, aplica al proyecto lo que cambia en este turno.
    La conversación se guarda con el proyecto (``assistant_state.chat``)."""
    p = store().get(code)
    st = p.assistant_state or assistant.new_state(p.family)
    st.setdefault("family", p.family)
    chat = list(st.get("chat") or [])
    r = assistant.handle(st, body.message, body.answers, current={"values": p.working_params,
                                                                  "sources": p.working_sources})
    switched = None
    want = (r.get("interpretation") or {}).get("family")
    if want and want != p.family:
        if not p.revisions and want in REGISTRY:
            # proyecto todavía sin revisiones: se cambia de familia y se interpreta de nuevo con la nueva
            keep, keep_src = I.carry_params(p.family, want, p.working_params or {}, p.working_sources or {},
                                            family(want).param_specs())
            store().change_family(code, want, keep, keep_src)
            switched = {"from": p.family, "to": want}
            r = assistant.handle(assistant.new_state(want), body.message, body.answers,
                                 current={"values": keep, "sources": keep_src})
            r["reply"] = (f"He cambiado el proyecto a «{I.LABELS.get(want, want)}» (todavía no tenía revisiones).\n"
                          + r["reply"])
            p = store().get(code)
        else:
            r["reply"] += (f"\nAtención: la solicitud corresponde a «{I.LABELS.get(want, want)}», pero el proyecto ya "
                           f"tiene revisiones de la familia «{I.LABELS.get(p.family, p.family)}». Cree un proyecto nuevo "
                           "para esa familia.")
            r["ready_to_generate"] = False
    applied = None
    if body.apply and r["ready_to_generate"]:
        try:
            trial = family(p.family).new_params()
            trial.update({**(p.working_params or {}), **r["to_apply"]})
            applied = store().set_params(code, r["to_apply"], {k: r["sources"][k] for k in r["to_apply"]}, "asistente")
            r["reply"] += "\n✔ Datos aplicados al proyecto: se genera y verifica el diseño."
        except ParamError as e:
            r["reply"] += f"\nNo se han podido aplicar los datos: {e}"
    if body.message or body.answers:
        labels = {sp.name: sp.label for sp in family(p.family).param_specs()}
        txt = body.message or " · ".join(f"{labels.get(k, k)}: {v}" for k, v in (body.answers or {}).items())
        chat.append({"who": "usuario", "text": txt})
    chat.append(_chat_entry(r))
    r["state"]["chat"] = chat[-CHAT_MAX:]
    store().set_assistant_state(code, r["state"])
    store().log(code, "asistente", {"message": body.message, "answers": body.answers or {},
                                    "parameters": r["to_apply"]})
    return _jsonable({**{k: v for k, v in r.items() if k != "state"}, "applied": applied, "switched": switched,
                      "chat": r["state"]["chat"]})


# ============================================================================ revisiones y expediente
@app.post("/api/projects/{code}/revisions")
async def post_revision(code: str, body: RevisionIn):
    p = store().get(code)
    d, _ = await in_cad(design_for, p.family, p.working_params, p.working_sources, False)
    q = d.qa.result()
    if q["blocking"]:
        raise HTTPException(409, {"message": "El diseño tiene errores bloqueantes: no puede emitirse revisión.", "qa": q})
    m = d.model
    r = store().freeze_revision(code, body.comment, body.author, dict(m.params.values), dict(m.params.sources),
                                m.product_code, d.bom["totals"]["total_mass"], d.eng["status"], q)
    return {"rev": r.rev, "project": project_dict(store().get(code))}


def _run_dossier(job_id: str, code: str, rev: str):
    job = JOBS[job_id]
    try:
        p = store().get(code)
        r = store().revision(code, rev)
        job["stage"] = "regenerando modelo"
        d, _ = design_for(p.family, r.params, r.sources, False)
        job["stage"] = "generando archivos"
        proj = {"code": p.code, "revision": rev, "designer": p.designer or r.author, "client": p.client,
                "validated_by": p.validated_by, "date": r.created.strftime("%Y-%m-%d")}
        res = generate_dossier(d, proj, store().dossiers / p.code, store().history(code))
        store().attach_dossier(code, rev, res)
        job.update(status="ok", result=_jsonable({k: v for k, v in res.items() if k != "files"} |
                                                 {"files": [f["path"] for f in res["files"]]}))
    except DossierError as e:
        job.update(status="error", error=str(e), qa=_jsonable(e.qa))
    except Exception as e:
        traceback.print_exc()
        job.update(status="error", error=f"{type(e).__name__}: {e}")
    job["finished"] = time.time()


@app.post("/api/projects/{code}/revisions/{rev}/dossier")
def post_dossier(code: str, rev: str):
    r = store().revision(code, rev)
    if r.dossier_path:
        raise HTTPException(409, "La revisión ya tiene expediente generado (no se sobrescribe).")
    jid = uuid.uuid4().hex[:10]
    JOBS[jid] = {"id": jid, "status": "running", "stage": "en cola", "project": code, "rev": rev, "started": time.time()}
    DOSSIER.submit(_run_dossier, jid, code, rev)
    return JOBS[jid]


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "Trabajo no encontrado")
    return JOBS[jid]


@app.get("/api/projects/{code}/revisions/{rev}/files")
def list_files(code: str, rev: str):
    r = store().revision(code, rev)
    return {"dossier": r.dossier_path, "zip": r.dossier_zip,
            "files": [{"path": d.path, "bytes": d.bytes, "sha256": d.sha256} for d in r.documents]}


@app.get("/api/projects/{code}/revisions/{rev}/files/{path:path}")
def get_file(code: str, rev: str, path: str):
    r = store().revision(code, rev)
    if not r.dossier_path:
        raise HTTPException(404, "Sin expediente")
    if path == "expediente.zip":
        return FileResponse(r.dossier_zip, filename=Path(r.dossier_zip).name)
    base = Path(r.dossier_path).resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(f, filename=f.name)


@app.post("/api/projects/{code}/status")
def post_status(code: str, body: StatusIn):
    try:
        p = store().set_status(code, body.status, body.user, body.validated_by)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return project_dict(store().get(p.code))


@app.post("/api/projects/{code}/template")
def save_template(code: str, body: TemplateIn):
    p = store().get(code)
    store().save_template(body.id, p.family, body.name, p.working_params)
    return {"ok": True}


@app.get("/api/statuses")
def statuses():
    return [{"id": s, "label": STATUS_LABELS[s]} for s in STATUSES]


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
