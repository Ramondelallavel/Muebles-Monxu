"""Corrección automática de un diseño que NO CUMPLE por valores fijados (usuario, plantilla o asistente).

El dimensionado sólo cambia lo que está en 'auto'; si una comprobación falla es porque un valor fijado lo impide (un
perfil, un espesor, el material de la chapa, «sin anclaje», el taco...). Aquí se propone la corrección mínima —devolver
esos valores a 'auto', anclar al suelo o, en un carro, limitar la fuerza de maniobra a la admisible— y se comprueba
regenerando y verificando el diseño corregido: sólo se ofrece si con ella el diseño CUMPLE.
"""
from __future__ import annotations

import math
from typing import Any

from ..core.params import AUTO, ParamError

#: chapa estructural a la que se pasa una chapa que no verifica con su material (fy garantizado, espesores hasta 6 mm)
STRUCTURAL_SHEET = "S235JR"
MEMBER_CATEGORIES = ("resistencia", "pandeo", "deformacion", "soldadura", "desplome")


def _fixed(values: dict[str, Any], k: str) -> bool:
    return k in values and values[k] not in (None, AUTO)


def _candidates(fam, values: dict[str, Any], eng: dict) -> list[tuple[dict[str, Any], list[str]]]:
    """Correcciones a probar, de la más leve a la más amplia: [(parámetros, motivos)]."""
    specs = {s.name: s for s in fam.param_specs()}
    fails = [c for c in eng["checks"] if c["status"] == "NO_CUMPLE"]
    fix: dict[str, Any] = {}
    why: list[str] = []

    def to_auto(keys, reason):
        ks = [k for k in keys if k in specs and specs[k].allow_auto and _fixed(values, k) and k not in fix]
        for k in ks:
            fix[k] = AUTO
        if ks:
            why.append(reason + ": " + ", ".join(specs[k].label for k in ks) + " → auto")

    profiles = [k for k in specs if k.startswith("PERFIL_")]
    for c in fails:
        cid = c["id"]
        if cid == "E.VUELCO":
            anc = specs.get("ANCLAJE")
            if anc is not None and "al_suelo" in (anc.choices or []):
                if values.get("ANCLAJE") != "al_suelo":
                    fix["ANCLAJE"] = "al_suelo"
                    if "TACO_ANCLAJE" in specs:
                        fix["TACO_ANCLAJE"] = AUTO
                    why.append("Vuelco sin anclar: anclaje al suelo con el taco dimensionado por cálculo")
            else:          # carro: no se ancla; la maniobra admisible del carro vacío
                adm = (c.get("details") or {}).get("empuje_admisible_N")
                if adm is not None and adm >= 5:
                    v = float(math.floor(adm / 5) * 5)
                    fix["CARGA_HORIZONTAL"] = v
                    why.append(f"Vuelco del carro vacío: fuerza de maniobra limitada a {v:g} N (la admisible); "
                               "indíquelo en las instrucciones de uso")
        elif cid == "E.ANCLAJE":
            to_auto(["TACO_ANCLAJE"], "Taco de anclaje insuficiente")
        elif cid.startswith("PL."):
            for t in fam.plate_targets({**{k: s.default for k, s in specs.items()}, **values}) or []:
                to_auto([t["t_param"], t.get("n_param")], "Chapa que no verifica")
        elif cid == "A.PIES":
            to_auto([fam.support_param], "Apoyos con capacidad insuficiente")
        elif c["category"] in MEMBER_CATEGORIES or cid.startswith(("B.", "D.", "S.", "W.")):
            to_auto(profiles, "Perfiles fijados que no verifican")
    out = [(dict(fix), list(why))] if fix else []
    # segundo intento: si falla una chapa con un material sin límite elástico garantizado, chapa estructural S235JR
    if any(c["id"].startswith("PL.") for c in fails):
        for mp in ("MATERIAL_CHAPA", "MATERIAL_PLACA"):
            sp = specs.get(mp)
            if sp and _fixed(values, mp) and values[mp] != STRUCTURAL_SHEET and STRUCTURAL_SHEET in (sp.choices or []):
                fix2 = dict(fix)
                fix2[mp] = STRUCTURAL_SHEET
                for t in fam.plate_targets({**{k: s.default for k, s in specs.items()}, **values}) or []:
                    for k in (t["t_param"], t.get("n_param")):
                        if k in specs and specs[k].allow_auto:
                            fix2[k] = AUTO
                out.append((fix2, why + [f"{sp.label}: {STRUCTURAL_SHEET} (límite elástico garantizado) con espesor "
                                         "por cálculo"]))
    return out


def _verify(fam, values: dict[str, Any], sources: dict[str, str] | None, fix: dict[str, Any]) -> dict | None:
    from .analysis import analyze
    ps = fam.new_params()
    by_src: dict[str, dict] = {}
    for k, v in {**values, **fix}.items():
        by_src.setdefault("correccion" if k in fix else (sources or {}).get(k, "usuario"), {})[k] = v
    try:
        for src, vals in by_src.items():
            ps.update(vals, src)
        return analyze(fam.build(ps))
    except (ParamError, ValueError):
        return None


def propose_fix(family_id: str, values: dict[str, Any], sources: dict[str, str] | None, eng: dict) -> dict | None:
    """Primera corrección que hace CUMPLIR el diseño (comprobada regenerando y verificando), o None."""
    from ..families import family
    if eng.get("status") != "NO_CUMPLE":
        return None
    fam = family(family_id)
    for fix, why in _candidates(fam, values, eng):
        r = _verify(fam, values, sources, fix)
        # carro: con menos fuerza el dimensionado aligera el carro y su peso estabiliza menos; se itera la admisible
        for _ in range(5):
            if r is None or r["status"] == "CUMPLE" or "CARGA_HORIZONTAL" not in fix:
                break
            vu = next((c for c in r["checks"] if c["id"] == "E.VUELCO" and c["status"] == "NO_CUMPLE"), None)
            adm = (vu or {}).get("details", {}).get("empuje_admisible_N")
            if adm is None or adm < 5 or math.floor(adm / 5) * 5 >= fix["CARGA_HORIZONTAL"]:
                break
            fix = {**fix, "CARGA_HORIZONTAL": float(math.floor(adm / 5) * 5)}
            why = [w for w in why if not w.startswith("Vuelco del carro")] + [
                f"Vuelco del carro vacío: fuerza de maniobra limitada a {fix['CARGA_HORIZONTAL']:g} N (la admisible); "
                "indíquelo en las instrucciones de uso"]
            r = _verify(fam, values, sources, fix)
        if r is not None and r["status"] == "CUMPLE":
            return {"params": fix, "reasons": why, "status": r["status"],
                    "governing": (r.get("governing") or {}).get("description")}
    return None
