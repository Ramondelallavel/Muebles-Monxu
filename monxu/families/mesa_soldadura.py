"""Familia A: mesa de soldadura (placa gruesa perforada sobre bastidor soldado).

La superficie de trabajo es una placa de acero de 10 a 20 mm, sin pintar, con retícula de taladros para el sistema de
amarre (Ø16 a paso 50 o Ø28 a paso 100), apoyada sobre el bastidor superior y soldada a él con cordones discontinuos.
La estructura (patas, bastidores, balda inferior y reposapiés opcionales, placas base y pies) es la de la mesa
industrial, retranqueada el vuelo de la placa respecto a sus cantos para dejar los bordes libres para las mordazas.

Cálculo de la placa: Navier sobre cada panel entre travesaños con la rigidez y la resistencia reducidas por la
eficiencia de ligamento (p − d)/p de la retícula, para carga uniforme y para carga puntual de pieza pesada.
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..cad.sheetmetal import EDGES
from ..core.model import Joint, PlatePart, ProductModel
from ..core.params import AUTO, ParamContext, ParamSpec
from .base import register
from .mesa_industrial import CANDIDATES as MESA_CANDIDATES, MesaIndustrial

# sistema de amarre: (diámetro, paso) de la retícula
HOLE_SYSTEMS = {"D16_P50": (16.0, 50.0), "D28_P100": (28.0, 100.0), "ninguno": None}
# espesor mínimo constructivo (planitud y deformación térmica al soldar sobre la placa), además del cálculo
MIN_PLATE_T = {"D16_P50": 12.0, "D28_P100": 15.0, "ninguno": 10.0}
PLATE_MATERIALS = ["S355JR", "S235JR", "S275JR"]
PLATE_THICKNESSES = [10.0, 12.0, 15.0, 20.0]
PLATE_CORNER_R = 5.0
STITCH_L, STITCH_PITCH = 50.0, 250.0         # cordones discontinuos: 50 mm cada 250 mm

CANDIDATES = {**MESA_CANDIDATES,
              "PERFIL_PATA": ["SHS 60x60x3", "SHS 70x70x4", "SHS 80x80x4", "SHS 90x90x4", "SHS 100x100x4",
                              "SHS 100x100x5", "SHS 120x120x5"],
              "PERFIL_LARGUERO": ["RHS 60x40x3", "RHS 80x40x3", "RHS 80x40x4", "RHS 100x50x3", "RHS 100x50x4",
                                  "RHS 120x60x4", "RHS 120x80x5"],
              "PERFIL_TRAVESANO": ["RHS 60x40x3", "RHS 80x40x3", "RHS 100x50x3", "RHS 100x50x4"],
              "PERFIL_BASTIDOR": ["RHS 50x30x2", "RHS 60x40x2", "RHS 60x40x3"]}
CONSTRUCTIVE_DEFAULTS = {"PERFIL_PATA": "SHS 80x80x4", "PERFIL_LARGUERO": "RHS 80x40x3", "PERFIL_TRAVESANO": "RHS 60x40x3",
                         "PERFIL_BASTIDOR": "RHS 60x40x2", "PERFIL_REPOSAPIES": "RHS 40x20x2", "ESPESOR_PLACA": 12.0,
                         "ESPESOR_BALDA": 2.0, "PIE_NIVELADOR": "PIE_NIV_M16_D100"}
DROP = {"ESPESOR_CHAPA", "ALA_ENCIMERA", "PETO_TRASERO", "FIJACION_ENCIMERA"}


def hole_grid(L: float, W: float, system: str) -> tuple[tuple[float, float, float], ...]:
    """Retícula centrada en la placa, con al menos medio paso de borde."""
    sd = HOLE_SYSTEMS[system]
    if not sd:
        return ()
    dh, p = sd
    nx, ny = int((L - p) // p) + 1, int((W - p) // p) + 1
    if nx < 1 or ny < 1:
        return ()
    x0, y0 = (L - (nx - 1) * p) / 2, (W - (ny - 1) * p) / 2
    return tuple((round(x0 + i * p, 3), round(y0 + j * p, 3), dh) for i in range(nx) for j in range(ny))


@register
class MesaSoldadura(MesaIndustrial):
    id = "mesa_soldadura"
    name = "Mesa de soldadura"
    prefix = "MS"
    category = "A"
    description = ("Mesa de soldadura con placa de acero de 10 a 20 mm perforada para el sistema de amarre (Ø16/50 o "
                   "Ø28/100), soldada sobre bastidor de tubo con vuelo libre para mordazas; espesor de placa y "
                   "separación de travesaños por cálculo, con carga uniforme y carga puntual de pieza pesada.")
    configurations = ["Mesa de soldadura sistema 16", "Mesa de soldadura sistema 28", "Mesa de calderería con balda"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    top_iid, top_label = "ENC.PLACA", "Placa de soldadura"

    # ------------------------------------------------------------------ cálculo
    def plate_targets(self, v):
        out = []
        if v.get("CARGA_TOTAL") or v.get("CARGA_PUNTUAL"):
            sd = HOLE_SYSTEMS.get(v.get("SISTEMA_TALADROS"))
            avail = set(catalog.sheet_thicknesses(v["MATERIAL_PLACA"]))
            out.append({"surface": "encimera", "t_param": "ESPESOR_PLACA", "n_param": "NUMERO_TRAVESANOS",
                        "load_param": "CARGA_TOTAL", "trv_param": "PERFIL_TRAVESANO", "min_t_by_use": False,
                        "mat_param": "MATERIAL_PLACA",
                        "t_options": [t for t in PLATE_THICKNESSES
                                      if t in avail and t >= MIN_PLATE_T.get(v.get("SISTEMA_TALADROS"), 10.0)],
                        # el corte láser de los taladros exige d ≥ t
                        "t_max": min(PLATE_THICKNESSES[-1], sd[0]) if sd else PLATE_THICKNESSES[-1]})
        if v.get("CARGA_BALDA") and (v.get("NUMERO_BALDAS") or 0) >= 1:
            out.append({"surface": "balda", "t_param": "ESPESOR_BALDA", "n_param": "NUMERO_TRAVESANOS_BALDA",
                        "load_param": "CARGA_BALDA", "trv_param": "PERFIL_BASTIDOR", "min_t_by_use": False})
        return out

    def sheet_defaults_without_load(self, v):
        out = {}
        if not (v.get("CARGA_TOTAL") or v.get("CARGA_PUNTUAL")):
            out["ESPESOR_PLACA"] = max(CONSTRUCTIVE_DEFAULTS["ESPESOR_PLACA"],
                                       MIN_PLATE_T.get(v.get("SISTEMA_TALADROS"), 10.0))
        if not (v.get("CARGA_BALDA") and (v.get("NUMERO_BALDAS") or 0) >= 1):
            out["ESPESOR_BALDA"] = CONSTRUCTIVE_DEFAULTS["ESPESOR_BALDA"]
        return out

    # ------------------------------------------------------------------ parámetros
    def param_specs(self):
        P = ParamSpec
        out = []
        for s in super().param_specs():
            if s.name in DROP:
                continue
            if s.name == "LONGITUD":
                s = P("LONGITUD", "Longitud de la placa", "float", 1500.0, "mm", "dimensiones", 800, 3000)
            elif s.name == "ANCHURA":
                s = P("ANCHURA", "Anchura (fondo) de la placa", "float", 1000.0, "mm", "dimensiones", 600, 1500)
            elif s.name == "ALTURA":
                s = P("ALTURA", "Altura de la superficie de trabajo", "float", 850.0, "mm", "dimensiones", 700, 1000)
            elif s.name == "NUMERO_BALDAS":
                s = P("NUMERO_BALDAS", "Balda inferior", "int", 0, "ud", "accesorios", 0, 1)
            elif s.name == "CARGA_TOTAL":
                s = P("CARGA_TOTAL", "Carga distribuida sobre la placa", "float", None, "kg", "cargas", 0, 5000,
                      nullable=True)
            elif s.name == "CARGA_PUNTUAL":
                s = P("CARGA_PUNTUAL", "Carga puntual sobre la placa (pieza pesada)", "float", None, "kg", "cargas", 0,
                      3000, nullable=True, help="Sobre una huella de 100×100 mm en el centro del panel más desfavorable.")
            elif s.name == "CARGA_HORIZONTAL":
                s = P("CARGA_HORIZONTAL", "Empuje horizontal en el canto de la placa", "float", 300.0, "N", "cargas", 0,
                      5000, help="Martilleo, tensado de amarres o desplazamiento de piezas.")
            elif s.name == "USO":
                s = P("USO", "Uso previsto", "choice", "trabajo_pesado", None, "cargas", choices=s.choices)
            out.append(s)
        idx = max(i for i, s in enumerate(out) if s.group == "dimensiones") + 1
        out.insert(idx, P("VUELO", "Vuelo de la placa sobre la estructura", "float", 60.0, "mm", "dimensiones", 30, 200,
                          help="Borde libre alrededor de la placa para mordazas y sargentos."))
        idx = max(i for i, s in enumerate(out) if s.group == "materiales") + 1
        out[idx:idx] = [
            P("MATERIAL_PLACA", "Material de la placa", "choice", "S355JR", None, "materiales", choices=PLATE_MATERIALS),
            P("ESPESOR_PLACA", "Espesor de la placa", "float", AUTO, "mm", "materiales", 10, 20, allow_auto=True,
              help="'auto': el menor que verifica la placa con la carga uniforme y la carga puntual."),
            P("SISTEMA_TALADROS", "Sistema de taladros de amarre", "choice", "D16_P50", None, "materiales",
              choices=list(HOLE_SYSTEMS),
              help="Retícula de taladros pasantes: Ø16 a paso 50 mm o Ø28 a paso 100 mm, centrada en la placa."),
        ]
        return out

    def templates(self):
        return [
            {"id": "MS-1200-16", "name": "Mesa de soldadura 1.200 × 800 mm, sistema 16", "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 800.0, "ALTURA": 850.0, "CARGA_TOTAL": 500.0,
                        "CARGA_PUNTUAL": 150.0, "SISTEMA_TALADROS": "D16_P50", "ESPESOR_PLACA": 15.0,
                        "CARGA_HORIZONTAL": 250.0}},
            {"id": "MS-2000-28", "name": "Mesa de soldadura 2.000 × 1.000 mm, sistema 28 (carga 1.000 kg)",
             "family": self.id,
             "values": {"LONGITUD": 2000.0, "ANCHURA": 1000.0, "ALTURA": 850.0, "CARGA_TOTAL": 1000.0,
                        "CARGA_PUNTUAL": 300.0, "SISTEMA_TALADROS": "D28_P100", "CARGA_HORIZONTAL": 500.0}},
            {"id": "MS-1500-16-BALDA", "name": "Mesa de calderería 1.500 × 1.000 mm con balda inferior",
             "family": self.id,
             "values": {"LONGITUD": 1500.0, "ANCHURA": 1000.0, "ALTURA": 850.0, "CARGA_TOTAL": 600.0,
                        "CARGA_PUNTUAL": 200.0, "SISTEMA_TALADROS": "D16_P50", "NUMERO_BALDAS": 1,
                        "CARGA_BALDA": 150.0, "ALTURA_BALDA": 250.0, "CARGA_HORIZONTAL": 300.0}},
        ]

    # ------------------------------------------------------------------ derivados
    def _derive(self, ctx: ParamContext, model: ProductModel) -> dict:
        v = ctx.params.values
        d: dict = {}
        with ctx.feature("F00", "Parámetros derivados y reglas constructivas"):
            t = ctx.derive("ESP_PLACA", lambda p: p["ESPESOR_PLACA"], "mm", "Espesor de la placa")
            c = ctx.derive("RETRANQUEO", lambda p: p["VUELO"], "mm",
                           "Retranqueo de la estructura respecto al canto de la placa (vuelo)")
            leg = catalog.profile(ctx["PERFIL_PATA"])
            rail = catalog.profile(ctx["PERFIL_LARGUERO"])
            trv = catalog.profile(ctx["PERFIL_TRAVESANO"])
            bas = catalog.profile(ctx["PERFIL_BASTIDOR"])
            if leg.B != leg.H:
                raise ValueError("Las patas deben ser de tubo cuadrado")
            a = leg.B
            ctx.set_derived("SECCION_PATA", f"{leg.B:g}x{leg.H:g}", "mm", "Sección de pata", ["PERFIL_PATA"])
            ctx.set_derived("ESPESOR_PERFIL_PATA", leg.t, "mm", "Espesor de pata", ["PERFIL_PATA"])
            foot = catalog.component(ctx[self.support_param])
            hn = float(foot["nominal_height"])
            tp = ctx["ESPESOR_PLACA_BASE"]
            z_tf = ctx.derive("COTA_BASTIDOR_SUP", lambda p: p["ALTURA"] - p["ESP_PLACA"], "mm",
                              "Cota cara superior del bastidor (apoyo de la placa)")
            sp = self.support_param
            z_leg0 = ctx.derive("COTA_INICIO_PATA", lambda p: float(catalog.component(p[sp])["nominal_height"])
                                + p["ESPESOR_PLACA_BASE"], "mm", "Cota inicio de pata")
            leg_len = ctx.derive("LONGITUD_PATA", lambda p: p["COTA_BASTIDOR_SUP"] - p["COTA_INICIO_PATA"], "mm",
                                 "Longitud de corte de pata")
            L, W, H = ctx["LONGITUD"], ctx["ANCHURA"], ctx["ALTURA"]
            ctx.derive("LONGITUD_LARGUERO", lambda p: p["LONGITUD"] - 2 * p["RETRANQUEO"]
                       - 2 * catalog.profile(p["PERFIL_PATA"]).B, "mm", "Longitud de largueros")
            ctx.derive("LONGITUD_TRAVESANO_EXT", lambda p: p["ANCHURA"] - 2 * p["RETRANQUEO"]
                       - 2 * catalog.profile(p["PERFIL_PATA"]).B, "mm", "Longitud de travesaños extremos")
            ctx.derive("LONGITUD_TRAVESANO_INT", lambda p: p["ANCHURA"] - 2 * p["RETRANQUEO"]
                       - 2 * catalog.profile(p["PERFIL_LARGUERO"]).B, "mm", "Longitud de travesaños intermedios")
            if rail.B > a or trv.B > a:
                model.note("error", "DFM-ANCHO-BASTIDOR", "El ancho de largueros/travesaños supera el de la pata: "
                           "no pueden enrasarse con la cara exterior.")
            xe0, xe1 = c + trv.B / 2, L - c - trv.B / 2
            n_top = ctx["NUMERO_TRAVESANOS"]
            if n_top == AUTO:
                n_top = max(0, math.ceil((xe1 - xe0) / ctx["SEPARACION_MAX_APOYOS"]) - 1)
            ctx.set_derived("N_TRAVESANOS_INT", n_top, "ud", "Travesaños intermedios", ["NUMERO_TRAVESANOS",
                            "SEPARACION_MAX_APOYOS", "LONGITUD"])
            ctx.set_derived("VANO_ENCIMERA", round((xe1 - xe0) / (n_top + 1), 2), "mm", "Vano entre apoyos de la placa",
                            ["LONGITUD", "NUMERO_TRAVESANOS", "PERFIL_TRAVESANO", "RETRANQUEO"])
            shelf = ctx["NUMERO_BALDAS"] >= 1
            d.update(Lx=L, Ly=W, leg=leg, rail=rail, trv=trv, bas=bas, a=a, c=c, t=t, hn=hn, tp=tp, z_tf=z_tf,
                     z_leg0=z_leg0, leg_len=leg_len, n_top=n_top, xe=(xe0, xe1), shelf=shelf, peto=0.0)
            d["weld_a"] = lambda tmin: 3.0 if tmin >= 3 else float(tmin)
            # ---- placa y retícula de amarre
            system = v["SISTEMA_TALADROS"]
            holes = hole_grid(L, W, system)
            sd = HOLE_SYSTEMS[system]
            eta = (sd[1] - sd[0]) / sd[1] if sd and holes else 1.0
            ctx.set_derived("N_TALADROS_PLACA", len(holes), "ud", "Taladros de la retícula de amarre",
                            ["SISTEMA_TALADROS", "LONGITUD", "ANCHURA"])
            ctx.set_derived("EFICIENCIA_LIGAMENTO", round(eta, 4), None, "Eficiencia de ligamento de la placa (p − d)/p",
                            ["SISTEMA_TALADROS"])
            d["plate"] = {"holes": holes, "eta": eta}
            d["top_surface"] = {"ligament_efficiency": eta} if eta < 1 else {}
            t_min = MIN_PLATE_T[system]
            if t < t_min:
                model.note("advertencia", "DFM-PLACA-DELGADA", f"Placa de {t:g} mm por debajo del mínimo constructivo "
                           f"de {t_min:g} mm para el sistema {system}: riesgo de deformación al soldar sobre ella.")
            if c < 30:
                model.note("advertencia", "ERG-VUELO", "Vuelo de la placa inferior a 30 mm: poco espacio para mordazas.")
            # sin fijaciones atornilladas: la placa se suelda al bastidor
            d["fix_top"] = {"s": {e: [] for e in EDGES}, "h": {e: 0.0 for e in EDGES}, "z_ref": H, "t": t,
                            "inset": 0.0, "offset": 0.0, "Lx": L, "Ly": W, "c": c,
                            "wall": {e: (rail if e in ("y0", "y1") else trv).t for e in EDGES}, "gap": 0.0}
            d["skirt"] = rail.H
            if shelf:
                self._derive_shelf(ctx, model, d)
            self._derive_footrest(ctx, model, d)
        return d

    # ------------------------------------------------------------------ ganchos de la mesa
    def _top_frame_uses(self):
        return ("ESPESOR_PLACA", "VUELO")

    def _build_top(self, model, ctx, d, H, mat_c, fin, rn, sc):
        v = model.params.values
        L, W, t = v["LONGITUD"], v["ANCHURA"], d["t"]
        with ctx.feature("F20", "Placa de soldadura perforada"):
            ctx.uses("LONGITUD", "ANCHURA", "ALTURA", "ESP_PLACA", "SISTEMA_TALADROS", "MATERIAL_PLACA", "VUELO")
            holes = d["plate"]["holes"]
            desc = f", {len(holes)} taladros Ø{holes[0][2]:g}" if holes else ""
            part = PlatePart("placa_soldadura", f"Placa de soldadura {t:g} mm{desc}", L, W, t, v["MATERIAL_PLACA"], None,
                             corner_r=PLATE_CORNER_R, holes=holes)
            model.add(self.top_iid, "Placa de soldadura", part, G.translation(0, 0, H - t), "ENC")
            # cordones discontinuos placa–bastidor en largueros y travesaños extremos
            lv = model.structure["levels"]["SUP"]
            for mid in lv["long"] + lv["end"]:
                inst = model.instance(mid)
                p0, p1 = inst.axis
                Lm = float(np.linalg.norm(p1 - p0))
                n = max(2, math.ceil(Lm / STITCH_PITCH))
                loc = tuple(float(x) for x in (p0 + p1) / 2 + np.array([0, 0, inst.part.profile.H / 2]))
                a_w = d["weld_a"](min(t, inst.part.profile.t))
                model.add_joint(Joint(f"J.PLACA_SOLD.{mid.split('.', 1)[1]}", "soldadura", (self.top_iid, mid), loc,
                                      "Placa de soldadura a bastidor",
                                      weld={"type": "fillet", "a": a_w, "all_around": False, "process": "135 (MAG)",
                                            "length": round(n * STITCH_L, 1),
                                            "note": f"{n} cordones de {STITCH_L:g} mm cada {STITCH_PITCH:g} mm, alternos"}))

    def _structure(self, model, d, legs):
        st = super()._structure(model, d, legs)
        st["assembly_texts"] = {
            "ENC": "Colocar la placa sobre el bastidor superior con el vuelo indicado y soldarla con cordones "
                   f"discontinuos a{d['weld_a'](min(d['t'], d['rail'].t)):g} de {STITCH_L:g} mm cada {STITCH_PITCH:g} mm, "
                   "alternos para limitar la deformación. Proteger los taladros de las proyecciones. La placa no se "
                   "pinta: se entrega aceitada."}
        return st
