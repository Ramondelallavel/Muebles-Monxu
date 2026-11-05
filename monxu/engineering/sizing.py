"""Propuesta constructiva: resolución de parámetros 'auto' mediante reglas y cálculo.

* Sin cargas definidas: se aplican valores constructivos por defecto y la verificación queda
  PENDIENTE (nunca se presenta como verificada).
* Con cargas: se dimensiona chapa y número de travesaños por el cálculo de placa (mínima masa)
  y los perfiles por el cálculo de barras, incrementando la sección de los grupos que no
  cumplen hasta verificar todas las comprobaciones.
"""
from __future__ import annotations

import math

from .. import catalog
from ..core.params import AUTO, ParameterSet
from .analysis import analyze
from .plate import navier

ROLE_PARAM = {"pata": "PERFIL_PATA", "larguero_sup": "PERFIL_LARGUERO", "travesano_ext_sup": "PERFIL_TRAVESANO",
              "travesano_int_sup": "PERFIL_TRAVESANO", "larguero_inf": "PERFIL_BASTIDOR",
              "travesano_ext_inf": "PERFIL_BASTIDOR", "travesano_int_inf": "PERFIL_BASTIDOR"}
G_ACC = 9.81


def _concrete(family, ps: ParameterSet, defaults: dict) -> ParameterSet:
    c = ps.copy()
    for k, v in defaults.items():
        if c.values.get(k) == AUTO:
            c.values[k] = v
    return c


def _plate_sizing(family, ps: ParameterSet, surface: str, t_param: str, n_param: str, load_param: str,
                  notes: list, auto_t: bool, auto_n: bool) -> None:
    crit = catalog.criteria()
    gG, gQ = crit["partial_factors"]["gamma_G"], crit["partial_factors"]["gamma_Q"]
    dl = crit["deflection_limits"]["panel_span_ratio"]
    mat = catalog.material(ps.values["MATERIAL_CHAPA"])
    load = ps.values[load_param]
    t_min = crit["min_sheet_thickness_by_use_mm"].get(ps.values.get("USO", "montaje"), 1.5) if surface == "encimera" else 1.0
    t_opts = [t for t in catalog.sheet_thicknesses(mat.code) if t_min <= t <= 4.0] if auto_t else [ps.values[t_param]]
    min_bay = crit["min_support_spacing_mm"]
    notes[:] = [n for n in notes if n.get("code") != f"DIM-{surface.upper()}"]
    trv_param = "PERFIL_TRAVESANO" if surface == "encimera" else "PERFIL_BASTIDOR"
    alternatives = []
    for t in t_opts:
        trial = ps.copy()
        trial.values[t_param] = t
        trial.values[n_param] = 0 if auto_n else ps.values[n_param]
        m = family.construct(trial)
        surf = next(s for s in m.structure["surfaces"] if s["id"] == surface)
        lvl = m.structure["levels"][surf["level"]]
        gx, (yf, yb) = lvl["grid_x"], lvl["grid_y"]
        span, b = gx[-1] - gx[0], yb - yf
        q = load * G_ACC / surf["area_mm2"]
        qg = mat.density * t * 1e-9 * G_ACC
        prof = catalog.profile(trial.values[trv_param])
        cross_len = yb - yf - prof.B
        n_range = range(0, 25) if auto_n else [ps.values[n_param]]
        for n in n_range:
            a = span / (n + 1)
            if a < min_bay:
                break
            ru = navier(a, b, t, mat.E, mat.nu, q=gG * qg + gQ * q)
            rs = navier(a, b, t, mat.E, mat.nu, q=qg + q)
            if ru["sigma"] <= mat.fy / mat.gamma_M0 and rs["w"] <= min(a, b) / dl:
                sheet = surf["area_mm2"] * t * 1e-9 * mat.density
                cross = n * cross_len * 1e-3 * prof.mass_per_m(catalog.material(trial.values["MATERIAL_ESTRUCTURAL"]).density)
                alternatives.append({"t": t, "n": n, "vano": round(a, 1), "masa_kg": round(sheet + cross, 2),
                                     "sigma": round(ru["sigma"], 1), "w": round(rs["w"], 2)})
                break
    if not alternatives:
        notes.append({"level": "error", "code": f"DIM-{surface.upper()}",
                      "message": f"No se encuentra combinación de espesor y travesaños que verifique la {surface} "
                                 f"con {load:g} kg. Se requiere refuerzo específico o reducir la carga."})
        if auto_t:
            ps.values[t_param] = max(t_opts)
            ps.sources[t_param] = "calculo"
        return
    best = min(alternatives, key=lambda a: a["masa_kg"])
    if auto_t:
        ps.values[t_param] = best["t"]
        ps.sources[t_param] = "calculo"
    if auto_n:
        ps.values[n_param] = best["n"]
        ps.sources[n_param] = "calculo"
    alt_txt = "; ".join(f"t={a['t']:g} mm con {a['n']} travesaños (vano {a['vano']:.0f} mm, {a['masa_kg']} kg)"
                        for a in sorted(alternatives, key=lambda a: a["masa_kg"])[:4])
    notes.append({"level": "propuesta", "code": f"DIM-{surface.upper()}",
                  "message": f"Propuesta para la {surface}: chapa de {best['t']:g} mm y {best['n']} travesaños "
                             f"intermedios (vano {best['vano']:.0f} mm), mínima masa entre las alternativas que "
                             f"verifican (espesor mínimo {t_min:g} mm por uso, separación mínima de apoyos "
                             f"{min_bay} mm): {alt_txt}.", "alternatives": alternatives})


def resolve_auto(family, params: ParameterSet, autos: list[str]):
    from ..families.mesa_industrial import CANDIDATES, CONSTRUCTIVE_DEFAULTS
    ps = params.copy()
    notes: list[dict] = []
    v = ps.values
    have_top = bool(v.get("CARGA_TOTAL"))
    have_shelf = bool(v.get("CARGA_BALDA")) and v.get("NUMERO_BALDAS", 0) >= 1
    prof_autos = [k for k in autos if k in CANDIDATES]
    # 1) valores constructivos iniciales
    start = {k: (CANDIDATES[k][0] if have_top else CONSTRUCTIVE_DEFAULTS[k]) for k in prof_autos}
    if "PERFIL_LARGUERO" in prof_autos and have_top:
        start["PERFIL_LARGUERO"] = "RHS 60x40x2"
    for k, val in start.items():
        v[k] = val
        ps.sources[k] = "regla_diseno"
    for k in ("ESPESOR_CHAPA", "ESPESOR_BALDA"):
        if v.get(k) == AUTO and not (have_top if k == "ESPESOR_CHAPA" else have_shelf):
            v[k] = CONSTRUCTIVE_DEFAULTS[k]
            ps.sources[k] = "regla_diseno"
    if not have_top and (prof_autos or "ESPESOR_CHAPA" in autos):
        notes.append({"level": "propuesta", "code": "DIM-SIN-CARGA",
                      "message": "Sin carga de trabajo definida: perfiles, espesores y separación de apoyos según "
                                 "reglas constructivas por defecto. La resistencia queda PENDIENTE de verificación."})

    def plates():
        if have_top and ("ESPESOR_CHAPA" in autos or "NUMERO_TRAVESANOS" in autos):
            _plate_sizing(family, ps, "encimera", "ESPESOR_CHAPA", "NUMERO_TRAVESANOS", "CARGA_TOTAL", notes,
                          "ESPESOR_CHAPA" in autos, "NUMERO_TRAVESANOS" in autos)
        if have_shelf and ("ESPESOR_BALDA" in autos or "NUMERO_TRAVESANOS_BALDA" in autos):
            _plate_sizing(family, ps, "balda", "ESPESOR_BALDA", "NUMERO_TRAVESANOS_BALDA", "CARGA_BALDA", notes,
                          "ESPESOR_BALDA" in autos, "NUMERO_TRAVESANOS_BALDA" in autos)

    work = ps.copy()
    for k in ("ESPESOR_CHAPA", "ESPESOR_BALDA"):
        if work.values[k] == AUTO:
            work.values[k] = CONSTRUCTIVE_DEFAULTS[k]
    plates_ps = work
    _orig = ps
    ps = plates_ps
    plates()
    # 2) perfiles por cálculo de barras
    if prof_autos and have_top:
        idx = {k: CANDIDATES[k].index(v[k]) if v[k] in CANDIDATES[k] else 0 for k in prof_autos}
        for k in prof_autos:
            ps.values[k] = CANDIDATES[k][idx[k]]
        history = []
        for it in range(40):
            m = family.construct(ps)
            rep = analyze(m, include_stability=False, include_welds=True)
            failing: set[str] = set()
            for c in rep["checks"]:
                if c["status"] == "NO_CUMPLE":
                    role = None
                    if c["element"] in m.structure["member_roles"]:
                        role = m.structure["member_roles"][c["element"]]
                    elif c["category"] == "soldadura":
                        j = next((j for j in m.joints if j.id == c["element"]), None)
                        if j:
                            role = m.instance(j.weld["fem"]["member"]).part.role
                    if role and ROLE_PARAM.get(role) in prof_autos:
                        failing.add(ROLE_PARAM[role])
            history.append({k: ps.values[k] for k in prof_autos})
            if not failing:
                break
            bumped = False
            for k in failing:
                if idx[k] + 1 < len(CANDIDATES[k]):
                    idx[k] += 1
                    ps.values[k] = CANDIDATES[k][idx[k]]
                    bumped = True
            # mantener anchos de bastidor <= pata
            leg = catalog.profile(ps.values["PERFIL_PATA"])
            for k in ("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "PERFIL_BASTIDOR"):
                if catalog.profile(ps.values[k]).B > leg.B and "PERFIL_PATA" in prof_autos:
                    while catalog.profile(ps.values[k]).B > catalog.profile(ps.values["PERFIL_PATA"]).B and \
                            idx["PERFIL_PATA"] + 1 < len(CANDIDATES["PERFIL_PATA"]):
                        idx["PERFIL_PATA"] += 1
                        ps.values["PERFIL_PATA"] = CANDIDATES["PERFIL_PATA"][idx["PERFIL_PATA"]]
            if not bumped:
                notes.append({"level": "error", "code": "DIM-PERFILES",
                              "message": "Se han agotado los perfiles candidatos sin verificar todas las "
                                         "comprobaciones: " + ", ".join(sorted(failing))})
                break
        for k in prof_autos:
            ps.sources[k] = "calculo"
        notes.append({"level": "propuesta", "code": "DIM-PERFILES",
                      "message": "Perfiles dimensionados por cálculo preliminar (sección mínima de la serie que "
                                 "verifica resistencia, pandeo, flechas y soldaduras): " +
                                 ", ".join(f"{k} = {ps.values[k]}" for k in prof_autos), "iterations": len(history)})
        plates()   # re-verifica el reparto de travesaños con los perfiles finales
    # 'auto' restantes de reglas constructivas (radio, K, holgura, nº travesaños sin carga) se resuelven en construct
    for k in ("ESPESOR_CHAPA", "ESPESOR_BALDA"):
        if ps.values[k] == AUTO:
            ps.values[k] = CONSTRUCTIVE_DEFAULTS[k]
    for k in prof_autos:
        if ps.values[k] == AUTO:
            ps.values[k] = CONSTRUCTIVE_DEFAULTS[k]
    del _orig
    return ps, notes
