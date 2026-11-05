"""Persistencia (SQLite + SQLAlchemy): usuarios, proyectos, revisiones, cambios, documentos y plantillas.

Las revisiones congeladas son inmutables: sus parámetros no se modifican y su expediente no se
sobrescribe. Los cambios de parámetros sobre el trabajo en curso quedan registrados.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

STATUSES = ["en_configuracion", "en_diseno", "pendiente_validacion", "validado", "preparado_fabricacion", "fabricado",
            "archivado"]
STATUS_LABELS = {"en_configuracion": "En configuración", "en_diseno": "En diseño",
                 "pendiente_validacion": "Pendiente de validación", "validado": "Validado",
                 "preparado_fabricacion": "Preparado para fabricación", "fabricado": "Fabricado", "archivado": "Archivado"}


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
        self._seed()

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
                    if not s.get(Template, t["id"]):
                        s.add(Template(id=t["id"], family=t["family"], name=t["name"], values=t["values"]))
            if not s.scalars(select(User)).first():
                s.add(User(name="Ingeniería", email="ingenieria@monxu.local", role="disenador"))
            for it in s.scalars(select(CatalogItem)):
                catalog.register_component(it.code, it.data)
            s.commit()

    # ------------------------------------------------------------------ proyectos
    def next_code(self, s: Session) -> str:
        year = now().year
        n = len(s.scalars(select(Project).where(Project.code.like(f"P-{year}-%"))).all()) + 1
        return f"P-{year}-{n:04d}"

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
            p = s.scalars(select(Project).where(Project.code == code)).first()
            if not p:
                raise KeyError(f"Proyecto no encontrado: {code}")
            p.revisions, p.changes  # carga
            return p

    def list_projects(self) -> list[Project]:
        with self.Session() as s:
            return list(s.scalars(select(Project).order_by(Project.id.desc())))

    def update_project(self, code: str, **fields) -> Project:
        with self.Session() as s:
            p = s.scalars(select(Project).where(Project.code == code)).one()
            for k, v in fields.items():
                if k in ("name", "client", "description", "designer"):
                    setattr(p, k, v)
            s.commit()
            return p

    def set_params(self, code: str, values: dict, sources: dict | None = None, author: str = "",
                   replace: bool = False) -> dict[str, tuple]:
        with self.Session() as s:
            p = s.scalars(select(Project).where(Project.code == code)).one()
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

    def set_assistant_state(self, code: str, state: dict):
        with self.Session() as s:
            p = s.scalars(select(Project).where(Project.code == code)).one()
            p.assistant_state = json.loads(json.dumps(state, default=str))
            s.commit()

    def log(self, code: str, kind: str, detail: dict, author: str = ""):
        with self.Session() as s:
            p = s.scalars(select(Project).where(Project.code == code)).one()
            s.add(ChangeLog(project_id=p.id, author=author, kind=kind, detail=json.loads(json.dumps(detail, default=str))))
            s.commit()

    # ------------------------------------------------------------------ revisiones
    def freeze_revision(self, code: str, comment: str, author: str, resolved: dict, sources: dict, product_code: str,
                        mass: float, structural: str, qa: dict) -> Revision:
        with self.Session() as s:
            p = s.scalars(select(Project).where(Project.code == code)).one()
            prev = p.revisions[-1] if p.revisions else None
            letter = chr(ord(prev.rev) + 1) if prev else "A"
            diff = {k: [prev.params.get(k), v] for k, v in resolved.items() if prev and prev.params.get(k) != v} if prev else {}
            r = Revision(project_id=p.id, rev=letter, params=json.loads(json.dumps(resolved, default=str)),
                         sources=sources, comment=comment, author=author, product_code=product_code, mass_kg=mass,
                         structural_status=structural, qa_summary=qa, changes_from_previous=diff)
            s.add(r)
            s.add(ChangeLog(project_id=p.id, author=author, kind="revision", detail={"rev": letter, "comment": comment,
                                                                                     "changes": diff}))
            s.commit()
            return r

    def revision(self, code: str, rev: str) -> Revision:
        with self.Session() as s:
            p = s.scalars(select(Project).where(Project.code == code)).one()
            r = next((r for r in p.revisions if r.rev == rev), None)
            if not r:
                raise KeyError(f"Revisión {rev} no encontrada")
            r.documents
            return r

    def attach_dossier(self, code: str, rev: str, result: dict) -> None:
        with self.Session() as s:
            p = s.scalars(select(Project).where(Project.code == code)).one()
            r = next(r for r in p.revisions if r.rev == rev)
            if r.dossier_path:
                raise ValueError("La revisión ya tiene expediente: no se sobrescribe")
            r.dossier_path, r.dossier_zip = result["path"], result["zip"]
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

    # ------------------------------------------------------------------ estados
    def set_status(self, code: str, status: str, user: str, validated_by: str | None = None) -> Project:
        if status not in STATUSES:
            raise ValueError(f"Estado no válido: {status}")
        with self.Session() as s:
            p = s.scalars(select(Project).where(Project.code == code)).one()
            last = p.revisions[-1] if p.revisions else None
            if status in ("validado", "preparado_fabricacion", "fabricado"):
                if not last or not last.dossier_path:
                    raise ValueError("Se requiere una revisión con expediente generado.")
                if last.structural_status != "CUMPLE":
                    raise ValueError("La verificación estructural de la revisión no es CUMPLE: no puede validarse.")
                if (last.qa_summary or {}).get("blocking"):
                    raise ValueError("La revisión tiene errores bloqueantes de control de calidad.")
            if status == "validado":
                if not validated_by:
                    raise ValueError("La validación requiere el nombre del técnico competente.")
                p.validated_by = validated_by
            if status in ("preparado_fabricacion", "fabricado") and not p.validated_by:
                raise ValueError("El proyecto debe estar validado por un técnico competente.")
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
                raise KeyError(tid)
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
