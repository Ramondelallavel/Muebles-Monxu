"""Persistencia (SQLite + SQLAlchemy): usuarios, proyectos, revisiones, cambios, documentos y plantillas.

Las revisiones congeladas son inmutables: sus parámetros no se modifican y su expediente no se
sobrescribe. Los cambios de parámetros sobre el trabajo en curso quedan registrados.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from ..docs.dependencies import affected_documents
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, selectinload, sessionmaker

STATUSES = ["en_configuracion", "en_diseno", "pendiente_validacion", "validado", "preparado_fabricacion", "fabricado",
            "archivado"]
STATUS_LABELS = {"en_configuracion": "En configuración", "en_diseno": "En diseño",
                 "pendiente_validacion": "Pendiente de validación", "validado": "Aprobado técnicamente",
                 "preparado_fabricacion": "Liberado para fabricación", "fabricado": "Fabricado", "archivado": "Archivado"}
#: versión del esquema de datos; las migraciones controladas se aplican al abrir la base de datos
SCHEMA_VERSION = 2


def now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(200), unique=True)
    role: Mapped[str] = mapped_column(String(40), default="disenador")   # disenador | tecnico_validador | admin


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    client: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    family: Mapped[str] = mapped_column(String(60))
    designer: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(40), default="en_configuracion")
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    updated: Mapped[dt.datetime] = mapped_column(DateTime, default=now, onupdate=now)
    working_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    working_sources: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assistant_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    revisions: Mapped[list["Revision"]] = relationship(back_populates="project", order_by="Revision.id")
    changes: Mapped[list["ChangeLog"]] = relationship(back_populates="project", order_by="ChangeLog.id")


class Revision(Base):
    __tablename__ = "revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    rev: Mapped[str] = mapped_column(String(8))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    sources: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    comment: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(120), default="")
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    product_code: Mapped[str] = mapped_column(String(60), default="")
    mass_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    structural_status: Mapped[str] = mapped_column(String(20), default="")
    qa_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dossier_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dossier_zip: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changes_from_previous: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # validaciones registradas por código de QA y firmas (fabricabilidad, cálculo, aprobación, liberación)
    approval: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dossier_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    project: Mapped[Project] = relationship(back_populates="revisions")
    documents: Mapped[list["Document"]] = relationship(back_populates="revision")


class ChangeLog(Base):
    __tablename__ = "change_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    author: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(40))        # parametros | revision | estado | expediente | asistente
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    project: Mapped[Project] = relationship(back_populates="changes")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("revisions.id"))
    path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(Integer)
    revision: Mapped[Revision] = relationship(back_populates="documents")


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    family: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    values: Mapped[dict[str, Any]] = mapped_column(JSON)
    builtin: Mapped[bool] = mapped_column(Boolean, default=True)


class Counter(Base):
    """Contadores persistentes: el número de proyecto no se reutiliza aunque se borren proyectos."""
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class Remnant(Base):
    """Inventario de retales reutilizables (barras y chapas): se ofrecen al plan de corte y al anidado de los proyectos
    y se consumen o se dan de alta al liberar una revisión para fabricación."""
    __tablename__ = "remnants"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))                 # barra | chapa
    profile: Mapped[str | None] = mapped_column(String(60), nullable=True)
    material: Mapped[str] = mapped_column(String(60))
    thickness: Mapped[float | None] = mapped_column(Float, nullable=True)
    length: Mapped[float] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="disponible")
    created: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    consumed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


def remnant_dict(r: "Remnant") -> dict[str, Any]:
    return {"id": r.id, "kind": r.kind, "profile": r.profile, "material": r.material, "thickness": r.thickness,
            "length": r.length, "width": r.width, "origin": r.origin, "status": r.status,
            "created": r.created.isoformat(), "consumed_by": r.consumed_by}


CODE_RX = re.compile(r"^P-(\d{4})-(\d{4,})$")


class CatalogItem(Base):
    __tablename__ = "catalog_items"
    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class Store:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root or os.environ.get("MONXU_DATA", "var"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.root / 'monxu.db'}", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False, future=True)
        self._migrate()
        self._seed()

    # ------------------------------------------------------------------ migraciones controladas
    def _migrate(self):
        """v2: columnas de aprobación en las revisiones y estados antiguos «validado» / «preparado para fabricación»
        reconvertidos: la validación anterior no cubría las comprobaciones nuevas (componentes, WPS, hipótesis de
        cálculo), así que se conserva como antecedente y el proyecto vuelve a «pendiente de validación»."""
        from sqlalchemy import text
        with self.engine.begin() as cx:
            cols = {r[1] for r in cx.execute(text("PRAGMA table_info(revisions)"))}
            if "approval" not in cols:
                cx.execute(text("ALTER TABLE revisions ADD COLUMN approval JSON DEFAULT '{}'"))
            if "dossier_state" not in cols:
                cx.execute(text("ALTER TABLE revisions ADD COLUMN dossier_state VARCHAR(40)"))
        with self.Session() as s:
            row = s.get(Counter, "schema_version")
            ver = row.value if row else 1
            if ver < 2:
                for p in s.scalars(select(Project)):
                    if p.status in ("validado", "preparado_fabricacion", "fabricado") and p.revisions:
                        last = p.revisions[-1]
                        ap = dict(last.approval or {})
                        ap["legacy"] = {"status": p.status, "validated_by": p.validated_by, "migrated": now().isoformat(),
                                        "note": "Validación anterior a la auditoría de 2026-11: no incluye las nuevas "
                                                "comprobaciones; debe repetirse con el flujo de aprobación."}
                        last.approval = ap
                        old = p.status
                        if p.status != "fabricado":
                            p.status = "pendiente_validacion"
                        s.add(ChangeLog(project_id=p.id, kind="migracion", author="sistema",
                                        detail={"schema": 2, "from": old, "to": p.status, "validated_by": p.validated_by}))
                if row:
                    row.value = SCHEMA_VERSION
                else:
                    s.add(Counter(name="schema_version", value=SCHEMA_VERSION))
                s.commit()

    @property
    def dossiers(self) -> Path:
        p = self.root / "expedientes"
        p.mkdir(exist_ok=True)
        return p

    def _seed(self):
        from ..families import REGISTRY
        from .. import catalog
        with self.Session() as s:
            for fam in REGISTRY.values():
                for t in fam.templates():
                    row = s.get(Template, t["id"])
                    if not row:
                        s.add(Template(id=t["id"], family=t["family"], name=t["name"], values=t["values"]))
                    elif row.builtin and (row.name, row.family, row.values) != (t["name"], t["family"], t["values"]):
                        # plantilla integrada modificada en el código: se actualiza (las del usuario no se tocan)
                        row.name, row.family, row.values = t["name"], t["family"], dict(t["values"])
            if not s.scalars(select(User)).first():
                s.add(User(name="Ingeniería", email="ingenieria@monxu.local", role="disenador"))
            for it in s.scalars(select(CatalogItem)):
                catalog.register_component(it.code, it.data)
            s.commit()

    # ------------------------------------------------------------------ proyectos
    def next_code(self, s: Session) -> str:
        """Siguiente código del año: mayor que cualquier código emitido (existente o borrado), nunca repetido."""
        year = now().year
        used = [int(m.group(2)) for c in s.scalars(select(Project.code).where(Project.code.like(f"P-{year}-%")))
                if (m := CODE_RX.match(c))]
        ctr = s.get(Counter, f"P-{year}") or Counter(name=f"P-{year}", value=0)
        n = max([ctr.value, *used]) + 1
        ctr.value = n
        s.merge(ctr)
        return f"P-{year}-{n:04d}"

    @staticmethod
    def _project(s: Session, code: str) -> Project:
        p = s.scalars(select(Project).where(Project.code == code)).first()
        if not p:
            raise KeyError(f"Proyecto no encontrado: {code}")
        return p

    def create_project(self, name: str, family: str, client: str = "", description: str = "", designer: str = "",
                       values: dict | None = None, sources: dict | None = None) -> Project:
        with self.Session() as s:
            p = Project(code=self.next_code(s), name=name, family=family, client=client, description=description,
                        designer=designer, working_params=values or {}, working_sources=sources or {})
            s.add(p)
            s.flush()
            s.add(ChangeLog(project_id=p.id, author=designer, kind="creacion", detail={"values": values or {}}))
            s.commit()
            return p

    def get(self, code: str) -> Project:
        with self.Session() as s:
            p = self._project(s, code)
            p.revisions, p.changes  # carga
            return p

    def delete_project(self, code: str) -> dict[str, Any]:
        """Borra el proyecto con sus revisiones, documentos, historial y carpeta de expedientes.

        El código no se reutiliza (contador persistente). Sólo se borra la carpeta ``expedientes/<código>``."""
        if not CODE_RX.match(code):
            raise KeyError(f"Proyecto no encontrado: {code}")
        with self.Session() as s:
            p = self._project(s, code)
            revs = list(p.revisions)
            info = {"code": p.code, "name": p.name, "status": p.status, "revisions": [r.rev for r in revs],
                    "dossiers": sum(1 for r in revs if r.dossier_path)}
            for r in revs:
                for doc in list(r.documents):
                    s.delete(doc)
                s.delete(r)
            for c in list(p.changes):
                s.delete(c)
            s.delete(p)
            s.commit()
        root = self.dossiers.resolve()
        folder = (root / code).resolve()
        info["files_removed"] = False
        if folder.parent == root and folder.name == code and folder.is_dir():
            shutil.rmtree(folder)
            info["files_removed"] = True
        return info

    def list_projects(self) -> list[Project]:
        with self.Session() as s:
            # las revisiones se cargan dentro de la sesión: la lista las necesita (antes: DetachedInstanceError → 500)
            return list(s.scalars(select(Project).options(selectinload(Project.revisions)).order_by(Project.id.desc())))

    def update_project(self, code: str, **fields) -> Project:
        with self.Session() as s:
            p = self._project(s, code)
            for k, v in fields.items():
                if k in ("name", "client", "description", "designer"):
                    setattr(p, k, v)
            s.commit()
            return p

    def set_params(self, code: str, values: dict, sources: dict | None = None, author: str = "",
                   replace: bool = False) -> dict[str, tuple]:
        with self.Session() as s:
            p = self._project(s, code)
            old = dict(p.working_params or {})
            new = dict(values) if replace else {**old, **values}
            changes = {k: (old.get(k), new.get(k)) for k in set(old) | set(new) if old.get(k) != new.get(k)}
            p.working_params = new
            p.working_sources = {**(p.working_sources or {}), **(sources or {k: "usuario" for k in values})}
            if p.status == "en_configuracion":
                p.status = "en_diseno"
            if changes:
                s.add(ChangeLog(project_id=p.id, author=author, kind="parametros",
                                detail={"changes": {k: list(v) for k, v in changes.items()}}))
            s.commit()
            return changes

    def change_family(self, code: str, family: str, values: dict | None = None, sources: dict | None = None,
                      author: str = "asistente") -> None:
        """Cambia la familia de un proyecto que todavía no tiene revisiones; conserva sólo ``values`` (los parámetros
        que mantienen su significado en la nueva familia)."""
        with self.Session() as s:
            p = self._project(s, code)
            if p.revisions:
                raise ValueError("El proyecto ya tiene revisiones: cree un proyecto nuevo para otra familia.")
            old = p.family
            p.family, p.working_params, p.working_sources = family, dict(values or {}), dict(sources or {})
            s.add(ChangeLog(project_id=p.id, author=author, kind="familia", detail={"from": old, "to": family}))
            s.commit()

    def set_assistant_state(self, code: str, state: dict):
        with self.Session() as s:
            p = self._project(s, code)
            p.assistant_state = json.loads(json.dumps(state, default=str))
            s.commit()

    def log(self, code: str, kind: str, detail: dict, author: str = ""):
        with self.Session() as s:
            p = self._project(s, code)
            s.add(ChangeLog(project_id=p.id, author=author, kind=kind, detail=json.loads(json.dumps(detail, default=str))))
            s.commit()

    # ------------------------------------------------------------------ revisiones
    def freeze_revision(self, code: str, comment: str, author: str, resolved: dict, sources: dict, product_code: str,
                        mass: float, structural: str, qa: dict, dependencies: dict | None = None,
                        stock: list | None = None) -> Revision:
        with self.Session() as s:
            p = self._project(s, code)
            prev = p.revisions[-1] if p.revisions else None
            letter = chr(ord(prev.rev) + 1) if prev else "A"
            diff = {k: [prev.params.get(k), v] for k, v in resolved.items() if prev and prev.params.get(k) != v} if prev else {}
            r = Revision(project_id=p.id, rev=letter, params=json.loads(json.dumps(resolved, default=str)),
                         sources=sources, comment=comment, author=author, product_code=product_code, mass_kg=mass,
                         structural_status=structural, qa_summary=qa, changes_from_previous=diff,
                         approval={"affected_documents": affected_documents(dependencies, diff) if dependencies and prev else
                                   [], "stock": stock or []})
            s.add(r)
            s.add(ChangeLog(project_id=p.id, author=author, kind="revision", detail={"rev": letter, "comment": comment,
                                                                                     "changes": diff}))
            s.commit()
            return r

    def revision(self, code: str, rev: str) -> Revision:
        with self.Session() as s:
            p = self._project(s, code)
            r = next((r for r in p.revisions if r.rev == rev), None)
            if not r:
                raise KeyError(f"Revisión {rev} no encontrada")
            r.documents
            return r

    def dossier_outdated(self, code: str, rev: str) -> bool:
        """El expediente se generó en un estado de aprobación anterior al actual (p. ej. antes de aprobar)."""
        from ..validation.approval import STATES
        r = self.revision(code, rev)
        if not r.dossier_path:
            return False
        ev = self._evaluate(r)
        return STATES.index(ev["state"]) > STATES.index(r.dossier_state or "diseno_generado") and \
            ev["state"] in ("aprobado_tecnicamente", "liberado_fabricacion")

    def attach_dossier(self, code: str, rev: str, result: dict) -> None:
        with self.Session() as s:
            p = self._project(s, code)
            r = next(r for r in p.revisions if r.rev == rev)
            if r.dossier_path and not result.get("edition"):
                raise ValueError("La revisión ya tiene expediente: no se sobrescribe")
            if r.dossier_path:            # nueva edición tras la aprobación: la anterior se conserva
                ap = json.loads(json.dumps(r.approval or {}))
                ap.setdefault("editions", []).append({"path": r.dossier_path, "zip": r.dossier_zip,
                                                      "state": r.dossier_state, "replaced": now().isoformat()})
                r.approval = ap
                for d in list(r.documents):
                    s.delete(d)
            r.dossier_path, r.dossier_zip = result["path"], result["zip"]
            r.dossier_state = result.get("approval_state")
            r.qa_summary = result["qa"]
            for f in result["files"]:
                s.add(Document(revision_id=r.id, path=f["path"], sha256=f["sha256"], bytes=f["bytes"]))
            s.add(ChangeLog(project_id=p.id, kind="expediente", detail={"rev": rev, "name": result["name"],
                                                                        "files": len(result["files"])}))
            if p.status in ("en_configuracion", "en_diseno"):
                p.status = "pendiente_validacion"
            s.commit()

    def history(self, code: str) -> list[dict]:
        p = self.get(code)
        return [{"revision": r.rev, "date": r.created.strftime("%Y-%m-%d"), "author": r.author, "comment": r.comment,
                 "changes": r.changes_from_previous} for r in p.revisions]

    # ------------------------------------------------------------------ aprobación
    @staticmethod
    def _evaluate(r: Revision) -> dict[str, Any]:
        from ..validation import approval as A
        dossier = {"qa": r.qa_summary, "state": r.dossier_state} if r.dossier_path else None
        return A.evaluate(r.qa_summary, r.structural_status, dossier, r.approval)

    def approval(self, code: str, rev: str | None = None) -> dict[str, Any]:
        p = self.get(code)
        r = next((x for x in p.revisions if x.rev == rev), None) if rev else (p.revisions[-1] if p.revisions else None)
        if not r:
            return {"state": None, "label": "Sin revisión", "gates": [], "open_validations": [], "release_blockers": [],
                    "records": {}}
        return {**self._evaluate(r), "revision": r.rev, "records": r.approval or {}}

    def record_validation(self, code: str, rev: str, item: str, by: str, reference: str, comment: str = "") -> dict:
        """Registra la validación de una comprobación PENDIENTE de la revisión (con su documento de referencia)."""
        if not by.strip() or not reference.strip():
            raise ValueError("La validación requiere el técnico y la referencia del documento que la justifica.")
        with self.Session() as s:
            p = self._project(s, code)
            r = next(x for x in p.revisions if x.rev == rev)
            pend = {i["code"] for i in (r.qa_summary or {}).get("items", []) if i["level"] == "pendiente"}
            if item not in pend:
                raise ValueError(f"{item} no es una validación pendiente de la revisión {rev}.")
            ap = json.loads(json.dumps(r.approval or {}))
            ap.setdefault("validations", {})[item] = {"by": by.strip(), "reference": reference.strip(),
                                                       "comment": comment, "date": now().strftime("%Y-%m-%d")}
            r.approval = ap
            s.add(ChangeLog(project_id=p.id, author=by, kind="validacion", detail={"rev": rev, "code": item,
                                                                                   "reference": reference}))
            s.commit()
        return self.approval(code, rev)

    def signoff(self, code: str, rev: str, stage: str, by: str, comment: str = "") -> dict:
        """Firma de una etapa (fabricabilidad, cálculo, aprobación, liberación) si se cumplen las anteriores."""
        from ..validation import approval as A
        if stage not in A.SIGNOFFS:
            raise ValueError(f"Etapa de firma no válida: {stage}")
        if not by.strip():
            raise ValueError("La firma requiere el nombre del técnico.")
        with self.Session() as s:
            p = self._project(s, code)
            r = next(x for x in p.revisions if x.rev == rev)
            ok, why = A.can_sign(self._evaluate(r), stage)
            if not ok:
                raise ValueError(f"No puede firmarse «{A.LABELS[A.SIGNOFFS[stage]]}»: {why}")
            ap = json.loads(json.dumps(r.approval or {}))
            ap.setdefault("signoffs", {})[stage] = {"by": by.strip(), "comment": comment, "date": now().strftime("%Y-%m-%d")}
            r.approval = ap
            ev = self._evaluate(r)
            old = p.status
            if stage == "aprobacion" and ev["state"] in ("aprobado_tecnicamente", "liberado_fabricacion"):
                p.status, p.validated_by = "validado", by.strip()
            if stage == "liberacion" and ev["state"] == "liberado_fabricacion":
                p.status = "preparado_fabricacion"
            s.add(ChangeLog(project_id=p.id, author=by, kind="firma", detail={"rev": rev, "stage": stage, "from": old,
                                                                              "to": p.status, "state": ev["state"]}))
            s.commit()
        return self.approval(code, rev)

    # ------------------------------------------------------------------ inventario de retales
    def remnants(self, status: str | None = "disponible") -> list[dict[str, Any]]:
        with self.Session() as s:
            q = select(Remnant).order_by(Remnant.created)
            if status:
                q = q.where(Remnant.status == status)
            return [remnant_dict(r) for r in s.scalars(q)]

    def add_remnant(self, kind: str, material: str, length: float, profile: str | None = None,
                    thickness: float | None = None, width: float | None = None, origin: str = "manual") -> dict:
        if kind not in ("barra", "chapa") or length <= 0 or (kind == "chapa" and not (width and thickness)) or \
                (kind == "barra" and not profile):
            raise ValueError("Retal no válido: barra con perfil y longitud, o chapa con espesor, largo y ancho.")
        with self.Session() as s:
            n = (s.get(Counter, "retal").value if s.get(Counter, "retal") else 0) + 1
            row = s.get(Counter, "retal")
            if row:
                row.value = n
            else:
                s.add(Counter(name="retal", value=n))
            r = Remnant(id=f"R-{n:05d}", kind=kind, profile=profile, material=material, thickness=thickness,
                        length=float(length), width=width, origin=origin)
            s.add(r)
            s.commit()
            return remnant_dict(r)

    def release_inventory(self, code: str, rev: str, used: list[str], produced: list[dict[str, Any]]) -> dict:
        """Al liberar para fabricación: consume los retales que usa el plan y da de alta los reutilizables nuevos."""
        with self.Session() as s:
            missing = [i for i in used if not s.get(Remnant, i) or s.get(Remnant, i).status != "disponible"]
            if missing:
                raise ValueError(f"Retales del plan ya no disponibles: {', '.join(missing)}. Regenere la revisión.")
            for i in used:
                r = s.get(Remnant, i)
                r.status, r.consumed_by = "consumido", f"{code} Rev.{rev}"
            s.commit()
        new = [self.add_remnant(p["kind"], p["material"], p["length"], p.get("profile"), p.get("thickness"),
                                p.get("width"), origin=f"{code} Rev.{rev}") for p in produced]
        self.log(code, "inventario", {"rev": rev, "consumidos": used, "nuevos": [r["id"] for r in new]})
        return {"consumed": used, "added": new}

    # ------------------------------------------------------------------ estados
    def set_status(self, code: str, status: str, user: str, validated_by: str | None = None) -> Project:
        """Estados del ciclo de vida. «Aprobado técnicamente» y «Liberado para fabricación» solo se alcanzan con las
        firmas del flujo de aprobación; aquí se comprueba que la revisión los tiene."""
        if status not in STATUSES:
            raise ValueError(f"Estado no válido: {status}")
        with self.Session() as s:
            p = self._project(s, code)
            last = p.revisions[-1] if p.revisions else None
            if status in ("validado", "preparado_fabricacion", "fabricado"):
                if not last or not last.dossier_path:
                    raise ValueError("Se requiere una revisión con expediente generado.")
                ev = self._evaluate(last)
                need = "aprobado_tecnicamente" if status == "validado" else "liberado_fabricacion"
                from ..validation.approval import LABELS, STATES
                if STATES.index(ev["state"]) < STATES.index(need):
                    g = next((g for g in ev["gates"] if not g["ok"]), None)
                    raise ValueError(f"La revisión {last.rev} está en «{ev['label']}»: se requiere «{LABELS[need]}»"
                                     + (f" ({g['label']}: {'; '.join(g['reasons'])})" if g else "") + ".")
            if status == "validado" and validated_by:
                p.validated_by = validated_by
            old = p.status
            p.status = status
            s.add(ChangeLog(project_id=p.id, author=user, kind="estado",
                            detail={"from": old, "to": status, "validated_by": validated_by}))
            s.commit()
            return p

    # ------------------------------------------------------------------ plantillas y catálogo
    def templates(self) -> list[Template]:
        with self.Session() as s:
            return list(s.scalars(select(Template)))

    def template(self, tid: str) -> Template:
        with self.Session() as s:
            t = s.get(Template, tid)
            if not t:
                raise KeyError(f"Plantilla no encontrada: {tid}")
            return t

    def save_template(self, tid: str, family: str, name: str, values: dict) -> Template:
        with self.Session() as s:
            t = Template(id=tid, family=family, name=name, values=values, builtin=False)
            s.merge(t)
            s.commit()
            return t

    def add_component(self, code: str, data: dict):
        from .. import catalog
        catalog.register_component(code, data)
        with self.Session() as s:
            s.merge(CatalogItem(code=code, data=data))
            s.commit()
