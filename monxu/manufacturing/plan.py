"""Plan de fabricación y reglas de diseño para fabricación (DFM).

Se calcula a partir de las definiciones de pieza del modelo CAD: no hay datos duplicados.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .. import catalog
from ..core.model import PlatePart, ProfilePart, SheetPart, StandardPart
from .optimization import best_format, optimize_bars


def _counts(model) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for i in model.instances:
        c[i.part.key] += 1
    return c


PAINT_REF_UM = 80.0          # µm: espesor de referencia del consumo de polvo del catálogo (= families.base.PAINT_REF_UM)


def bar_length(model) -> float:
    """Longitud de barra comercial: la del proyecto (LONGITUD_BARRA) o la del catálogo."""
    return float(model.params.values.get("LONGITUD_BARRA") or catalog.profile_meta()["default_bar_length_mm"])


def routing(part) -> list[str]:
    if isinstance(part, ProfilePart):
        r = ["Corte por sierra de cinta (90°)"]
        if part.holes:
            r.append(f"Taladrado Ø{part.holes[0][3]:g} ({len(part.holes)} uds)")
        return r + ["Soldadura MAG (en conjunto)"]
    if isinstance(part, SheetPart):
        return ["Corte por láser", f"Plegado ({len(part.spec.flanges)} pliegues a 90°)"]
    if isinstance(part, PlatePart):
        return ["Corte por láser"]
    return ["Compra"]


def lot_size(model) -> int:
    """Lote de fabricación del proyecto (LOTE_FABRICACION, 1 por defecto): el plan de corte, el anidado y la
    lista de compras se calculan para el lote completo."""
    return max(1, int(model.params.values.get("LOTE_FABRICACION") or 1))


def cutting_params(model) -> dict[str, float]:
    cm = catalog.profile_meta().get("cutting", {})
    return {"bar_length": bar_length(model), "kerf": float(model.params.values.get("CORTE_SIERRA") or 3.0),
            "trim": float(cm.get("trim_start_mm", 10.0)), "trim_end": float(cm.get("trim_end_mm", 0.0)),
            "reusable_min": float(cm.get("reusable_min_mm", 500.0))}


def _stock_for(stock, kind, **key):
    return [s for s in (stock or []) if s.get("kind") == kind and all(s.get(k) == v for k, v in key.items())
            and s.get("status", "disponible") == "disponible"]


def material_purchase(model, lot: int = 1, stock: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Plan de corte de perfiles, anidado de chapa y balance de material de ``lot`` unidades.

    ``stock`` es el inventario de retales reutilizables ([{"id", "kind": "barra"|"chapa", "profile"/"thickness",
    "material", "length", "width"}]); los compatibles se consumen antes de comprar material nuevo."""
    counts = _counts(model)
    sd = catalog.sheet_data()
    cp = cutting_params(model)
    # ------------------------------------------------------------- perfiles
    groups: dict[tuple, list] = defaultdict(list)
    for k, p in model.parts.items():
        if isinstance(p, ProfilePart):
            groups[(p.profile.code, p.material)].append({"ref": p.ref, "label": p.name, "length": p.length,
                                                         "qty": counts[k] * lot})
    cutting = []
    for (code, mat), pieces in sorted(groups.items()):
        st = [{"id": s["id"], "length": s["length"]} for s in _stock_for(stock, "barra", profile=code, material=mat)]
        r = optimize_bars(pieces, bar_length=cp["bar_length"], kerf=cp["kerf"], trim=cp["trim"],
                          trim_end=cp["trim_end"], reusable_min=cp["reusable_min"], stock=st)
        kg_m = catalog.profile(code).mass_per_m(catalog.material(mat).density)
        r.update({"profile": code, "material": mat, "kg_per_m": round(kg_m, 4),
                  "mass_per_bar_kg": round(kg_m * cp["bar_length"] / 1000, 2)})
        cutting.append(r)
    # ------------------------------------------------------------- chapa y pletinas
    sgroups: dict[tuple, list] = defaultdict(list)
    for k, p in model.parts.items():
        if isinstance(p, SheetPart):
            fp = p.flat
            sgroups[(p.material, p.spec.t)].append({"ref": p.ref, "w": fp.width, "h": fp.height, "qty": counts[k] * lot,
                                                     "area": fp.net_area(), "rotate": p.finish != "INOX_SATINADO",
                                                     "kind": "chapa"})
        elif isinstance(p, PlatePart):
            sgroups[(p.material, p.t)].append({"ref": p.ref, "w": p.w, "h": p.h, "qty": counts[k] * lot,
                                                "area": plate_net_area(p), "rotate": True, "kind": "pletina"})
    nesting = []
    las, pur = sd["laser"], sd.get("purchase", {})
    fmt = model.params.values.get("FORMATO_CHAPA")
    formats = [f for f in catalog.sheet_formats() if f["code"] == fmt] or catalog.sheet_formats()
    for (mat, t), parts in sorted(sgroups.items()):
        st = [{"id": s["id"], "length": s["length"], "width": s["width"]}
              for s in _stock_for(stock, "chapa", material=mat, thickness=t)]
        r = best_format(parts, formats, margin=las["sheet_margin_mm"], spacing=las["part_spacing_mm"],
                        kerf=las["kerf_mm"], stock=st,
                        purchase={"min_utilization": pur.get("custom_cut_min_utilization", 0.10),
                                  "remnant_min": pur.get("remnant_min_mm", 300.0),
                                  "round_to": pur.get("custom_cut_round_mm", 10.0)})
        rho = catalog.material(mat).density
        r.update({"material": mat, "thickness": t, "kg_per_m2": round(t * 1e-3 * rho, 4),
                  "mass_per_sheet_kg": round(r.get("length", 0) * r.get("width", 0) * t * 1e-9 * rho, 2)
                  if r.get("feasible") else None})
        nesting.append(r)
    return {"lot": lot, "cutting": cutting, "nesting": nesting, "balance": material_balance(cutting, nesting),
            "cutting_params": cp}


def material_balance(cutting, nesting) -> dict[str, Any]:
    """Balance de material por grupo, en longitudes o superficies y en masa nominal (kg/m o kg/m²):
    comprado + retales de inventario = neto en piezas + desperdicio no recuperable + retales reutilizables."""
    rows = []
    for c in cutting:
        k = c["kg_per_m"] / 1000
        rows.append({"kind": "perfil", "group": f"{c['profile']} {c['material']}", "unit": "mm",
                     "purchased": c["purchased_length"], "from_stock": c["stock_length"], "net": c["pieces_length"],
                     "waste": c["waste_length"], "reusable": c["reusable_length"],
                     "purchased_kg": c["purchased_length"] * k, "from_stock_kg": c["stock_length"] * k,
                     "net_kg": c["pieces_length"] * k, "waste_kg": c["waste_length"] * k,
                     "reusable_kg": c["reusable_length"] * k, "balance": c["balance_mm"]})
    for n in nesting:
        if not n.get("feasible"):
            rows.append({"kind": "chapa", "group": f"{n['material']} e={n['thickness']:g} mm", "unit": "m2",
                         "purchased": None, "from_stock": 0.0, "net": n["parts_area_m2"], "waste": None, "reusable": 0.0,
                         "purchased_kg": None, "from_stock_kg": 0.0, "net_kg": None, "waste_kg": None,
                         "reusable_kg": 0.0, "balance": None, "infeasible": True})
            continue
        pu, k = n["purchase"], n["kg_per_m2"]
        rows.append({"kind": "chapa", "group": f"{n['material']} e={n['thickness']:g} mm", "unit": "m2",
                     "purchased": pu["purchased_area_m2"], "from_stock": pu["stock_area_m2"],
                     "net": pu["parts_area_m2"], "waste": pu["waste_area_m2"], "reusable": pu["reusable_area_m2"],
                     "purchased_kg": pu["purchased_area_m2"] * k, "from_stock_kg": pu["stock_area_m2"] * k,
                     "net_kg": pu["parts_area_m2"] * k, "waste_kg": pu["waste_area_m2"] * k,
                     "reusable_kg": pu["reusable_area_m2"] * k,
                     "balance": round(pu["purchased_area_m2"] + pu["stock_area_m2"] - pu["parts_area_m2"]
                                      - pu["waste_area_m2"] - pu["reusable_area_m2"], 6)})
    tot = {}
    for key in ("purchased_kg", "from_stock_kg", "net_kg", "waste_kg", "reusable_kg"):
        tot[key] = round(sum(r[key] or 0.0 for r in rows), 3)
    for r in rows:
        for key in ("purchased_kg", "from_stock_kg", "net_kg", "waste_kg", "reusable_kg"):
            if r[key] is not None:
                r[key] = round(r[key], 3)
    return {"rows": rows, "totals": tot}


def plate_net_area(p) -> float:
    """Superficie neta de una pletina (contorno con radios exactos menos taladros), igual en los dos motores."""
    return p.w * p.h - (4 - math.pi) * p.corner_r * p.corner_r - sum(math.pi * d * d / 4 for _, _, d in p.holes)


def _std_label(c: dict[str, Any]) -> str:
    """Norma del componente comercial, o la indicación de que no hay norma de producto aplicable."""
    if c.get("standard"):
        return c["standard"]
    return "sin norma de producto, según fabricante"


def purchases(model, mp: dict[str, Any], welding: dict[str, Any], painting: dict[str, Any]) -> dict[str, Any]:
    """Lista de compras del lote: barras y chapas del plan de corte y del anidado, componentes comerciales del
    modelo y consumibles. Cada línea indica el documento del que procede."""
    lot = mp["lot"]
    out = []
    for c in mp["cutting"]:
        if c["n_bars"]:
            out.append({"type": "Perfil", "description": f"Barra {c['profile']} {c['material']} L={c['bar_length']:.0f} mm",
                        "qty": c["n_bars"], "unit": "barra", "mass_kg": round(c["purchased_length"] * c["kg_per_m"] / 1000, 2),
                        "basis": "plan de corte", "group": f"{c['profile']} {c['material']}"})
        if c["n_stock_used"]:
            out.append({"type": "Perfil (retal de inventario)", "description": f"Retales {c['profile']} {c['material']}: "
                        + ", ".join(str(i) for i in c["stock_used"]), "qty": c["n_stock_used"], "unit": "retal",
                        "mass_kg": round(c["stock_length"] * c["kg_per_m"] / 1000, 2), "basis": "inventario de retales",
                        "group": f"{c['profile']} {c['material']}", "purchase": False})
    for n in mp["nesting"]:
        grp = f"{n['material']} e={n['thickness']:g} mm"
        if not n.get("feasible"):
            out.append({"type": "Chapa", "description": f"Chapa {n['material']} e={n['thickness']:g} mm — sin formato "
                        "comercial válido (pieza mayor que los formatos)", "qty": None, "unit": "chapa", "mass_kg": None,
                        "basis": "anidado", "group": grp, "blocking": True})
            continue
        pu = n["purchase"]
        if pu["n_full"]:
            out.append({"type": "Chapa", "description": f"Chapa {n['material']} e={n['thickness']:g} mm formato "
                        f"{n['format']}", "qty": pu["n_full"], "unit": "chapa",
                        "mass_kg": round(pu["n_full"] * n["length"] * n["width"] * 1e-6 * n["kg_per_m2"], 2),
                        "basis": "anidado", "group": grp})
        for x in pu["sheets"]:
            if x["mode"] == "corte_medida":
                out.append({"type": "Chapa (corte a medida)", "description": f"Chapa {n['material']} e={n['thickness']:g} "
                            f"mm cortada a medida {x['length']:.0f}x{x['width']:.0f} mm (hoja {x['sheet']} del anidado)",
                            "qty": 1, "unit": "ud", "mass_kg": round(x["area_mm2"] * 1e-6 * n["kg_per_m2"], 2),
                            "basis": "anidado", "group": grp})
            elif x["mode"] == "retal":
                out.append({"type": "Chapa (retal de inventario)", "description": f"Retal {x['stock_id']} {n['material']} "
                            f"e={n['thickness']:g} mm {x['length']:.0f}x{x['width']:.0f} mm", "qty": 1, "unit": "retal",
                            "mass_kg": round(x["area_mm2"] * 1e-6 * n["kg_per_m2"], 2), "basis": "inventario de retales",
                            "group": grp, "purchase": False})
    std: dict[str, int] = defaultdict(int)
    for i in model.instances:
        if isinstance(i.part, StandardPart):
            std[i.part.code] += 1
    for code in sorted(std):
        c = catalog.component(code)
        val = (c.get("validation") or {}).get("status", "pendiente_validacion")
        out.append({"type": "Comercial", "description": f"{c['name']} ({_std_label(c)})", "qty": std[code] * lot,
                    "unit": "ud", "mass_kg": round(c["mass_kg"] * std[code] * lot, 4), "code": code,
                    "ref": f"N-{code}", "basis": "BOM", "validation": val})
    consumables = [
        {"description": welding["wire"], "qty": round(welding["wire_kg"] * lot, 3), "unit": "kg", "basis": "cordones del modelo"},
        {"description": welding["gas"], "qty": round(welding["gas_l"] * lot, 1), "unit": "l", "basis": "tiempo de arco"},
    ] if welding["joints"] else []
    if painting["powder_kg"]:
        consumables.append({"description": catalog.finish(painting["finish"])["name"],
                            "qty": round(painting["powder_kg"] * lot, 3), "unit": "kg",
                            "basis": f"{painting['area_m2']} m² pintados por unidad"})
    remnants = []
    for c in mp["cutting"]:
        for b in c["bars"]:
            if b["remnant"] > 0:
                remnants.append({"kind": "barra", "profile": c["profile"], "material": c["material"], "bar": b["bar"],
                                 "length": b["remnant"], "reusable": b["remnant_reusable"], "status": b["remnant_status"]})
    for n in mp["nesting"]:
        for x in (n.get("purchase") or {}).get("sheets", []):
            if x["remnant"]:
                remnants.append({"kind": "chapa", "material": n["material"], "thickness": n["thickness"], "sheet": x["sheet"],
                                 "length": x["remnant"]["length"], "width": x["remnant"]["width"], "reusable": True,
                                 "status": "reutilizable"})
    return {"lot": lot, "items": out, "consumables": consumables, "remnants": remnants}


def manufacturing_plan(model, stock: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    counts = _counts(model)
    lot = lot_size(model)
    mp = material_purchase(model, lot, stock)
    # ------------------------------------------------------------- soldadura (por unidad)
    welds = [j for j in model.joints if j.kind == "soldadura"]
    weld_len = sum(j.weld["length"] for j in welds)
    wire = catalog.consumables()["HILO_G3Si1"]
    gas = catalog.consumables()["GAS_M21"]
    deposit_kg = sum(j.weld["a"] ** 2 * j.weld["length"] for j in welds) * 1e-6 * wire["deposit_density_kg_dm3"]
    wire_kg = deposit_kg / wire["efficiency"]
    arc_h = deposit_kg / gas["deposit_rate_kg_h"]
    gas_l = arc_h * 60 * gas["flow_l_min"]
    # ------------------------------------------------------------- pintura (por unidad)
    painted = 0.0
    for k, p in model.parts.items():
        if p.finish and catalog.finish(p.finish)["consumable_kg_m2"] > 0:
            if isinstance(p, ProfilePart):
                a = (2 * (p.profile.B + p.profile.H) - (8 - 2 * math.pi) * p.profile.r_out) * p.length
            elif isinstance(p, SheetPart):
                a = 2 * p.flat.net_area()
            elif isinstance(p, PlatePart):
                a = 2 * p.w * p.h + 2 * (p.w + p.h) * p.t
            else:
                continue
            painted += a * counts[k]
    fin = model.params.values.get("ACABADO")
    film = float(model.params.values.get("ESPESOR_PINTURA") or PAINT_REF_UM)      # consumo ∝ espesor de película
    paint_kg = painted / 1e6 * catalog.finish(fin)["consumable_kg_m2"] * film / PAINT_REF_UM if fin else 0.0
    welding = {"joints": len(welds), "total_length_mm": round(weld_len, 1), "deposit_kg": round(deposit_kg, 3),
               "wire_kg": round(wire_kg, 3), "arc_time_h": round(arc_h, 3), "gas_l": round(gas_l, 1),
               "wire": wire["name"], "gas": gas["name"]}
    painting = {"area_m2": round(painted / 1e6, 3), "powder_kg": round(paint_kg, 3), "finish": fin}
    return {"lot": lot, "cutting": mp["cutting"], "nesting": mp["nesting"], "balance": mp["balance"],
            "cutting_params": mp["cutting_params"], "welding": welding, "painting": painting,
            "purchases": purchases(model, mp, welding, painting),
            "stock_offered": len(stock or []),
            "routing": {p.ref: routing(p) for p in model.parts.values()}}


# ============================================================================ DFM
def weld_face_conditions(model, tol: float = 0.05) -> dict[str, Any]:
    """Posición de las caras laterales de cada barra soldada a tope sobre otra, calculada desde la geometría.

    * ``flush``: uniones en las que una cara de la barra queda enrasada con la de la barra de apoyo (misma cara
      exterior o mismo canto): en esa cara el cordón cae sobre el radio de esquina.
    * ``corner``: uniones en las que una cara queda a menos del radio de esquina de la cara de apoyo, sin enrasar:
      en ese lado el cordón es en bisel abocinado sobre el radio. ``corner_min`` es la menor distancia y
      ``corner_r`` el radio de esquina de esa barra de apoyo."""
    flush = corner = 0
    dmin = rmin = None
    for j in model.joints:
        fem = (j.weld or {}).get("fem") if j.kind == "soldadura" else None
        if not fem:
            continue
        a, b = model.instance(fem["member"]), model.instance(fem["onto"])
        if a.part.kind != "perfil" or b.part.kind != "perfil":
            continue
        (alo, ahi), (blo, bhi) = a.bbox, b.bbox
        r = b.part.profile.r_out
        ax_a = max(range(3), key=lambda k: abs(a.axis[1][k] - a.axis[0][k]))
        ax_b = max(range(3), key=lambda k: abs(b.axis[1][k] - b.axis[0][k]))
        state, d_c = None, None
        for k in range(3):
            if k in (ax_a, ax_b) or not (alo[k] >= blo[k] - tol and ahi[k] <= bhi[k] + tol):
                continue                      # eje transversal a las dos barras con la barra dentro del ancho del apoyo
            d = min(alo[k] - blo[k], bhi[k] - ahi[k])
            if d <= tol:
                state = "flush"
            elif d < r - tol and state != "flush":
                state, d_c = "corner", d if d_c is None else min(d_c, d)
        if state == "flush":
            flush += 1
        elif state == "corner":
            corner += 1
            if dmin is None or d_c < dmin:
                dmin, rmin = d_c, r
    return {"flush": flush, "corner": corner, "corner_min": None if dmin is None else round(float(dmin), 2),
            "corner_r": None if rmin is None else round(float(rmin), 2)}


def dfm_check(model, plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    sd = catalog.sheet_data()
    pb, las = sd["press_brake"], sd["laser"]
    out: list[dict[str, Any]] = []

    def add(level, code, element, msg, proposal=""):
        out.append({"level": level, "code": code, "element": element, "message": msg, "proposal": proposal})

    bar_len = bar_length(model)
    for p in model.parts.values():
        if isinstance(p, SheetPart):
            mat = catalog.material(p.material)
            s = p.spec
            avail = catalog.sheet_thicknesses(p.material)
            if s.t not in avail:
                near = min(avail, key=lambda v: abs(v - s.t)) if avail else None
                add("error", "LAS-ESPESOR", p.ref, f"Espesor {s.t} mm no disponible en {p.material}.",
                    f"Usar {near} mm." if near else "Seleccionar otro material.")
            if s.t > las["max_thickness_mm"].get(mat.family, 10):
                add("error", "LAS-ESPESOR-MAX", p.ref, f"Espesor {s.t} mm supera la capacidad del láser.")
            rmin = pb["min_inner_radius_factor"].get(mat.family, 1.0) * s.t
            if s.r < rmin - 1e-9:
                add("error", "PLG-RADIO", p.ref, f"Radio interior {s.r} mm inferior al mínimo {rmin:g} mm para "
                    f"{p.material}.", f"Aumentar RADIO_PLEGADO a {rmin:g} mm.")
            V = next((v for v in pb["v_dies_mm"] if v >= pb["v_die_factor"] * s.t), pb["v_dies_mm"][-1])
            bmin = V / 2 + s.r + s.t
            for f in s.flanges:
                if f.height < bmin:
                    add("error", "PLG-ALA-MIN", p.ref, f"Pestaña {f.edge} de {f.height} mm inferior al mínimo "
                        f"{bmin:.1f} mm (matriz V{V}).", f"Aumentar la pestaña a {math.ceil(bmin)} mm.")
                for sx, h, d in f.holes:
                    clr = h - d / 2 - s.R
                    if clr < pb["min_hole_to_bend_factor_t"] * s.t:
                        add("error", "PLG-TALADRO-PLIEGUE", p.ref, f"Taladro Ø{d} a {clr:.1f} mm del pliegue "
                            f"(mín. {pb['min_hole_to_bend_factor_t'] * s.t:.1f} mm): se deformará al plegar.",
                            "Alejar el taladro del pliegue o aumentar la pestaña.")
                    if f.height - h - d / 2 < s.t:
                        add("error", "LAS-TALADRO-BORDE", p.ref, f"Taladro Ø{d} demasiado próximo al borde de la pestaña.")
                    dmin = las["min_hole_diameter_factor"].get(mat.family, 1.0) * s.t
                    if d < dmin:
                        add("error", "LAS-TALADRO-DIAM", p.ref, f"Taladro Ø{d} menor que el mínimo {dmin:g} mm.")
            for L in s.bend_lengths():
                if L > pb["max_bend_length_mm"]:
                    add("error", "PLG-LONGITUD", p.ref, f"Longitud de pliegue {L:.0f} mm supera la plegadora "
                        f"({pb['max_bend_length_mm']} mm).", "Dividir la pieza o usar una plegadora mayor.")
            nx, ny = s.notch
            if nx and nx < s.R:
                add("error", "PLG-ESCOTADURA", p.ref, "Escotadura de esquina menor que el radio exterior de plegado.")
            add("ok", "PLG-ALIVIO", p.ref, "Esquinas abiertas con alivio de plegado ≥ radio exterior.")
        elif isinstance(p, ProfilePart):
            if p.length > bar_len - 20:
                add("error", "PRF-LONGITUD", p.ref, f"Longitud {p.length} mm superior a la barra comercial.",
                    "Prever empalme soldado o barra de 12 m.")
            if p.length < 40:
                add("advertencia", "PRF-CORTA", p.ref, "Pieza muy corta para la sujeción en sierra.")
            for face, z, off, d in p.holes:
                flat = (p.profile.H if face in ("+x", "-x") else p.profile.B) - 2 * p.profile.r_out
                if d > flat:
                    add("error", "PRF-TALADRO", p.ref, f"Taladro Ø{d} mayor que la zona plana del perfil ({flat:.1f} mm).")
                if abs(off) + d / 2 > flat / 2 + 1e-6:
                    add("error", "PRF-TALADRO-POS", p.ref, f"Taladro Ø{d} fuera de la zona plana del perfil.")
        elif isinstance(p, PlatePart):
            for x, y, d in p.holes:
                if d < p.t:
                    add("error", "LAS-TALADRO-DIAM", p.ref, f"Taladro Ø{d} menor que el espesor {p.t} mm.")
    # tornillería (por unión atornillada; datos registrados por la familia)
    seen = set()
    for j in model.joints:
        if j.kind != "atornillada" or not j.data:
            continue
        dd = j.data
        tray = model.instance(j.members[0]).part
        key = (tray.ref, dd["screw"], dd["rivet"], dd["wall"])
        if key in seen:
            continue
        seen.add(key)
        sc = catalog.component(dd["screw"])
        rnd = catalog.component(dd["rivet"])
        clamp = dd["t_sheet"] + dd["gap"]
        if not dd.get("rivet_found", True):
            add("error", "MON-REMACHABLE-AGARRE", tray.ref, f"Ninguna tuerca remachable del catálogo admite pared de "
                f"{dd['wall']:g} mm.", "Usar un perfil de pared ≤ 5,5 mm o fijación con tornillo pasante.")
        if not dd.get("screw_found", True):
            add("error", "MON-TORNILLO", tray.ref, f"Ningún tornillo ISO 7380 M6 del catálogo da 1·d de rosca útil con "
                f"{clamp:g} mm de chapa + holgura sin sobrepasar la tuerca remachable.",
                "Reducir holgura o espesor, o añadir longitudes de tornillo al catálogo.")
        # taladro de paso: el registrado por la familia (paneles lisos con otros taladros mayores) o el de las pestañas
        hole = dd.get("hole") or max((h[2] for f in tray.spec.flanges for h in f.holes), default=sc["clearance_hole"])
        if hole > sc["head_d"] - 2.0:
            add("error", "MON-APOYO-CABEZA", tray.ref, f"Taladro Ø{hole:g} demasiado grande para la cabeza Ø{sc['head_d']:g} "
                "del tornillo.", "Usar arandela ancha ISO 7093 o tornillo de cabeza mayor.")
        if rnd["head_h"] > dd["gap"] + 1e-9:
            add("error", "DFM-HOLGURA-REMACHABLE", tray.ref, "La cabeza de la tuerca remachable no cabe en la holgura.")
        # compatibilidad tornillo – tuerca remachable – pared (datos de la base de componentes)
        if sc["thread"] != rnd["thread"]:
            add("error", "MON-ROSCA", tray.ref, f"Rosca del tornillo {sc['thread']} distinta de la de la tuerca remachable "
                f"{rnd['thread']}.", "Usar tornillo y tuerca de la misma métrica.")
        engaged = sc["length"] - clamp
        need = min(sc["d"], rnd.get("thread_len", sc["d"]))
        if engaged < need - 1e-9:
            add("error", "MON-ROSCA-UTIL", tray.ref, f"Rosca útil {engaged:g} mm menor que la mínima {need:g} mm en la tuerca "
                "remachable.", "Usar un tornillo más largo.")
        if sc["length"] > clamp + rnd["body_l"] + 1e-9:
            add("error", "MON-PROFUNDIDAD", tray.ref, f"El tornillo ({sc['length']:g} mm) sobrepasa el cuerpo de la tuerca "
                f"remachable ({clamp + rnd['body_l']:g} mm desde la cabeza).", "Usar un tornillo más corto.")
        tq = [v for v in (sc.get("tightening_torque_Nm"), rnd.get("max_torque_Nm")) if v is not None]
        pend = (rnd.get("validation") or {}).get("status") != "definido_por_norma"
        add("ok", "MON-TORNILLERIA", tray.ref, f"{sc['name']} con {rnd['name'].split(',')[0]} (pared {dd['wall']:g} mm, "
            f"paquete {clamp:g} mm, rosca útil {engaged:g} mm, par {min(tq):g} N·m"
            f"{' orientativo' if pend else ''}, {sc.get('tool', 'herramienta según ficha')}).")
    # soldadura
    leg_ids = model.structure.get("leg_ids", [])
    if leg_ids and model.structure.get("nuts_inside_legs", True):     # tuerca dentro del tubo de la pata
        leg = model.instance(leg_ids[0]).part.profile
        nut = next((p for p in model.parts.values() if isinstance(p, StandardPart) and p.role == "tuerca_soldar"), None)
        if nut:
            ac = nut.data["s"] / math.cos(math.pi / 6)
            inner = leg.B - 2 * leg.t
            if ac > inner - 1:
                add("error", "SOL-TUERCA", nut.ref, f"La tuerca de soldar ({ac:.1f} mm entre vértices) no cabe en la pata.")
    thin = [j for j in model.joints if j.kind == "soldadura" and j.weld["a"] < 3]
    if thin:
        add("advertencia", "SOL-GARGANTA", "Uniones soldadas", f"{len(thin)} cordones con garganta < 3 mm en pared "
            "delgada: requieren WPS cualificada y control de penetración.", "Soldar con MAG pulsado, hilo Ø0,8.")
    # compatibilidad de materiales en las uniones soldadas (la tuerca DIN 929 de acero no se suelda a aluminio)
    def weld_family(inst):
        p = inst.part
        if isinstance(p, StandardPart):
            return p.data.get("material_family", "acero_carbono")
        mat = getattr(p, "material", None)
        return catalog.material(mat).family if mat else None
    alu_steel, dissimilar = [], []
    for j in model.joints:
        if j.kind != "soldadura":
            continue
        fams = {weld_family(model.instance(i)) for i in j.members} - {None}
        if "aluminio" in fams and len(fams) > 1:
            alu_steel.append(j.id)
        elif fams == {"acero_carbono", "acero_inoxidable"}:
            dissimilar.append(j.id)
    if alu_steel:
        add("error", "SOL-MATERIALES", "Uniones soldadas", f"{len(alu_steel)} uniones soldadas entre aluminio y acero "
            f"(p. ej. {alu_steel[0]}): no son soldables por fusión.", "Usar el mismo material en las piezas soldadas.")
    if dissimilar:
        add("advertencia", "SOL-DISIMILAR", "Uniones soldadas", f"{len(dissimilar)} uniones soldadas entre acero al "
            f"carbono e inoxidable (p. ej. {dissimilar[0]}): soldadura disimilar con aporte austenítico (tipo 309L) y "
            "riesgo de corrosión en ambiente húmedo.", "Usar el mismo material en las piezas soldadas.")
    # caras enrasadas o dentro del radio de esquina de la barra de apoyo: siempre desde la geometría (no supuesto)
    wf = weld_face_conditions(model)
    if wf["flush"]:
        add("advertencia", "SOL-ENRASE", "Uniones soldadas", f"{wf['flush']} uniones con una cara enrasada con la de la "
            "barra a la que se sueldan (misma cara exterior o mismo canto): en esa cara el cordón cae sobre el radio de "
            "esquina (ángulo exterior o borde).", "Amolar esos cordones donde apoye una chapa y antes de pintar.")
    if wf["corner"]:
        add("advertencia", "SOL-RADIO-ESQUINA", "Uniones soldadas", f"{wf['corner']} uniones con una cara lateral a "
            f"{wf['corner_min']:g} mm de la cara de la barra de apoyo, dentro de su radio de esquina ({wf['corner_r']:g} mm): "
            "en ese lado el cordón es en bisel abocinado sobre el radio, con garganta efectiva reducida.",
            "Recogerlo en la WPS o separar la barra de la cara al menos el radio de esquina.")
    weld_notes = model.structure.get("dfm_weld_notes")     # advertencias de soldeo propias de la familia
    if weld_notes is None:
        weld_notes = [("SOL-DEFORMACION", "Estructura soldada", "Riesgo de distorsión en bastidores de pared delgada: "
                       "puntear en mesa plana con escuadras, soldar en secuencia simétrica alterna y verificar la "
                       "planitud de las superficies de apoyo de las chapas (EN ISO 13920 clase F).")]
    for code, elem, msg in weld_notes:
        add("advertencia", code, elem, msg)
    # galvanizado en caliente: los tubos cerrados por soldadura necesitan venteo y drenaje (no modelados)
    galv = sorted({i.part.ref for i in model.instances if i.part.kind == "perfil" and i.part.finish == "GALVANIZADO"})
    if galv:
        add("advertencia", "GAL-VENTEO", "Perfiles huecos", f"Galvanizado en caliente (EN ISO 1461) de {len(galv)} perfiles "
            "huecos cerrados por soldadura: necesitan taladros de venteo y drenaje en los dos extremos de cada tubo "
            "(EN ISO 14713-2), que no están modelados. Criterio orientativo: Ø ≥ 25 % de la dimensión interior y no menos "
            "de 10 mm, en caras opuestas. Las roscas de las tuercas soldadas se repasan después del galvanizado.",
            "Añadir los taladros en los planos de taller antes de fabricar y consultarlos con el galvanizador.")
    if plan:
        for n in plan["nesting"]:
            if not n.get("feasible", False):
                add("error", "LAS-FORMATO", f"Chapa {n['material']} {n['thickness']} mm", n.get("reason", ""),
                    "Dividir la pieza en dos o seleccionar un formato mayor.")
    grouped: dict[tuple, dict[str, Any]] = {}
    for f in out:                       # un hallazgo por pieza y código, con número de casos
        k = (f["level"], f["code"], f["element"])
        if k in grouped:
            grouped[k]["count"] += 1
        else:
            grouped[k] = {**f, "count": 1}
    for g in grouped.values():
        if g["count"] > 1:
            g["message"] = f"{g['message']} ({g['count']} casos)"
    return list(grouped.values())
