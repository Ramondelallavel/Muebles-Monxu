"""Generación automática de planos técnicos a partir del modelo CAD (HLR exacto).

Planos: 01 conjunto general · 02 estructura (vistas y cotas) · 02B perfiles y lista de corte ·
03 piezas de chapa · 04 desarrollos · 05 soldaduras · 06 explosionado · 07 montaje · 08 despiece.
Todas las cotas se miden sobre la geometría del modelo y se registran por hoja.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

from .. import catalog
from ..cad import geometry as G
from ..core.model import PlatePart, ProfilePart, SheetPart, StandardPart
from . import hlr
from .drawing_kit import (FRAME, GREY, LW_DIM, LW_THICK, LW_THIN, SCALES, Drawing, choose_scale, fmt, place_view,
                          scale_label)

TB_RESERVED = (226.0, 6.0, 412.0, 80.0)


def _intersects(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _size(proj):
    b = proj["bbox"]
    return b[2] - b[0], b[3] - b[1]


class _Ctx:
    def __init__(self, model, plan, bom, eng, info):
        self.m, self.plan, self.bom, self.eng, self.info = model, plan, bom, eng, info
        self._cache: dict[tuple, dict] = {}

    def proj(self, key: str, insts, view: str, hidden=True):
        k = (key, view, hidden)
        if k not in self._cache:
            self._cache[k] = hlr.project([i.shape if hasattr(i, "shape") else i for i in insts], view, hidden)
        return self._cache[k]

    def inst(self, iid):
        return self.m.instance(iid)

    def group(self, *groups):
        return [i for i in self.m.instances if i.group in groups]


def _P(v, view, p):
    return v.P(*hlr.project_point(p, view))


# ============================================================================ disposición
def layout_ortho(projs: dict[str, dict], region, reserved=(), gap=24.0, pad=16.0, views=("alzado", "perfil", "planta")):
    wf, hf = _size(projs["alzado"])
    ws = _size(projs["perfil"])[0] if "perfil" in views else 0
    ht = _size(projs["planta"])[1] if "planta" in views else 0
    for s in SCALES:
        k = s[0] / s[1]
        ox = region[0] + pad
        top = region[3] - pad
        fr = (ox, top - hf * k, ox + wf * k, top)
        rects = {"alzado": fr}
        if "perfil" in views:
            rects["perfil"] = (fr[2] + gap, fr[1], fr[2] + gap + ws * k, top)
        if "planta" in views:
            rects["planta"] = (ox, fr[1] - gap - ht * k, ox + wf * k, fr[1] - gap)
        ok = True
        for r in rects.values():
            padded = (r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad)
            if r[0] < region[0] or r[1] - pad < region[1] or r[2] > region[2] or r[3] > region[3]:
                ok = False
            if any(_intersects(padded, z) for z in reserved):
                ok = False
        if ok:
            pl = {n: place_view(projs[n], k, rects[n][0], rects[n][1]) for n in rects}
            return s, pl
    raise ValueError("No se encuentra escala que permita disponer las vistas")


def fit_view(proj, rect, scales=SCALES, free=False):
    w, h = _size(proj)
    w, h = max(w, 1e-3), max(h, 1e-3)
    for s in ([] if free else scales):
        k = s[0] / s[1]
        if w * k <= rect[2] - rect[0] and h * k <= rect[3] - rect[1]:
            ox = rect[0] + (rect[2] - rect[0] - w * k) / 2
            oy = rect[1] + (rect[3] - rect[1] - h * k) / 2
            return s, place_view(proj, k, ox, oy)
    k = min((rect[2] - rect[0]) / w, (rect[3] - rect[1]) / h)
    ox = rect[0] + (rect[2] - rect[0] - w * k) / 2
    oy = rect[1] + (rect[3] - rect[1] - h * k) / 2
    return None, place_view(proj, k, ox, oy)


def balloons(d: Drawing, view, view_name, targets: list[tuple[str, Any]], above=True, spacing=10.0, y_off=14.0):
    """targets: [(etiqueta, punto 3D)] -> globos en fila sobre (o bajo) la vista, ordenados por x."""
    pts = sorted(((lbl, _P(view, view_name, p)) for lbl, p in targets), key=lambda t: t[1][0])
    if not pts:
        return
    n = len(pts)
    xs = []
    for _, tgt in pts:
        x = tgt[0] if not xs else max(tgt[0], xs[-1] + spacing)
        xs.append(x)
    over = xs[-1] - (view.ox + view.w + 5)
    if over > 0:                     # desplaza a la izquierda manteniendo la separación
        xs = [x - over for x in xs]
        for i in range(n - 2, -1, -1):
            xs[i] = min(xs[i], xs[i + 1] - spacing)
    y = view.oy + view.h + y_off if above else view.oy - y_off
    for (lbl, tgt), x in zip(pts, xs):
        d.balloon((x, y), tgt, lbl)


# ============================================================================ planos
def _support_line(m) -> str:
    """Nota de altura según el tipo de apoyo (pies niveladores regulables o ruedas)."""
    sups = m.structure.get("supports", [])
    c = catalog.component(sups[0]["component"]) if sups else None
    if c is None:
        return ""
    if c["category"].startswith("ruedas"):
        return f"Altura sobre ruedas Ø{c['wheel_d']:g} mm (altura de rueda {c['nominal_height']:g} mm, sin regulación)."
    return f"Altura con pies niveladores en posición nominal (regulación ±{c['adjust'] / 2:g} mm)."


EDGE_NAMES = {"y0": "delantero", "y1": "trasero", "x0": "izquierdo", "x1": "derecho"}


def bend_direction_text(spec) -> str:
    """Sentido de los pliegues de una chapa: único o, si se mezclan, los bordes plegados hacia arriba."""
    ups = [f.edge for f in spec.flanges if f.direction == "up"]
    if not ups:
        return "Pliegues a 90° hacia abajo"
    if len(ups) == len(spec.flanges):
        return "Pliegues a 90° hacia arriba"
    names = [EDGE_NAMES[e] for e in ("y0", "y1", "x0", "x1") if e in ups]
    return f"Pliegues a 90° hacia abajo; borde{'s' if len(names) > 1 else ''} {', '.join(names)} hacia arriba"


def plan_general(d: Drawing, X: _Ctx):
    m = X.m
    insts = m.instances
    projs = {v: X.proj("all", insts, v, hidden=False) for v in ("alzado", "perfil", "planta")}
    s, V = layout_ortho(projs, (28, 18, 405, 272), [TB_RESERVED])
    env = m.dims["envelope"]
    env_insts = [X.inst(i) for i in env["ids"]] if env.get("ids") else [i for i in insts if i.group in env["groups"]]
    lo = np.min([i.bbox[0] for i in env_insts], axis=0)
    hi = np.max([i.bbox[1] for i in env_insts], axis=0)
    nx, ny = env.get("names", ("LONGITUD", "ANCHURA"))
    d.new_sheet("01", "Conjunto general", scale_label(s), "Ver despiece (plano 08)")
    for n, v in V.items():
        v.label = {"alzado": "ALZADO", "perfil": "PERFIL IZQUIERDO", "planta": "PLANTA"}[n]
        v.draw(d, hidden=False)
    a, p, pl = V["alzado"], V["perfil"], V["planta"]
    # alzado: longitud y altura
    x0, ztop = _P(a, "alzado", (lo[0], 0, hi[2]))
    x1, _ = _P(a, "alzado", (hi[0], 0, hi[2]))
    d.dim_h(x0, x1, ztop, ztop, ztop + 9, hi[0] - lo[0], nx)
    _, yfloor = _P(a, "alzado", (0, 0, 0))
    xl = a.ox
    # niveles: (nombre, instancia[, cota explícita]); sin cota, la cara superior de la instancia
    levels = [(lv[0], lv[2] if len(lv) > 2 else X.inst(lv[1]).bbox[1][2]) for lv in m.dims.get("levels", [])]
    if len(levels) <= 1:
        d.dim_v(yfloor, ztop, xl, xl, xl - 9, hi[2], "ALTURA")
        for name, z in levels:
            _, ys = _P(a, "alzado", (0, 0, z))
            d.dim_v(yfloor, ys, xl, xl, xl - 17, z, name)
    else:     # cadena de cotas de niveles y altura total
        d.dim_v(yfloor, ztop, xl, xl, xl - 17, hi[2], "ALTURA")
        zs = [0.0] + sorted(z for _, z in levels)
        for k in range(len(zs) - 1):
            _, ya_ = _P(a, "alzado", (0, 0, zs[k]))
            _, yb_ = _P(a, "alzado", (0, 0, zs[k + 1]))
            d.dim_v(ya_, yb_, xl, xl, xl - 9, zs[k + 1] - zs[k], f"DIST_NIVEL_{k + 1}")
    # perfil: anchura
    u0, zt = _P(p, "perfil", (0, hi[1], hi[2]))
    u1, _ = _P(p, "perfil", (0, lo[1], hi[2]))
    d.dim_h(u0, u1, zt, zt, zt + 9, hi[1] - lo[1], ny)
    # planta
    xa, ya = _P(pl, "planta", (lo[0], lo[1], 0))
    xb, yb = _P(pl, "planta", (hi[0], hi[1], 0))
    d.dim_h(xa, xb, ya, ya, pl.oy - 9, hi[0] - lo[0])
    d.dim_v(ya, yb, pl.ox, pl.ox, pl.ox - 9, hi[1] - lo[1])
    # isométrica en el mayor hueco libre
    iso = X.proj("all", insts, "iso", hidden=False)
    cands = [(p.ox + p.w + 18, 86, 405, 270), (pl.ox + pl.w + 22, 86, 405, p.oy - 14)]
    best = None
    for r in cands:
        if r[2] - r[0] < 40 or r[3] - r[1] < 40:
            continue
        sc, vi = fit_view(iso, r, SCALES + [(1, 200)])
        if best is None or vi.scale > best[1].scale:
            best = (sc, vi)
    if best:
        vi = best[1]
        vi.label = "PERSPECTIVA ISOMÉTRICA" + (f" (E {scale_label(best[0])})" if best[0] else " (sin escala)")
        vi.draw(d, hidden=False, lw=0.35)
    # datos del producto
    eng = X.eng
    ps = m.params.values
    lines = [f"Producto: {m.family_name} {m.product_code}",
             f"Masa total calculada desde la geometría: {X.bom['totals']['total_mass']:.1f} kg",
             m.dims.get("load_text", ""),
             f"Estado de verificación: {eng['status_label']}",
             _support_line(m),
             f"Acabado: {catalog.finish(ps['ACABADO'])['name']}"]
    if pl.oy - 30 > 52:
        d.notes(32, pl.oy - 30, lines, width=190)
    else:
        d.notes(pl.ox + pl.w + 24, min(pl.oy + pl.h, 140), lines, width=max(60.0, 222 - pl.ox - pl.w - 24))


def plan_structure(d: Drawing, X: _Ctx):
    m = X.m
    est = X.group("EST")
    projs = {v: X.proj("est", est, v) for v in ("alzado", "perfil", "planta")}
    s, V = layout_ortho(projs, (28, 18, 405, 272), [TB_RESERVED, (300, 80, 412, 272)])
    d.new_sheet("02", "Estructura soldada: vistas y cotas", scale_label(s), m.params.values["MATERIAL_ESTRUCTURAL"])
    for n, v in V.items():
        v.label = {"alzado": "ALZADO", "perfil": "PERFIL IZQUIERDO", "planta": "PLANTA"}[n]
        v.draw(d)
    a, p, pl = V["alzado"], V["perfil"], V["planta"]
    lv = m.structure["levels"]
    legs = [X.inst(i) for i in m.structure["leg_ids"]]
    lo = np.min([i.bbox[0] for i in est], axis=0)
    hi = np.max([i.bbox[1] for i in est], axis=0)
    # alzado: posición de patas y cotas de bastidores
    x0, yz = _P(a, "alzado", (lo[0], 0, hi[2]))
    x1, _ = _P(a, "alzado", (hi[0], 0, hi[2]))
    d.dim_h(x0, x1, yz, yz, yz + 9, hi[0] - lo[0], "EST_LONGITUD")
    _, yb = _P(a, "alzado", (0, 0, lo[2]))
    d.dim_v(yb, yz, a.ox, a.ox, a.ox - 9, hi[2] - lo[2], "EST_ALTURA")
    lower = sorted((X.inst(lv[k]["long"][0]).bbox[1][2], k) for k in lv if k != "SUP")
    if len(lower) == 1:
        z, k = lower[0]
        _, yr = _P(a, "alzado", (0, 0, z))
        d.dim_v(yb, yr, a.ox, a.ox, a.ox - 17, z - lo[2], f"COTA_BASTIDOR_{k}")
    elif lower:
        zs = [lo[2]] + [z for z, _ in lower]
        for k in range(len(zs) - 1):
            ya_, yb_ = _P(a, "alzado", (0, 0, zs[k]))[1], _P(a, "alzado", (0, 0, zs[k + 1]))[1]
            d.dim_v(ya_, yb_, a.ox, a.ox, a.ox - 17, zs[k + 1] - zs[k])
    # planta: paso de travesaños intermedios (cadena)
    top = lv["SUP"]
    ids = [top["end"][0]] + top["int"] + [top["end"][1]]
    xs = [X.inst(i).bbox[0][0] + (X.inst(i).bbox[1][0] - X.inst(i).bbox[0][0]) / 2 for i in ids]
    yy = pl.oy - 9
    for k in range(len(xs) - 1):
        xa, ya = _P(pl, "planta", (xs[k], lo[1], 0))
        xb, _ = _P(pl, "planta", (xs[k + 1], lo[1], 0))
        d.dim_h(xa, xb, ya, ya, yy, xs[k + 1] - xs[k], f"PASO_TRAVESANO_{k + 1}")
    ya0 = _P(pl, "planta", (0, lo[1], 0))[1]
    ya1 = _P(pl, "planta", (0, hi[1], 0))[1]
    d.dim_v(ya0, ya1, pl.ox, pl.ox, pl.ox - 9, hi[1] - lo[1], "EST_ANCHURA")
    # perfil: separación de patas
    u0, zt = _P(p, "perfil", (0, legs[2].bbox[1][1], hi[2]))
    u1, _ = _P(p, "perfil", (0, legs[0].bbox[0][1], hi[2]))
    d.dim_h(u0, u1, zt, zt, zt + 9, legs[2].bbox[1][1] - legs[0].bbox[0][1])
    # globos en la planta
    reps = {}
    for i in est:
        if i.part.kind in ("perfil", "pletina", "normalizado") and i.part.key not in reps:
            reps[i.part.key] = i
    targets = [(str(i.part.pos), i.centroid if i.part.kind != "normalizado" else (i.bbox[0] + i.bbox[1]) / 2)
               for i in reps.values() if i.part.kind == "perfil"]
    balloons(d, a, "alzado", targets, above=True, y_off=20)
    d.notes(305, 268, ["Estructura soldada (subconjunto EST).",
                       f"Clase de ejecución {m.params.values['CLASE_EJECUCION']} según EN 1090-2.",
                       "Cotas a caras exteriores de perfil.",
                       "Planitud del plano de apoyo de encimera: EN ISO 13920 clase F.",
                       "Detalle de uniones soldadas: plano 05.",
                       "Longitudes de corte y mecanizados: plano 02B."], width_chars=40)


def plan_profiles(d: Drawing, X: _Ctx):
    m = X.m
    profs = sorted([p for p in m.parts.values() if isinstance(p, ProfilePart)], key=lambda p: p.pos)
    counts = defaultdict(int)
    for i in m.instances:
        counts[i.part.key] += 1
    d.new_sheet("02B", "Perfiles: longitudes de corte, mecanizados y plan de corte", "Sin escala",
                m.params.values["MATERIAL_ESTRUCTURAL"])
    y = 262.0
    maxL = max(p.length for p in profs)
    for p in profs:
        w = 150.0 * p.length / maxL + 20
        x0 = 40.0
        hgt = 7.0
        d.text(x0 - 6, y + 2, str(p.pos), 3.2, "r", bold=True)
        d.polyline([(x0, y), (x0 + w, y), (x0 + w, y + hgt), (x0, y + hgt), (x0, y)], LW_THICK)
        d.line((x0 - 3, y + hgt / 2), (x0 + w + 3, y + hgt / 2), LW_THIN, dash=[6, 1, 1, 1], color=GREY)
        for face, z, off, dia in p.holes:
            xx = x0 + w * z / p.length
            d.c.setLineWidth(LW_THIN)
            d.c.circle(xx, y + hgt / 2, 1.2)
        d.dim_h(x0, x0 + w, y + hgt, y + hgt, y + hgt + 4, p.length, f"L_{p.ref}", "geometria_pieza")
        desc = f"{p.ref}  {p.profile.code}  {p.material}  L={fmt(p.length)}  90°/90°  ×{counts[p.key]}"
        if p.holes:
            zs = sorted(h[2] for h in [(h[0], h[2], h[1]) for h in p.holes])
            desc += f"  Taladros Ø{p.holes[0][3]:g} en cara exterior a: " + ", ".join(fmt(h[1]) for h in p.holes)
        d.text(x0 + w + 6, y + 2, desc[:110], 2.4, "l")
        y -= 17
        if y < 95:
            break
    # plan de corte
    y -= 2
    d.text(32, y, "PLAN DE CORTE DE BARRAS", 3.2, "l", bold=True)
    y -= 7
    for c in X.plan["cutting"]:
        d.text(32, y, f"{c['profile']} {c['material']} — barras de {fmt(c['bar_length'])} mm: {c['n_bars']} "
                      f"(cota inferior {c['lower_bound']}, aprovechamiento {c['utilization'] * 100:.1f} %, sierra "
                      f"{fmt(c['kerf'])} mm)", 2.6)
        y -= 5
        for b in c["bars"]:
            x = 40.0
            W = 180.0
            d.polyline([(x, y), (x + W, y), (x + W, y + 3.5), (x, y + 3.5), (x, y)], LW_THIN)
            k = W / c["bar_length"]
            xx = x + c["trim"] * k
            for cut in b["cuts"]:
                ww = cut["length"] * k
                d.c.setFillColorRGB(0.82, 0.86, 0.9)
                d.c.rect(xx, y, ww, 3.5, stroke=1, fill=1)
                d.c.setFillColorRGB(0, 0, 0)
                if ww > 9:
                    d.text(xx + ww / 2, y + 0.9, cut["ref"].split("-")[-1], 2.0, "c")
                xx += ww + c["kerf"] * k
            d.text(x + W + 3, y + 0.6, f"Barra {b['bar']}: retal {fmt(b['remnant'])} mm"
                                     f"{' (aprovechable)' if b['remnant_reusable'] else ''}", 2.2)
            y -= 5.5
            if y < 22:
                return
        y -= 2


def plan_sheet_part(d: Drawing, X: _Ctx, part: SheetPart, number: str):
    sh = part.shape
    projs = {v: hlr.project([sh], v) for v in ("alzado", "perfil", "planta")}
    s, V = layout_ortho(projs, (28, 18, 405, 272), [TB_RESERVED, (290, 80, 412, 272)])
    d.new_sheet(number, f"Pieza de chapa: {part.name}", scale_label(s), f"{part.material} e={fmt(part.spec.t)}")
    for n, v in V.items():
        v.label = {"alzado": "ALZADO", "perfil": "PERFIL IZQUIERDO", "planta": "PLANTA"}[n]
        v.draw(d)
    spec = part.spec
    lo, hi = G.bbox(sh)
    a, pl, pf = V["alzado"], V["planta"], V["perfil"]
    xa, ya = _P(pl, "planta", (lo[0], lo[1], 0))
    xb, yb = _P(pl, "planta", (hi[0], hi[1], 0))
    d.dim_h(xa, xb, ya, ya, pl.oy - 9, hi[0] - lo[0], f"{part.ref}_LX")
    d.dim_v(ya, yb, pl.ox, pl.ox, pl.ox - 9, hi[1] - lo[1], f"{part.ref}_LY")
    _, z0 = _P(a, "alzado", (0, 0, lo[2]))
    _, z1 = _P(a, "alzado", (0, 0, hi[2]))
    if lo[2] < -1e-6 and hi[2] > 1e-6:     # pestañas hacia abajo (derecha) y peto hacia arriba (izquierda)
        _, zm = _P(a, "alzado", (0, 0, 0))
        d.dim_v(z0, zm, a.ox + a.w, a.ox + a.w, a.ox + a.w + 9, -lo[2], f"{part.ref}_ALA")
        d.dim_v(zm, z1, a.ox, a.ox, a.ox - 9, hi[2], f"{part.ref}_PETO")
    else:
        d.dim_v(z0, z1, a.ox + a.w, a.ox + a.w, a.ox + a.w + 9, hi[2] - lo[2], f"{part.ref}_ALA")
    if spec.notch[0]:
        nx = spec.notch[0]
        x1, _ = _P(pl, "planta", (nx, lo[1], 0))
        d.dim_h(xa, x1, yb, yb, pl.oy + pl.h + 7, nx, f"{part.ref}_ESCOTADURA")
    # sección por plano x = Lx/2 (detalle del pliegue), recortada a la zona de la pestaña delantera
    from shapely.geometry import LineString, box as sbox
    hf = spec.flanges[0].height
    win = sbox(-(hf + 15), -hf - 3, 3, 3)
    segs = []
    for pl_ in section_polylines(sh, (spec.Lx / 2, 0, 0), (1, 0, 0)):
        g = LineString([(-q[1], q[2]) for q in pl_]).intersection(win)
        for part_ in getattr(g, "geoms", [g]):
            if not part_.is_empty and part_.geom_type == "LineString":
                segs.append(list(part_.coords))
    rect = (296, 176, 404, 262)
    if segs:
        b = win.bounds
        sc = next((sc for sc in [(5, 1), (2, 1), (1, 1)] if (b[2] - b[0]) * sc[0] <= rect[2] - rect[0] - 14
                   and (b[3] - b[1]) * sc[0] <= rect[3] - rect[1] - 6), (1, 1))
        k = sc[0] / sc[1]
        ox, oy = rect[0] + 12, rect[1] + 3
        Q = lambda u, v: (ox + (u - b[0]) * k, oy + (v - b[1]) * k)
        for sg in segs:
            d.polyline([Q(*q) for q in sg], LW_THICK)
        d.dim_v(Q(0, -hf)[1], Q(0, 0)[1], Q(0, 0)[0], Q(0, 0)[0], Q(0, 0)[0] + 7, hf, f"{part.ref}_ALA_SECCION",
                "seccion")
        d.dim_h(Q(-spec.t, -hf)[0], Q(0, -hf)[0], Q(0, -hf)[1], Q(0, -hf)[1], Q(0, -hf)[1] - 4, spec.t,
                f"{part.ref}_ESPESOR", "seccion")
        d.text(Q(-spec.R, -spec.R)[0] - 2, Q(-spec.R, -spec.R)[1] - 4, f"Ri {fmt(spec.r)}", 2.6, "r")
        d.text((rect[0] + rect[2]) / 2, rect[1] - 6, f"SECCIÓN A-A (E {scale_label(sc)})", 3.0, "c", bold=True)
        d.notes(rect[0], rect[1] - 12, [f"Espesor t = {fmt(spec.t)} mm · Ri = {fmt(spec.r)} mm · K = {spec.K:.3f}",
                                        f"{bend_direction_text(spec)} · BD = {fmt(spec.BD, 3)} mm"], width=105)
    holes = sum(len(f.holes) for f in spec.flanges) + len(spec.holes)
    d.notes(296, 150, [f"Referencia: {part.ref}", f"Material: {catalog.material(part.material).name}",
                       f"Masa (desde sólido): {part.mass:.2f} kg", f"Taladros: {holes} uds — posiciones en "
                       "desarrollo (plano 04) y DXF", f"Acabado: {catalog.finish(part.finish)['name'] if part.finish else '—'}",
                       "Rebabas eliminadas. Aristas vivas matadas 0,5 mm."], width=105)


def section_polylines(shape, point, normal) -> list[list[tuple[float, float, float]]]:
    sec = BRepAlgoAPI_Section(shape.wrapped, gp_Pln(gp_Pnt(*point), gp_Dir(*normal)))
    sec.Build()
    out = []
    for e in cq.Shape.cast(sec.Shape()).Edges():
        n = 2 if e.geomType() == "LINE" else 12
        out.append([tuple(e.positionAt(i / n)) for i in range(n + 1)])
    return out


def plan_flat(d: Drawing, X: _Ctx, part: SheetPart, number: str):
    fp = part.flat.normalized()
    w, h = fp.width, fp.height
    rect = (52, 100, 400, 238)
    s = choose_scale(lambda k: w * k <= rect[2] - rect[0] and h * k <= rect[3] - rect[1])
    k = s[0] / s[1]
    d.new_sheet(number, f"Desarrollo: {part.name}", scale_label(s), f"{part.material} e={fmt(part.spec.t)}")
    ox, oy = rect[0] + (rect[2] - rect[0] - w * k) / 2, rect[1] + (rect[3] - rect[1] - h * k) / 2 + 4
    P = lambda x, y: (ox + x * k, oy + y * k)
    d.polyline([P(*q) for q in fp.outline.exterior.coords], LW_THICK)
    for ho in fp.holes:
        if ho["kind"] == "round":
            cx, cy = P(ho["x"], ho["y"])
            d.c.setLineWidth(LW_THIN)
            d.c.circle(cx, cy, max(0.4, ho["d"] / 2 * k))
        else:
            x0, y0 = P(ho["x"] - ho["w"] / 2, ho["y"] - ho["h"] / 2)
            d.c.setLineWidth(LW_THIN)
            d.c.rect(x0, y0, ho["w"] * k, ho["h"] * k)
    xs, ys = [], []
    for b in fp.bends:
        p0, p1 = P(*b["p0"]), P(*b["p1"])
        d.line(p0, p1, LW_THIN, dash=[6, 1.5, 1, 1.5])
        mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
        horiz = abs(p1[1] - p0[1]) < 1e-6
        d.text(mid[0] + (0 if horiz else -1.5), mid[1] + (1.2 if horiz else 0), f"{b['direction']} 90° Ri{fmt(b['radius'])}",
               2.2, "c", angle=0 if horiz else 90, color=GREY)
        if horiz:
            ys.append(b["p0"][1])
        else:
            xs.append(b["p0"][0])
    d.dim_h(*P(0, 0)[:1], P(w, 0)[0], oy, oy, oy - 14, w, f"{part.ref}_DESARROLLO_X", "desarrollo")
    d.dim_v(P(0, 0)[1], P(0, h)[1], ox, ox, ox - 14, h, f"{part.ref}_DESARROLLO_Y", "desarrollo")
    chain = [0.0] + sorted(xs) + [w]
    for a_, b_ in zip(chain[:-1], chain[1:]):
        d.dim_h(P(a_, 0)[0], P(b_, 0)[0], oy, oy, oy - 7, b_ - a_)
    chain = [0.0] + sorted(ys) + [h]
    for a_, b_ in zip(chain[:-1], chain[1:]):
        d.dim_v(P(0, a_)[1], P(0, b_)[1], ox, ox, ox - 7, b_ - a_)
    spec = part.spec
    rows = []
    for n, ho in enumerate(fp.holes[:40], start=1):
        rows.append([n, round(ho["x"], 2), round(ho["y"], 2),
                     f"Ø{fmt(ho['d'])}" if ho["kind"] == "round" else f"□{fmt(ho['w'])}x{fmt(ho['h'])}"])
    if rows:
        d.table(40, 86, [("Nº", 10, "c"), ("X", 22, "r"), ("Y", 22, "r"), ("Forma", 22, "c")], rows[:12], row_h=4.4,
                text_h=2.2)
        if len(rows) > 12:
            d.table(122, 86, [("Nº", 10, "c"), ("X", 22, "r"), ("Y", 22, "r"), ("Forma", 22, "c")], rows[12:24],
                    row_h=4.4, text_h=2.2)
    d.notes(32, 268, [
        f"Desarrollo plano de {part.ref} — origen en la esquina inferior izquierda · espesor {fmt(spec.t)} mm · Ri "
        f"{fmt(spec.r)} mm · K {spec.K:.3f} (DIN 6935) · BA = π/2·(Ri+K·t) = {fmt(spec.BA, 3)} mm · BD = "
        f"{fmt(spec.BD, 3)} mm.",
        f"Contorno neto {fmt(fp.net_area() / 1e6, 4)} m² · longitud de corte {fmt(fp.cut_length() / 1000, 2)} m · "
        f"fichero de corte 03_DXF_CORTE/{part.ref}.dxf (escala 1:1, mm) · tolerancias EN ISO 9013 clase 2.",
    ], width=370)


def plan_plates(d: Drawing, X: _Ctx, number: str):
    plates = [p for p in X.m.parts.values() if isinstance(p, PlatePart)]
    if not plates:
        return
    d.new_sheet(number, "Pletinas cortadas por láser", "2:1", ", ".join(sorted({p.material for p in plates})))
    x = 50.0
    for p in sorted(plates, key=lambda p: p.pos):
        k = 2.0
        y = 170.0
        pts = []
        from .dxf import rounded_rect_points
        poly = p.outline_2d()
        d.polyline([(x + q[0] * k, y + q[1] * k) for q in poly.exterior.coords], LW_THICK)
        for hx, hy, hd in p.holes:
            d.c.setLineWidth(LW_THIN)
            d.c.circle(x + hx * k, y + hy * k, hd / 2 * k)
            d.line((x + hx * k - hd * k, y + hy * k), (x + hx * k + hd * k, y + hy * k), LW_THIN, dash=[3, 1, 1, 1])
            d.line((x + hx * k, y + hy * k - hd * k), (x + hx * k, y + hy * k + hd * k), LW_THIN, dash=[3, 1, 1, 1])
            d.text(x + hx * k + hd * k / 2 + 2, y + hy * k + hd * k / 2 + 2, f"Ø{fmt(hd)}", 2.8)
        d.dim_h(x, x + p.w * k, y, y, y - 9, p.w, f"{p.ref}_W", "geometria_pieza")
        d.dim_v(y, y + p.h * k, x, x, x - 9, p.h, f"{p.ref}_H", "geometria_pieza")
        d.text(x, y + p.h * k + 12, f"Pos. {p.pos} — {p.ref}", 3.0, bold=True)
        d.text(x, y + p.h * k + 7, f"{p.name} · {p.material} e={fmt(p.t)} · R{fmt(p.corner_r)}", 2.6)
        x += p.w * k + 70


def _detail(d, X, joint, members, rect, title, half=60.0):
    loc = np.array(joint.location, float)
    clip = G.box(*(loc - half), *(loc + half))
    shapes = []
    for iid in members:
        try:
            sh = X.inst(iid).shape.intersect(clip)
            if sh.Volume() > 1:
                shapes.append(sh)
        except Exception:
            pass
    if not shapes:
        return
    proj = hlr.project(shapes, "iso", hidden=False)
    sc, v = fit_view(proj, (rect[0] + 4, rect[1] + 10, rect[2] - 30, rect[3] - 8), [(1, 1), (1, 2), (1, 5)])
    v.draw(d, hidden=False, lw=0.35)
    d.c.setLineWidth(0.3)
    d.c.rect(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
    d.text(rect[0] + 3, rect[3] - 5, f"{title} (E {scale_label(sc) if sc else 'S/E'})", 2.8, "l", bold=True)
    tgt = _P(v, "iso", loc)
    d.weld_symbol(tgt, (min(rect[2] - 28, tgt[0] + 14), min(rect[3] - 10, tgt[1] + 14)), joint.weld["a"],
                  joint.weld.get("all_around", True), "135")


def plan_welds(d: Drawing, X: _Ctx):
    m = X.m
    est = X.group("EST")
    proj = X.proj("est", est, "alzado", hidden=False)
    rect = (35, 152, 290, 248)
    s, v = fit_view(proj, rect)
    d.new_sheet("05", "Uniones soldadas: símbolos, detalles y secuencia", scale_label(s) if s else "S/E",
                m.params.values["MATERIAL_ESTRUCTURAL"])
    v.label = "ALZADO DE LA ESTRUCTURA"
    v.label_offset = 8
    v.draw(d, hidden=False)
    groups: dict[str, list] = defaultdict(list)
    for j in m.joints:
        if j.kind == "soldadura":
            groups[j.description].append(j)
    rows = []
    placed = []
    for n, (desc, js) in enumerate(sorted(groups.items()), start=1):
        j = js[0]
        tgt = _P(v, "alzado", j.location)
        left = tgt[0] < v.ox + v.w / 2
        side = -1 if left else 1
        y = v.oy + v.h + 6
        while any(abs(y - py) < 6.5 and (px < v.ox + v.w / 2) == left for px, py in placed):
            y += 6.5
        bx = (v.ox - 4) if left else (v.ox + v.w + 4)
        if y < 268:
            d.weld_symbol(tgt, (bx, y), j.weld["a"], j.weld.get("all_around", True), "135", side=side)
            d.text(bx + 24 * side + (3 if side > 0 else -3), y + 1.2, f"({n})", 2.4, "l" if side > 0 else "r")
            placed.append((bx, y))
        L = j.weld["length"]
        rows.append([n, desc, f"a{fmt(j.weld['a'])}", "perimetral" if j.weld.get("all_around") else "3 cordones",
                     fmt(L), len(js), fmt(L * len(js)), j.weld.get("process", "135")])
    d.table(32, 140, [("Nº", 8, "c"), ("Unión", 80, "l"), ("Garganta", 15, "c"), ("Tipo", 19, "c"),
                      ("L unit. mm", 18, "r"), ("Uds", 9, "c"), ("L total mm", 19, "r"), ("Proceso", 22, "c")],
            rows, row_h=4.4, text_h=2.2)
    top_long = m.structure["levels"]["SUP"]["long"][0]
    jl = next((j for j in m.joints if j.id == f"J.{top_long}.0"), None)
    jp = next((j for j in m.joints if j.id.startswith("J.PLACA.")), None)
    if jl:
        _detail(d, X, jl, jl.members, (300, 205, 405, 268), "DETALLE A: LARGUERO–PATA", 70)
    if jp:
        _detail(d, X, jp, jp.members + (jp.id.replace("J.PLACA", "EST.TUERCA"),), (300, 140, 405, 203),
                "DETALLE B: PLACA BASE", 45)
    w = X.plan["welding"]
    d.notes(300, 134, [
        "NOTAS DE SOLDADURA",
        "Representación simbólica EN ISO 2553. Proceso 135 (MAG, hilo macizo G3Si1).",
        f"Cordón total {fmt(w['total_length_mm'] / 1000, 2)} m · depositado {fmt(w['deposit_kg'], 3)} kg · hilo "
        f"{fmt(w['wire_kg'], 3)} kg · gas {fmt(w['gas_l'], 0)} l.",
        f"Calidad EN ISO 5817-C · {m.params.values['CLASE_EJECUCION']} (EN 1090-2).",
        "Secuencia: 1) puntear bastidor superior en mesa plana con escuadras; 2) puntear patas y verificar "
        "diagonales; 3) bastidor inferior; 4) soldar alternando esquinas opuestas; 5) placas base y tuercas; "
        "6) enderezar, amolar caras enrasadas y verificar planitud.",
        "Pared de 2 mm: cordones cortos alternos para limitar la distorsión.",
        "Garganta a < 3 mm: requiere WPS cualificada (EN ISO 15614-1)." if any(
            j.weld["a"] < 3 for j in m.joints if j.kind == "soldadura") else "",
    ], h=2.2, width=104, bold_first=True)


def plan_exploded(d: Drawing, X: _Ctx):
    m = X.m
    moved = []
    targets = {}
    for i in m.instances:
        ex = np.array(m.subassemblies[i.group].explode) + np.array(i.tags.get("explode_extra", (0, 0, 0)))
        T = G.translation(*ex) @ i.T
        moved.append(G.place(i.part.shape, T))
        if i.part.key not in targets:
            c = (i.bbox[0] + i.bbox[1]) / 2 + ex
            targets[i.part.key] = (str(i.part.pos), c)
    proj = hlr.project(moved, "iso", hidden=False)
    rect = (35, 30, 295, 248)
    s, v = fit_view(proj, rect, SCALES + [(1, 200)])
    d.new_sheet("06", "Vista explosionada", scale_label(s) if s else "S/E", "Ver despiece")
    v.label = "PERSPECTIVA ISOMÉTRICA EXPLOSIONADA"
    v.draw(d, hidden=False, lw=0.3)
    balloons(d, v, "iso", list(targets.values()), above=True, y_off=8, spacing=9)
    rows = [[r["pos"], r["ref"].split("-")[-1] if r["kind"] != "normalizado" else "N", r["description"], r["qty"]]
            for r in X.bom["rows"]]
    d.table(300, 262, [("Pos", 9, "c"), ("Ref", 10, "c"), ("Descripción", 70, "l"), ("Cant", 11, "c")], rows,
            row_h=4.6, text_h=2.2)


def plan_assembly(d: Drawing, X: _Ctx):
    m = X.m
    order = sorted(m.subassemblies.values(), key=lambda s: s.step)
    d.new_sheet("07", "Instrucciones de montaje", "S/E", "—")
    cells = [(28, 178, 152, 270), (156, 178, 280, 270), (284, 178, 408, 270), (28, 84, 152, 174),
             (156, 84, 280, 174)]
    texts = {
        "EST": "Recepción de la estructura soldada y pintada. Insertar las tuercas remachables M6 en los taladros "
               "Ø9,1 de largueros y travesaños con remachadora manual.",
        "APO": "Roscar los pies niveladores en las tuercas soldadas de las placas base. Nivelar la mesa en su "
               "emplazamiento (nivel de burbuja sobre encimera al final).",
        "BAL": "Colocar la balda sobre el bastidor inferior, con las escotaduras alrededor de las patas. Fijar con "
               "tornillos ISO 7380 M6x12 (par 8 N·m, llave Allen 4 mm).",
        "ENC": "Colocar la encimera sobre el bastidor superior y fijarla con tornillos ISO 7380 M6x12 por las "
               "pestañas (par 8 N·m). Apretar en cruz desde el centro.",
    }
    texts.update(m.structure.get("assembly_texts", {}))
    shown: list = []
    for n, sa in enumerate(order[:4]):
        shown += [i for i in m.instances if i.group == sa.id]
        proj = hlr.project([i.shape for i in shown], "iso", hidden=False)
        cell = cells[n]
        _, v = fit_view(proj, (cell[0] + 2, cell[1] + 18, cell[2] - 2, cell[3] - 9), [(1, 10), (1, 20)], free=True)
        v.draw(d, hidden=False, lw=0.25)
        d.c.setLineWidth(0.3)
        d.c.rect(cell[0], cell[1], cell[2] - cell[0], cell[3] - cell[1])
        d.text(cell[0] + 3, cell[3] - 6, f"PASO {n + 1}: {sa.name.upper()}", 3.0, "l", bold=True)
        d.notes(cell[0] + 3, cell[1] + 14, [texts.get(sa.id, "")], h=2.1, width=118)
    d.c.setLineWidth(0.3)
    d.c.rect(284, 84, 124, 90)
    d.notes(287, 170, ["HERRAMIENTAS:", "· Remachadora para tuercas M6", "· Llave Allen 4 mm (dinamométrica)",
                       "· Llave fija 17/19 para contratuerca de pies", "· Nivel de burbuja", "",
                       "PARES DE APRIETE:", "· ISO 7380 M6 8.8 en remachable de acero: 8 N·m", "",
                       "DESMONTAJE:", "Encimera y balda desmontables (uniones atornilladas). La estructura es un",
                       "subconjunto soldado no desmontable.", "",
                       "SEGURIDAD:", "Manipular la encimera entre dos personas; usar guantes",
                       "(cantos de chapa)."], h=2.2, width=118)


def plan_bom(d: Drawing, X: _Ctx):
    rows = [[r["pos"], r["ref"], r["description"], r["material"] or "", r["thickness"], r["length"], r["width"],
             r["qty"], r["unit_mass"], r["total_mass"]] for r in X.bom["rows"]]
    d.new_sheet("08", "Despiece y lista de materiales", "—", "Ver lista")
    y = d.table(30, 268, [("Pos", 10, "c"), ("Referencia", 42, "l"), ("Descripción", 105, "l"), ("Material", 42, "l"),
                          ("Espesor", 16, "r"), ("Largo", 20, "r"), ("Ancho", 18, "r"), ("Cant.", 13, "c"),
                          ("Peso unit. kg", 22, "r"), ("Peso total kg", 22, "r")], rows, row_h=5.2, text_h=2.4)
    t = X.bom["totals"]
    d.notes(30, y - 6, [f"Componentes: {t['components']} ({t['manufactured_parts']} fabricados, {t['standard_parts']} "
                        f"normalizados) · Referencias distintas: {t['distinct_parts']} · Masa total: "
                        f"{t['total_mass']:.2f} kg (calculada desde los sólidos).",
                        "Metros de perfil: " + "; ".join(f"{k}: {v:.3f} m" for k, v in t["profile_meters"].items()),
                        "Superficie de chapa: " + "; ".join(f"{k}: {v:.4f} m²" for k, v in t["sheet_area_m2"].items())],
            width_chars=150)


def generate(model, plan, bom, eng, info, path: Path) -> dict[str, Any]:
    X = _Ctx(model, plan, bom, eng, info)
    sheets = [p for p in model.parts.values() if isinstance(p, SheetPart)]
    plates = [p for p in model.parts.values() if isinstance(p, PlatePart)]
    total = 2 + 1 + len(sheets) * 2 + (1 if plates else 0) + 4
    info = dict(info, total_sheets=total)
    d = Drawing(str(path), info)
    plan_general(d, X)
    plan_structure(d, X)
    plan_profiles(d, X)
    for n, p in enumerate(sorted(sheets, key=lambda p: p.pos), start=1):
        plan_sheet_part(d, X, p, f"03.{n}")
    for n, p in enumerate(sorted(sheets, key=lambda p: p.pos), start=1):
        plan_flat(d, X, p, f"04.{n}")
    if plates:
        plan_plates(d, X, f"04.{len(sheets) + 1}")
    plan_welds(d, X)
    plan_exploded(d, X)
    plan_assembly(d, X)
    plan_bom(d, X)
    d.finish()
    return {"path": str(path), "sheets": d.pages, "total": len(d.pages)}
