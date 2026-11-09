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


def manufacturing_plan(model) -> dict[str, Any]:
    counts = _counts(model)
    sd = catalog.sheet_data()
    meta = catalog.profile_meta()
    bar_len = bar_length(model)
    kerf = float(model.params.values.get("CORTE_SIERRA") or 3.0)
    # ------------------------------------------------------------- perfiles
    groups: dict[tuple, list] = defaultdict(list)
    for k, p in model.parts.items():
        if isinstance(p, ProfilePart):
            groups[(p.profile.code, p.material)].append({"ref": p.ref, "label": p.name, "length": p.length,
                                                         "qty": counts[k]})
    cutting = []
    for (code, mat), pieces in sorted(groups.items()):
        r = optimize_bars(pieces, bar_length=bar_len, kerf=kerf)
        r.update({"profile": code, "material": mat,
                  "mass_per_bar_kg": round(catalog.profile(code).mass_per_m(catalog.material(mat).density) * bar_len / 1000, 2)})
        cutting.append(r)
    # ------------------------------------------------------------- chapa y pletinas
    sgroups: dict[tuple, list] = defaultdict(list)
    for k, p in model.parts.items():
        if isinstance(p, SheetPart):
            fp = p.flat
            sgroups[(p.material, p.spec.t)].append({"ref": p.ref, "w": fp.width, "h": fp.height, "qty": counts[k],
                                                     "area": fp.net_area(), "rotate": p.finish != "INOX_SATINADO",
                                                     "kind": "chapa"})
        elif isinstance(p, PlatePart):
            sgroups[(p.material, p.t)].append({"ref": p.ref, "w": p.w, "h": p.h, "qty": counts[k],
                                                "area": p.outline_2d().area - sum(math.pi * d * d / 4 for _, _, d in p.holes),
                                                "rotate": True, "kind": "pletina"})
    nesting = []
    las = sd["laser"]
    fmt = model.params.values.get("FORMATO_CHAPA")
    formats = [f for f in catalog.sheet_formats() if f["code"] == fmt] or catalog.sheet_formats()
    for (mat, t), parts in sorted(sgroups.items()):
        r = best_format(parts, formats, margin=las["sheet_margin_mm"], spacing=las["part_spacing_mm"],
                        kerf=las["kerf_mm"])
        r.update({"material": mat, "thickness": t,
                  "mass_per_sheet_kg": round(r.get("length", 0) * r.get("width", 0) * t * 1e-9 *
                                             catalog.material(mat).density, 2) if r.get("feasible") else None})
        nesting.append(r)
    # ------------------------------------------------------------- soldadura
    welds = [j for j in model.joints if j.kind == "soldadura"]
    weld_len = sum(j.weld["length"] for j in welds)
    wire = catalog.consumables()["HILO_G3Si1"]
    gas = catalog.consumables()["GAS_M21"]
    deposit_kg = sum(j.weld["a"] ** 2 * j.weld["length"] for j in welds) * 1e-6 * wire["deposit_density_kg_dm3"]
    wire_kg = deposit_kg / wire["efficiency"]
    arc_h = deposit_kg / gas["deposit_rate_kg_h"]
    gas_l = arc_h * 60 * gas["flow_l_min"]
    # ------------------------------------------------------------- pintura
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
    return {"cutting": cutting, "nesting": nesting,
            "welding": {"joints": len(welds), "total_length_mm": round(weld_len, 1), "deposit_kg": round(deposit_kg, 3),
                        "wire_kg": round(wire_kg, 3), "arc_time_h": round(arc_h, 3), "gas_l": round(gas_l, 1),
                        "wire": wire["name"], "gas": gas["name"]},
            "painting": {"area_m2": round(painted / 1e6, 3), "powder_kg": round(paint_kg, 3), "finish": fin},
            "routing": {p.ref: routing(p) for p in model.parts.values()}}


# ============================================================================ DFM
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
        add("ok", "MON-TORNILLERIA", tray.ref, f"{sc['name']} con {rnd['name'].split(',')[0]} (pared {dd['wall']:g} mm, "
            f"paquete {clamp:g} mm, rosca útil {sc['length'] - clamp:g} mm).")
    # soldadura
    leg_ids = model.structure.get("leg_ids", [])
    if leg_ids:
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
    add("advertencia", "SOL-ENRASE", "Bastidores", "Largueros y travesaños extremos enrasados con la cara exterior de "
        "las patas: en la cara enrasada el cordón es en ángulo exterior/borde y debe amolarse antes de pintar.")
    add("advertencia", "SOL-DEFORMACION", "Estructura soldada", "Riesgo de distorsión en bastidores de pared delgada: "
        "puntear en mesa plana con escuadras, soldar en secuencia simétrica alterna y verificar planitud de la "
        "superficie de apoyo de la encimera (EN ISO 13920 clase F).")
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
