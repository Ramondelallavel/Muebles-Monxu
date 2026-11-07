"""Lista de materiales sincronizada con el modelo CAD (pesos calculados desde los sólidos)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import catalog
from ..core.model import KIND_LABEL, PlatePart, ProfilePart, SheetPart, StandardPart


def build_bom(model, plan: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    for i in model.instances:
        counts[i.part.key] += 1
    rows = []
    for p in sorted(model.parts.values(), key=lambda p: p.pos):
        dims = p.bom_dims()
        qty = counts[p.key]
        um = round(p.mass, 4)
        rows.append({
            "pos": p.pos, "ref": p.ref, "description": p.name, "kind": p.kind, "kind_label": KIND_LABEL[p.kind],
            "material": p.material or (p.data.get("standard") if isinstance(p, StandardPart) else ""),
            "finish": catalog.finish(p.finish)["name"] if p.finish else "",
            "thickness": dims.get("espesor"), "length": dims.get("largo"), "width": dims.get("ancho"),
            "section": dims.get("seccion"), "qty": qty, "unit_mass": um, "total_mass": round(um * qty, 4), "mass_exact": p.mass * qty,
            "process": " + ".join(plan["routing"].get(p.ref, [])),
            "nominal_mass": round(p.nominal_mass, 3) if isinstance(p, ProfilePart) else (
                round(p.flat.net_area() * p.spec.t * 1e-9 * p.density, 3) if isinstance(p, SheetPart) else None),
            "standard": p.data.get("standard") if isinstance(p, StandardPart) else
            (catalog.profile(p.profile.code).standard if isinstance(p, ProfilePart) else None),
            "code": p.code if isinstance(p, StandardPart) else None,
            "instances": [i.id for i in model.instances if i.part.key == p.key],
        })
    # ------------------------------------------------------------- totales
    prof_m: dict[str, float] = defaultdict(float)
    sheet_m2: dict[str, float] = defaultdict(float)
    std_units: dict[str, int] = defaultdict(int)
    for p in model.parts.values():
        n = counts[p.key]
        if isinstance(p, ProfilePart):
            prof_m[f"{p.profile.code} {p.material}"] += p.length * n / 1000
        elif isinstance(p, SheetPart):
            sheet_m2[f"{p.material} e={p.spec.t:g} mm"] += p.flat.net_area() * n / 1e6
        elif isinstance(p, PlatePart):
            sheet_m2[f"{p.material} e={p.t:g} mm"] += p.w * p.h * n / 1e6
        elif isinstance(p, StandardPart):
            std_units[p.name] += n
    totals = {
        "components": sum(r["qty"] for r in rows),
        "distinct_parts": len(rows),
        "manufactured_parts": sum(r["qty"] for r in rows if r["kind"] != "normalizado"),
        "standard_parts": sum(r["qty"] for r in rows if r["kind"] == "normalizado"),
        "total_mass": round(sum(r["mass_exact"] for r in rows), 3),
        "profile_meters": {k: round(v, 3) for k, v in sorted(prof_m.items())},
        "sheet_area_m2": {k: round(v, 4) for k, v in sorted(sheet_m2.items())},
        "standard_units": dict(sorted(std_units.items())),
    }
    # ------------------------------------------------------------- compras
    purchases = []
    for c in plan["cutting"]:
        purchases.append({"type": "Perfil", "description": f"Barra {c['profile']} {c['material']} L={c['bar_length']:.0f} mm",
                          "qty": c["n_bars"], "unit": "barra", "mass_kg": round(c["n_bars"] * c["mass_per_bar_kg"], 2)})
    for n in plan["nesting"]:
        if n.get("feasible") and n["utilization"] >= 0.10:
            purchases.append({"type": "Chapa", "description": f"Chapa {n['material']} e={n['thickness']:g} mm "
                              f"formato {n['format']}", "qty": n["n_sheets"], "unit": "chapa",
                              "mass_kg": round(n["n_sheets"] * n["mass_per_sheet_kg"], 2)})
        elif n.get("feasible"):
            gap = n["spacing"] + n["kerf"]
            area = sum((p["w"] + gap) * (p["h"] + gap) for s in n["sheets"] for p in s["placements"]) * 1.15 / 1e6
            rho = catalog.material(n["material"]).density
            purchases.append({"type": "Chapa (retal / corte a medida)",
                              "description": f"Chapa {n['material']} e={n['thickness']:g} mm — aprovechamiento de "
                                             f"formato < 10 %: pedir corte a medida o usar retal",
                              "qty": round(area, 3), "unit": "m²",
                              "mass_kg": round(area * n["thickness"] * 1e-3 * rho, 2)})
    for r in rows:
        if r["kind"] == "normalizado":
            purchases.append({"type": "Comercial", "description": f"{r['description']} ({r['standard']})",
                              "qty": r["qty"], "unit": "ud", "mass_kg": r["total_mass"], "code": r["code"]})
    w = plan["welding"]
    pnt = plan["painting"]
    consumables = [
        {"description": w["wire"], "qty": w["wire_kg"], "unit": "kg"},
        {"description": w["gas"], "qty": w["gas_l"], "unit": "l"},
    ]
    if pnt["powder_kg"]:
        consumables.append({"description": catalog.finish(pnt["finish"])["name"], "qty": pnt["powder_kg"], "unit": "kg",
                            "basis": f"{pnt['area_m2']} m² pintados"})
    remnants = []
    for c in plan["cutting"]:
        for b in c["bars"]:
            remnants.append({"profile": c["profile"], "bar": b["bar"], "length": b["remnant"],
                             "reusable": b["remnant_reusable"]})
    return {"rows": rows, "totals": totals, "purchases": purchases, "consumables": consumables, "remnants": remnants}
