"""Optimización de fabricación: corte de barras (1D) y anidado de chapa (2D).

* Barras: Best-Fit Decreasing con ancho de sierra, refrentado inicial y clasificación de retales;
  se informa la cota inferior teórica para valorar la optimalidad.
* Chapa: MaxRects (Best Short Side Fit) sobre la envolvente rectangular de cada desarrollo, con
  separación entre piezas, ancho de corte, márgenes, rotación opcional y dirección de laminación.
  El anidado se realiza por envolvente rectangular (no anidado de forma libre).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ============================================================================ 1D
def optimize_bars(pieces: list[dict[str, Any]], bar_length: float = 6000.0, kerf: float = 3.0,
                  trim: float = 10.0, reusable_min: float = 500.0) -> dict[str, Any]:
    """pieces: [{"label", "ref", "length", "qty"}] de un mismo perfil y material."""
    items = []
    for p in pieces:
        if p["length"] + trim + kerf > bar_length:
            raise ValueError(f"La pieza {p['ref']} ({p['length']} mm) supera la longitud de barra {bar_length} mm")
        items += [dict(p)] * int(p["qty"])
    items.sort(key=lambda p: -p["length"])
    bars: list[dict[str, Any]] = []
    for it in items:
        need = it["length"] + kerf
        best, best_rem = None, None
        for b in bars:
            rem = b["free"] - need
            if rem >= -kerf + 1e-9 and (best_rem is None or rem < best_rem):
                best, best_rem = b, rem
        if best is None:
            best = {"cuts": [], "free": bar_length - trim}
            bars.append(best)
        best["cuts"].append({"ref": it["ref"], "label": it.get("label", ""), "length": it["length"]})
        best["free"] -= need
    total_pieces = sum(p["length"] for p in items)
    out = []
    for n, b in enumerate(bars, start=1):
        rem = max(0.0, b["free"])
        out.append({"bar": n, "cuts": b["cuts"], "used": round(sum(c["length"] for c in b["cuts"]), 1),
                    "kerf_loss": round(kerf * len(b["cuts"]) + trim, 1), "remnant": round(rem, 1),
                    "remnant_reusable": rem >= reusable_min})
    lb = math.ceil(sum(p["length"] + kerf for p in items) / (bar_length - trim)) if items else 0
    nb = len(bars)
    return {"bar_length": bar_length, "kerf": kerf, "trim": trim, "reusable_min": reusable_min, "bars": out,
            "n_bars": nb, "lower_bound": lb, "optimal": nb == lb, "pieces": len(items),
            "pieces_length": round(total_pieces, 1),
            "utilization": round(total_pieces / (nb * bar_length), 4) if nb else 0.0,
            "reusable_remnants": [b["remnant"] for b in out if b["remnant_reusable"]],
            "scrap": round(sum(b["remnant"] for b in out if not b["remnant_reusable"]) +
                           sum(b["kerf_loss"] for b in out), 1)}


# ============================================================================ 2D
@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    def contains(self, o: "Rect") -> bool:
        return o.x >= self.x - 1e-9 and o.y >= self.y - 1e-9 and o.x + o.w <= self.x + self.w + 1e-9 and \
            o.y + o.h <= self.y + self.h + 1e-9


@dataclass
class _Bin:
    W: float
    H: float
    free: list[Rect] = field(default_factory=list)
    used: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        self.free = [Rect(0, 0, self.W, self.H)]

    def find(self, w, h, allow_rot):
        best = None
        for fr in self.free:
            for rot, (ww, hh) in ((False, (w, h)), (True, (h, w))):
                if rot and not allow_rot:
                    continue
                if ww <= fr.w + 1e-9 and hh <= fr.h + 1e-9:
                    short = min(fr.w - ww, fr.h - hh)
                    long_ = max(fr.w - ww, fr.h - hh)
                    key = (short, long_)
                    if best is None or key < best[0]:
                        best = (key, Rect(fr.x, fr.y, ww, hh), rot)
        return best

    def place(self, r: Rect):
        new_free = []
        for fr in self.free:
            if r.x >= fr.x + fr.w or r.x + r.w <= fr.x or r.y >= fr.y + fr.h or r.y + r.h <= fr.y:
                new_free.append(fr)
                continue
            if r.x > fr.x:
                new_free.append(Rect(fr.x, fr.y, r.x - fr.x, fr.h))
            if r.x + r.w < fr.x + fr.w:
                new_free.append(Rect(r.x + r.w, fr.y, fr.x + fr.w - r.x - r.w, fr.h))
            if r.y > fr.y:
                new_free.append(Rect(fr.x, fr.y, fr.w, r.y - fr.y))
            if r.y + r.h < fr.y + fr.h:
                new_free.append(Rect(fr.x, r.y + r.h, fr.w, fr.y + fr.h - r.y - r.h))
        pruned = []
        for i, a in enumerate(new_free):
            if a.w <= 1e-9 or a.h <= 1e-9:
                continue
            if any(j != i and b.contains(a) and not (a.contains(b) and j > i) for j, b in enumerate(new_free)):
                continue
            pruned.append(a)
        self.free = pruned


def nest_sheets(parts: list[dict[str, Any]], sheet_l: float, sheet_w: float, margin: float = 10.0,
                spacing: float = 8.0, kerf: float = 0.3) -> dict[str, Any]:
    """parts: [{"ref", "w", "h", "qty", "area", "rotate"}]; w = dimensión en la dirección de laminación."""
    gap = spacing + kerf
    UW, UH = sheet_l - 2 * margin + gap, sheet_w - 2 * margin + gap
    items = []
    for p in parts:
        if not ((p["w"] + gap <= UW and p["h"] + gap <= UH) or
                (p.get("rotate", True) and p["h"] + gap <= UW and p["w"] + gap <= UH)):
            return {"feasible": False, "reason": f"{p['ref']} ({p['w']:.0f}×{p['h']:.0f} mm) no cabe en el formato "
                                                 f"{sheet_l:.0f}×{sheet_w:.0f} mm con márgenes de {margin} mm"}
        items += [p] * int(p["qty"])
    items.sort(key=lambda p: -(p["w"] * p["h"]))
    bins: list[_Bin] = []
    for p in items:
        placed = False
        for b in bins:
            f = b.find(p["w"] + gap, p["h"] + gap, p.get("rotate", True))
            if f:
                b.place(f[1])
                b.used.append({"ref": p["ref"], "x": f[1].x + margin, "y": f[1].y + margin, "rot": f[2],
                               "w": p["h"] if f[2] else p["w"], "h": p["w"] if f[2] else p["h"], "area": p["area"]})
                placed = True
                break
        if not placed:
            b = _Bin(UW, UH)
            f = b.find(p["w"] + gap, p["h"] + gap, p.get("rotate", True))
            b.place(f[1])
            b.used.append({"ref": p["ref"], "x": f[1].x + margin, "y": f[1].y + margin, "rot": f[2],
                           "w": p["h"] if f[2] else p["w"], "h": p["w"] if f[2] else p["h"], "area": p["area"]})
            bins.append(b)
    sheet_area = sheet_l * sheet_w
    sheets = []
    for n, b in enumerate(bins, start=1):
        used = sum(u["area"] for u in b.used)
        sheets.append({"sheet": n, "placements": b.used, "parts_area_mm2": round(used, 1),
                       "utilization": round(used / sheet_area, 4)})
    total_used = sum(s["parts_area_mm2"] for s in sheets)
    return {"feasible": True, "format": f"{sheet_l:.0f}x{sheet_w:.0f}", "length": sheet_l, "width": sheet_w,
            "margin": margin, "spacing": spacing, "kerf": kerf, "sheets": sheets, "n_sheets": len(sheets),
            "parts_area_m2": round(total_used / 1e6, 4), "sheet_area_m2": round(len(sheets) * sheet_area / 1e6, 4),
            "utilization": round(total_used / (len(sheets) * sheet_area), 4) if sheets else 0,
            "waste_m2": round((len(sheets) * sheet_area - total_used) / 1e6, 4)}


def best_format(parts: list[dict[str, Any]], formats: list[dict[str, Any]], **kw) -> dict[str, Any]:
    results = []
    for f in formats:
        r = nest_sheets(parts, f["length"], f["width"], **kw)
        r["format_code"] = f["code"]
        results.append(r)
    feasible = [r for r in results if r["feasible"]]
    if not feasible:
        return {"feasible": False, "alternatives": results,
                "reason": "Ninguna pieza cabe en los formatos comerciales configurados"}
    best = min(feasible, key=lambda r: (r["sheet_area_m2"], r["n_sheets"]))
    best = dict(best)
    best["alternatives"] = [{"format": r["format_code"], "feasible": r["feasible"], "n_sheets": r.get("n_sheets"),
                             "utilization": r.get("utilization"), "reason": r.get("reason")} for r in results]
    return best
