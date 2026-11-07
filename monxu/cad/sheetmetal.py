"""Chapa plegada basada en operaciones (cara base + pestañas) con radio, espesor y factor K.

El sólido 3D y el desarrollo plano se obtienen de la MISMA definición de operaciones
(como en los módulos de chapa de los CAD paramétricos). El desarrollo usa la tolerancia
de plegado BA = θ·(r + K·t); la coherencia entre ambos se verifica de forma exacta con
:func:`volume_consistency` (el volumen del sólido y el del desarrollo difieren sólo en el
término conocido θ/2·t²·(0,5 − K)·L de cada pliegue).

Coordenadas de la base: X ∈ [0, Lx], Y ∈ [0, Ly] medidas a líneas de molde exteriores,
cara superior de la base en z = 0 y cara inferior en z = −t.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

import cadquery as cq
import numpy as np
from shapely.geometry import Polygon, box as sbox
from shapely.ops import unary_union

from . import geometry as G

EDGES = ("x0", "x1", "y0", "y1")


@dataclass(frozen=True)
class FlangeSpec:
    edge: str                       # x0 | x1 | y0 | y1
    height: float                   # altura exterior (línea de molde) desde la cara exterior de la base
    direction: str = "down"         # down | up
    holes: tuple[tuple[float, float, float], ...] = ()   # (s a lo largo del borde, h desde cara exterior, Ø)


@dataclass(frozen=True)
class SheetMetalSpec:
    Lx: float
    Ly: float
    t: float
    r: float                        # radio interior de plegado
    K: float                        # factor K
    flanges: tuple[FlangeSpec, ...] = ()
    notch: tuple[float, float] = (0.0, 0.0)     # escotadura de esquina (nx, ny)
    holes: tuple[tuple, ...] = ()   # ("round", x, y, d) | ("rect", x, y, w, h)
    #: esquinas con escotadura (por defecto las 4): "x0y0" (delantera izquierda), "x1y0", "x0y1", "x1y1"
    notch_corners: tuple[str, ...] = ("x0y0", "x1y0", "x0y1", "x1y1")

    # ------------------------------------------------------------------ magnitudes
    @property
    def R(self) -> float:
        return self.r + self.t

    @property
    def BA(self) -> float:
        return bend_allowance(self.t, self.r, self.K)

    @property
    def BD(self) -> float:
        return bend_deduction(self.t, self.r, self.K)

    def flange(self, edge: str) -> FlangeSpec | None:
        for f in self.flanges:
            if f.edge == edge:
                return f
        return None

    @property
    def flat_bounds_base(self) -> tuple[float, float, float, float]:
        R = self.R
        bx0 = R if self.flange("x0") else 0.0
        bx1 = self.Lx - R if self.flange("x1") else self.Lx
        by0 = R if self.flange("y0") else 0.0
        by1 = self.Ly - R if self.flange("y1") else self.Ly
        return bx0, bx1, by0, by1

    def notched(self, corner: str) -> bool:
        return self.notch[0] > 0 and self.notch[1] > 0 and corner in self.notch_corners

    def flange_extent(self, edge: str) -> tuple[float, float]:
        nx, ny = self.notch
        R = self.R
        if edge in ("x0", "x1"):
            s0 = max(ny if self.notched(f"{edge}y0") else 0.0, R if self.flange("y0") else 0.0)
            s1 = self.Ly - max(ny if self.notched(f"{edge}y1") else 0.0, R if self.flange("y1") else 0.0)
        else:
            e = edge[1]
            s0 = max(nx if self.notched(f"x0y{e}") else 0.0, R if self.flange("x0") else 0.0)
            s1 = self.Lx - max(nx if self.notched(f"x1y{e}") else 0.0, R if self.flange("x1") else 0.0)
        return s0, s1

    def base_region(self) -> Polygon:
        bx0, bx1, by0, by1 = self.flat_bounds_base
        poly = sbox(bx0, by0, bx1, by1)
        nx, ny = self.notch
        if nx > 0 and ny > 0:
            boxes = {"x0y0": sbox(-1, -1, nx, ny), "x1y0": sbox(self.Lx - nx, -1, self.Lx + 1, ny),
                     "x0y1": sbox(-1, self.Ly - ny, nx, self.Ly + 1), "x1y1": sbox(self.Lx - nx, self.Ly - ny, self.Lx + 1, self.Ly + 1)}
            cuts = [b for k, b in boxes.items() if k in self.notch_corners]
            if cuts:
                poly = poly.difference(unary_union(cuts))
        return poly

    # ------------------------------------------------------------------ 3D
    def _edge_frame(self, edge: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, callable]:
        """(n̂ hacia el interior, ĉ dirección de extrusión, origen, s→punto en línea de molde)."""
        s0, s1 = self.flange_extent(edge)
        if edge == "x0":
            n, c, o = (1, 0, 0), (0, -1, 0), (0, s1, 0)
            pt = lambda s: np.array([0.0, s, 0.0])
        elif edge == "x1":
            n, c, o = (-1, 0, 0), (0, 1, 0), (self.Lx, s0, 0)
            pt = lambda s: np.array([self.Lx, s, 0.0])
        elif edge == "y0":
            n, c, o = (0, 1, 0), (1, 0, 0), (s0, 0, 0)
            pt = lambda s: np.array([s, 0.0, 0.0])
        else:
            n, c, o = (0, -1, 0), (-1, 0, 0), (s1, self.Ly, 0)
            pt = lambda s: np.array([s, self.Ly, 0.0])
        return np.array(n, float), np.array(c, float), np.array(o, float), pt

    def _flange_section(self, f: FlangeSpec) -> cq.Workplane:
        t, r, R, h = self.t, self.r, self.R, f.height
        c45 = math.cos(math.pi / 4)
        pts = {
            "o0": (R, 0.0), "om": (R - R * c45, -R + R * c45), "o1": (0.0, -R),
            "tip0": (0.0, -h), "tip1": (t, -h), "i0": (t, -R), "im": (R - r * c45, -R + r * c45), "i1": (R, -t),
        }
        if f.direction == "up":
            pts = {k: (x, -t - y) for k, (x, y) in pts.items()}
        wp = cq.Workplane("XY").moveTo(*pts["o0"]).threePointArc(pts["om"], pts["o1"])
        if h - R >= 0.01:
            wp = wp.lineTo(*pts["tip0"]).lineTo(*pts["tip1"])
        # si la pestaña no supera el pliegue sólo queda la zona curva (diseño señalado por el DFM como PLG-ALA-MIN),
        # igual que en el motor del navegador
        return wp.lineTo(*pts["i0"]).threePointArc(pts["im"], pts["i1"]).close()

    def solid(self) -> cq.Shape:
        base = self.base_region()
        coords = list(base.exterior.coords)[:-1]
        rects = [h for h in self.holes if h[0] == "rect"]
        if rects:
            # perforaciones rectangulares como contornos interiores de la cara base (una sola extrusión, sin
            # booleanas por agujero: los paneles perforados tienen cientos)
            outer = cq.Wire.makePolygon([cq.Vector(x, y, 0) for x, y in coords], close=True)
            inners = [cq.Wire.makePolygon([cq.Vector(x - w / 2, y - hh / 2, 0), cq.Vector(x + w / 2, y - hh / 2, 0),
                                           cq.Vector(x + w / 2, y + hh / 2, 0), cq.Vector(x - w / 2, y + hh / 2, 0)],
                                          close=True) for _, x, y, w, hh in rects]
            solid = cq.Solid.extrudeLinear(outer, inners, cq.Vector(0, 0, self.t)).translate(cq.Vector(0, 0, -self.t))
        else:
            solid = G._polyline_face_extrude(coords, self.t).translate((0, 0, -self.t))
        tools: list[cq.Shape] = []
        for f in self.flanges:
            s0, s1 = self.flange_extent(f.edge)
            n, c, o, pt = self._edge_frame(f.edge)
            sec = self._flange_section(f).extrude(s1 - s0).val()
            T = G.frame(o, n, (0, 0, 1))  # X local = n̂, Y local = ẑ, Z local = n̂ × ẑ = ĉ
            assert np.allclose(T[:3, 2], c)
            solid = solid.fuse(G.place(sec, T))
            if f.height - self.R < 0.01:
                continue          # sin ala recta no hay taladros de pestaña
            for s, hh, d in f.holes:
                zl = -hh if f.direction == "down" else -self.t + hh
                p = pt(s) + np.array([0, 0, zl]) - n * 1.0
                tools.append(G.cylinder(d, self.t + 2.0, tuple(p), tuple(n)))
        for h in self.holes:
            if h[0] == "round":
                _, x, y, d = h
                tools.append(G.cylinder(d, self.t + 2.0, (x, y, -self.t - 1.0)))
        solid = solid.clean()
        return G.cut_many(solid, tools)

    # ------------------------------------------------------------------ desarrollo
    def flat_pattern(self) -> "FlatPattern":
        bx0, bx1, by0, by1 = self.flat_bounds_base
        BA, R = self.BA, self.R
        parts = [self.base_region()]
        bends: list[dict[str, Any]] = []
        holes: list[dict[str, Any]] = []
        for f in self.flanges:
            s0, s1 = self.flange_extent(f.edge)
            F = f.height - R
            label = "ABAJO" if f.direction == "down" else "ARRIBA"
            if f.edge == "x0":
                parts.append(sbox(bx0 - BA - F, s0, bx0, s1))
                xb = bx0 - BA / 2
                bends.append({"p0": (xb, s0), "p1": (xb, s1)})
                holes += [{"kind": "round", "x": bx0 - BA - (hh - R), "y": s, "d": d} for s, hh, d in f.holes]
            elif f.edge == "x1":
                parts.append(sbox(bx1, s0, bx1 + BA + F, s1))
                xb = bx1 + BA / 2
                bends.append({"p0": (xb, s0), "p1": (xb, s1)})
                holes += [{"kind": "round", "x": bx1 + BA + (hh - R), "y": s, "d": d} for s, hh, d in f.holes]
            elif f.edge == "y0":
                parts.append(sbox(s0, by0 - BA - F, s1, by0))
                yb = by0 - BA / 2
                bends.append({"p0": (s0, yb), "p1": (s1, yb)})
                holes += [{"kind": "round", "x": s, "y": by0 - BA - (hh - R), "d": d} for s, hh, d in f.holes]
            else:
                parts.append(sbox(s0, by1, s1, by1 + BA + F))
                yb = by1 + BA / 2
                bends.append({"p0": (s0, yb), "p1": (s1, yb)})
                holes += [{"kind": "round", "x": s, "y": by1 + BA + (hh - R), "d": d} for s, hh, d in f.holes]
            bends[-1].update({"edge": f.edge, "direction": label, "angle": 90.0, "radius": self.r,
                              "length": s1 - s0})
        for h in self.holes:
            if h[0] == "round":
                holes.append({"kind": "round", "x": h[1], "y": h[2], "d": h[3]})
            else:
                holes.append({"kind": "rect", "x": h[1], "y": h[2], "w": h[3], "h": h[4]})
        outline = unary_union(parts)
        if outline.geom_type != "Polygon":
            raise ValueError("El desarrollo no es una única región conexa")
        outline = Polygon(outline.exterior).simplify(1e-6)
        return FlatPattern(outline=outline, holes=holes, bends=bends, t=self.t)

    def bend_lengths(self) -> list[float]:
        return [self.flange_extent(f.edge)[1] - self.flange_extent(f.edge)[0] for f in self.flanges]


def bend_allowance(t: float, r: float, K: float, angle_deg: float = 90.0) -> float:
    return math.radians(angle_deg) * (r + K * t)


def bend_deduction(t: float, r: float, K: float, angle_deg: float = 90.0) -> float:
    """Deducción de plegado para líneas de molde exteriores (ángulo de plegado θ)."""
    th = math.radians(angle_deg)
    ossb = math.tan(th / 2) * (r + t)
    return 2 * ossb - bend_allowance(t, r, K, angle_deg)


@dataclass
class FlatPattern:
    outline: Polygon
    holes: list[dict[str, Any]]
    bends: list[dict[str, Any]]
    t: float

    @cached_property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.outline.bounds

    @property
    def width(self) -> float:
        b = self.bounds
        return b[2] - b[0]

    @property
    def height(self) -> float:
        b = self.bounds
        return b[3] - b[1]

    def holes_area(self) -> float:
        a = 0.0
        for h in self.holes:
            a += math.pi * h["d"] ** 2 / 4 if h["kind"] == "round" else h["w"] * h["h"]
        return a

    def net_area(self) -> float:
        return self.outline.area - self.holes_area()

    def cut_length(self) -> float:
        L = self.outline.exterior.length
        for h in self.holes:
            L += math.pi * h["d"] if h["kind"] == "round" else 2 * (h["w"] + h["h"])
        return L

    def normalized(self) -> "FlatPattern":
        """Copia trasladada para que el desarrollo empiece en (0, 0)."""
        from shapely.affinity import translate
        x0, y0 = self.bounds[0], self.bounds[1]
        holes = []
        for h in self.holes:
            h2 = dict(h)
            h2["x"] -= x0
            h2["y"] -= y0
            holes.append(h2)
        bends = []
        for b in self.bends:
            b2 = dict(b)
            b2["p0"] = (b["p0"][0] - x0, b["p0"][1] - y0)
            b2["p1"] = (b["p1"][0] - x0, b["p1"][1] - y0)
            bends.append(b2)
        return FlatPattern(translate(self.outline, -x0, -y0), holes, bends, self.t)


def analytic_volume(spec: SheetMetalSpec) -> float:
    """Volumen exacto de la pieza plegada a partir del desarrollo (área neta · t + corrección de cada pliegue)."""
    fp = spec.flat_pattern()
    expected = fp.net_area() * spec.t
    for L in spec.bend_lengths():
        expected += (math.pi / 2) * spec.t ** 2 * (0.5 - spec.K) * L
    return expected


def volume_consistency(spec: SheetMetalSpec, solid_volume: float) -> tuple[float, float]:
    """Devuelve (volumen esperado a partir del desarrollo, desviación relativa)."""
    expected = analytic_volume(spec)
    return expected, abs(solid_volume - expected) / expected


def perforation_grid(x0: float, y0: float, x1: float, y1: float, pitch: float, w: float,
                     h: float | None = None, shape: str = "rect") -> tuple[tuple, ...]:
    """Patrón regular de perforaciones centrado en la zona [x0,x1]×[y0,y1]."""
    h = h if h is not None else w
    nx = int((x1 - x0 - w) // pitch) + 1
    ny = int((y1 - y0 - h) // pitch) + 1
    if nx < 1 or ny < 1:
        return ()
    ox = x0 + (x1 - x0 - (nx - 1) * pitch) / 2
    oy = y0 + (y1 - y0 - (ny - 1) * pitch) / 2
    out = []
    for i in range(nx):
        for j in range(ny):
            if shape == "rect":
                out.append(("rect", ox + i * pitch, oy + j * pitch, w, h))
            else:
                out.append(("round", ox + i * pitch, oy + j * pitch, w))
    return tuple(out)
