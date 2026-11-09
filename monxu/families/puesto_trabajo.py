"""Familia A: puesto de trabajo industrial.

Mesa industrial (encimera, balda inferior opcional, pies niveladores) cuyas patas traseras se prolongan como
montantes hasta la altura de la superestructura, unidos arriba por un travesaño soldado. Opcionalmente:

* Estante superior en voladizo: bandeja de chapa plegada sobre un bastidor soldado a los montantes
  (larguero trasero entre montantes, brazos en voladizo y larguero delantero), con escotaduras traseras
  alrededor de los montantes y fijación atornillada con tuercas remachables, como el resto de chapas.
* Panel portaherramientas: chapa perforada (agujero cuadrado 10x10 a paso 38) con pestañas superior e inferior
  de rigidez, atornillada a la cara delantera de los montantes con tuercas remachables.

La encimera lleva escotaduras en las dos esquinas traseras para dejar pasar los montantes.
Sistema de coordenadas como la mesa: X = longitud, Y = fondo (Y=0 frente de trabajo), Z = altura.
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..cad.sheetmetal import EDGES, FlangeSpec, SheetMetalSpec, analytic_volume, bend_deduction, perforation_grid
from ..core.model import Joint, ProfilePart, SheetPart, StandardPart
from ..core.params import ParamError, AUTO, ParamSpec
from .base import register
from .mesa_industrial import (ALLP, CANDIDATES as MESA_CANDIDATES, CONSTRUCTIVE_DEFAULTS as MESA_DEFAULTS, MesaIndustrial,
                              even_positions, flange_hole_d, frame_z, r10)

CANDIDATES = {**MESA_CANDIDATES,
              "PERFIL_ALTILLO": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2", "RHS 80x40x2", "RHS 80x40x3"]}
CONSTRUCTIVE_DEFAULTS = {**MESA_DEFAULTS, "PERFIL_ALTILLO": "RHS 40x20x2", "ESPESOR_ESTANTE": 1.5}

PANEL_HOLE, PANEL_PITCH = 10.0, 38.0      # perforación cuadrada 10x10 a paso 38 (sistema de ganchos habitual)


@register
class PuestoTrabajo(MesaIndustrial):
    id = "puesto_trabajo"
    name = "Puesto de trabajo industrial"
    prefix = "PT"
    category = "A"
    description = ("Mesa de trabajo con montantes traseros prolongados y travesaño superior; estante superior en "
                   "voladizo y panel perforado portaherramientas opcionales. Calculada con las cargas de encimera, "
                   "balda y estante.")
    configurations = ["Puesto de montaje", "Puesto con estante superior", "Puesto con panel portaherramientas",
                      "Puesto de embalaje"]
    verification_inputs = ["CARGA_TOTAL"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    frame_params = ("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "PERFIL_BASTIDOR", "PERFIL_REPOSAPIES", "PERFIL_ALTILLO")
    auto_in_construct = MesaIndustrial.auto_in_construct + ("NUMERO_TRAVESANOS_ESTANTE",)

    def param_for_role(self, role):
        if role in ("montante",):
            return "PERFIL_PATA"
        if role in ("travesano_alto", "larguero_est", "brazo_est", "travesano_int_est"):
            return "PERFIL_ALTILLO"
        return super().param_for_role(role)

    def vertical_load_present(self, v):
        return super().vertical_load_present(v) or bool(v.get("CARGA_ESTANTE") and v.get("ESTANTE_SUPERIOR"))

    #: carga de uso por defecto del estante superior (cajas de piezas y pequeño material), kg/m²
    shelf_top_load_kg_m2 = 100

    def default_loads(self, v):
        out = super().default_loads(v)
        if v.get("ESTANTE_SUPERIOR"):
            q, L, D = self.shelf_top_load_kg_m2, v.get("LONGITUD") or 0, v.get("PROFUNDIDAD_ESTANTE") or 0
            out["CARGA_ESTANTE"] = (r10(q * (L * D * 1e-6)), f"{q:g} kg/m² sobre el estante de {L:g} × {D:g} mm")
        return out

    def plate_targets(self, v):
        out = super().plate_targets(v)
        if v.get("ESTANTE_SUPERIOR") and v.get("CARGA_ESTANTE"):
            out.append({"surface": "estante", "t_param": "ESPESOR_ESTANTE", "n_param": "NUMERO_TRAVESANOS_ESTANTE",
                        "load_param": "CARGA_ESTANTE", "trv_param": "PERFIL_ALTILLO", "min_t_by_use": False})
        return out

    def sheet_defaults_without_load(self, v):
        out = super().sheet_defaults_without_load(v)
        if not (v.get("ESTANTE_SUPERIOR") and v.get("CARGA_ESTANTE")):
            out["ESPESOR_ESTANTE"] = CONSTRUCTIVE_DEFAULTS["ESPESOR_ESTANTE"]
        return out

    # ------------------------------------------------------------------ parámetros
    def param_specs(self):
        P = ParamSpec
        specs = super().param_specs()
        extra = [
            P("ALTURA_TOTAL", "Altura de los montantes (superestructura)", "float", 1800.0, "mm", "dimensiones", 1300, 2400,
              help="Cota superior de los montantes traseros y del travesaño alto, desde el suelo."),
            P("ESPESOR_ESTANTE", "Espesor de chapa del estante superior", "float", AUTO, "mm", "materiales", 0.8, 4,
              allow_auto=True),
            P("ESPESOR_PANEL", "Espesor del panel perforado", "float", 1.5, "mm", "materiales", 1, 2.5),
            P("PERFIL_ALTILLO", "Perfil del travesaño alto y del bastidor del estante", "choice", AUTO, None,
              "construccion", choices=ALLP, allow_auto=True),
            P("NUMERO_TRAVESANOS_ESTANTE", "Travesaños intermedios bajo el estante superior", "int", AUTO, "ud",
              "construccion", 0, 12, allow_auto=True),
            P("ALA_ESTANTE", "Altura de pestaña del estante superior", "float", 25.0, "mm", "construccion", 15, 50),
            P("ESTANTE_SUPERIOR", "Estante superior en voladizo", "int", 1, "ud", "accesorios", 0, 1),
            P("ALTURA_ESTANTE", "Altura del estante superior (cara superior)", "float", 1450.0, "mm", "accesorios",
              1000, 2300),
            P("PROFUNDIDAD_ESTANTE", "Fondo del estante superior", "float", 300.0, "mm", "accesorios", 150, 450),
            P("PANEL_HERRAMIENTAS", "Panel perforado portaherramientas", "int", 1, "ud", "accesorios", 0, 1),
            P("CARGA_ESTANTE", "Carga distribuida sobre el estante superior", "float", None, "kg", "cargas", 0, 300,
              nullable=True),
        ]
        # orden: cada parámetro nuevo detrás del último de su grupo
        out = list(specs)
        for e in extra:
            idx = max(i for i, s in enumerate(out) if s.group == e.group) + 1
            out.insert(idx, e)
        return out

    def templates(self):
        return [
            {"id": "PT-1500-MONTAJE", "name": "Puesto de montaje 1.500 mm con estante y panel", "family": self.id,
             "values": {"LONGITUD": 1500.0, "ANCHURA": 750.0, "ALTURA": 900.0, "ALTURA_TOTAL": 1800.0,
                        "CARGA_TOTAL": 200.0, "NUMERO_BALDAS": 1, "CARGA_BALDA": 80.0, "CARGA_ESTANTE": 40.0,
                        "USO": "montaje", "ACABADO": "RAL7035_POLVO", "ANCLAJE": "al_suelo"}},
            {"id": "PT-1200-INSPECCION", "name": "Puesto de inspección 1.200 mm con panel portaherramientas y reposapiés",
             "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 700.0, "ALTURA": 850.0, "ALTURA_TOTAL": 1700.0,
                        "CARGA_TOTAL": 100.0, "NUMERO_BALDAS": 0, "ESTANTE_SUPERIOR": 0, "USO": "inspeccion",
                        "REPOSAPIES": 1, "ALTURA_REPOSAPIES": 220.0,
                        "CARGA_HORIZONTAL": 150.0, "ACABADO": "RAL5015_POLVO", "ANCLAJE": "al_suelo"}},
            {"id": "PT-1800-EMBALAJE", "name": "Puesto de embalaje 1.800 mm con estante superior y peto trasero",
             "family": self.id,
             "values": {"LONGITUD": 1800.0, "ANCHURA": 800.0, "ALTURA": 900.0, "ALTURA_TOTAL": 1900.0,
                        "CARGA_TOTAL": 250.0, "NUMERO_BALDAS": 1, "CARGA_BALDA": 120.0, "PANEL_HERRAMIENTAS": 0,
                        "PETO_TRASERO": 50.0,
                        "PROFUNDIDAD_ESTANTE": 350.0, "ALTURA_ESTANTE": 1500.0, "CARGA_ESTANTE": 60.0,
                        "USO": "embalaje", "ACABADO": "RAL7016_POLVO", "ANCLAJE": "al_suelo"}},
            {"id": "PT-2000-TALLER", "name": "Puesto de taller pesado 2.000 mm", "family": self.id,
             "values": {"LONGITUD": 2000.0, "ANCHURA": 800.0, "ALTURA": 900.0, "ALTURA_TOTAL": 2000.0,
                        "CARGA_TOTAL": 500.0, "CARGA_PUNTUAL": 100.0, "NUMERO_BALDAS": 1, "CARGA_BALDA": 150.0,
                        "CARGA_ESTANTE": 80.0, "ESPESOR_CHAPA": 3.0, "USO": "trabajo_pesado", "ANCLAJE": "al_suelo",
                        "ACABADO": "RAL5010_POLVO"}},
            {"id": "PT-1500-LAB-INOX", "name": "Puesto de laboratorio inoxidable 1.500 mm con estante y peto", "family": self.id,
             "values": {"LONGITUD": 1500.0, "ANCHURA": 750.0, "ALTURA": 900.0, "ALTURA_TOTAL": 1700.0,
                        "CARGA_TOTAL": 150.0, "CARGA_ESTANTE": 30.0, "PANEL_HERRAMIENTAS": 0, "PETO_TRASERO": 60.0,
                        "MATERIAL_ESTRUCTURAL": "1.4301", "MATERIAL_CHAPA": "1.4301", "ACABADO": "INOX_SATINADO",
                        "ENTORNO": "alimentario", "USO": "inspeccion", "CARGA_HORIZONTAL": 150.0,
                        "ANCLAJE": "al_suelo"}},
            {"id": "PT-1200-SENTADO", "name": "Puesto de montaje sentado 1.200 mm con reposapiés", "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 700.0, "ALTURA": 750.0, "ALTURA_TOTAL": 1600.0,
                        "CARGA_TOTAL": 100.0, "CARGA_ESTANTE": 20.0, "REPOSAPIES": 1, "ALTURA_REPOSAPIES": 200.0,
                        "NUMERO_BALDAS": 0, "CARGA_HORIZONTAL": 150.0, "ANCLAJE": "al_suelo",
                        "USO": "montaje_ligero"}},
        ]

    # ------------------------------------------------------------------ ganchos de la mesa
    def _leg_uses(self):
        return ("ALTURA_TOTAL", "PANEL_HERRAMIENTAS")

    def _leg_def(self, corner, d, leg):
        if corner in ("TI", "TD"):
            return "montante", "Montante trasero", d["z_top_alt"], d["leg_holes"]
        return "pata", "Pata", d["z_tf"], ()

    def _top_notch(self, ctx, d):
        n = d["c"] + d["a"] + ctx["HOLGURA_ESCOTADURA"]
        return (n, n), ("x0y1", "x1y1")

    def _derive(self, ctx, model):
        d = super()._derive(ctx, model)
        v = ctx.params.values
        with ctx.feature("F05", "Superestructura: montantes, estante y panel"):
            a, c, L, W, H = d["a"], d["c"], ctx["LONGITUD"], ctx["ANCHURA"], ctx["ALTURA"]
            alt = catalog.profile(ctx["PERFIL_ALTILLO"])
            zt = ctx.derive("COTA_SUPERIOR_MONTANTE", lambda p: p["ALTURA_TOTAL"], "mm", "Cota superior de montantes")
            ctx.derive("LONGITUD_MONTANTE", lambda p: p["ALTURA_TOTAL"] - p["COTA_INICIO_PATA"], "mm",
                       "Longitud de corte de montante trasero")
            d.update(alt=alt, z_top_alt=zt, leg_holes=())
            if zt < H + 300:
                model.note("error", "GEO-ALTURA-TOTAL", f"Altura de montantes {zt:g} mm insuficiente: debe superar la "
                           f"encimera ({H:g} mm) en al menos 300 mm.")
            if alt.B > a:
                model.note("error", "DFM-ALTILLO-ANCHO", f"El perfil {alt.code} es más ancho que el montante: no puede "
                           "enrasarse con él.")
            rn = catalog.component("TUERCA_REMACHABLE_M6")
            sc = catalog.component("TORNILLO_ISO7380_M6x12")
            head_h = float(rn["head_h"])
            # ---- estante superior
            d["shelf_top"] = bool(ctx["ESTANTE_SUPERIOR"])
            if d["shelf_top"]:
                fam = catalog.material(v["MATERIAL_CHAPA"]).family
                rmin = catalog.sheet_data()["press_brake"]["min_inner_radius_factor"].get(fam, 1.0)
                ts = ctx.derive("ESP_EST", lambda p: p["ESPESOR_ESTANTE"], "mm", "Espesor del estante superior")
                rs = ctx.derive("RADIO_EST", lambda p: round(max(p["ESP_EST"], rmin * p["ESP_EST"]), 2)
                                if p["RADIO_PLEGADO"] == AUTO else p["RADIO_PLEGADO"], "mm", "Radio de plegado (estante)")
                Ks = ctx.derive("K_EST", lambda p: round(catalog.din6935_k_factor(p["RADIO_EST"], p["ESP_EST"]), 4)
                                if p["FACTOR_K"] == AUTO else p["FACTOR_K"], None, "Factor K (estante)")
                ctx.derive("DEDUCCION_PLEGADO_EST", lambda p: round(bend_deduction(p["ESP_EST"], p["RADIO_EST"],
                                                                                   p["K_EST"]), 4), "mm",
                           "Deducción de plegado 90° (estante)")
                g = ctx.derive("HOLGURA_EST", lambda p: max(p["RADIO_EST"], head_h) if p["HOLGURA_ENCIMERA"] == AUTO
                               else p["HOLGURA_ENCIMERA"], "mm", "Holgura bastidor–pestaña (estante)")
                e = ts + g
                D, zs = ctx["PROFUNDIDAD_ESTANTE"], ctx["ALTURA_ESTANTE"]
                notch = a + ctx["HOLGURA_ESCOTADURA"]
                Lx = L - 2 * c
                if e + alt.B > a:
                    model.note("error", "DFM-BASTIDOR-ESTANTE", "El bastidor retranqueado del estante no cabe en la "
                               "sección del montante.")
                arm_len = D - a - e - alt.B
                if arm_len <= 0:        # brazos de longitud nula o negativa: geometría imposible (sólidos abiertos)
                    raise ParamError(f"Fondo de estante {D:g} mm insuficiente para el montante y el bastidor del estante "
                                     f"({alt.code}): mínimo {a + e + alt.B + 40:.0f} mm.")
                if arm_len < 40:
                    model.note("error", "GEO-ESTANTE-CORTO", f"Fondo de estante {D:g} mm insuficiente para el montante "
                               f"y el bastidor (mínimo {a + e + alt.B + 40:.0f} mm).")
                if zs > zt - 100 + 1e-9:
                    model.note("error", "GEO-ESTANTE-ALTO", f"El estante superior ({zs:g} mm) debe quedar al menos "
                               f"100 mm por debajo de la cota superior de los montantes ({zt:g} mm).")
                if zs < H + 300:
                    model.note("error", "GEO-ESTANTE-BAJO", f"El estante superior ({zs:g} mm) debe quedar al menos "
                               f"300 mm por encima de la encimera ({H:g} mm).")
                xa0, xa1 = c + e + alt.B / 2, L - c - e - alt.B / 2
                n_int = ctx["NUMERO_TRAVESANOS_ESTANTE"]
                if n_int == AUTO:
                    n_int = max(0, math.ceil((xa1 - xa0) / ctx["SEPARACION_MAX_APOYOS"]) - 1)
                ctx.set_derived("N_TRAVESANOS_ESTANTE", n_int, "ud", "Travesaños intermedios bajo el estante",
                                ["NUMERO_TRAVESANOS_ESTANTE", "SEPARACION_MAX_APOYOS", "LONGITUD"])
                ala = ctx["ALA_ESTANTE"]
                hd = flange_hole_d(v["MATERIAL_CHAPA"], ts, sc)
                m = 40.0
                ranges = {"y0": (e + alt.B + m, Lx - e - alt.B - m, 2), "y1": (notch + 30, Lx - notch - 30, 2),
                          "x0": (e + alt.B + 30, D - notch - 20, 1), "x1": (e + alt.B + 30, D - notch - 20, 1)}
                fix = self._fix_layout(model, ctx, Lx, D, 0.0, a, ts, rs + ts, ala, alt, alt, z_ref=zs, inset=e,
                                       hole_d=hd, rn=rn, pitch=ctx["PASO_FIJACIONES"], short_min=1, tag="estante",
                                       offset=(c, W - c - D), ranges=ranges)
                fix["gap"] = g
                flanges = tuple(FlangeSpec(ed, ala, "down", tuple((s, fix["h"][ed], hd) for s in fix["s"][ed]))
                                for ed in EDGES)
                d["est_spec"] = SheetMetalSpec(Lx, D, ts, rs, Ks, flanges, notch=(notch, notch),
                                               notch_corners=("x0y1", "x1y1"))
                d.update(est_t=ts, est_e=e, est_D=D, est_z=zs, est_notch=notch, est_n_int=n_int, fix_est=fix,
                         est_xa=(xa0, xa1))
            # ---- panel perforado
            d["panel"] = bool(ctx["PANEL_HERRAMIENTAS"])
            if d["panel"]:
                tp = ctx["ESPESOR_PANEL"]
                z0 = H + 40.0
                z1 = (ctx["ALTURA_ESTANTE"] - d["est_t"] - alt.H - 30.0) if d["shelf_top"] else (zt - alt.H - 30.0)
                Hp = round(z1 - z0, 3)
                if Hp < 200:
                    model.note("advertencia", "GEO-PANEL-SIN-HUECO", f"No queda hueco para el panel portaherramientas "
                               f"({Hp:.0f} mm entre encimera y estante): se omite.")
                    d["panel"] = False
                else:
                    fam = catalog.material(v["MATERIAL_CHAPA"]).family
                    rmin = catalog.sheet_data()["press_brake"]["min_inner_radius_factor"].get(fam, 1.0)
                    rp = round(max(tp, rmin * tp), 2) if v["RADIO_PLEGADO"] == AUTO else v["RADIO_PLEGADO"]
                    Kp = round(catalog.din6935_k_factor(rp, tp), 4) if v["FACTOR_K"] == AUTO else v["FACTOR_K"]
                    Rp = rp + tp
                    Lp = L - 2 * c
                    gp = head_h                     # la cabeza de la remachable queda entre panel y montante
                    hd = flange_hole_d(v["MATERIAL_CHAPA"], tp, sc)
                    n_fix = max(2, math.ceil((Hp - 2 * Rp - 50) / ctx["PASO_FIJACIONES"]) + 1)
                    ys = even_positions(Rp + 25, Hp - Rp - 25, n_fix)
                    holes = [("round", a / 2, y, hd) for y in ys] + [("round", Lp - a / 2, y, hd) for y in ys]
                    holes += list(perforation_grid(a + 15, Rp + 2 * tp + 12, Lp - a - 15, Hp - Rp - 2 * tp - 12,
                                                   PANEL_PITCH, PANEL_HOLE))
                    fl = 15.0
                    d["panel_spec"] = SheetMetalSpec(Lp, Hp, tp, rp, Kp,
                                                     (FlangeSpec("y0", fl, "down"), FlangeSpec("y1", fl, "down")),
                                                     notch=(a + 3, Rp), holes=tuple(holes))
                    y_front = W - c - a - gp - tp
                    d.update(panel_z=(z0, z1), panel_y=y_front, panel_gap=gp, panel_t=tp, panel_fix_z=[z0 + y for y in ys])
                    ctx.set_derived("ALTO_PANEL", Hp, "mm", "Altura del panel perforado",
                                    ["ALTURA", "ALTURA_ESTANTE", "ALTURA_TOTAL", "PANEL_HERRAMIENTAS"])
                    # taladros de las remachables en la cara delantera de los montantes
                    d["leg_holes"] = tuple(("-y", round(z - d["z_leg0"], 3), 0.0, rn["hole_d"]) for z in d["panel_fix_z"])
        return d

    def _extras(self, model, ctx, d, legs, corners):
        ps = model.params
        v = ps.values
        mat_s, mat_c, fin = v["MATERIAL_ESTRUCTURAL"], v["MATERIAL_CHAPA"], v["ACABADO"]
        a, c, L, W = d["a"], d["c"], v["LONGITUD"], v["ANCHURA"]
        alt = d["alt"]
        weld = self._make_welder(model, d)
        rn = catalog.component("TUERCA_REMACHABLE_M6")
        sc = catalog.component("TORNILLO_ISO7380_M6x12")
        yR = W - c - a / 2
        with ctx.feature("F14", "Travesaño alto entre montantes"):
            ctx.uses("PERFIL_ALTILLO", "ALTURA_TOTAL", "LONGITUD", "RETRANQUEO", "PERFIL_PATA", "MATERIAL_ESTRUCTURAL")
            zc = d["z_top_alt"] - alt.H / 2
            p0, p1 = np.array([c + a, yR, zc]), np.array([L - c - a, yR, zc])
            part = ProfilePart("travesano_alto", f"Travesaño alto {alt.code}", alt.code, L - 2 * c - 2 * a, mat_s, fin)
            model.add("EST.TRV_ALTO", "Travesaño alto entre montantes", part, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                      axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
            weld("J.EST.TRV_ALTO.0", "EST.TRV_ALTO", 0, legs["TI"], alt, "Travesaño alto a montante")
            weld("J.EST.TRV_ALTO.1", "EST.TRV_ALTO", 1, legs["TD"], alt, "Travesaño alto a montante")
        if d["shelf_top"]:
            self._shelf_top(model, ctx, d, legs, weld, rn, sc, mat_s, mat_c, fin)
        if d["panel"]:
            self._panel(model, ctx, d, rn, sc, mat_c, fin)

    def _shelf_top(self, model, ctx, d, legs, weld, rn, sc, mat_s, mat_c, fin):
        v = model.params.values
        a, c, L, W = d["a"], d["c"], v["LONGITUD"], v["ANCHURA"]
        alt, e, D, zs, ts = d["alt"], d["est_e"], d["est_D"], d["est_z"], d["est_t"]
        fix = d["fix_est"]
        model.add_subassembly("ALT", "Estante superior", explode=(0, -0.6 * D, 120), step=5)
        hole_rn = rn["hole_d"]
        y_front_tray = W - c - D
        z_top = zs - ts
        zc = z_top - alt.H / 2

        def hz(edge):
            return fix["z_ref"] - fix["h"][edge] - zc
        with ctx.feature("F15", "Bastidor del estante superior"):
            ctx.uses("PERFIL_ALTILLO", "ALTURA_ESTANTE", "PROFUNDIDAD_ESTANTE", "ESP_EST", "HOLGURA_EST",
                     "N_TRAVESANOS_ESTANTE", "PASO_FIJACIONES", "ALA_ESTANTE", "MATERIAL_ESTRUCTURAL")
            # larguero delantero (+X) con taladros en la cara delantera ("-x" = -Y)
            yF = y_front_tray + e + alt.B / 2
            x0, x1 = c + e, L - c - e
            holes = tuple(("-x", round(c + s - x0, 3), round(hz("y0"), 3), hole_rn) for s in fix["s"]["y0"])
            pF = ProfilePart("larguero_est", f"Larguero delantero de estante {alt.code}", alt.code, x1 - x0, mat_s, fin,
                             holes=holes)
            p0, p1 = np.array([x0, yF, zc]), np.array([x1, yF, zc])
            model.add("EST.EST_LAR.D", "Larguero delantero del estante", pF, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                      axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
            # larguero trasero entre montantes (-X, "-x" = +Y)
            yB = W - c - e - alt.B / 2
            xb0, xb1 = L - c - a, c + a
            holes = tuple(("-x", round(xb0 - (c + s), 3), round(hz("y1"), 3), hole_rn) for s in fix["s"]["y1"])
            pB = ProfilePart("larguero_est", f"Larguero trasero de estante {alt.code}", alt.code, xb0 - xb1, mat_s, fin,
                             holes=holes)
            p0, p1 = np.array([xb0, yB, zc]), np.array([xb1, yB, zc])
            model.add("EST.EST_LAR.T", "Larguero trasero del estante", pB, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                      axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
            weld("J.EST.EST_LAR.T.0", "EST.EST_LAR.T", 0, legs["TD"], alt, "Larguero trasero de estante a montante")
            weld("J.EST.EST_LAR.T.1", "EST.EST_LAR.T", 1, legs["TI"], alt, "Larguero trasero de estante a montante")
            # brazos en voladizo (-Y) desde la cara delantera del montante hasta el larguero delantero
            ya0, ya1 = W - c - a, yF + alt.B / 2
            arms = []
            for k, nm, x, face, edge, leg in (("I", "izquierdo", c + e + alt.B / 2, "-x", "x0", "TI"),
                                              ("D", "derecho", L - c - e - alt.B / 2, "+x", "x1", "TD")):
                holes = tuple((face, round(ya0 - (y_front_tray + s), 3), round(hz(edge), 3), hole_rn)
                              for s in fix["s"][edge])
                pA = ProfilePart("brazo_est", f"Brazo {nm} de estante {alt.code}", alt.code, ya0 - ya1, mat_s, fin,
                                 holes=holes)
                iid = f"EST.EST_BRZ.{k}"
                p0, p1 = np.array([x, ya0, zc]), np.array([x, ya1, zc])
                model.add(iid, f"Brazo {nm} del estante", pA, G.axis_frame(p0, p1, (0, 0, 1)), "EST", axis=(p0, p1),
                          up=np.array([0, 0, 1.0]), structural=True)
                weld(f"J.{iid}.0", iid, 0, legs[leg], alt, "Brazo de estante a montante")
                weld(f"J.{iid}.1", iid, 1, "EST.EST_LAR.D", alt, "Brazo de estante a larguero delantero")
                arms.append(iid)
            # travesaños intermedios (+Y) entre larguero delantero y trasero
            xa0, xa1 = d["est_xa"]
            n_int = d["est_n_int"]
            xs = [xa0 + i * (xa1 - xa0) / (n_int + 1) for i in range(1, n_int + 1)]
            ints = []
            if n_int:
                yi0, yi1 = yF + alt.B / 2, yB - alt.B / 2
                pI = ProfilePart("travesano_int_est", f"Travesaño intermedio de estante {alt.code}", alt.code, yi1 - yi0,
                                 mat_s, fin)
                for n, x in enumerate(xs, start=1):
                    iid = f"EST.EST_TRI.{n:02d}"
                    p0, p1 = np.array([x, yi0, zc]), np.array([x, yi1, zc])
                    model.add(iid, f"Travesaño intermedio del estante {n}", pI, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                              axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
                    weld(f"J.{iid}.0", iid, 0, "EST.EST_LAR.D", alt, "Travesaño intermedio de estante a larguero")
                    weld(f"J.{iid}.1", iid, 1, "EST.EST_LAR.T", alt, "Travesaño intermedio de estante a larguero")
                    ints.append(iid)
            model.structure.setdefault("levels", {})["ALTO"] = {
                "long": ["EST.EST_LAR.D", "EST.EST_LAR.T"], "end": arms, "int": ints, "grid_x": [xa0] + xs + [xa1],
                "grid_y": [yF, yB], "z": z_top}
        with ctx.feature("F35", "Estante superior de chapa plegada"):
            ctx.uses("LONGITUD", "PROFUNDIDAD_ESTANTE", "ALTURA_ESTANTE", "ESP_EST", "ALA_ESTANTE", "MATERIAL_CHAPA",
                     "PERFIL_PATA", "HOLGURA_ESCOTADURA", "PERFIL_ALTILLO", "ACABADO")
            tray = SheetPart("estante", f"Estante superior chapa {ts:g} mm", d["est_spec"], mat_c, fin)
            model.add("ALT.BANDEJA", "Estante superior", tray, G.translation(c, y_front_tray, zs), "ALT")
            self._fasteners(model, fix, "ALT", rn, sc, ctx, tray_id="ALT.BANDEJA")

    def _panel(self, model, ctx, d, rn, sc, mat_c, fin):
        v = model.params.values
        a, c, L = d["a"], d["c"], v["LONGITUD"]
        spec = d["panel_spec"]
        model.add_subassembly("PAN", "Panel portaherramientas", explode=(0, -220, 0), step=6)
        with ctx.feature("F36", "Panel perforado portaherramientas"):
            ctx.uses("PANEL_HERRAMIENTAS", "ESPESOR_PANEL", "LONGITUD", "ALTURA", "ALTURA_ESTANTE", "ALTURA_TOTAL",
                     "MATERIAL_CHAPA", "PERFIL_PATA", "ACABADO")
            z0 = d["panel_z"][0]
            yF = d["panel_y"]
            # chapa: X local = X, Y local = Z (altura), cara exterior hacia -Y y pestañas hacia +Y (montantes)
            T = np.array([[1.0, 0, 0, c], [0, 0, -1.0, yF], [0, 1.0, 0, z0], [0, 0, 0, 1.0]])
            part = SheetPart("panel", f"Panel perforado chapa {spec.t:g} mm", spec, mat_c, fin)
            model.add("PAN.PANEL", "Panel portaherramientas", part, T, "PAN")
            tp, gp = d["panel_t"], d["panel_gap"]
            wall = d["leg"].t
            sel_rn = catalog.select_rivet_nut(wall)
            code_rn = sel_rn[0] if sel_rn else "TUERCA_REMACHABLE_M6"
            rnd = sel_rn[1] if sel_rn else rn
            sel_sc = catalog.select_screw(tp + gp, tp + gp + rnd["body_l"])
            code_sc = sel_sc[0] if sel_sc else "TORNILLO_ISO7380_M6x12"
            nrm = np.array([0, -1.0, 0])
            n = 0
            for x in (c + a / 2, L - c - a / 2):
                for z in d["panel_fix_z"]:
                    n += 1
                    pf = np.array([x, yF, z])
                    pr = pf - nrm * (tp + gp)
                    rid, sid = f"PAN.TREM.{n:02d}", f"PAN.TORN.{n:02d}"
                    model.add(rid, f"Tuerca remachable {n}", StandardPart("tuerca_remachable", code_rn), frame_z(pr, nrm),
                              "PAN", tags={"explode_extra": tuple(nrm * 30)})
                    model.add(sid, f"Tornillo {n}", StandardPart("tornillo", code_sc), frame_z(pf, nrm), "PAN",
                              tags={"explode_extra": tuple(nrm * 80)})
                    model.add_joint(Joint(f"J.{sid}", "atornillada", ("PAN.PANEL", rid), tuple(pf),
                                          f"Tornillo {catalog.component(code_sc)['thread']} en tuerca remachable",
                                          fasteners=(sid, rid),
                                          data={"t_sheet": tp, "gap": gp, "wall": wall, "screw": code_sc,
                                                "rivet": code_rn, "rivet_found": sel_rn is not None,
                                                "screw_found": sel_sc is not None}))
            # el peso del panel cuelga de los montantes (no es una superficie de carga)
            pm = analytic_volume(spec) * 1e-9 * catalog.material(mat_c).density
            pts = [(legs_id, z) for legs_id in ("EST.PATA.TI", "EST.PATA.TD") for z in d["panel_fix_z"]]
            model.structure.setdefault("attached_masses", []).extend(
                {"member": m, "point": (model.instance(m).axis[0][0], model.instance(m).axis[0][1], z),
                 "mass_kg": pm / len(pts), "label": "Panel portaherramientas"} for m, z in pts)

    def _structure(self, model, d, legs):
        st = super()._structure(model, d, legs)
        if d["shelf_top"]:
            v = model.params.values
            notch = d["est_notch"]
            st["surfaces"].append({"id": "estante", "label": "Estante superior", "level": "ALTO",
                                   "load_param": "CARGA_ESTANTE", "sheet_instance": "ALT.BANDEJA",
                                   "area_mm2": (v["LONGITUD"] - 2 * d["c"]) * d["est_D"] - 2 * notch * notch,
                                   "count_param": "NUMERO_TRAVESANOS_ESTANTE"})
        st["attached_masses"] = model.structure.get("attached_masses", [])
        st["product_word"] = "puesto"
        st["assembly_texts"] = {
            "ALT": "Colocar el estante superior sobre su bastidor, con las escotaduras traseras alrededor de los "
                   "montantes, y fijarlo con tornillos ISO 7380 M6 (8 N·m).",
            "PAN": "Presentar el panel perforado contra la cara delantera de los montantes y atornillarlo a las tuercas "
                   "remachables M6 (8 N·m), de abajo arriba."}
        return st

    def _extra_dims(self, model, d):
        v = model.params.values
        levels = []
        if d["shelf"]:
            levels.append(("ALTURA_BALDA", "BAL.BANDEJA"))
        levels.append(("ALTURA_ENCIMERA", "ENC.BANDEJA", v["ALTURA"]))
        levels += self._peto_level(d, v["ALTURA"])
        if d["shelf_top"]:
            levels.append(("ALTURA_ESTANTE", "ALT.BANDEJA"))
        zs = [0.0] + [{"ALTURA_BALDA": d.get("z_shelf"), "ALTURA_ENCIMERA": v["ALTURA"], "ALTURA_ESTANTE": d.get("est_z"),
                       "COTA_PETO": v["ALTURA"] + d["peto"]}[n] for n, *_ in levels]
        model.dims["ALTURA_ENCIMERA"] = v["ALTURA"]
        model.dims.update({
            "ALTURA_TOTAL": d["z_top_alt"],
            "envelope": {"ids": ["ENC.BANDEJA", "EST.PATA.TI", "EST.PATA.TD"], "dx": v["LONGITUD"], "dy": v["ANCHURA"],
                         "zmax": max(d["z_top_alt"], v["ALTURA"] + d["peto"]), "names": ("LONGITUD", "ANCHURA")},
            "levels": levels,
            "drawing_expected": {f"DIST_NIVEL_{k + 1}": zs[k + 1] - zs[k] for k in range(len(levels))},
            "load_text": (f"Cargas de proyecto: encimera {v.get('CARGA_TOTAL') or 'NO DEFINIDA'} kg"
                          + (f", balda {v.get('CARGA_BALDA') or 'NO DEFINIDA'} kg" if d["shelf"] else "")
                          + (f", estante superior {v.get('CARGA_ESTANTE') or 'NO DEFINIDA'} kg" if d["shelf_top"] else "")),
        })
