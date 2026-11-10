"""Modelo de producto: definiciones de pieza, instancias, subconjuntos y uniones.

Una :class:`PartDef` describe una pieza fabricable o comercial (geometría en coordenadas
locales generada por el motor CAD). Una :class:`Instance` coloca una pieza en el conjunto con
una matriz homogénea. Las piezas idénticas comparten definición (misma referencia y cantidad en
el BOM). Cada instancia y cada definición tienen identificador único.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

import cadquery as cq
import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..cad.sheetmetal import SheetMetalSpec
from .params import ParamContext, ParameterSet

KIND_ORDER = {"perfil": 0, "chapa": 1, "pletina": 2, "normalizado": 3}
KIND_LABEL = {"perfil": "Perfil comercial", "chapa": "Pieza de chapa", "pletina": "Pletina cortada",
              "normalizado": "Elemento normalizado"}


def _h(*items: Any) -> str:
    return hashlib.sha1(repr(items).encode()).hexdigest()[:12]


class PartDef:
    kind: str = ""

    def __init__(self, role: str, name: str, material: str | None, finish: str | None):
        self.role = role
        self.name = name
        self.material = material
        self.finish = finish
        self.ref = ""          # referencia asignada al numerar el BOM
        self.pos = 0
        self._shape: cq.Shape | None = None

    # -- geometría
    def build_shape(self) -> cq.Shape:
        raise NotImplementedError

    @property
    def shape(self) -> cq.Shape:
        if self._shape is None:
            self._shape = self.build_shape()
        return self._shape

    @property
    def key(self) -> str:
        raise NotImplementedError

    @cached_property
    def volume(self) -> float:
        return G.volume(self.shape)

    @cached_property
    def local_centroid(self) -> np.ndarray:
        """Centro de gravedad en ejes de la pieza (una vez por pieza; las instancias lo transforman)."""
        return G.centroid(self.shape)

    @cached_property
    def local_bbox(self) -> tuple[np.ndarray, np.ndarray]:
        return G.bbox(self.shape)

    @property
    def density(self) -> float:
        return catalog.material(self.material).density if self.material else 0.0

    @property
    def mass(self) -> float:
        """Masa en kg calculada a partir del volumen real del sólido y la densidad del material."""
        return self.volume * 1e-9 * self.density

    def bom_dims(self) -> dict[str, Any]:
        return {"espesor": None, "largo": None, "ancho": None}

    def info(self) -> dict[str, Any]:
        return {"ref": self.ref, "pos": self.pos, "kind": self.kind, "role": self.role, "name": self.name,
                "material": self.material, "finish": self.finish, **self.bom_dims()}


class ProfilePart(PartDef):
    kind = "perfil"

    def __init__(self, role, name, profile_code: str, length: float, material: str, finish: str | None,
                 holes: tuple[tuple[str, float, float, float], ...] = (), end_angles=(90.0, 90.0)):
        super().__init__(role, name, material, finish)
        self.profile = catalog.profile(profile_code)
        self.length = round(float(length), 2)
        # cotas redondeadas a 0,001 mm: piezas geométricamente idénticas comparten referencia aunque las
        # cotas se hayan obtenido por caminos aritméticos distintos (p. ej. niveles de una estantería)
        self.holes = tuple((f, round(float(z), 3), round(float(o), 3), d) for f, z, o, d in holes)
        self.end_angles = end_angles

    @property
    def key(self):
        return f"P|{self.profile.code}|{self.material}|{self.length:.2f}|{_h(self.holes, self.end_angles)}"

    def build_shape(self):
        return G.profile_solid(self.profile, self.length, self.holes)

    @property
    def nominal_mass(self) -> float:
        return self.profile.mass_per_m(self.density) * self.length / 1000

    @property
    def analytic_mass(self) -> float:
        """Masa de la definición (sección × longitud − taladros), igual que el motor del navegador."""
        holes = sum(math.pi * h[3] * h[3] / 4 * self.profile.t for h in self.holes)
        return (self.profile.props.A * self.length - holes) * 1e-9 * self.density

    def bom_dims(self):
        return {"espesor": self.profile.t, "largo": self.length, "ancho": None,
                "seccion": self.profile.code}


class SheetPart(PartDef):
    kind = "chapa"

    def __init__(self, role, name, spec: SheetMetalSpec, material: str, finish: str | None):
        super().__init__(role, name, material, finish)
        self.spec = spec

    @property
    def key(self):
        return f"S|{self.material}|{_h(self.spec)}"

    def build_shape(self):
        return self.spec.solid()

    @cached_property
    def flat(self):
        return self.spec.flat_pattern()

    @property
    def analytic_mass(self) -> float:
        """Masa de la definición (desarrollo neto × espesor + corrección de pliegues), igual que el navegador."""
        s = self.spec
        vol = self.flat.net_area() * s.t
        for L in s.bend_lengths():
            vol += math.pi / 2 * s.t * s.t * (0.5 - s.K) * L
        return vol * 1e-9 * self.density

    def bom_dims(self):
        fp = self.flat
        return {"espesor": self.spec.t, "largo": round(max(fp.width, fp.height), 1),
                "ancho": round(min(fp.width, fp.height), 1), "desarrollo": True}


class PlatePart(PartDef):
    kind = "pletina"

    def __init__(self, role, name, w: float, h: float, t: float, material: str, finish: str | None,
                 corner_r: float = 0.0, holes: tuple[tuple[float, float, float], ...] = ()):
        super().__init__(role, name, material, finish)
        self.w, self.h, self.t = float(w), float(h), float(t)
        self.corner_r = corner_r
        self.holes = tuple(holes)

    @property
    def key(self):
        return f"PL|{self.material}|{self.w}|{self.h}|{self.t}|{self.corner_r}|{_h(self.holes)}"

    def build_shape(self):
        return G.plate_solid(self.w, self.h, self.t, self.corner_r, self.holes)

    @property
    def analytic_volume(self) -> float:
        """Volumen de la definición (contorno con radios menos taladros): igual que el motor del navegador."""
        area = self.w * self.h - (4 - math.pi) * self.corner_r ** 2 - sum(math.pi * d * d / 4 for _, _, d in self.holes)
        return area * self.t

    @property
    def analytic_mass(self) -> float:
        return self.analytic_volume * 1e-9 * self.density

    def outline_2d(self):
        from shapely.geometry import box as sbox
        poly = sbox(0, 0, self.w, self.h)
        if self.corner_r > 0:
            poly = poly.buffer(-self.corner_r, join_style=2).buffer(self.corner_r, quad_segs=8)
        return poly

    def bom_dims(self):
        return {"espesor": self.t, "largo": max(self.w, self.h), "ancho": min(self.w, self.h)}


class StandardPart(PartDef):
    kind = "normalizado"

    def __init__(self, role, code: str):
        c = catalog.component(code)
        super().__init__(role, c["name"], None, None)
        self.code = code
        self.data = c

    @property
    def key(self):
        return f"N|{self.code}"

    def build_shape(self):
        cat = self.data["category"]
        if cat == "patas":
            return G.leveling_foot_solid(self.data)
        if cat == "ruedas_espiga":
            return G.stem_castor_solid(self.data)
        if cat == "anclajes":
            return G.anchor_solid(self.data)
        if self.code.startswith("TUERCA_SOLDAR"):
            return G.weld_nut_solid(self.data)
        if self.code.startswith("TUERCA_REMACHABLE"):
            return G.rivet_nut_solid(self.data)
        if self.code.startswith("TORNILLO_ISO7380"):
            return G.button_screw_solid(self.data)
        return G.generic_box_solid(self.data.get("dims", (20, 20, 10)))

    @property
    def mass(self) -> float:
        return float(self.data["mass_kg"])

    def bom_dims(self):
        return {"espesor": None, "largo": None, "ancho": None, "norma": self.data.get("standard")}


@dataclass
class Subassembly:
    id: str
    name: str
    parent: str | None = None
    explode: tuple[float, float, float] = (0.0, 0.0, 0.0)
    step: int = 0                   # orden de montaje
    welded: bool = False            # subconjunto soldado (se suministra como una unidad)


@dataclass
class Instance:
    id: str
    name: str
    part: PartDef
    T: np.ndarray
    group: str
    feature: str = ""
    axis: tuple[np.ndarray, np.ndarray] | None = None   # eje del perfil en coordenadas globales
    up: np.ndarray | None = None
    structural: bool = False
    tags: dict[str, Any] = field(default_factory=dict)
    # función de la instancia: la de la pieza pedida, aunque se reutilice otra pieza geométricamente idéntica
    # (p. ej. un asa igual que un travesaño); el dimensionado elige el parámetro de perfil por esta función
    role: str = ""

    def __post_init__(self):
        self.role = self.role or self.part.role

    @cached_property
    def shape(self) -> cq.Shape:
        return G.place(self.part.shape, self.T)

    @cached_property
    def bbox(self) -> tuple[np.ndarray, np.ndarray]:
        return G.bbox(self.shape)

    @cached_property
    def centroid(self) -> np.ndarray:
        """Centro de gravedad en ejes globales, a partir del de la pieza (sin colocar el sólido B-rep de cada
        instancia); el de un normalizado es el centro de su envolvente, exacto con giros de 90° como en el motor web."""
        R, t = self.T[:3, :3], self.T[:3, 3]
        if self.part.kind != "normalizado":
            return R @ self.part.local_centroid + t
        lo, hi = self.part.local_bbox
        pts = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ R.T + t
        return (pts.min(axis=0) + pts.max(axis=0)) / 2


@dataclass
class Joint:
    id: str
    kind: str                       # soldadura | atornillada | roscada | remachada
    members: tuple[str, ...]
    location: tuple[float, float, float]
    description: str = ""
    weld: dict[str, Any] | None = None
    fasteners: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductModel:
    family: str
    family_name: str
    product_code: str
    params: ParameterSet
    ctx: ParamContext
    parts: dict[str, PartDef] = field(default_factory=dict)
    instances: list[Instance] = field(default_factory=list)
    subassemblies: dict[str, Subassembly] = field(default_factory=dict)
    joints: list[Joint] = field(default_factory=list)
    structure: dict[str, Any] = field(default_factory=dict)    # datos para el motor de cálculo
    design_notes: list[dict[str, Any]] = field(default_factory=list)
    dims: dict[str, float] = field(default_factory=dict)        # cotas principales esperadas
    # parámetros por defecto incompatibles entre sí que la regla de diseño corrige: {param: (valor, motivo)}
    rule_fixes: dict[str, tuple[Any, str]] = field(default_factory=dict)

    # -- construcción
    def auto_explode(self) -> None:
        """Explosionado sin solapes: cada subconjunto, en su orden de montaje, se desplaza en la dirección de su vector
        lo justo para que su envolvente (con los desplazamientos propios de sus piezas) quede separada, con un margen, de
        la de los subconjuntos ya colocados. El vector de la familia fija la dirección y el desplazamiento mínimo. Antes
        los desplazamientos eran fijos y, por ejemplo, las bandejas de una estantería seguían atravesando los montantes."""
        boxes: dict[str, list[np.ndarray]] = {}
        for i in self.instances:
            lo, hi = i.part.local_bbox
            R, t = i.T[:3, :3], i.T[:3, 3]
            pts = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ R.T + t
            pts = pts + np.array(i.tags.get("explode_extra", (0.0, 0.0, 0.0)), float)
            b = boxes.setdefault(i.group, [pts.min(axis=0), pts.max(axis=0)])
            b[0], b[1] = np.minimum(b[0], pts.min(axis=0)), np.maximum(b[1], pts.max(axis=0))
        if not boxes:
            return
        all_lo = np.min([b[0] for b in boxes.values()], axis=0)
        all_hi = np.max([b[1] for b in boxes.values()], axis=0)
        m = max(60.0, 10.0 * math.ceil(0.04 * float(np.linalg.norm(all_hi - all_lo)) / 10.0))
        order = sorted(range(len(self.subassemblies)), key=lambda k: (list(self.subassemblies.values())[k].step, k))
        placed: list[tuple[np.ndarray, np.ndarray]] = []
        for k in order:
            sa = list(self.subassemblies.values())[k]
            if sa.id not in boxes:
                continue
            lo, hi = boxes[sa.id]
            e = np.array(sa.explode, float)
            L = float(np.linalg.norm(e))
            if L < 1e-9:
                placed.append((lo, hi))
                continue
            d = e / L
            t = L
            for _ in range(2 * len(placed) + 2):
                moved = False
                for blo, bhi in placed:
                    # intervalo de t en que las envolventes (con margen) se cortan: intersección por ejes
                    a, b = -math.inf, math.inf
                    for j in range(3):
                        if abs(d[j]) < 1e-12:
                            if not (lo[j] < bhi[j] + m and hi[j] > blo[j] - m):
                                a, b = 1.0, 0.0        # nunca se cortan
                                break
                            continue           # sin componente en este eje: se cortan siempre en él
                        t1, t2 = (bhi[j] + m - lo[j]) / d[j], (blo[j] - m - hi[j]) / d[j]
                        a, b = max(a, min(t1, t2)), min(b, max(t1, t2))
                    if a < b and a < t < b:
                        t, moved = b, True
                if not moved:
                    break
            t = 10.0 * math.ceil(t / 10.0 - 1e-9)
            sa.explode = tuple(float(v) for v in d * t)
            placed.append((lo + t * d, hi + t * d))

    def add_subassembly(self, sid: str, name: str, **kw) -> Subassembly:
        sa = Subassembly(sid, name, **kw)
        self.subassemblies[sid] = sa
        return sa

    def part(self, p: PartDef) -> PartDef:
        """Registra una definición; si ya existe una idéntica la reutiliza."""
        k = p.key
        if k not in self.parts:
            self.parts[k] = p
        return self.parts[k]

    def add(self, iid: str, name: str, part: PartDef, T: np.ndarray, group: str, **kw) -> Instance:
        if any(i.id == iid for i in self.instances):
            raise ValueError(f"Identificador de instancia duplicado: {iid}")
        role = kw.pop("role", None) or part.role
        part = self.part(part)
        feat = self.ctx.current_feature
        inst = Instance(iid, name, part, T, group, feature=feat.id if feat else "", role=role, **kw)
        if feat:
            feat.produces.append(iid)
        self.instances.append(inst)
        return inst

    def add_joint(self, j: Joint) -> Joint:
        self.joints.append(j)
        return j

    def note(self, level: str, code: str, message: str, **data) -> None:
        """level: info | propuesta | advertencia | error."""
        self.design_notes.append({"level": level, "code": code, "message": message, **data})

    # -- consultas
    def instance(self, iid: str) -> Instance:
        for i in self.instances:
            if i.id == iid:
                return i
        raise KeyError(iid)

    def by_part(self) -> dict[str, list[Instance]]:
        out: dict[str, list[Instance]] = {}
        for i in self.instances:
            out.setdefault(i.part.key, []).append(i)
        return out

    def number_parts(self) -> None:
        """Asigna posición y referencia a cada definición (orden: subconjunto, tipo, rol)."""
        sa_order = {sid: n for n, sid in enumerate(self.subassemblies)}
        first: dict[str, Instance] = {}
        for i in self.instances:
            first.setdefault(i.part.key, i)
        keys = sorted(self.parts, key=lambda k: (KIND_ORDER[self.parts[k].kind],
                                                 sa_order.get(first[k].group, 99) if k in first else 99,
                                                 self.parts[k].role, self.parts[k].name, k))
        for n, k in enumerate(keys, start=1):
            p = self.parts[k]
            p.pos = n
            p.ref = f"{self.product_code}-{n:02d}" if p.kind != "normalizado" else f"N-{p.code}"

    def compound(self, kinds: set[str] | None = None) -> cq.Compound:
        return cq.Compound.makeCompound([i.shape for i in self.instances
                                         if kinds is None or i.part.kind in kinds])

    def total_mass(self) -> float:
        return sum(i.part.mass for i in self.instances)

    def center_of_mass(self) -> np.ndarray:
        m = np.array([i.part.mass for i in self.instances])
        c = np.array([i.centroid for i in self.instances])
        return (c * m[:, None]).sum(axis=0) / m.sum()

    def bounding_box(self) -> tuple[np.ndarray, np.ndarray]:
        return G.bbox(self.compound())

    def component_tree(self) -> dict[str, Any]:
        def node(sid):
            sa = self.subassemblies[sid]
            return {
                "id": sid, "name": sa.name, "type": "subconjunto", "welded": sa.welded,
                "children": [node(c) for c, s in self.subassemblies.items() if s.parent == sid] + [
                    {"id": i.id, "name": i.name, "type": i.part.kind, "ref": i.part.ref, "part": i.part.key}
                    for i in self.instances if i.group == sid],
            }
        roots = [sid for sid, s in self.subassemblies.items() if s.parent is None]
        return {"id": self.product_code, "name": self.family_name, "type": "conjunto",
                "children": [node(r) for r in roots]}

    def feature_tree(self) -> list[dict[str, Any]]:
        return [{"id": f.id, "label": f.label, "parent": f.parent,
                 "params": sorted(self.ctx.feature_base_dependencies(f.id)), "produces": list(f.produces)}
                for f in self.ctx.features.values()]

    def parameter_table(self) -> list[dict[str, Any]]:
        rows = []
        for name, spec in self.params.specs.items():
            rows.append({"name": name, "label": spec.label, "value": self.params.values[name], "unit": spec.unit,
                         "group": spec.group, "source": self.params.sources.get(name), "derived": False})
        for name, d in self.ctx.derived.items():
            v = d.value
            if isinstance(v, float):
                v = round(v, 4)
            if isinstance(v, (int, float, str, bool)) or v is None:
                rows.append({"name": name, "label": d.label, "value": v, "unit": d.unit, "group": "derivado",
                             "source": "regla_diseno", "derived": True,
                             "depends_on": sorted(self.ctx.base_dependencies(name))})
        return rows


def isclose(a: float, b: float, tol: float = 1e-6) -> bool:
    return math.isclose(a, b, abs_tol=tol)
