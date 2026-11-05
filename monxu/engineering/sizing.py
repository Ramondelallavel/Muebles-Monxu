"""Propuesta constructiva: resolución de parámetros 'auto' mediante reglas y cálculo.

Genérico para cualquier familia que declare:
``candidates``, ``constructive_defaults``, ``leg_param``, ``frame_params``, ``param_for_role(role)``,
``vertical_load_present(values)``, ``plate_targets(values)`` y ``sheet_defaults_without_load(values)``.

* Sin cargas definidas: valores constructivos por defecto y verificación PENDIENTE.
* Con cargas: chapa y número de travesaños por cálculo de placa (mínima masa entre alternativas
  que verifican) y perfiles por cálculo de barras, incrementando la sección de los grupos que no
  cumplen hasta verificar todas las comprobaciones.
"""
from __future__ import annotations

from .. import catalog
from ..core.params import AUTO, ParameterSet
from .analysis import analyze
from .plate import navier

G_ACC = 9.81


def _plate_sizing(family, ps: ParameterSet, tgt: dict, notes: list, auto_t: bool, auto_n: bool) -> None:
    crit = catalog.criteria()
    gG, gQ = crit["partial_factors"]["gamma_G"], crit["partial_factors"]["gamma_Q"]
    dl = crit["deflection_limits"]["panel_span_ratio"]
    surface, t_param, n_param = tgt["surface"], tgt["t_param"], tgt["n_param"]
    mat = catalog.material(ps.values["MATERIAL_CHAPA"])
    load = ps.values[tgt["load_param"]]
    t_min = crit["min_sheet_thickness_by_use_mm"].get(ps.values.get("USO", "montaje"), 1.5) \
        if tgt.get("min_t_by_use") else 1.0
    t_opts = [t for t in catalog.sheet_thicknesses(mat.code) if t_min <= t <= 4.0] if auto_t else [ps.values[t_param]]
    min_bay = crit["min_support_spacing_mm"]
    code = f"DIM-{surface.upper()}"
    notes[:] = [n for n in notes if n.get("code") != code]
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
        prof = catalog.profile(trial.values[tgt["trv_param"]])
        cross_len = yb - yf - prof.B
        rho_s = catalog.material(trial.values["MATERIAL_ESTRUCTURAL"]).density
        for n in (range(0, 25) if auto_n else [ps.values[n_param]]):
            a = span / (n + 1)
            if a < min_bay:
                break
            ru = navier(a, b, t, mat.E, mat.nu, q=gG * qg + gQ * q)
            rs = navier(a, b, t, mat.E, mat.nu, q=qg + q)
            if ru["sigma"] <= mat.fy / mat.gamma_M0 and rs["w"] <= min(a, b) / dl:
                sheet = surf["area_mm2"] * t * 1e-9 * mat.density
                cross = n * cross_len * 1e-3 * prof.mass_per_m(rho_s)
                alternatives.append({"t": t, "n": n, "vano": round(a, 1), "masa_kg": round(sheet + cross, 2),
                                     "sigma": round(ru["sigma"], 1), "w": round(rs["w"], 2)})
                break
    label = surf["label"].lower() if alternatives or t_opts else surface
    if not alternatives:
        notes.append({"level": "error", "code": code,
                      "message": f"No se encuentra combinación de espesor y travesaños que verifique la {label} con "
                                 f"{load:g} kg. Se requiere refuerzo específico o reducir la carga."})
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
    notes.append({"level": "propuesta", "code": code,
                  "message": f"Propuesta para la {label}: chapa de {best['t']:g} mm y {best['n']} travesaños "
                             f"intermedios (vano {best['vano']:.0f} mm), mínima masa entre las alternativas que "
                             f"verifican (espesor mínimo {t_min:g} mm, separación mínima de apoyos {min_bay} mm): "
                             f"{alt_txt}.", "alternatives": alternatives})


def resolve_auto(family, params: ParameterSet, autos: list[str]):
    cands, defaults = family.candidates, family.constructive_defaults
    ps = params.copy()
    notes: list[dict] = []
    v = ps.values
    have_load = family.vertical_load_present(v)
    prof_autos = [k for k in autos if k in cands]
    for k in prof_autos:
        v[k] = cands[k][0] if have_load else defaults[k]
        ps.sources[k] = "regla_diseno"
    if have_load and "PERFIL_LARGUERO" in prof_autos and "PERFIL_LARGUERO" in defaults:
        v["PERFIL_LARGUERO"] = defaults["PERFIL_LARGUERO"]       # punto de partida razonable para vanos largos
    for k, val in family.sheet_defaults_without_load(v).items():
        if v.get(k) == AUTO:
            v[k] = val
            ps.sources[k] = "regla_diseno"
    if not have_load and (prof_autos or any(k in autos for k in defaults)):
        notes.append({"level": "propuesta", "code": "DIM-SIN-CARGA",
                      "message": "Sin carga de trabajo definida: perfiles, espesores y separación de apoyos según "
                                 "reglas constructivas por defecto. La resistencia queda PENDIENTE de verificación."})
    targets = family.plate_targets(v)
    sized = {t["t_param"] for t in targets}
    for k in list(v):     # espesores 'auto' que no se dimensionan por placa: valor constructivo
        if v[k] == AUTO and k in defaults and k not in cands and k not in sized:
            v[k] = defaults[k]
            ps.sources[k] = "regla_diseno"

    def plates():
        for tgt in targets:        # valores provisionales para construir los modelos de prueba
            if ps.values[tgt["t_param"]] == AUTO:
                ps.values[tgt["t_param"]] = defaults.get(tgt["t_param"], 2.0)
        for tgt in targets:
            at, an = tgt["t_param"] in autos, tgt["n_param"] in autos
            if at or an:
                _plate_sizing(family, ps, tgt, notes, at, an)

    plates()
    if prof_autos and have_load:
        idx = {k: cands[k].index(v[k]) if v[k] in cands[k] else 0 for k in prof_autos}
        for k in prof_autos:
            ps.values[k] = cands[k][idx[k]]
        iterations = 0
        for iterations in range(1, 41):
            m = family.construct(ps)
            rep = analyze(m, include_stability=False, include_welds=True)
            failing: set[str] = set()
            for c in rep["checks"]:
                if c["status"] != "NO_CUMPLE":
                    continue
                role = m.structure["member_roles"].get(c["element"])
                if role is None and c["category"] == "soldadura":
                    j = next((j for j in m.joints if j.id == c["element"]), None)
                    role = m.instance(j.weld["fem"]["member"]).part.role if j else None
                prm = family.param_for_role(role) if role else None
                if prm in prof_autos:
                    failing.add(prm)
            if not failing:
                break
            bumped = False
            for k in failing:
                if idx[k] + 1 < len(cands[k]):
                    idx[k] += 1
                    ps.values[k] = cands[k][idx[k]]
                    bumped = True
            lp = family.leg_param
            if lp in prof_autos:
                for k in family.frame_params:
                    while k in ps.values and catalog.profile(ps.values[k]).B > catalog.profile(ps.values[lp]).B \
                            and idx[lp] + 1 < len(cands[lp]):
                        idx[lp] += 1
                        ps.values[lp] = cands[lp][idx[lp]]
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
                                 ", ".join(f"{k} = {ps.values[k]}" for k in prof_autos), "iterations": iterations})
        plates()      # re-verifica el reparto de travesaños con los perfiles finales
    for k in list(ps.values):
        if ps.values[k] == AUTO and k in defaults:
            ps.values[k] = defaults[k]
    return ps, notes
