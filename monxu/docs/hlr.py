"""Proyección con eliminación de líneas ocultas (HLR exacto de OpenCascade) para los planos."""
from __future__ import annotations

import math
from typing import Iterable

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GeomAbs import GeomAbs_Line
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

# Proyección del primer diedro (ISO E): (dirección hacia el observador, eje X del papel)
VIEWS = {
    "alzado": ((0, -1, 0), (1, 0, 0)),          # vista frontal (desde Y-)
    "perfil": ((-1, 0, 0), (0, -1, 0)),         # vista desde la izquierda, se dibuja a la derecha del alzado
    "planta": ((0, 0, 1), (1, 0, 0)),           # vista superior, se dibuja bajo el alzado
    "perfil_der": ((1, 0, 0), (0, 1, 0)),
    "iso": ((1, -1, 1), (1, 1, 0)),
    "iso_izq": ((-1, -1, 1), (1, -1, 0)),
}


def projector(view: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    z, x = (np.array(v, float) for v in VIEWS[view])
    z /= np.linalg.norm(z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return x, y, z


def project_point(p, view: str) -> tuple[float, float]:
    x, y, _ = projector(view)
    p = np.asarray(p, float)
    return float(p @ x), float(p @ y)


def _discretize(edge, deflection: float) -> list[tuple[float, float]]:
    c = BRepAdaptor_Curve(edge)
    if c.GetType() == GeomAbs_Line:
        p0, p1 = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
        return [(p0.X(), p0.Y()), (p1.X(), p1.Y())]
    d = GCPnts_QuasiUniformDeflection(c, deflection)
    if not d.IsDone() or d.NbPoints() < 2:
        p0, p1 = c.Value(c.FirstParameter()), c.Value(c.LastParameter())
        return [(p0.X(), p0.Y()), (p1.X(), p1.Y())]
    return [(d.Value(i).X(), d.Value(i).Y()) for i in range(1, d.NbPoints() + 1)]


def _edges(shape, deflection) -> list[list[tuple[float, float]]]:
    out = []
    if shape is None or shape.IsNull():
        return out
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        out.append(_discretize(TopoDS.Edge_s(exp.Current()), deflection))
        exp.Next()
    return out


def project(shapes: Iterable[cq.Shape], view: str, hidden: bool = True, deflection: float = 0.2) -> dict:
    """Devuelve polilíneas 2D (coordenadas de modelo en mm) visibles y ocultas."""
    algo = HLRBRep_Algo()
    n = 0
    for s in shapes:
        algo.Add(s.wrapped)
        n += 1
    if n == 0:
        return {"visible": [], "hidden": [], "bbox": (0, 0, 0, 0)}
    xd, yd, zd = projector(view)
    ax = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*zd), gp_Dir(*xd))
    algo.Projector(HLRAlgo_Projector(ax))
    algo.Update()
    algo.Hide()
    h = HLRBRep_HLRToShape(algo)
    vis = _edges(h.VCompound(), deflection) + _edges(h.OutLineVCompound(), deflection)
    if view.startswith("iso"):
        # aristas de tangencia de los radios (esquinas de tubo, pliegues) en perspectiva: sin ellas un tubo cuadrado se
        # ve como una cinta plana; en las vistas ortogonales duplicarían el contorno y no se dibujan
        vis += _edges(h.Rg1LineVCompound(), deflection)
    hid = (_edges(h.HCompound(), deflection) + _edges(h.OutLineHCompound(), deflection)) if hidden else []
    pts = [p for pl in vis for p in pl] or [(0, 0)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return {"visible": vis, "hidden": hid, "bbox": (min(xs), min(ys), max(xs), max(ys))}


def project_polyline_bbox(points3d, view) -> tuple[float, float, float, float]:
    pts = [project_point(p, view) for p in points3d]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_corners(lo, hi):
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def view_angle_deg(view: str) -> float:
    x, _, _ = projector(view)
    return math.degrees(math.atan2(x[1], x[0]))
