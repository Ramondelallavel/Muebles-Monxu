"""Lista de materiales sincronizada con el modelo CAD (pesos calculados desde los sólidos)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import catalog
from ..core.model import KIND_LABEL, PlatePart, ProfilePart, SheetPart, StandardPart
from ..manufacturing.plan import _std_label, plate_net_area


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
            "material": p.material or (p.data.get("material") or "" if isinstance(p, StandardPart) else ""),
            "finish": catalog.finish(p.finish)["name"] if p.finish else "",
            "thickness": dims.get("espesor"), "length": dims.get("largo"), "width": dims.get("ancho"),
            "section": dims.get("seccion"), "qty": qty, "unit_mass": um, "total_mass": round(um * qty, 4), "mass_exact": p.mass * qty,
            "process": " + ".join(plan["routing"].get(p.ref, [])),
            "nominal_mass": round(p.nominal_mass, 3) if isinstance(p, ProfilePart) else (
                round(p.flat.net_area() * p.spec.t * 1e-9 * p.density, 3) if isinstance(p, SheetPart) else None),
            "standard": _std_label(p.data) if isinstance(p, StandardPart) else
            (catalog.profile(p.profile.code).standard if isinstance(p, ProfilePart) else None),
            "validation": (p.data.get("validation") or {}).get("status", "pendiente_validacion")
            if isinstance(p, StandardPart) else None,
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
            sheet_m2[f"{p.material} e={p.t:g} mm"] += plate_net_area(p) * n / 1e6
        elif isinstance(p, StandardPart):
            std_units[p.name] += n
    man = sum(r["mass_exact"] for r in rows if r["kind"] != "normalizado")
    com = sum(r["mass_exact"] for r in rows if r["kind"] == "normalizado")
    bal = plan["balance"]["totals"]
    lot = plan.get("lot", 1)
    totals = {
        "components": sum(r["qty"] for r in rows),
        "distinct_parts": len(rows),
        "manufactured_parts": sum(r["qty"] for r in rows if r["kind"] != "normalizado"),
        "standard_parts": sum(r["qty"] for r in rows if r["kind"] == "normalizado"),
        "total_mass": round(man + com, 3),
        # masas separadas (por unidad): producto = piezas fabricadas (sólidos × densidad) + componentes comerciales
        "mass_manufactured_kg": round(man, 3),
        "mass_commercial_kg": round(com, 3),
        "mass_product_kg": round(man + com, 3),
        # material en bruto del lote (plan de corte y anidado, masa nominal): no se mezcla con la masa del producto
        "material_lot": lot,
        "mass_purchased_kg": bal["purchased_kg"],
        "mass_from_stock_kg": bal["from_stock_kg"],
        "mass_raw_net_kg": bal["net_kg"],
        "mass_waste_kg": bal["waste_kg"],
        "mass_reusable_kg": bal["reusable_kg"],
        "profile_meters": {k: round(v, 3) for k, v in sorted(prof_m.items())},
        "sheet_area_m2": {k: round(v, 4) for k, v in sorted(sheet_m2.items())},
        "standard_units": dict(sorted(std_units.items())),
    }
    pu = plan["purchases"]
    purchases = [{k: v for k, v in it.items()} for it in pu["items"]]
    return {"rows": rows, "totals": totals, "purchases": purchases, "consumables": pu["consumables"],
            "remnants": pu["remnants"], "lot": lot}
