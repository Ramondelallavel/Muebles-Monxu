"""Familia D: carro estantería (estantería de N niveles sobre ruedas).

Estantería industrial soldada (montantes tubulares, bastidores por nivel y bandejas de chapa plegada) apoyada en
cuatro ruedas giratorias de espiga roscada, roscadas en las tuercas soldadas de las placas base como los pies
niveladores. Las ruedas del extremo izquierdo (X = 0) llevan freno.

Asa de empuje opcional (``ASA_EMPUJE``): un tubo soldado entre los dos montantes de un extremo (o de los dos), a la
altura ``ALTURA_ASA``, en el plano de los montantes. El asa debe dejar holgura para la mano respecto a las bandejas
y bastidores de los niveles; si no, se informa un error de geometría.

La fuerza horizontal de maniobra (``CARGA_HORIZONTAL``) se aplica en el nivel superior para el cálculo de barras y,
para el vuelco, a la altura de empuje: la del asa (o ``ALTURA_ASA`` como altura de mano si no hay asa), nunca por
encima de la altura total.
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..core.model import ProfilePart, StandardPart
from ..core.params import AUTO, ParamSpec
from .base import register
from .carro_taller import CASTORS
from .estanteria import CANDIDATES as EST_CANDIDATES, CONSTRUCTIVE_DEFAULTS as EST_DEFAULTS, Estanteria
from .mesa_industrial import ALLP

HANDLE_MODES = ["un_extremo", "dos_extremos", "ninguna"]
CANDIDATES = {**EST_CANDIDATES, "PERFIL_ASA": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2"]}
CONSTRUCTIVE_DEFAULTS = {**{k: v for k, v in EST_DEFAULTS.items() if k != "PIE_NIVELADOR"},
                         "PERFIL_ASA": "RHS 40x20x2", "RUEDA": "RUEDA_ESP_M12_D100"}
HAND_CLEARANCE = 40.0      # holgura mínima del asa a bandejas y bastidores (mano)


def nearest_handle(z_levels, lo_of, asa_h, H, za):
    """Cota superior del asa válida más próxima a ``za``: deja HAND_CLEARANCE con la banda de cada nivel
    (de ``lo_of(z)`` a ``z``) y no sobrepasa los montantes; preferentemente a 800 mm o más. None si no hay ninguna."""
    forb = [(lo_of(z) - HAND_CLEARANCE, z + HAND_CLEARANCE + asa_h) for z in z_levels]   # intervalos abiertos
    for z_min in (800.0, 600.0):
        cands = {math.ceil(z_min / 5) * 5, math.floor(H / 5) * 5}
        for a, b in forb:
            cands |= {math.floor(a / 5) * 5, math.ceil(b / 5) * 5}
        ok = sorted(float(c) for c in cands if z_min <= c <= H and not any(a < c < b for a, b in forb))
        if ok:
            return min(ok, key=lambda c: (abs(c - za), c))
    return None


@register
class CarroEstanteria(Estanteria):
    id = "carro_estanteria"
    name = "Carro estantería"
    prefix = "CE"
    category = "D"
    description = ("Estantería de N niveles de bandejas de chapa plegada sobre ruedas giratorias de espiga roscada (con "
                   "freno en un extremo) y asa de empuje opcional entre montantes. Carro de picking, de bandejas o de "
                   "transporte interno, comprobado frente al vuelco sin anclaje.")
    configurations = ["Carro de picking", "Carro de bandejas", "Carro estantería de transporte interno"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    frame_params = ("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "PERFIL_ASA")
    support_param = "RUEDA"
    level_load_kg_m2 = 100            # carga de uso por defecto de cada bandeja (kg/m²)
    support_category = "ruedas_espiga"
    support_group = ("RUE", "Ruedas")

    def param_for_role(self, role):
        if role == "asa":
            return "PERFIL_ASA"
        return super().param_for_role(role)

    # ------------------------------------------------------------------ parámetros
    def param_specs(self):
        P = ParamSpec
        out = []
        for s in super().param_specs():
            if s.name == "PIE_NIVELADOR":
                out.append(P("RUEDA", "Rueda giratoria (espiga roscada)", "choice", AUTO, None, "accesorios",
                             choices=CASTORS, allow_auto=True,
                             help="'auto': la de menor capacidad nominal que soporta la reacción de servicio por rueda. "
                                  "Las del extremo izquierdo se montan con freno."))
                out.append(P("ASA_EMPUJE", "Asa de empuje", "choice", "un_extremo", None, "accesorios",
                             choices=HANDLE_MODES,
                             help="Tubo soldado entre los montantes de un extremo, de los dos o ninguno."))
                out.append(P("PERFIL_ASA", "Perfil del asa", "choice", AUTO, None, "construccion", choices=ALLP,
                             allow_auto=True))
                continue
            if s.name == "ANCHURA":
                s = P("ANCHURA", "Anchura (frente)", "float", 1000.0, "mm", "dimensiones", 500, 2000)
            elif s.name == "PROFUNDIDAD":
                s = P("PROFUNDIDAD", "Profundidad (fondo)", "float", 600.0, "mm", "dimensiones", 350, 1000)
            elif s.name == "ALTURA":
                s = P("ALTURA", "Altura total", "float", 1400.0, "mm", "dimensiones", 700, 2000)
            elif s.name == "NUMERO_NIVELES":
                s = P("NUMERO_NIVELES", "Número de niveles", "int", 3, "ud", "dimensiones", 2, 6)
            elif s.name == "ALTURA_PRIMER_NIVEL":
                s = P("ALTURA_PRIMER_NIVEL", "Altura del primer nivel (cara superior)", "float", 300.0, "mm",
                      "dimensiones", 200, 800)
            elif s.name == "TIPO_APOYO":
                s = P("TIPO_APOYO", "Tipo de apoyo", "choice", "ruedas", None, "accesorios", choices=["ruedas"])
            elif s.name == "TACO_ANCLAJE":
                continue                                     # un carro no se ancla
            elif s.name == "ANCLAJE":
                s = P("ANCLAJE", "Anclaje", "choice", "ninguno", None, "cargas", choices=["ninguno"],
                      help="Un carro no se ancla: la estabilidad se comprueba sin anclaje.")
            elif s.name == "CARGA_HORIZONTAL":
                s = P("CARGA_HORIZONTAL", "Fuerza horizontal de maniobra", "float", 100.0, "N", "cargas", 0, 1000,
                      help="Empuje o arrastre con las ruedas frenadas o bloqueadas por un obstáculo, aplicado a la "
                           "altura de empuje; es la acción que puede volcar el carro.")
            out.append(s)
        idx = max(i for i, s in enumerate(out) if s.group == "dimensiones") + 1
        out.insert(idx, P("ALTURA_ASA", "Altura del asa (altura de empuje)", "float", 1000.0, "mm", "dimensiones",
                          600, 1400, help="Cota superior del asa desde el suelo. Sin asa, altura de la mano al "
                                          "empujar (se usa en la comprobación de vuelco)."))
        return out

    def templates(self):
        return [
            {"id": "CE-1000-3", "name": "Carro estantería de tres niveles 1.000 mm", "family": self.id,
             "values": {"ANCHURA": 1000.0, "PROFUNDIDAD": 600.0, "ALTURA": 1400.0, "NUMERO_NIVELES": 3,
                        "ALTURA_PRIMER_NIVEL": 300.0, "CARGA_POR_NIVEL": 60.0, "ALTURA_ASA": 1000.0,
                        "CARGA_HORIZONTAL": 80.0, "ACABADO": "RAL7035_POLVO"}},
            {"id": "CE-1200-4-PICKING", "name": "Carro de picking de cuatro niveles 1.200 mm (asa en los dos extremos)",
             "family": self.id,
             "values": {"ANCHURA": 1200.0, "PROFUNDIDAD": 600.0, "ALTURA": 1600.0, "NUMERO_NIVELES": 4,
                        "ALTURA_PRIMER_NIVEL": 250.0, "CARGA_POR_NIVEL": 40.0, "ALTURA_ASA": 1000.0,
                        "ASA_EMPUJE": "dos_extremos", "CARGA_HORIZONTAL": 60.0, "ACABADO": "RAL5010_POLVO"}},
            {"id": "CE-800-5-INOX", "name": "Carro de bandejas inoxidable de cinco niveles 800 mm", "family": self.id,
             "values": {"ANCHURA": 800.0, "PROFUNDIDAD": 500.0, "ALTURA": 1500.0, "NUMERO_NIVELES": 5,
                        "ALTURA_PRIMER_NIVEL": 250.0, "CARGA_POR_NIVEL": 25.0, "ALTURA_ASA": 1000.0,
                        "MATERIAL_ESTRUCTURAL": "1.4301", "MATERIAL_CHAPA": "1.4301", "ACABADO": "INOX_SATINADO",
                        "ENTORNO": "interior_humedo", "CARGA_HORIZONTAL": 50.0}},
            {"id": "CE-1000-4-PESADO", "name": "Carro estantería de cuatro niveles 1.000 mm (80 kg por nivel)", "family": self.id,
             "values": {"ANCHURA": 1000.0, "PROFUNDIDAD": 600.0, "ALTURA": 1600.0, "NUMERO_NIVELES": 4,
                        "CARGA_POR_NIVEL": 80.0, "ASA_EMPUJE": "un_extremo", "ALTURA_ASA": 1000.0,
                        "CARGA_HORIZONTAL": 60.0, "ACABADO": "RAL7016_POLVO"}},
            {"id": "CE-700-4-COMPACTO", "name": "Carro de bandejas compacto de cuatro niveles 700 mm", "family": self.id,
             "values": {"ANCHURA": 700.0, "PROFUNDIDAD": 450.0, "ALTURA": 1200.0, "NUMERO_NIVELES": 4,
                        "CARGA_POR_NIVEL": 20.0, "ASA_EMPUJE": "un_extremo", "ALTURA_ASA": 1000.0,
                        "CARGA_HORIZONTAL": 30.0, "ACABADO": "RAL5010_POLVO"}},
        ]

    # ------------------------------------------------------------------ ganchos
    def _support_part(self, corner, ps):
        code = ps.values["RUEDA"]
        if corner in ("DI", "TI"):
            return StandardPart("rueda", f"{code}_FRENO"), "Rueda con freno"
        return StandardPart("rueda", code), "Rueda giratoria"

    def _derive_shelf(self, ctx, model):
        d = super()._derive_shelf(ctx, model)
        mode = ctx["ASA_EMPUJE"]
        d.update(asa_mode=mode, z_asa=None)
        with ctx.feature("F06", "Asa de empuje y altura de maniobra"):
            H = ctx["ALTURA"]
            asa = catalog.profile(ctx["PERFIL_ASA"])
            d["asa"] = asa
            ctx.derive("ALTURA_EMPUJE", lambda p: min(p["ALTURA_ASA"], p["ALTURA"]), "mm",
                       "Altura de aplicación de la fuerza de maniobra (vuelco)")
            if mode != "ninguna":
                za = ctx.derive("COTA_ASA", lambda p: p["ALTURA_ASA"], "mm", "Cota superior del asa")
                d["z_asa"] = za
                if za > H + 1e-9:
                    model.note("error", "GEO-ASA-ALTA", f"El asa ({za:g} mm) queda por encima de los montantes "
                               f"({H:g} mm): reduzca ALTURA_ASA.")
                if asa.B > d["a"]:
                    model.note("error", "DFM-ASA-ANCHO", f"El perfil del asa {asa.code} es más ancho que el montante.")
                band = d["ts"] + max(d["rail"].H, d["trv"].H)
                lo_b, hi_b = za - asa.H, za
                ala = ctx["ALA_BALDA"]
                for i, z in enumerate(d["z_levels"], start=1):
                    lo_l = z - max(ala, band)
                    if not (lo_b >= z + HAND_CLEARANCE or hi_b <= lo_l - HAND_CLEARANCE):
                        z_ok = nearest_handle(d["z_levels"], lambda zz: zz - max(ala, band), asa.H, H, za)
                        if z_ok is not None and ctx.params.sources.get("ALTURA_ASA") == "defecto":
                            model.rule_fixes["ALTURA_ASA"] = (
                                z_ok, f"Asa a {z_ok:g} mm (regla de diseño): a la altura por defecto, {za:g} mm, no dejaba "
                                      f"{HAND_CLEARANCE:g} mm para la mano con el nivel {i}.")
                        model.note("error", "GEO-ASA-NIVEL",
                                   f"El asa ({lo_b:g}–{hi_b:g} mm) no deja {HAND_CLEARANCE:g} mm de holgura para la mano "
                                   f"con el nivel {i} ({lo_l:g}–{z:g} mm): " +
                                   (f"ALTURA_ASA válida más próxima, {z_ok:g} mm." if z_ok is not None else
                                    "ninguna altura de asa es válida con estos niveles; cambie la distancia entre "
                                    "niveles."))
                        break
            c = catalog.component(ctx["RUEDA"])
            ctx.set_derived("DIAMETRO_RUEDA", c["wheel_d"], "mm", "Diámetro de rueda", ["RUEDA"])
        return d

    def _extras(self, model, ctx, d, legs, corners):
        if d["asa_mode"] == "ninguna":
            return
        v = model.params.values
        asa, a, A, Pf = d["asa"], d["a"], v["ANCHURA"], v["PROFUNDIDAD"]
        weld = self._make_welder(model, d)
        two = d["asa_mode"] == "dos_extremos"
        handles = [("EST.ASA", a / 2, "DI", "TI", " izquierda" if two else "")]
        if two:
            handles.append(("EST.ASA_D", A - a / 2, "DD", "TD", " derecha"))
        with ctx.feature("F16", "Asa de empuje soldada"):
            ctx.uses("PERFIL_ASA", "ALTURA_ASA", "ASA_EMPUJE", "PROFUNDIDAD", "PERFIL_MONTANTE", "MATERIAL_ESTRUCTURAL",
                     "ACABADO")
            part = ProfilePart("asa", f"Asa de empuje {asa.code}", asa.code, Pf - 2 * a, v["MATERIAL_ESTRUCTURAL"],
                               v["ACABADO"])
            zc = d["z_asa"] - asa.H / 2
            for iid, x, l0, l1, side in handles:
                p0, p1 = np.array([x, a, zc]), np.array([x, Pf - a, zc])
                model.add(iid, f"Asa de empuje{side}", part, G.axis_frame(p0, p1, (0, 0, 1)), "EST", axis=(p0, p1),
                          up=np.array([0, 0, 1.0]), structural=True)
                weld(f"J.{iid}.0", iid, 0, legs[l0], asa, "Asa a montante")
                weld(f"J.{iid}.1", iid, 1, legs[l1], asa, "Asa a montante")

    def _shelf_structure(self, model, d, legs):
        st = super()._shelf_structure(model, d, legs)
        v = model.params.values
        st["product_word"] = "carro"
        st["push_height"] = min(v["ALTURA_ASA"], v["ALTURA"])        # vuelco: altura de la mano o del asa
        st["mobile"] = d["asa_mode"] != "ninguna"              # con asa: maniobra en la dirección de la marcha (X)
        texts = dict(st["assembly_texts"])
        texts.pop("APO", None)
        texts["RUE"] = ("Roscar las ruedas de espiga en las tuercas soldadas de las placas base hasta el tope y "
                        "bloquearlas con su contratuerca. Las ruedas con freno van en el extremo izquierdo (X = 0).")
        st["assembly_texts"] = texts
        return st

    def _extra_dims(self, model, d):
        if d["z_asa"] is not None:
            model.dims["ALTURA_ASA"] = d["z_asa"]
