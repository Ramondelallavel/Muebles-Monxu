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
from .analysis import analyze, surface_sheet
from .plate import navier

G_ACC = 9.81


def _plate_sizing(family, ps: ParameterSet, tgt: dict, notes: list, auto_t: bool, auto_n: bool) -> None:
    crit = catalog.criteria()
    gG, gQ = crit["partial_factors"]["gamma_G"], crit["partial_factors"]["gamma_Q"]
    dl = crit["deflection_limits"]["panel_span_ratio"]
    surface, t_param, n_param = tgt["surface"], tgt["t_param"], tgt["n_param"]
    mat = catalog.material(ps.values[tgt.get("mat_param", "MATERIAL_CHAPA")])
    load = ps.values[tgt["load_param"]]
    t_min = crit["min_sheet_thickness_by_use_mm"].get(ps.values.get("USO", "montaje"), 1.5) \
        if tgt.get("min_t_by_use") else 1.0
    t_max = 6.0                     # chapa de encimera/bandeja razonable para plegar y manipular
    t_opts = [t for t in (tgt.get("t_options") or catalog.sheet_thicknesses(mat.code)) if t_min <= t <= tgt.get("t_max", t_max)] \
        if auto_t else [ps.values[t_param]]
    min_bay = crit["min_support_spacing_mm"]
    code = f"DIM-{surface.upper()}"
    notes[:] = [n for n in notes if n.get("code") != code]
    alternatives = []
    for t in t_opts:
        trial = ps.copy()
        trial.values[t_param] = t
        trial.values[n_param] = 0 if auto_n else ps.values[n_param]
        m = family.construct(trial)
        if any(n["code"].startswith("DFM-FIJ") and n["level"] == "error" for n in m.design_notes):
            continue          # con este espesor no hay zona válida para las fijaciones: no es fabricable
        surf = next(s for s in m.structure["surfaces"] if s["id"] == surface)
        lvl = m.structure["levels"][surf["level"]]
        gx, (yf, yb) = lvl["grid_x"], lvl["grid_y"]
        span, b = gx[-1] - gx[0], yb - yf
        q = load * G_ACC / surf["area_mm2"]
        # peso propio igual que en la verificación: chapa real (con pestañas y escotaduras) repartida en la superficie
        qg = surface_sheet(m.instance(surf["sheet_instance"]).part)[0] * G_ACC / surf["area_mm2"]
        eta = surf.get("ligament_efficiency", 1.0)
        P_kg = ps.values.get("CARGA_PUNTUAL") if surface == "encimera" else None
        fyd = mat.fy / mat.gamma_M0
        prof = catalog.profile(trial.values[tgt["trv_param"]])
        cross_len = yb - yf - prof.B
        rho_s = catalog.material(trial.values["MATERIAL_ESTRUCTURAL"]).density
        for n in (range(0, 25) if auto_n else [ps.values[n_param]]):
            a = span / (n + 1)
            if a < min_bay:
                break
            ru = navier(a, b, t, mat.E, mat.nu, q=gG * qg + gQ * q)
            rs = navier(a, b, t, mat.E, mat.nu, q=qg + q)
            ru, rs = {"sigma": ru["sigma"] / eta}, {"w": rs["w"] / eta}
            ok_p = True
            if P_kg:          # carga puntual sobre la encimera: misma comprobación que la verificación final
                size = crit["point_load_patch_mm"]
                rp = navier(a, b, t, mat.E, mat.nu, q=gG * qg, patch=(gQ * P_kg * G_ACC, size, size, a / 2, b / 2),
                            terms=121)
                ok_p = rp["sigma"] / eta <= fyd
            if ru["sigma"] <= fyd and rs["w"] <= min(a, b) / dl and ok_p:
                sheet = surf["area_mm2"] * t * 1e-9 * mat.density
                cross = n * cross_len * 1e-3 * prof.mass_per_m(rho_s)
                alternatives.append({"t": t, "n": n, "vano": round(a, 1), "masa_kg": round(sheet + cross, 2),
                                     "sigma": round(ru["sigma"], 1), "w": round(rs["w"], 2)})
                break
    label = {"encimera": "la encimera", "balda": "la balda inferior", "estante": "el estante superior"}.get(
        surface, f"la bandeja ({surface})")
    if not alternatives:
        fixed = [p for p, a in ((t_param, auto_t), (n_param, auto_n)) if not a]
        notes.append({"level": "error", "code": code,
                      "message": f"No se encuentra combinación de espesor y travesaños que verifique {label} con "
                                 f"{load:g} kg" + (f" manteniendo fijo {', '.join(fixed)}" if fixed else "") +
                                 f" (espesores disponibles en {mat.code}: {', '.join(f'{t:g}' for t in t_opts) or '—'} mm; "
                                 f"separación mínima de apoyos {min_bay} mm). Ponga esos parámetros en 'auto', reduzca la "
                                 "carga" + ("" if mat.fy_guaranteed and max(t_opts or [0]) >= t_max else
                                           ", use un material de chapa con más espesores o límite elástico garantizado "
                                           "(p. ej. S235JR)") + " o prevea refuerzos específicos."})
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
                  "message": f"Propuesta para {label}: chapa de {best['t']:g} mm y {best['n']} travesaños "
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
                      "message": "Sin carga vertical de trabajo definida: espesores y separación de apoyos según "
                                 "reglas constructivas; los perfiles sólo se comprueban frente al empuje horizontal. "
                                 "La resistencia a cargas verticales queda PENDIENTE de verificación."})
    sp = getattr(family, "support_param", "PIE_NIVELADOR")
    foot_auto = v.get(sp) == AUTO
    if foot_auto:
        v[sp] = defaults.get(sp, "PIE_NIV_M12_D60")
        ps.sources[sp] = "regla_diseno"
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
    def size_profiles():
        idx = {k: cands[k].index(v[k]) if v[k] in cands[k] else 0 for k in prof_autos}
        for k in prof_autos:
            ps.values[k] = cands[k][idx[k]]
        if _fit_leg(family, ps, prof_autos):
            idx[family.leg_param] = cands[family.leg_param].index(ps.values[family.leg_param])
        iterations = 0
        for iterations in range(1, 41):
            m = family.construct(ps)
            rep = analyze(m, include_stability=False, include_welds=True)
            failing: set[str] = set()
            for c in rep["checks"]:
                if c["status"] != "NO_CUMPLE":
                    continue
                if c["id"].startswith("S."):          # desplome del conjunto: rigidez lateral de patas/montantes
                    if family.leg_param in prof_autos:
                        failing.add(family.leg_param)
                    continue
                role = m.structure["member_roles"].get(c["element"])
                if role is None and c["category"] == "soldadura":
                    j = next((j for j in m.joints if j.id == c["element"]), None)
                    role = m.instance(j.weld["fem"]["member"]).role if j else None
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
                _fit_leg(family, ps, prof_autos)
                idx[lp] = cands[lp].index(ps.values[lp])
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
        _fit_leg(family, ps, prof_autos)

    run_profiles = bool(prof_autos and (have_load or v.get("CARGA_HORIZONTAL")))   # el empuje también dimensiona patas
    if run_profiles:
        size_profiles()
    for k in list(ps.values):
        if ps.values[k] == AUTO and k in defaults:
            ps.values[k] = defaults[k]
    _fit_leg(family, ps, prof_autos)
    if foot_auto and have_load:
        for _ in range(3):                   # el pie cambia la longitud de pata: iterar hasta converger
            before = ps.values[sp]
            _select_feet(family, ps, notes)
            if ps.values[sp] == before or not run_profiles:
                break
            notes[:] = [n for n in notes if n.get("code") not in ("DIM-PERFILES", "DIM-PIES")]
            size_profiles()
    return ps, notes


def _fit_leg(family, ps: ParameterSet, prof_autos) -> bool:
    """Regla constructiva propia de la familia sobre la pata/montante (``leg_fits``): aumenta el perfil 'auto' de la
    serie hasta cumplirla. Devuelve True si lo ha cambiado."""
    fits, lp = getattr(family, "leg_fits", None), family.leg_param
    if fits is None or lp not in prof_autos or ps.values.get(lp) not in family.candidates[lp]:
        return False
    series, changed = family.candidates[lp], False
    while not fits(ps.values) and series.index(ps.values[lp]) + 1 < len(series):
        ps.values[lp] = series[series.index(ps.values[lp]) + 1]
        changed = True
    return changed


def _select_feet(family, ps: ParameterSet, notes: list) -> None:
    """Pie nivelador de menor capacidad nominal que soporta la reacción vertical de servicio (ELS-1)."""
    m = family.construct(ps)
    rep = analyze(m, include_stability=False, include_welds=False)
    rz = [r["Rz_N"] for r in rep["reactions"] if r["combination"] == "ELS-1"]
    if not rz:
        return
    need = max(rz) / G_ACC
    sp = getattr(family, "support_param", "PIE_NIVELADOR")
    cat = getattr(family, "support_category", "patas")
    word = "Rueda" if cat.startswith("ruedas") else "Pie nivelador"
    feet = sorted((c for c in catalog.components().items() if c[1]["category"] == cat and not c[1].get("brake")),
                  key=lambda kv: kv[1]["rated_load_kg"])
    leg = catalog.profile(ps.values[family.leg_param])
    for code, c in feet:
        nut = catalog.component(f"TUERCA_SOLDAR_{c['thread']}")
        fits = nut["s"] / 0.8660254 <= leg.B - 2 * leg.t - 1
        if c["rated_load_kg"] >= need and fits:
            ps.values[sp] = code
            ps.sources[sp] = "calculo"
            notes.append({"level": "propuesta", "code": "DIM-PIES",
                          "message": f"{word} seleccionad{'a' if word == 'Rueda' else 'o'} por cálculo: {c['name']} (capacidad nominal de catálogo "
                                     f"{c['rated_load_kg']} kg ≥ reacción de servicio {need:.0f} kg por apoyo). Capacidad "
                                     "a confirmar con la ficha del proveedor."})
            return
    notes.append({"level": "advertencia", "code": "DIM-PIES",
                  "message": f"Ningún {word.lower()} del catálogo admite {need:.0f} kg por apoyo con la pata/montante "
                             f"{leg.code}: se mantiene {ps.values[sp]} y la comprobación no se cumplirá."})
