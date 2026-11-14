"""DXF de fabricación a escala 1:1 en milímetros con capas separadas (corte, plegado, grabado, información)."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import bbox as ezbbox

from ..core.model import PlatePart, SheetPart

LAYERS = {
    "CORTE_EXTERIOR": {"color": 7, "linetype": "CONTINUOUS"},
    "CORTE_INTERIOR": {"color": 1, "linetype": "CONTINUOUS"},
    "PLEGADO_ABAJO": {"color": 3, "linetype": "DASHDOT"},
    "PLEGADO_ARRIBA": {"color": 4, "linetype": "DASHDOT"},
    "GRABADO": {"color": 2, "linetype": "CONTINUOUS"},
    "INFO": {"color": 8, "linetype": "CONTINUOUS"},
    "FORMATO": {"color": 9, "linetype": "CONTINUOUS"},
    "RETAL": {"color": 5, "linetype": "DASHED"},
}
CUT_LAYERS = ("CORTE_EXTERIOR", "CORTE_INTERIOR")


def new_doc() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    for name, a in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=a["color"], linetype=a["linetype"])
    return doc


def rounded_rect_points(w: float, h: float, r: float):
    """Contorno de rectángulo con esquinas redondeadas como LWPOLYLINE con 'bulge' (arcos exactos)."""
    if r <= 0:
        return [(0, 0, 0), (w, 0, 0), (w, h, 0), (0, h, 0)]
    b = math.tan(math.radians(90) / 4)
    return [(r, 0, 0), (w - r, 0, b), (w, r, 0), (w, h - r, b), (w - r, h, 0), (r, h, b), (0, h - r, 0), (0, r, b)]


def _transform(x, y, tr):
    """tr = (dx, dy, rot90, w_rot_ref) -> aplica rotación de 90° y traslación."""
    dx, dy, rot, ref_h = tr
    if rot:
        x, y = ref_h - y, x
    return x + dx, y + dy


def add_part_geometry(msp, part, tr=(0.0, 0.0, False, 0.0), label: str | None = None, info: bool = True) -> None:
    if isinstance(part, SheetPart):
        fp = part.flat.normalized()
        ref_h = fp.height
        pts = [_transform(x, y, (*tr[:3], ref_h)) for x, y in list(fp.outline.exterior.coords)[:-1]]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "CORTE_EXTERIOR"})
        for h in fp.holes:
            cx, cy = _transform(h["x"], h["y"], (*tr[:3], ref_h))
            if h["kind"] == "round":
                msp.add_circle((cx, cy), h["d"] / 2, dxfattribs={"layer": "CORTE_INTERIOR"})
            else:
                w, hh = (h["h"], h["w"]) if tr[2] else (h["w"], h["h"])
                msp.add_lwpolyline([(cx - w / 2, cy - hh / 2), (cx + w / 2, cy - hh / 2), (cx + w / 2, cy + hh / 2),
                                    (cx - w / 2, cy + hh / 2)], close=True, dxfattribs={"layer": "CORTE_INTERIOR"})
        for b in fp.bends:
            p0 = _transform(*b["p0"], (*tr[:3], ref_h))
            p1 = _transform(*b["p1"], (*tr[:3], ref_h))
            lay = "PLEGADO_ABAJO" if b["direction"] == "ABAJO" else "PLEGADO_ARRIBA"
            msp.add_line(p0, p1, dxfattribs={"layer": lay})
            if info:
                mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                ang = math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))
                if ang > 90 or ang < -90:
                    ang += 180
                msp.add_text(f"{b['direction']} 90° Ri{b['radius']:g}", height=4,
                             dxfattribs={"layer": "INFO", "rotation": ang}).set_placement(mid)
        w, h = (fp.height, fp.width) if tr[2] else (fp.width, fp.height)
    elif isinstance(part, PlatePart):
        pts = rounded_rect_points(part.w, part.h, part.corner_r)
        ref_h = part.h
        out = []
        for x, y, bulge in pts:
            X, Y = _transform(x, y, (*tr[:3], ref_h))
            out.append((X, Y, 0, 0, bulge))
        msp.add_lwpolyline(out, format="xyseb", close=True, dxfattribs={"layer": "CORTE_EXTERIOR"})
        for x, y, d in part.holes:
            msp.add_circle(_transform(x, y, (*tr[:3], ref_h)), d / 2, dxfattribs={"layer": "CORTE_INTERIOR"})
        w, h = (part.h, part.w) if tr[2] else (part.w, part.h)
    else:
        raise TypeError("Sólo piezas de chapa y pletinas generan DXF de corte")
    if label:
        size = max(3.0, min(8.0, min(w, h) / 12))
        msp.add_text(label, height=size, dxfattribs={"layer": "GRABADO"}).set_placement(
            (tr[0] + w / 2, tr[1] + h / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)


def export_part_dxf(part, path: Path, project: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = new_doc()
    msp = doc.modelspace()
    add_part_geometry(msp, part, label=part.ref)
    t = part.spec.t if isinstance(part, SheetPart) else part.t
    note = f"{part.ref} | {part.name} | {part.material} e={t:g} mm | Escala 1:1 | mm"
    if project:
        note += f" | {project.get('code', '')} Rev.{project.get('revision', '')}"
    msp.add_text(note, height=4, dxfattribs={"layer": "INFO"}).set_placement((0, -15))
    doc.saveas(path)
    return verify_dxf(path)


def export_nesting_dxf(nest: dict[str, Any], parts_by_ref: dict[str, Any], path_pattern: str) -> list[Path]:
    """Un DXF 1:1 por chapa del anidado comprado: contorno de la chapa (formato, corte a medida o retal del
    inventario), piezas colocadas y, si existe, el retal reutilizable en la capa RETAL."""
    paths = []
    total = len(nest["sheets"])
    for sh in nest["sheets"]:
        doc = new_doc()
        msp = doc.modelspace()
        L, W = sh.get("length", nest["length"]), sh.get("width", nest["width"])
        msp.add_lwpolyline([(0, 0), (L, 0), (L, W), (0, W)], close=True, dxfattribs={"layer": "FORMATO"})
        for pl in sh["placements"]:
            part = parts_by_ref[pl["ref"]]
            add_part_geometry(msp, part, (pl["x"], pl["y"], pl["rot"], 0.0), label=pl["ref"], info=False)
        rem = sh.get("remnant")
        if rem:
            x0, y0 = (rem["at"], 0.0) if rem["axis"] == "x" else (0.0, rem["at"])
            msp.add_lwpolyline([(x0, y0), (x0 + rem["length"], y0), (x0 + rem["length"], y0 + rem["width"]),
                                (x0, y0 + rem["width"])], close=True, dxfattribs={"layer": "RETAL"})
        msp.add_text(f"Chapa {nest['material']} e={nest['thickness']:g} mm  {sheet_label(nest, sh)}  "
                     f"hoja {sh['sheet']}/{total}  aprovechamiento {sh['utilization'] * 100:.1f} %",
                     height=10, dxfattribs={"layer": "INFO"}).set_placement((0, -25))
        p = Path(path_pattern.format(n=sh["sheet"]))
        doc.saveas(p)
        paths.append(p)
    return paths


def sheet_label(nest: dict[str, Any], sh: dict[str, Any]) -> str:
    """Rótulo de la chapa comprada: formato comercial, corte a medida o retal del inventario."""
    mode = sh.get("mode") or {"comercial": "formato"}.get(sh.get("source", "comercial"), sh.get("source"))
    L, W = sh.get("length", nest["length"]), sh.get("width", nest["width"])
    if mode == "corte_medida":
        return f"corte a medida {L:.0f}x{W:.0f}"
    if mode == "retal":
        return f"retal {sh.get('stock_id')} {L:.0f}x{W:.0f}"
    return f"formato {nest['format']}"


def verify_nesting_dxf(path: Path) -> dict[str, Any]:
    """Relee un DXF de anidado: contornos exteriores de corte y dimensiones del contorno de la chapa (FORMATO)."""
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    cut = [e for e in msp if e.dxf.layer == "CORTE_EXTERIOR" and e.dxftype() == "LWPOLYLINE"]
    fmt = next((e for e in msp if e.dxf.layer == "FORMATO" and e.dxftype() == "LWPOLYLINE"), None)
    size = None
    if fmt is not None:
        pts = [(p[0], p[1]) for p in fmt.get_points()]
        size = (max(x for x, _ in pts) - min(x for x, _ in pts), max(y for _, y in pts) - min(y for _, y in pts))
    return {"cut_contours": len(cut), "format": size, "errors": len(doc.audit().errors)}


def verify_dxf(path: Path) -> dict[str, Any]:
    """Relee el DXF, ejecuta la auditoría de ezdxf y mide la geometría de corte."""
    doc = ezdxf.readfile(path)
    auditor = doc.audit()
    msp = doc.modelspace()
    cut = [e for e in msp if e.dxf.layer in CUT_LAYERS]
    ext = ezbbox.extents(cut)
    layers = sorted({e.dxf.layer for e in msp})
    closed = all(e.closed for e in cut if e.dxftype() == "LWPOLYLINE")
    return {"path": str(path), "errors": len(auditor.errors), "fixes": len(auditor.fixes), "units": doc.units,
            "insunits": doc.header.get("$INSUNITS"), "layers": layers, "closed_contours": closed,
            "cut_entities": len(cut), "width": round(ext.size.x, 3) if ext.has_data else None,
            "height": round(ext.size.y, 3) if ext.has_data else None}
