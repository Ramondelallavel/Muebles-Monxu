"""Catálogo técnico: materiales, perfiles, chapas, componentes, normas y criterios.

Los datos se guardan en ficheros JSON versionados (``monxu/catalog/data``) para que
puedan revisarse y actualizarse sin modificar código. Es posible superponer un
catálogo de usuario (componentes añadidos) mediante :func:`register_component`.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=None)
def _load(name: str) -> dict[str, Any]:
    with open(DATA_DIR / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)


def catalog_versions() -> dict[str, str]:
    return {n: _load(n)["_meta"]["version"] for n in
            ("materials", "profiles", "sheets", "components", "standards", "criteria")}


# --------------------------------------------------------------------------- materiales
@dataclass(frozen=True)
class Material:
    code: str
    name: str
    family: str
    standard: str
    density: float          # kg/m3
    E: float | None         # MPa
    G: float | None
    nu: float | None
    fy: float | None
    fu: float | None
    fy_guaranteed: bool
    gamma_M0: float
    gamma_M1: float
    gamma_M2: float
    beta_w: float
    design_code: str | None
    weldable: bool
    render_color: tuple[float, float, float]
    haz_reduction_required: bool = False
    note: str = ""

    @property
    def structural(self) -> bool:
        return self.E is not None and self.fy is not None

    @property
    def epsilon(self) -> float:
        return math.sqrt(235.0 / self.fy) if self.fy else 1.0


def material(code: str) -> Material:
    data = _load("materials")["materials"]
    if code not in data:
        raise KeyError(f"Material desconocido: {code}")
    d = data[code]
    return Material(
        code=code, name=d["name"], family=d["family"], standard=d["standard"],
        density=d["density"], E=d.get("E"), G=d.get("G"), nu=d.get("nu"), fy=d.get("fy"), fu=d.get("fu"),
        fy_guaranteed=d.get("fy_guaranteed", False), gamma_M0=d.get("gamma_M0", 1.0),
        gamma_M1=d.get("gamma_M1", 1.0), gamma_M2=d.get("gamma_M2", 1.25), beta_w=d.get("beta_w", 1.0),
        design_code=d.get("design_code"), weldable=d.get("weldable", False),
        render_color=tuple(d.get("render_color", (0.5, 0.5, 0.5))),
        haz_reduction_required=d.get("haz_reduction_required", False), note=d.get("note", ""),
    )


def materials() -> dict[str, Material]:
    return {c: material(c) for c in _load("materials")["materials"]}


def finishes() -> dict[str, dict[str, Any]]:
    return _load("materials")["finishes"]


def finish(code: str) -> dict[str, Any]:
    f = finishes()
    if code not in f:
        raise KeyError(f"Acabado desconocido: {code}")
    return f[code]


# --------------------------------------------------------------------------- perfiles
@dataclass(frozen=True)
class SectionProperties:
    A: float      # mm2
    Iy: float     # mm4 (eje fuerte, flexión en el plano de H)
    Iz: float     # mm4
    Wel_y: float  # mm3
    Wel_z: float
    Wpl_y: float
    Wpl_z: float
    iy: float     # mm
    iz: float
    It: float     # mm4 (torsión, fórmula de Bredt para sección cerrada)
    Av_z: float   # área a cortante en dirección z (paralela a H)
    Av_y: float


@dataclass(frozen=True)
class Profile:
    code: str
    type: str
    B: float      # anchura (eje local x de la sección)
    H: float      # altura (eje local y de la sección)
    t: float
    standard: str

    @property
    def r_out(self) -> float:
        return 2.0 * self.t

    @property
    def r_in(self) -> float:
        return self.t

    def outline(self, inner: bool = False, seg: int = 12) -> list[tuple[float, float]]:
        """Contorno poligonal (sentido antihorario) de la sección centrada en el origen."""
        if inner:
            b, h, r = self.B - 2 * self.t, self.H - 2 * self.t, self.r_in
        else:
            b, h, r = self.B, self.H, self.r_out
        pts: list[tuple[float, float]] = []
        corners = [(b / 2 - r, h / 2 - r, 0.0), (-b / 2 + r, h / 2 - r, 90.0),
                   (-b / 2 + r, -h / 2 + r, 180.0), (b / 2 - r, -h / 2 + r, 270.0)]
        for cx, cy, a0 in corners:
            for i in range(seg + 1):
                a = math.radians(a0 + 90.0 * i / seg)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return pts

    @property
    def props(self) -> SectionProperties:
        return _section_props(self)

    def mass_per_m(self, density: float) -> float:
        return self.props.A * 1e-6 * density


def _poly_area_moments(pts):
    """Área, Ix (respecto eje x por el origen) e Iy de un polígono simple (Green)."""
    A = Ix = Iy = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        A += c
        Ix += (y0 * y0 + y0 * y1 + y1 * y1) * c
        Iy += (x0 * x0 + x0 * x1 + x1 * x1) * c
    return A / 2.0, Ix / 12.0, Iy / 12.0


def _clip_half(pts, axis: int):
    """Recorta un polígono convexo al semiplano coordenada[axis] >= 0 (Sutherland-Hodgman)."""
    out = []
    n = len(pts)
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        pin, qin = p[axis] >= 0, q[axis] >= 0
        if pin:
            out.append(p)
        if pin != qin:
            s = p[axis] / (p[axis] - q[axis])
            out.append((p[0] + s * (q[0] - p[0]), p[1] + s * (q[1] - p[1])))
    return out


def _first_moment(pts, axis: int) -> float:
    """Momento estático respecto al eje coordenado (axis=1 -> integral de y dA)."""
    S = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        S += ((y0 + y1) if axis == 1 else (x0 + x1)) * c
    return S / 6.0


@lru_cache(maxsize=None)
def _section_props(p: Profile) -> SectionProperties:
    out, inn = p.outline(False, 24), p.outline(True, 24)
    Ao, Ixo, Iyo = _poly_area_moments(out)
    Ai, Ixi, Iyi = _poly_area_moments(inn)
    A = Ao - Ai
    Iy = Ixo - Ixi   # flexión alrededor del eje horizontal de la sección (resiste cargas según H)
    Iz = Iyo - Iyi
    Wpl_y = 2 * (_first_moment(_clip_half(out, 1), 1) - _first_moment(_clip_half(inn, 1), 1))
    Wpl_z = 2 * (_first_moment(_clip_half(out, 0), 0) - _first_moment(_clip_half(inn, 0), 0))
    # Bredt: It = 4 Am^2 t / pm (línea media)
    bm, hm, rm = p.B - p.t, p.H - p.t, (p.r_out + p.r_in) / 2
    Am = bm * hm - (4 - math.pi) * rm ** 2
    pm = 2 * (bm + hm) - 2 * (4 - math.pi) * rm
    It = 4 * Am ** 2 * p.t / pm
    return SectionProperties(
        A=A, Iy=Iy, Iz=Iz, Wel_y=Iy / (p.H / 2), Wel_z=Iz / (p.B / 2), Wpl_y=Wpl_y, Wpl_z=Wpl_z,
        iy=math.sqrt(Iy / A), iz=math.sqrt(Iz / A), It=It,
        Av_z=A * p.H / (p.B + p.H), Av_y=A * p.B / (p.B + p.H),
    )


def profile(code: str) -> Profile:
    data = _load("profiles")["profiles"]
    if code not in data:
        raise KeyError(f"Perfil desconocido: {code}")
    d = data[code]
    return Profile(code=code, type=d["type"], B=float(d["B"]), H=float(d["H"]), t=float(d["t"]),
                   standard=d["standard"])


def profiles() -> dict[str, Profile]:
    return {c: profile(c) for c in _load("profiles")["profiles"]}


def profile_meta() -> dict[str, Any]:
    return _load("profiles")["_meta"]


def profile_materials() -> dict[str, list[str]]:
    return _load("profiles")["available_materials"]


# --------------------------------------------------------------------------- chapa
def sheet_data() -> dict[str, Any]:
    return _load("sheets")


def sheet_thicknesses(mat_code: str) -> list[float]:
    return sheet_data()["thicknesses_mm"].get(mat_code, [])


def sheet_formats() -> list[dict[str, Any]]:
    return sheet_data()["formats_mm"]


def din6935_k_factor(r: float, t: float) -> float:
    """Factor K (posición de la fibra neutra / t) según DIN 6935.

    DIN 6935 define el factor de corrección k = 0,65 + 0,5·lg(r/s) para r/s < 5
    (k = 1 para r/s >= 5); la fibra neutra queda a k·s/2 de la cara interior, por lo que
    el factor K equivalente es k/2.
    """
    ratio = r / t
    if ratio >= 5:
        return 0.5
    k = 0.65 + 0.5 * math.log10(ratio)
    return max(0.2, min(0.5, k / 2.0))


# --------------------------------------------------------------------------- componentes
_USER_COMPONENTS: dict[str, dict[str, Any]] = {}


def components() -> dict[str, dict[str, Any]]:
    d = dict(_load("components")["components"])
    d.update(_USER_COMPONENTS)
    return d


def component(code: str) -> dict[str, Any]:
    c = components()
    if code not in c:
        raise KeyError(f"Componente desconocido: {code}")
    return c[code]


def register_component(code: str, data: dict[str, Any]) -> None:
    required = {"category", "name", "mass_kg"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Faltan propiedades del componente: {sorted(missing)}")
    _USER_COMPONENTS[code] = dict(data)


def consumables() -> dict[str, dict[str, Any]]:
    return _load("components")["consumables"]


# --------------------------------------------------------------------------- normas / criterios
def standards(family: str | None = None, market: str = "EU", material_families: set[str] | None = None):
    out = []
    for s in _load("standards")["standards"]:
        if family and "*" not in s["families"] and family not in s["families"]:
            continue
        if "*" not in s["markets"] and market not in s["markets"]:
            continue
        if material_families is not None and "materials" in s and not (set(s["materials"]) & material_families):
            continue
        out.append(s)
    return out


def standards_meta() -> dict[str, Any]:
    return _load("standards")["_meta"]


def criteria() -> dict[str, Any]:
    return _load("criteria")
