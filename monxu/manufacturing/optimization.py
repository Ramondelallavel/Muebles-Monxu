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
def _bar_balance(n: int, b: dict[str, Any], kerf: float, trim: float, trim_end: float,
                 reusable_min: float) -> dict[str, Any]:
    """Balance físico de una barra: L = despunte inicial + Σ piezas + ancho de sierra + despunte final + retal.

    Cortes: el de refrentado inicial más uno por pieza; si la última pieza agota la barra no hay corte final.
    Si sobran menos milímetros que el ancho de sierra, el último corte solo consume ese resto."""
    L = b["length"]
    used = sum(c["length"] for c in b["cuts"])
    npc = len(b["cuts"])
    free = L - trim - trim_end - used - npc * kerf
    if free >= 0:
        remnant, kerf_total, n_cuts = free, npc * kerf, 1 + npc
    else:                                   # la última pieza apura la barra (free ≥ −kerf)
        last = kerf + free
        remnant, kerf_total = 0.0, (npc - 1) * kerf + max(0.0, last)
        n_cuts = 1 + npc - (0 if last > 1e-9 else 1)
    reusable = remnant >= reusable_min
    status = "reutilizable" if reusable else ("chatarra" if remnant > 1e-9 else "sin retal")
    bal = L - (trim + used + kerf_total + trim_end + remnant)
    return {"bar": n, "source": b.get("source", "comercial"), "stock_id": b.get("stock_id"), "length": L,
            "cuts": b["cuts"], "n_pieces": npc, "n_cuts": n_cuts, "used": round(used, 1),
            "trim_start": trim, "trim_end": trim_end, "kerf_total": round(kerf_total, 1),
            "kerf_loss": round(kerf_total + trim + trim_end, 1), "remnant": round(remnant, 1),
            "remnant_reusable": reusable, "remnant_status": status, "balance_mm": round(bal, 6)}


def optimize_bars(pieces: list[dict[str, Any]], bar_length: float = 6000.0, kerf: float = 3.0,
                  trim: float = 10.0, reusable_min: float = 500.0, trim_end: float = 0.0,
                  stock: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """pieces: [{"label", "ref", "length", "qty"}] de un mismo perfil y material.

    ``trim`` es el despunte inicial (refrentado del extremo de laminación, incluye su corte) y ``trim_end``
    el despunte final; ``stock`` son retales del inventario ([{"id", "length"}]) del mismo perfil y material,
    que se usan antes de abrir barras comerciales nuevas."""
    items = []
    for p in pieces:
        if p["length"] + trim + trim_end + kerf > bar_length:
            raise ValueError(f"La pieza {p['ref']} ({p['length']} mm) supera la longitud de barra {bar_length} mm")
        items += [dict(p)] * int(p["qty"])
    items.sort(key=lambda p: -p["length"])
    avail = sorted((dict(s) for s in (stock or []) if s["length"] - trim - trim_end > 0),
                   key=lambda s: (s["length"], str(s["id"])))
    bars: list[dict[str, Any]] = []
    for it in items:
        need = it["length"] + kerf
        best, best_rem = None, None
        for b in bars:
            rem = b["free"] - need
            if rem >= -kerf + 1e-9 and (best_rem is None or rem < best_rem):
                best, best_rem = b, rem
        if best is None:                    # retal del inventario más corto en el que cabe la pieza
            k = next((n for n, s in enumerate(avail) if s["length"] - trim - trim_end - need >= -kerf + 1e-9), None)
            if k is not None:
                s = avail.pop(k)
                best = {"cuts": [], "free": s["length"] - trim - trim_end, "length": s["length"], "source": "retal",
                        "stock_id": s["id"]}
            else:
                best = {"cuts": [], "free": bar_length - trim - trim_end, "length": bar_length, "source": "comercial"}
            bars.append(best)
        best["cuts"].append({"ref": it["ref"], "label": it.get("label", ""), "length": it["length"]})
        best["free"] -= need
    cap = bar_length - trim - trim_end + kerf
    new = [b for b in bars if b["source"] == "comercial"]
    from_stock = [b for b in bars if b["source"] == "retal"]
    new_items = [it for b in new for it in b["cuts"]]
    # cota inferior válida: cada barra admite hasta un ancho de sierra más (la última pieza puede apurarla)
    lb0 = math.ceil(sum(p["length"] + kerf for p in new_items) / cap - 1e-9) if new_items else 0
    if len(new) > lb0 and len(new_items) <= 60:
        for k in range(lb0, len(new)):
            exact = _exact_pack(new_items, cap, kerf, k)
            if exact is not None:
                new = [{"cuts": [{"ref": it["ref"], "label": it.get("label", ""), "length": it["length"]} for it in b],
                        "length": bar_length, "source": "comercial"} for b in exact]
                break
    bars = from_stock + new
    out = [_bar_balance(n, b, kerf, trim, trim_end, reusable_min) for n, b in enumerate(bars, start=1)]
    nb = len(new)
    total_pieces = sum(p["length"] for p in items)
    stock_len = sum(b["length"] for b in out if b["source"] == "retal")
    purchased = nb * bar_length
    kerf_tot = sum(b["kerf_total"] for b in out)
    trims = sum(b["trim_start"] + b["trim_end"] for b in out)
    reus = sum(b["remnant"] for b in out if b["remnant_reusable"])
    scrap_rem = sum(b["remnant"] for b in out if not b["remnant_reusable"])
    waste = kerf_tot + trims + scrap_rem
    return {"bar_length": bar_length, "kerf": kerf, "trim": trim, "trim_start": trim, "trim_end": trim_end,
            "reusable_min": reusable_min, "bars": out, "n_bars": nb, "n_stock_used": len(from_stock),
            "stock_used": [b["stock_id"] for b in out if b["source"] == "retal"],
            "lower_bound": lb0, "optimal": nb == lb0, "pieces": len(items), "pieces_length": round(total_pieces, 1),
            "n_cuts": sum(b["n_cuts"] for b in out), "purchased_length": round(purchased, 1),
            "stock_length": round(stock_len, 1), "kerf_total": round(kerf_tot, 1), "trim_total": round(trims, 1),
            "scrap_remnant_length": round(scrap_rem, 1), "reusable_length": round(reus, 1),
            "waste_length": round(waste, 1),
            "balance_mm": round(purchased + stock_len - (total_pieces + kerf_tot + trims + scrap_rem + reus), 6),
            "utilization": round(total_pieces / (purchased + stock_len), 4) if purchased + stock_len else 0.0,
            "reusable_remnants": [b["remnant"] for b in out if b["remnant_reusable"]],
            "scrap": round(waste, 1)}


def _exact_pack(items, cap, kerf, k, node_limit=200000):
    """Búsqueda exacta (ramificación y poda) de un reparto en k barras; None si no existe o se agota el límite.

    cap es la capacidad para la suma de (longitud + sierra) de las piezas de una barra."""
    need = [it["length"] + kerf for it in items]
    order = sorted(range(len(items)), key=lambda i: -need[i])
    free = [cap] * k
    assign: list[list[int]] = [[] for _ in range(k)]
    nodes = [0]

    def rec(n):
        if n == len(order):
            return True
        nodes[0] += 1
        if nodes[0] > node_limit:
            return False
        i = order[n]
        tried = set()
        for b in range(k):
            if free[b] + 1e-9 >= need[i] and free[b] not in tried:
                tried.add(free[b])
                free[b] -= need[i]
                assign[b].append(i)
                if rec(n + 1):
                    return True
                assign[b].pop()
                free[b] += need[i]
        return False

    if rec(0):
        return [[items[i] for i in b] for b in assign if b]
    return None


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
                spacing: float = 8.0, kerf: float = 0.3, stock: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """parts: [{"ref", "w", "h", "qty", "area", "rotate"}]; w = dimensión en la dirección de laminación.

    ``stock``: retales de chapa del inventario ([{"id", "length", "width"}]) del mismo material y espesor; se
    llenan antes de abrir chapas comerciales del formato."""
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
    meta: list[dict[str, Any]] = []
    for s in sorted(stock or [], key=lambda s: (s["length"] * s["width"], str(s["id"]))):
        sw, sh = s["length"] - 2 * margin + gap, s["width"] - 2 * margin + gap
        if sw > gap and sh > gap:
            bins.append(_Bin(sw, sh))
            meta.append({"source": "retal", "stock_id": s["id"], "length": s["length"], "width": s["width"]})

    def put(b, p, f):
        b.place(f[1])
        b.used.append({"ref": p["ref"], "x": f[1].x + margin, "y": f[1].y + margin, "rot": f[2],
                       "w": p["h"] if f[2] else p["w"], "h": p["w"] if f[2] else p["h"], "area": p["area"]})

    for p in items:
        placed = False
        for b in bins:
            f = b.find(p["w"] + gap, p["h"] + gap, p.get("rotate", True))
            if f:
                put(b, p, f)
                placed = True
                break
        if not placed:
            b = _Bin(UW, UH)
            put(b, p, b.find(p["w"] + gap, p["h"] + gap, p.get("rotate", True)))
            bins.append(b)
            meta.append({"source": "comercial", "stock_id": None, "length": sheet_l, "width": sheet_w})
    sheets = []
    n = 0
    for b, m in zip(bins, meta):
        if not b.used:                    # retal del inventario que no se ha usado
            continue
        n += 1
        used = sum(u["area"] for u in b.used)
        area = m["length"] * m["width"]
        ext = (max(u["x"] + u["w"] for u in b.used), max(u["y"] + u["h"] for u in b.used))
        sheets.append({"sheet": n, **m, "placements": b.used, "parts_area_mm2": round(used, 1),
                       "extent": [round(ext[0], 3), round(ext[1], 3)], "utilization": round(used / area, 4)})
    com = [s for s in sheets if s["source"] == "comercial"]
    total_used = sum(s["parts_area_mm2"] for s in sheets)
    sheet_area = sheet_l * sheet_w
    all_area = sum(s["length"] * s["width"] for s in sheets)
    return {"feasible": True, "format": f"{sheet_l:.0f}x{sheet_w:.0f}", "length": sheet_l, "width": sheet_w,
            "margin": margin, "spacing": spacing, "kerf": kerf, "sheets": sheets, "n_sheets": len(com),
            "n_stock_used": len(sheets) - len(com), "stock_used": [s["stock_id"] for s in sheets if s["source"] == "retal"],
            "parts_area_m2": round(total_used / 1e6, 4), "sheet_area_m2": round(len(com) * sheet_area / 1e6, 4),
            "utilization": round(total_used / all_area, 4) if sheets else 0,
            "waste_m2": round((all_area - total_used) / 1e6, 4)}


def best_format(parts: list[dict[str, Any]], formats: list[dict[str, Any]], purchase: dict[str, Any] | None = None,
                **kw) -> dict[str, Any]:
    """Anida en cada formato comercial y elige el de menor superficie comprada. Con ``purchase`` (opciones de
    :func:`sheet_purchase`) la comparación se hace sobre la compra real (chapas enteras y corte a medida)."""
    results = []
    for f in formats:
        r = nest_sheets(parts, f["length"], f["width"], **kw)
        r["format_code"] = f["code"]
        if r["feasible"] and purchase is not None:
            sheet_purchase(r, parts, **purchase)
        results.append(r)
    feasible = [r for r in results if r["feasible"]]
    if not feasible:
        return {"feasible": False, "alternatives": results,
                "reason": "Ninguna pieza cabe en los formatos comerciales configurados",
                "parts_area_m2": round(sum(p["area"] * p["qty"] for p in parts) / 1e6, 4)}
    if purchase is not None:
        best = min(feasible, key=lambda r: (r["purchase"]["purchased_area_m2"], r["n_sheets"]))
    else:
        best = min(feasible, key=lambda r: (r["sheet_area_m2"], r["n_sheets"]))
    best = dict(best)
    best["alternatives"] = [{"format": r["format_code"], "feasible": r["feasible"], "n_sheets": r.get("n_sheets"),
                             "utilization": r.get("utilization"), "reason": r.get("reason"),
                             "purchased_area_m2": (r.get("purchase") or {}).get("purchased_area_m2")} for r in results]
    return best


def _compact_blank(items: list[dict[str, Any]], L: float, W: float, margin: float, spacing: float, kerf: float,
                   round_to: float):
    """Rectángulo mínimo (redondeado) que admite todas las piezas de ``items`` en una sola chapa: se anidan en
    bandas de anchura creciente del formato y se elige la de menor superficie."""
    lim = max((min(p["w"], p["h"]) if p.get("rotate", True) else p["h"]) for p in items) + 2 * margin
    best = None
    for i in range(21):
        wc = lim + (W - lim) * i / 20
        n = nest_sheets(items, L, wc, margin, spacing, kerf)
        if not n["feasible"] or n["n_sheets"] != 1:
            continue
        ux, uy = n["sheets"][0]["extent"]
        bl = min(L, math.ceil((ux + margin) / round_to - 1e-9) * round_to)
        bw = min(W, math.ceil((uy + margin) / round_to - 1e-9) * round_to)
        if best is None or bl * bw < best[0] - 1e-6:
            best = (bl * bw, bl, bw, n["sheets"][0])
    return best


def sheet_purchase(nest: dict[str, Any], parts: list[dict[str, Any]], min_utilization: float = 0.10,
                   remnant_min: float = 300.0, round_to: float = 10.0) -> dict[str, Any]:
    """Compra real de chapa a partir del anidado (modifica ``nest`` para que el anidado dibujado sea el comprado).

    * Chapas enteras del formato, salvo la última si su aprovechamiento es menor que ``min_utilization``: esa se
      pide cortada a medida; sus piezas se reanidan en el rectángulo mínimo (más el margen perimetral,
      redondeado a ``round_to`` mm) y ese rectángulo es la chapa que se compra y se dibuja.
    * En cada chapa entera o retal se identifica el retal reutilizable: la franja recta (un solo corte) que
      queda libre a lo largo o a lo ancho, si sus dos lados alcanzan ``remnant_min``.
    Superficies en mm² por chapa y m² en los totales."""
    margin, spacing = nest["margin"], nest["spacing"]
    last = nest["sheets"][-1] if nest["sheets"] else None
    if last and last["source"] == "comercial" and last["utilization"] < min_utilization:
        cnt: dict[str, int] = {}
        for u in last["placements"]:
            cnt[u["ref"]] = cnt.get(u["ref"], 0) + 1
        items = [dict(p, qty=cnt[p["ref"]]) for p in parts if p["ref"] in cnt]
        cb = _compact_blank(items, last["length"], last["width"], margin, spacing, nest["kerf"], round_to)
        if cb:
            _, bl, bw, sh = cb
            last.update({"source": "corte_medida", "length": bl, "width": bw, "placements": sh["placements"],
                         "extent": sh["extent"], "utilization": round(last["parts_area_mm2"] / (bl * bw), 4)})
    lines = []
    for s in nest["sheets"]:
        L, W = s["length"], s["width"]
        ux, uy = s["extent"]
        mode = {"comercial": "formato"}.get(s["source"], s["source"])
        s["mode"] = mode
        rem = None
        if mode != "corte_medida":
            cand = [(L - ux - spacing, W, "x", ux + spacing), (L, W - uy - spacing, "y", uy + spacing)]
            cand = [c for c in cand if min(c[0], c[1]) >= remnant_min]
            if cand:
                c = max(cand, key=lambda c: c[0] * c[1])
                rem = {"length": round(c[0], 1), "width": round(c[1], 1), "axis": c[2], "at": round(c[3], 1),
                       "area_mm2": round(c[0] * c[1], 1)}
        s["remnant"] = rem
        lines.append({"sheet": s["sheet"], "mode": mode, "stock_id": s.get("stock_id"), "length": L, "width": W,
                      "area_mm2": round(L * W, 1), "parts_area_mm2": s["parts_area_mm2"], "remnant": rem,
                      "utilization": round(s["parts_area_mm2"] / (L * W), 4)})
    bought = [x for x in lines if x["mode"] != "retal"]
    purchased = sum(x["area_mm2"] for x in bought)
    stock_area = sum(x["area_mm2"] for x in lines if x["mode"] == "retal")
    parts_a = sum(x["parts_area_mm2"] for x in lines)
    reus = sum(x["remnant"]["area_mm2"] for x in lines if x["remnant"])
    out = {"sheets": lines, "n_full": sum(1 for x in lines if x["mode"] == "formato"),
           "n_custom": sum(1 for x in lines if x["mode"] == "corte_medida"),
           "n_stock": sum(1 for x in lines if x["mode"] == "retal"),
           "purchased_area_m2": round(purchased / 1e6, 6), "stock_area_m2": round(stock_area / 1e6, 6),
           "parts_area_m2": round(parts_a / 1e6, 6), "reusable_area_m2": round(reus / 1e6, 6),
           "waste_area_m2": round((purchased + stock_area - parts_a - reus) / 1e6, 6),
           "utilization": round(parts_a / (purchased + stock_area), 4) if purchased + stock_area else 0.0,
           "min_utilization": min_utilization, "remnant_min": remnant_min}
    nest["purchase"] = out
    nest["utilization"] = out["utilization"]
    nest["waste_m2"] = round((purchased + stock_area - parts_a) / 1e6, 4)
    return out
