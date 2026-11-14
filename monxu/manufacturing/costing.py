"""Presupuesto estimado de fabricación (coste unitario por tamaño de lote).

Todo sale del modelo y del plan de fabricación, con las tarifas orientativas de ``catalog/data/costs.json``:

* Material: barras y chapas que hay que comprar para el lote según el plan de corte y el anidado reales
  (``imputacion_material`` = "compra"), o lo comprado menos los retales reutilizables que vuelven al inventario
  ("consumo"). Nunca porcentajes genéricos de merma o aprovechamiento.
* Normalizados: pies, ruedas, tuercas y tornillos, a precio unitario de catálogo.
* Consumibles: hilo y gas de soldadura.
* Fabricación: cortes de sierra del plan de corte (refrentado + uno por pieza), taladros de los perfiles,
  láser (metros de contorno y una perforación por contorno cerrado), plegado y soldadura. La soldadura se
  calcula como horas de arco divididas por el factor de marcha.
* Acabado: superficie tratada o masa (galvanizado).
* Montaje: tiempo por tornillo, tuerca remachable y apoyo, más un tiempo fijo por unidad.
* Control de calidad: tiempo fijo por unidad y por unión soldada (control dimensional y visual).
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
from .plan import material_purchase


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

    def add(group, concept, qty, unit, unit_eur, eur=None, basis=""):
        eur = qty * unit_eur if eur is None else eur
        lines.append({"group": group, "concept": concept, "qty": round(qty, 4), "unit": unit,
                      "unit_eur": round(unit_eur, 4), "eur": eur, "basis": basis})

    counts: dict[str, int] = defaultdict(int)
    for i in model.instances:
        counts[i.part.key] += 1
    # el material del lote sale de su propio plan de corte y anidado (el del proyecto si coincide el lote)
    mp = plan if plan.get("lot", 1) == lot else material_purchase(model, lot)
    basis = op["imputacion_material"]
    if basis not in ("compra", "consumo"):
        raise ValueError(f"imputacion_material desconocida: {basis}")
    # ---------------------------------------------------------------- material
    for c in mp["cutting"]:
        eur_kg = _material_rate(R, c["material"], "tubo")
        k = c["kg_per_m"] / 1000
        if basis == "compra":
            kg = c["purchased_length"] * k
            what = f"{c['n_bars']} barras de {c['bar_length']:g} mm compradas"
        else:
            kg = (c["purchased_length"] + c["stock_length"] - c["reusable_length"]) * k
            what = f"consumo {(c['purchased_length'] + c['stock_length'] - c['reusable_length']) / 1000:.2f} m"
        txt = (f"Perfil {c['profile']} {c['material']}: {what} por lote de {lot} (neto {c['pieces_length'] / 1000:.2f} m, "
               f"desperdicio {c['waste_length'] / 1000:.2f} m, retal reutilizable {c['reusable_length'] / 1000:.2f} m)")
        add("Material", txt, kg / lot, "kg", eur_kg, basis="plan de corte")
    for n in mp["nesting"]:
        forms = catalog._load("materials")["materials"][n["material"]].get("forms", [])
        eur_kg = _material_rate(R, n["material"], "chapa" if "chapa" in forms else "pletina")
        k = n["thickness"] * 1e-3 * catalog.material(n["material"]).density
        if not n.get("feasible"):
            kg = n["parts_area_m2"] * k
            txt = (f"Chapa {n['material']} e={n['thickness']:g} mm: sin formato comercial válido, superficie neta de "
                   f"piezas {n['parts_area_m2']:.3f} m² (PENDIENTE: la pieza no cabe en ningún formato)")
            add("Material", txt, kg / lot, "kg", eur_kg, basis="superficie neta (sin anidado válido)")
            continue
        pu = n["purchase"]
        if basis == "compra":
            kg = pu["purchased_area_m2"] * k
            what = (f"{pu['n_full']} chapas {n['format']}" if pu["n_full"] else "") + \
                   (f"{' + ' if pu['n_full'] else ''}{pu['n_custom']} cortada a medida" if pu["n_custom"] else "")
        else:
            kg = (pu["purchased_area_m2"] + pu["stock_area_m2"] - pu["reusable_area_m2"]) * k
            what = f"consumo {pu['purchased_area_m2'] + pu['stock_area_m2'] - pu['reusable_area_m2']:.3f} m²"
        txt = (f"Chapa {n['material']} e={n['thickness']:g} mm: {what or 'retales de inventario'} por lote de {lot} "
               f"(piezas {pu['parts_area_m2']:.3f} m², aprovechamiento real {pu['utilization'] * 100:.1f} %)")
        add("Material", txt, kg / lot, "kg", eur_kg, basis="anidado")
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
        add("Normalizados", catalog.component(code)["name"], std[code], "ud", eur, basis="BOM")
    # ---------------------------------------------------------------- fabricación
    holes = 0
    laser_m: dict[tuple, float] = defaultdict(float)
    pierces = bends = 0
    sheet_refs = laser_refs = 0
    surf_m2 = galv_kg = 0.0
    for k, p in model.parts.items():
        q = counts[k]
        if isinstance(p, ProfilePart):
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
    cuts = sum(c["n_cuts"] for c in mp["cutting"])
    if cuts:
        add("Fabricación", f"Corte de perfiles en sierra ({cuts} cortes por lote de {lot}: refrentado de cada barra y uno "
            "por pieza)", cuts / lot, "corte", op["sierra_eur_corte"], basis="plan de corte")
    if holes:
        add("Fabricación", "Taladrado de perfiles", holes, "taladro", op["taladro_eur"], basis="geometría (taladros de perfiles)")
    for (t, fam), m in sorted(laser_m.items()):
        add("Fabricación", f"Corte por láser e={t:g} mm ({fam.replace('_', ' ')})", m, "m", _laser_rate(R, t, fam),
            basis="contornos exteriores e interiores de los desarrollos")
    if pierces:
        add("Fabricación", "Perforaciones del láser (una por contorno cerrado)", pierces, "ud", op["laser_eur_perforacion"],
            basis="contornos de los desarrollos")
    if bends:
        add("Fabricación", "Plegado a 90°", bends, "pliegue", op["plegado_eur_pliegue"], basis="pliegues del modelo")
    w = plan["welding"]
    if w["joints"]:
        h = w["arc_time_h"] / op["soldadura_factor_marcha"]
        add("Fabricación", f"Soldadura MAG ({w['total_length_mm'] / 1000:.2f} m de cordón, factor de marcha "
            f"{op['soldadura_factor_marcha']:g})", h, "h", lab["soldadura"], basis="cordones del modelo")
        add("Consumibles", "Hilo de soldadura", w["wire_kg"], "kg", R["consumables_eur"]["hilo_kg"], basis="cordones del modelo")
        add("Consumibles", "Gas de protección", w["gas_l"], "l", R["consumables_eur"]["gas_l"], basis="tiempo de arco")
    # ---------------------------------------------------------------- acabado
    fin = model.params.values.get("ACABADO")
    base, eur_f = _finish_rate(R, fin)
    if eur_f:
        name = catalog.finish(fin)["name"] if fin else "Acabado"
        if base == "kg":
            add("Acabado", name, galv_kg, "kg", eur_f, basis="masa de las piezas")
        else:
            add("Acabado", name, surf_m2, "m²", eur_f, basis="superficie de las piezas")
    # ---------------------------------------------------------------- montaje
    mm = op["montaje_min"]
    roles = defaultdict(int)
    for i in model.instances:
        roles[i.part.role] += 1
    minutes = (roles["tornillo"] * mm["tornillo"] + roles["tuerca_remachable"] * mm["tuerca_remachable"]
               + (roles["pie_nivelador"] + roles["rueda"]) * mm["apoyo"] + mm["por_unidad"])
    add("Montaje", "Montaje y ajuste final", minutes / 60, "h", lab["montaje"], basis="componentes del modelo")
    # ---------------------------------------------------------------- control de calidad
    cm = op.get("control_min")
    if cm:
        qmin = cm["por_unidad"] + cm["por_union_soldada"] * w["joints"]
        add("Control de calidad", f"Control dimensional y visual de soldaduras ({w['joints']} uniones soldadas)",
            qmin / 60, "h", lab["control"], basis="uniones del modelo")
    # ---------------------------------------------------------------- preparación del lote
    n_prof = len(mp["cutting"])
    prep = (n_prof * setup["sierra_por_perfil"] + laser_refs * setup["laser_por_referencia"]
            + sheet_refs * setup["plegado_por_referencia"] + (setup["soldadura_util"] if w["joints"] else 0.0))
    add("Preparación", f"Programación y preparación de máquinas y útil ({lot} ud por lote)", 1 / lot, "lote", prep,
        basis="referencias del modelo")
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
    mat_kg = sum(ln["qty"] for ln in lines if ln["group"] == "Material")
    return {"currency": R["_meta"]["currency"], "lot": lot, "lines": lines,
            "groups": {k: round(v, 2) for k, v in groups.items()}, "direct": round(direct, 2),
            "overheads": round(oh, 2), "cost": round(cost, 2), "margin": round(margin, 2), "price": round(price, 2),
            "eur_per_kg": round(cost / mass, 2) if mass else None, "hours": hours,
            "rates_version": R["_meta"]["version"], "unpriced": unpriced, "material_basis": basis,
            "material_kg_per_unit": round(mat_kg, 3), "saw_cuts_lot": cuts,
            "overhead_rate": R["overheads"]["gastos_generales"], "margin_rate": R["overheads"]["margen"],
            "note": R["_meta"]["note"]}


def quotation(model, plan: dict[str, Any], R: dict[str, Any] | None = None) -> dict[str, Any]:
    """Presupuesto del lote del proyecto (LOTE_FABRICACION, 1 por defecto) y tabla de coste por unidad según el lote."""
    R = R or rates()
    lot = max(1, int(model.params.values.get("LOTE_FABRICACION") or 1))     # lote del proyecto (parámetro avanzado)
    base = estimate(model, plan, lot, R)
    lots = sorted(set(R["lots"]) | {lot})
    base["by_lot"] = [{"lot": n, **{k: e[k] for k in ("direct", "cost", "price")},
                       "material": e["groups"].get("Material", 0.0)}
                      for n in lots for e in [base if n == lot else estimate(model, plan, n, R)]]
    return base
