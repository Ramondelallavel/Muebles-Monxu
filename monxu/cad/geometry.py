"""Construcción de sólidos B-rep reales con OpenCascade (vía CadQuery/OCP).

Convenciones locales de cada tipo de pieza:

* Perfil: sección centrada en el origen en el plano XY (X = ancho B, Y = canto H) y
  extrusión según +Z de 0 a la longitud de corte.
* Pletina: contorno en XY con origen en la esquina, espesor según +Z.
* Componente normalizado: origen en su plano de apoyo característico (ver cada función).
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import cadquery as cq
import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Trsf

from ..catalog import Profile

# ----------------------------------------------------------------------------- transformaciones


def identity() -> np.ndarray:
    return np.eye(4)


def translation(x: float, y: float, z: float) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = (x, y, z)
    return T


def frame(origin: Sequence[float], xdir: Sequence[float], ydir: Sequence[float]) -> np.ndarray:
    """Matriz homogénea cuyo eje X local es ``xdir`` e Y local es ``ydir`` (Z = X × Y)."""
    x = np.asarray(xdir, float)
    x /= np.linalg.norm(x)
    y = np.asarray(ydir, float)
    y = y - x * np.dot(x, y)
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, origin
    return T


def axis_frame(p0: Sequence[float], p1: Sequence[float], up: Sequence[float]) -> np.ndarray:
    """Sistema local de un perfil: Z según el eje p0→p1 y el canto (Y local) lo más próximo a ``up``."""
    p0 = np.asarray(p0, float)
    z = np.asarray(p1, float) - p0
    z /= np.linalg.norm(z)
    up = np.asarray(up, float)
    y = up - z * np.dot(z, up)
    if np.linalg.norm(y) < 1e-9:
        raise ValueError("Vector 'up' paralelo al eje del perfil")
    y /= np.linalg.norm(y)
    x = np.cross(y, z)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, p0
    return T


def to_location(T: np.ndarray) -> cq.Location:
    tr = gp_Trsf()
    tr.SetValues(*(float(T[i, j]) for i in range(3) for j in range(4)))
    return cq.Location(tr)


def transform_point(T: np.ndarray, p: Sequence[float]) -> np.ndarray:
    return (T @ np.array([p[0], p[1], p[2], 1.0]))[:3]


def place(shape: cq.Shape, T: np.ndarray) -> cq.Shape:
    return shape.moved(to_location(T))


# ----------------------------------------------------------------------------- análisis


def volume(shape: cq.Shape) -> float:
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, p)
    return p.Mass()


def centroid(shape: cq.Shape) -> np.ndarray:
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, p)
    c = p.CentreOfMass()
    return np.array([c.X(), c.Y(), c.Z()])


def area(shape: cq.Shape) -> float:
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape.wrapped, p)
    return p.Mass()


def bbox(shape: cq.Shape, optimal: bool = True) -> tuple[np.ndarray, np.ndarray]:
    b = Bnd_Box()
    if optimal:
        BRepBndLib.AddOptimal_s(shape.wrapped, b, False, False)
    else:
        BRepBndLib.Add_s(shape.wrapped, b)
    x0, y0, z0, x1, y1, z1 = b.Get()
    return np.array([x0, y0, z0]), np.array([x1, y1, z1])


def common_volume(a: cq.Shape, b: cq.Shape) -> float:
    op = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
    op.SetFuzzyValue(1e-5)
    op.Build()
    if not op.IsDone():
        return float("nan")
    return volume(cq.Shape.cast(op.Shape()))


# ----------------------------------------------------------------------------- primitivas


def _polyline_face_extrude(pts: Sequence[tuple[float, float]], height: float) -> cq.Solid:
    wp = cq.Workplane("XY").polyline(list(pts)).close().extrude(height)
    return wp.val()


def rounded_rect_solid(b: float, h: float, r: float, length: float) -> cq.Shape:
    wp = cq.Workplane("XY").rect(b, h).extrude(length)
    if r > 1e-6:
        wp = wp.edges("|Z").fillet(r)
    return wp.val()


def cylinder(d: float, length: float, base: Sequence[float] = (0, 0, 0),
             direction: Sequence[float] = (0, 0, 1)) -> cq.Shape:
    return cq.Solid.makeCylinder(d / 2.0, length, cq.Vector(*base), cq.Vector(*direction))


def box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> cq.Shape:
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def cut_many(shape: cq.Shape, tools: list[cq.Shape]) -> cq.Shape:
    if not tools:
        return shape
    return shape.cut(cq.Compound.makeCompound(tools)).clean()


# ----------------------------------------------------------------------------- perfiles


def profile_solid(p: Profile, length: float,
                  holes: Iterable[tuple[str, float, float, float]] = ()) -> cq.Shape:
    """Tubo hueco con radios EN 10219-2 y taladros en una pared.

    ``holes``: (cara, z, desplazamiento transversal, diámetro); cara en {"+x","-x","+y","-y"}.
    """
    outer = rounded_rect_solid(p.B, p.H, p.r_out, length)
    inner = rounded_rect_solid(p.B - 2 * p.t, p.H - 2 * p.t, p.r_in, length + 2).translate((0, 0, -1))
    solid = outer.cut(inner)
    tools = []
    for face, z, off, d in holes:
        depth = p.t + 2.0
        if face in ("+x", "-x"):
            sgn = 1 if face == "+x" else -1
            x_out = sgn * (p.B / 2 + 1.0)
            tools.append(cylinder(d, depth, (x_out, off, z), (-sgn, 0, 0)))
        else:
            sgn = 1 if face == "+y" else -1
            y_out = sgn * (p.H / 2 + 1.0)
            tools.append(cylinder(d, depth, (off, y_out, z), (0, -sgn, 0)))
    return cut_many(solid, tools)


# ----------------------------------------------------------------------------- pletinas


def plate_solid(w: float, h: float, t: float, corner_r: float = 0.0,
                holes: Iterable[tuple[float, float, float]] = ()) -> cq.Shape:
    wp = cq.Workplane("XY").rect(w, h, centered=False).extrude(t)
    if corner_r > 0:
        wp = wp.edges("|Z").fillet(corner_r)
    solid = wp.val()
    tools = [cylinder(d, t + 2, (x, y, -1)) for x, y, d in holes]
    return cut_many(solid, tools)


# ----------------------------------------------------------------------------- normalizados


def hex_prism(s: float, m: float, bore: float) -> cq.Shape:
    """Prisma hexagonal (entrecaras s, altura m) con taladro pasante, base en z=0."""
    wp = cq.Workplane("XY").polygon(6, s / math.cos(math.pi / 6)).extrude(m)
    solid = wp.val()
    return solid.cut(cylinder(bore, m + 2, (0, 0, -1)))


def leveling_foot_solid(c: dict) -> cq.Shape:
    """Pie nivelador. Origen en el centro de la base sobre el suelo; vástago según +Z."""
    d = float(c["thread"][1:])
    base = cylinder(c["base_d"], c["base_h"])
    joint = cylinder(d * 1.6, 6.0, (0, 0, c["base_h"]))
    stem = cylinder(d, c["stem_len"], (0, 0, c["base_h"] + 6.0))
    return base.fuse(joint).fuse(stem).clean()


def weld_nut_solid(c: dict) -> cq.Shape:
    d = float(c["thread"][1:])
    return hex_prism(c["s"], c["m"], d)


def rivet_nut_solid(c: dict) -> cq.Shape:
    """Tuerca remachable. Origen en la cara inferior de la cabeza; cabeza hacia +Z, cuerpo hacia -Z."""
    d = float(c["thread"][1:])
    head = cylinder(c["head_d"], c["head_h"])
    body = cylinder(c["body_d"], c["body_l"], (0, 0, -c["body_l"]))
    return head.fuse(body).cut(cylinder(d, c["body_l"] + c["head_h"] + 2, (0, 0, -c["body_l"] - 1))).clean()


def button_screw_solid(c: dict) -> cq.Shape:
    """Tornillo ISO 7380. Origen bajo cabeza; cabeza hacia +Z, caña hacia -Z."""
    head = cq.Workplane("XY").circle(c["head_d"] / 2).extrude(c["head_h"]).faces(">Z").edges().fillet(
        min(c["head_h"] * 0.6, c["head_d"] * 0.2)).val()
    shank = cylinder(c["d"], c["length"], (0, 0, -c["length"]))
    return head.fuse(shank).clean()


def generic_box_solid(dims: Sequence[float]) -> cq.Shape:
    return box(-dims[0] / 2, -dims[1] / 2, 0, dims[0] / 2, dims[1] / 2, dims[2])
