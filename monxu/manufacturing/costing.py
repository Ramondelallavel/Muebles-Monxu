"""Presupuesto estimado de fabricación (coste unitario por tamaño de lote).

Todo sale del modelo y del plan de fabricación, con las tarifas orientativas de ``catalog/data/costs.json``:

* Material: barras y chapas que hay que comprar. En lote, la compra se reparte por consumo real, con el
  aprovechamiento de la chapa indicado en las tarifas.
* Normalizados: pies, ruedas, tuercas y tornillos, a precio unitario de catálogo.
* Consumibles: hilo y gas de soldadura.
* Fabricación: cortes y taladros de perfiles, láser (metros de corte y perforaciones), plegado y soldadura.
  La soldadura se calcula como horas de arco divididas por el factor de marcha.
* Acabado: superficie tratada o masa (galvanizado).
* Montaje: tiempo por tornillo, tuerca remachable y apoyo, más un tiempo fijo por unidad.
* Preparación: programación del láser, puesta a punto de sierra y plegadora y útil de soldadura, repartidas
  entre las unidades del lote.
* Gastos generales y margen sobre el coste directo.

El motor del navegador (``frontend/src/engine/costing.ts``) aplica exactamente el mismo cálculo.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .. import catalog
from ..core.model import PlatePart, ProfilePart, SheetPart, StandardPart


def rates() -> dict[str, Any]:
    return catalog._load("costs")


def _material_rate(R, code: str, form: str) -> float:
    if code in R["material_overrides_eur_kg"]:
        return R["material_overrides_eur_kg"][code]
    fam = catalog.material(code).family
    return R["material_eur_kg"].get(fam, R["material_eur_kg"]["acero_carbono"])[form]


def _component_price(R, code: str) -> tuple[float, bool]:
    for prefix, eur in R["components_eur"]:
        if code.startswith(prefix):
            return eur, True
    return R["component_default_eur"], False


def _laser_rate(R, t: float, family: str) -> float:
    table = R["operations"]["laser_eur_m"]
    eur = table[-1][1]
    for tmax, v in table:
        if t <= tmax + 1e-9:
            eur = v
            break
    return eur * R["operations"]["laser_factor_material"].get(family, 1.0)


def _finish_rate(R, finish: str | None) -> tuple[str, float]:
    """(base: m2 | kg, €/unidad) del acabado."""
    F = R["finishes_eur"]
    if not finish:
        return "m2", 0.0
    if finish == "CATAFORESIS_POLVO":
        return "m2", F["CATAFORESIS_POLVO_m2"]
    if finish.endswith("_POLVO"):
        return "m2", F["POLVO_m2"]
    if f"{finish}_kg" in F:
        return "kg", F[f"{finish}_kg"]
    return "m2", F.get(f"{finish}_m2", 0.0)


def _surface_mm2(p) -> float:
    if isinstance(p, ProfilePart):
        return (2 * (p.profile.B + p.profile.H) - (8 - 2 * math.pi) * p.profile.r_out) * p.length
    if isinstance(p, SheetPart):
        return 2 * p.flat.net_area()
    if isinstance(p, PlatePart):
        return 2 * p.w * p.h + 2 * (p.w + p.h) * p.t
    return 0.0


def _plate_cut_mm(p: PlatePart) -> float:
    r = p.corner_r
    return 2 * (p.w + p.h) - (8 - 2 * math.pi) * r + sum(math.pi * d for _, _, d in p.holes)


def estimate(model, plan: dict[str, Any], lot: int = 1, R: dict[str, Any] | None = None) -> dict[str, Any]:
    R = R or rates()
    lot = max(1, int(lot))
    op, lab, setup = R["operations"], R["labor_eur_h"], R["setup_eur"]
    lines: list[dict[str, Any]] = []

    def add(group, concept, qty, unit, unit_eur, eur=None):
        eur = qty * unit_eur if eur is None else eur
        lines.append({"group": group, "concept": concept, "qty": round(qty, 4), "unit": unit,
                      "unit_eur": round(unit_eur, 4), "eur": eur})

    counts: dict[str, int] = defaultdict(int)
    for i in model.instances:
        counts[i.part.key] += 1
    # ---------------------------------------------------------------- material
    # "consumo": se imputa lo que se gasta (con merma) y el sobrante vuelve a almacén;
    # "compra": barras y chapas completas necesarias para el lote.
    by_use = op["imputacion_material"] == "consumo"
    for c in plan["cutting"]:
        used = c["pieces_length"] + c["pieces"] * c["kerf"]
        eur_kg = _material_rate(R, c["material"], "tubo")
        if by_use:
            bars = used / c["bar_length"] * (1 + op["merma_perfil"])
            kg = bars * c["mass_per_bar_kg"]
            txt = f"Perfil {c['profile']} {c['material']} ({used / 1000:.2f} m + {op['merma_perfil'] * 100:g} % de merma)"
        else:
            bars = c["n_bars"] if lot == 1 else math.ceil(lot * used / (c["bar_length"] - c["trim"]))
            kg = bars * c["mass_per_bar_kg"] / lot
            txt = f"Perfil {c['profile']} {c['material']} (barras de {c['bar_length']:g} mm: {bars} por lote)"
        add("Material", txt, kg, "kg", eur_kg)
    for n in plan["nesting"]:
        mat = catalog.material(n["material"])
        forms = catalog._load("materials")["materials"][n["material"]].get("forms", [])
        eur_kg = _material_rate(R, n["material"], "chapa" if "chapa" in forms else "pletina")
        u = op["aprovechamiento_chapa_lote"]
        if by_use or not n.get("feasible"):
            kg = n["parts_area_m2"] * 1e6 * n["thickness"] * 1e-9 * mat.density / u
            txt = (f"Chapa {n['material']} e={n['thickness']:g} mm ({n['parts_area_m2']:.3f} m² de piezas, "
                   f"aprovechamiento {u * 100:g} %)")
        else:
            sheets = n["n_sheets"] if lot == 1 else math.ceil(lot * n["parts_area_m2"] / (n["sheet_area_m2"] * u))
            kg = sheets * n["mass_per_sheet_kg"] / lot
            txt = f"Chapa {n['material']} e={n['thickness']:g} mm (formato {n['format']}: {sheets} por lote)"
        add("Material", txt, kg, "kg", eur_kg)
    # ---------------------------------------------------------------- normalizados
    std: dict[str, int] = defaultdict(int)
    for i in model.instances:
        if isinstance(i.part, StandardPart):
            std[i.part.code] += 1
    unpriced = []
    for code in sorted(std):
        eur, known = _component_price(R, code)
        if not known:
            unpriced.append(code)
        add("Normalizados", catalog.component(code)["name"], std[code], "ud", eur)
    # ---------------------------------------------------------------- fabricación
    cuts = holes = 0
    laser_m: dict[tuple, float] = defaultdict(float)
    pierces = bends = 0
    sheet_refs = laser_refs = 0
    surf_m2 = galv_kg = 0.0
    for k, p in model.parts.items():
        q = counts[k]
        if isinstance(p, ProfilePart):
            cuts += q
            holes += q * len(p.holes)
        elif isinstance(p, SheetPart):
            fp = p.flat
            laser_m[(p.spec.t, catalog.material(p.material).family)] += q * fp.cut_length() / 1000
            pierces += q * (1 + len(fp.holes))
            bends += q * len(p.spec.flanges)
            sheet_refs += 1
            laser_refs += 1
        elif isinstance(p, PlatePart):
            laser_m[(p.t, catalog.material(p.material).family)] += q * _plate_cut_mm(p) / 1000
            pierces += q * (1 + len(p.holes))
            laser_refs += 1
        if not isinstance(p, StandardPart) and p.finish:
            surf_m2 += q * _surface_mm2(p) / 1e6
            if p.finish == "GALVANIZADO":
                galv_kg += q * p.mass
    if cuts:
        add("Fabricación", "Corte de perfiles en sierra", cuts, "corte", op["sierra_eur_corte"])
    if holes:
        add("Fabricación", "Taladrado de perfiles", holes, "taladro", op["taladro_eur"])
    for (t, fam), m in sorted(laser_m.items()):
        add("Fabricación", f"Corte por láser e={t:g} mm ({fam.replace('_', ' ')})", m, "m", _laser_rate(R, t, fam))
    if pierces:
        add("Fabricación", "Perforaciones del láser (contornos y taladros)", pierces, "ud", op["laser_eur_perforacion"])
    if bends:
        add("Fabricación", "Plegado a 90°", bends, "pliegue", op["plegado_eur_pliegue"])
    w = plan["welding"]
    if w["joints"]:
        h = w["arc_time_h"] / op["soldadura_factor_marcha"]
        add("Fabricación", f"Soldadura MAG ({w['total_length_mm'] / 1000:.2f} m de cordón, factor de marcha "
            f"{op['soldadura_factor_marcha']:g})", h, "h", lab["soldadura"])
        add("Consumibles", "Hilo de soldadura", w["wire_kg"], "kg", R["consumables_eur"]["hilo_kg"])
        add("Consumibles", "Gas de protección", w["gas_l"], "l", R["consumables_eur"]["gas_l"])
    # ---------------------------------------------------------------- acabado
    fin = model.params.values.get("ACABADO")
    base, eur_f = _finish_rate(R, fin)
    if eur_f:
        name = catalog.finish(fin)["name"] if fin else "Acabado"
        if base == "kg":
            add("Acabado", name, galv_kg, "kg", eur_f)
        else:
            add("Acabado", name, surf_m2, "m²", eur_f)
    # ---------------------------------------------------------------- montaje
    mm = op["montaje_min"]
    roles = defaultdict(int)
    for i in model.instances:
        roles[i.part.role] += 1
    minutes = (roles["tornillo"] * mm["tornillo"] + roles["tuerca_remachable"] * mm["tuerca_remachable"]
               + (roles["pie_nivelador"] + roles["rueda"]) * mm["apoyo"] + mm["por_unidad"])
    add("Montaje", "Montaje, ajuste y control final", minutes / 60, "h", lab["montaje"])
    # ---------------------------------------------------------------- preparación del lote
    n_prof = len(plan["cutting"])
    prep = (n_prof * setup["sierra_por_perfil"] + laser_refs * setup["laser_por_referencia"]
            + sheet_refs * setup["plegado_por_referencia"] + (setup["soldadura_util"] if w["joints"] else 0.0))
    add("Preparación", f"Programación y preparación de máquinas y útil ({lot} ud por lote)", 1 / lot, "lote", prep)
    # ---------------------------------------------------------------- totales
    groups: dict[str, float] = {}
    for ln in lines:
        groups[ln["group"]] = groups.get(ln["group"], 0.0) + ln["eur"]
    direct = sum(groups.values())
    oh = direct * R["overheads"]["gastos_generales"]
    cost = direct + oh
    margin = cost * R["overheads"]["margen"]
    price = cost + margin
    mass = sum(i.part.mass for i in model.instances)
    for ln in lines:
        ln["eur"] = round(ln["eur"], 2)
    hours = {"soldadura": round(w["arc_time_h"] / op["soldadura_factor_marcha"], 3) if w["joints"] else 0.0,
             "montaje": round(minutes / 60, 3)}
    return {"currency": R["_meta"]["currency"], "lot": lot, "lines": lines,
            "groups": {k: round(v, 2) for k, v in groups.items()}, "direct": round(direct, 2),
            "overheads": round(oh, 2), "cost": round(cost, 2), "margin": round(margin, 2), "price": round(price, 2),
            "eur_per_kg": round(cost / mass, 2) if mass else None, "hours": hours,
            "rates_version": R["_meta"]["version"], "unpriced": unpriced, "material_basis": op["imputacion_material"],
            "overhead_rate": R["overheads"]["gastos_generales"], "margin_rate": R["overheads"]["margen"],
            "note": R["_meta"]["note"]}


def quotation(model, plan: dict[str, Any], R: dict[str, Any] | None = None) -> dict[str, Any]:
    """Presupuesto del lote unitario y tabla de coste por unidad según el tamaño de lote."""
    R = R or rates()
    base = estimate(model, plan, 1, R)
    base["by_lot"] = [{"lot": n, **{k: e[k] for k in ("direct", "cost", "price")}}
                      for n in R["lots"] for e in [estimate(model, plan, n, R)]]
    return base
