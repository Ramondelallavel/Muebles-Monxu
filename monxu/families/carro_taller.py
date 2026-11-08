"""Familia D: carro de taller de dos niveles sobre ruedas.

Mesa industrial (encimera y balda inferior de chapa plegada sobre bastidores soldados) apoyada en cuatro ruedas
giratorias de espiga roscada, roscadas en las tuercas soldadas de las placas base como los pies niveladores.
Las dos patas del extremo izquierdo (X = 0) se prolongan como montantes del asa de empuje, unidos arriba por el
asa soldada; la encimera lleva escotaduras en esas dos esquinas. Las ruedas del lado izquierdo llevan freno.
``ASA_EMPUJE`` permite también asa en los dos extremos (carro de pasillo, se empuja desde cualquier lado) o
ninguna (mesa móvil de trabajo, con todas las patas a la altura de la encimera).

El empuje horizontal (CARGA_HORIZONTAL) representa la fuerza de empuje o arrastre del carro y se aplica en el
plano de la encimera, como en el resto de familias.
"""
from __future__ import annotations

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..core.model import ProfilePart, StandardPart
from ..core.params import AUTO, ParamSpec
from .base import register
from .mesa_industrial import ALLP, CANDIDATES as MESA_CANDIDATES, CONSTRUCTIVE_DEFAULTS as MESA_DEFAULTS, MesaIndustrial

CASTORS = [c for c, d in catalog.components().items() if d["category"] == "ruedas_espiga" and not d.get("brake")]
CANDIDATES = {**MESA_CANDIDATES, "PERFIL_ASA": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2"]}
CONSTRUCTIVE_DEFAULTS = {**{k: v for k, v in MESA_DEFAULTS.items() if k != "PIE_NIVELADOR"},
                         "PERFIL_ASA": "RHS 40x20x2", "RUEDA": "RUEDA_ESP_M12_D100"}
HANDLE_MODES = ["un_extremo", "dos_extremos", "ninguna"]
# esquinas cuyas patas se prolongan como montantes del asa y esquinas de la encimera con escotadura
HANDLE_CORNERS = {"un_extremo": ("DI", "TI"), "dos_extremos": ("DI", "TI", "DD", "TD"), "ninguna": ()}
NOTCH_CORNERS = {"un_extremo": ("x0y0", "x0y1"), "dos_extremos": ("x0y0", "x0y1", "x1y0", "x1y1"), "ninguna": ()}


@register
class CarroTaller(MesaIndustrial):
    id = "carro_taller"
    name = "Carro de taller"
    prefix = "CT"
    category = "D"
    description = ("Carro de dos niveles con encimera y balda de chapa plegada sobre bastidores soldados, ruedas "
                   "giratorias de espiga roscada (con freno en el lado del asa) y asa de empuje soldada.")
    configurations = ["Carro de taller", "Carro de transporte interno", "Carro inoxidable"]
    verification_inputs = ["CARGA_TOTAL"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    frame_params = ("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "PERFIL_BASTIDOR", "PERFIL_REPOSAPIES", "PERFIL_ASA")
    support_param = "RUEDA"
    support_category = "ruedas_espiga"
    support_group = ("RUE", "Ruedas")

    def param_for_role(self, role):
        if role == "montante":
            return "PERFIL_PATA"
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
                                  "Las del extremo izquierdo (lado del asa) se montan con freno."))
                out.append(P("ASA_EMPUJE", "Asa de empuje", "choice", "un_extremo", None, "accesorios",
                             choices=HANDLE_MODES,
                             help="un_extremo: asa en el extremo izquierdo. dos_extremos: asa en ambos extremos (se "
                                  "maniobra desde cualquier lado). ninguna: mesa móvil sin asa."))
                continue
            if s.name == "TIPO_APOYO":
                s = P("TIPO_APOYO", "Tipo de apoyo", "choice", "ruedas", None, "accesorios", choices=["ruedas"])
            elif s.name == "ANCLAJE":
                s = P("ANCLAJE", "Anclaje al suelo", "choice", "ninguno", None, "cargas", choices=["ninguno"],
                      help="Un carro no se ancla: la estabilidad se comprueba sin anclaje.")
            elif s.name == "CARGA_HORIZONTAL":
                s = P("CARGA_HORIZONTAL", "Fuerza horizontal de maniobra", "float", 100.0, "N", "cargas", 0, 2000,
                      help="Empuje o arrastre con las ruedas frenadas o bloqueadas por un obstáculo; se aplica en el plano "
                           "de la encimera y es la acción que puede volcar el carro.")
            elif s.name == "LONGITUD":
                s = P("LONGITUD", "Longitud", "float", 1000.0, "mm", "dimensiones", 600, 2000)
            elif s.name == "ANCHURA":
                s = P("ANCHURA", "Anchura (fondo)", "float", 600.0, "mm", "dimensiones", 400, 1000)
            elif s.name == "ALTURA_BALDA":
                s = P("ALTURA_BALDA", "Altura de la balda (cara superior)", "float", 320.0, "mm", "accesorios", 200, 700)
            out.append(s)
        idx = max(i for i, s in enumerate(out) if s.group == "dimensiones") + 1
        out.insert(idx, P("ALTURA_ASA", "Altura del asa de empuje", "float", 1000.0, "mm", "dimensiones", 850, 1250,
                          help="Cota superior del asa desde el suelo (sin efecto si el carro no lleva asa)."))
        idx = max(i for i, s in enumerate(out) if s.group == "construccion" and not s.advanced) + 1
        out.insert(idx, P("PERFIL_ASA", "Perfil del asa", "choice", AUTO, None, "construccion", choices=ALLP,
                          allow_auto=True))
        return out

    def templates(self):
        return [
            {"id": "CT-1000-2N", "name": "Carro de taller de dos niveles 1.000 mm", "family": self.id,
             "values": {"LONGITUD": 1000.0, "ANCHURA": 600.0, "ALTURA": 900.0, "CARGA_TOTAL": 100.0,
                        "NUMERO_BALDAS": 1, "CARGA_BALDA": 80.0, "CARGA_HORIZONTAL": 80.0, "ACABADO": "RAL5010_POLVO"}},
            {"id": "CT-1200-PESADO", "name": "Carro de transporte 1.200 mm (carga 300 kg)", "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 700.0, "ALTURA": 900.0, "CARGA_TOTAL": 180.0,
                        "NUMERO_BALDAS": 1, "CARGA_BALDA": 120.0, "ESPESOR_CHAPA": 2.0, "USO": "trabajo_pesado",
                        "CARGA_HORIZONTAL": 120.0, "ACABADO": "RAL7016_POLVO"}},
            {"id": "CT-1200-2ASAS", "name": "Carro de pasillo con asa en los dos extremos 1.200 mm", "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 700.0, "ALTURA": 900.0, "ALTURA_ASA": 1000.0,
                        "CARGA_TOTAL": 150.0, "NUMERO_BALDAS": 1, "CARGA_BALDA": 100.0, "ASA_EMPUJE": "dos_extremos",
                        "CARGA_HORIZONTAL": 100.0, "ACABADO": "RAL7016_POLVO"}},
            {"id": "MM-1200-RUEDAS", "name": "Mesa móvil de trabajo 1.200 mm (sin asa, con peto trasero)",
             "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 700.0, "ALTURA": 900.0, "CARGA_TOTAL": 120.0,
                        "NUMERO_BALDAS": 1, "CARGA_BALDA": 60.0, "ASA_EMPUJE": "ninguna", "PETO_TRASERO": 50.0,
                        "CARGA_HORIZONTAL": 80.0, "ACABADO": "RAL5010_POLVO"}},
            {"id": "CT-800-INOX", "name": "Carro inoxidable 800 mm (alimentario)", "family": self.id,
             "values": {"LONGITUD": 800.0, "ANCHURA": 500.0, "ALTURA": 850.0, "ALTURA_ASA": 950.0,
                        "CARGA_TOTAL": 50.0, "NUMERO_BALDAS": 1, "CARGA_BALDA": 40.0,
                        "MATERIAL_ESTRUCTURAL": "1.4301", "MATERIAL_CHAPA": "1.4301", "ACABADO": "INOX_SATINADO",
                        "ENTORNO": "alimentario", "USO": "inspeccion", "CARGA_HORIZONTAL": 50.0}},
            {"id": "CT-1000-ALU", "name": "Carro de aluminio ligero 1.000 mm", "family": self.id,
             "values": {"LONGITUD": 1000.0, "ANCHURA": 600.0, "ALTURA": 900.0, "ALTURA_ASA": 1000.0,
                        "CARGA_TOTAL": 60.0, "NUMERO_BALDAS": 1, "CARGA_BALDA": 40.0,
                        "MATERIAL_ESTRUCTURAL": "EN AW-6082 T6", "MATERIAL_CHAPA": "EN AW-5754 H22",
                        "ACABADO": "ANODIZADO_NATURAL", "USO": "inspeccion", "CARGA_HORIZONTAL": 30.0}},
            {"id": "MM-1500-TALLER", "name": "Mesa móvil de taller 1.500 mm (sin asa, trabajo pesado)", "family": self.id,
             "values": {"LONGITUD": 1500.0, "ANCHURA": 750.0, "ALTURA": 900.0, "CARGA_TOTAL": 200.0,
                        "NUMERO_BALDAS": 1, "CARGA_BALDA": 100.0, "ASA_EMPUJE": "ninguna", "USO": "trabajo_pesado",
                        "CARGA_HORIZONTAL": 100.0, "ACABADO": "RAL7016_POLVO"}},
        ]

    # ------------------------------------------------------------------ ganchos de la mesa
    def _leg_uses(self):
        return ("ALTURA_ASA", "ASA_EMPUJE")

    def _leg_def(self, corner, d, leg):
        if corner in d["asa_corners"]:
            return "montante", "Montante del asa", d["z_asa"], ()
        return "pata", "Pata", d["z_tf"], ()

    def _support_part(self, corner, ps):
        code = ps.values["RUEDA"]
        if corner in ("DI", "TI"):
            return StandardPart("rueda", f"{code}_FRENO"), "Rueda con freno"
        return StandardPart("rueda", code), "Rueda giratoria"

    def _top_notch(self, ctx, d):
        corners = NOTCH_CORNERS[ctx["ASA_EMPUJE"]]
        if not corners:
            return None
        n = d["c"] + d["a"] + ctx["HOLGURA_ESCOTADURA"]
        return (n, n), corners

    def _derive(self, ctx, model):
        d = super()._derive(ctx, model)
        mode = ctx["ASA_EMPUJE"]
        d.update(asa_mode=mode, asa_corners=HANDLE_CORNERS[mode], z_asa=None)
        with ctx.feature("F06", "Asa de empuje"):
            H = ctx["ALTURA"]
            asa = catalog.profile(ctx["PERFIL_ASA"])
            d["asa"] = asa
            if mode != "ninguna":
                za = ctx.derive("COTA_ASA", lambda p: p["ALTURA_ASA"], "mm", "Cota superior del asa")
                ctx.derive("LONGITUD_MONTANTE_ASA", lambda p: p["ALTURA_ASA"] - p["COTA_INICIO_PATA"], "mm",
                           "Longitud de corte de los montantes del asa")
                d["z_asa"] = za
                if za < H + 80:
                    model.note("error", "GEO-ASA-BAJA", f"El asa ({za:g} mm) debe quedar al menos 80 mm por encima de "
                               f"la {self.top_label.lower()} ({H:g} mm) para poder agarrarla.")
                if asa.B > d["a"]:
                    model.note("error", "DFM-ASA-ANCHO", f"El perfil del asa {asa.code} es más ancho que el montante.")
            c = catalog.component(ctx["RUEDA"])
            ctx.set_derived("DIAMETRO_RUEDA", c["wheel_d"], "mm", "Diámetro de rueda", ["RUEDA"])
        return d

    def _extras(self, model, ctx, d, legs, corners):
        if d["asa_mode"] == "ninguna":
            return
        v = model.params.values
        asa, a, c, L, W = d["asa"], d["a"], d["c"], v["LONGITUD"], v["ANCHURA"]
        weld = self._make_welder(model, d)
        two = d["asa_mode"] == "dos_extremos"
        handles = [("EST.ASA", c + a / 2, "DI", "TI", " izquierda" if two else "")]
        if two:
            handles.append(("EST.ASA_D", L - c - a / 2, "DD", "TD", " derecha"))
        with ctx.feature("F16", "Asa de empuje soldada"):
            ctx.uses("PERFIL_ASA", "ALTURA_ASA", "ASA_EMPUJE", "ANCHURA", "RETRANQUEO", "PERFIL_PATA",
                     "MATERIAL_ESTRUCTURAL", "ACABADO")
            part = ProfilePart("asa", f"Asa de empuje {asa.code}", asa.code, W - 2 * c - 2 * a, v["MATERIAL_ESTRUCTURAL"],
                               v["ACABADO"])
            zc = d["z_asa"] - asa.H / 2
            for iid, x, l0, l1, side in handles:
                p0, p1 = np.array([x, c + a, zc]), np.array([x, W - c - a, zc])
                model.add(iid, f"Asa de empuje{side}", part, G.axis_frame(p0, p1, (0, 0, 1)), "EST", axis=(p0, p1),
                          up=np.array([0, 0, 1.0]), structural=True)
                weld(f"J.{iid}.0", iid, 0, legs[l0], asa, "Asa a montante")
                weld(f"J.{iid}.1", iid, 1, legs[l1], asa, "Asa a montante")

    def _structure(self, model, d, legs):
        st = super()._structure(model, d, legs)
        mode = d["asa_mode"]
        st["product_word"] = "carro" if mode != "ninguna" else "mesa"
        brake = ("Las ruedas con freno van en el extremo del asa." if mode == "un_extremo" else
                 "Las ruedas con freno van en el extremo izquierdo (X = 0).")
        notch = {"un_extremo": ", con las escotaduras alrededor de los montantes del asa,",
                 "dos_extremos": ", con las escotaduras alrededor de los montantes de las asas,", "ninguna": ""}[mode]
        st["assembly_texts"] = {
            "RUE": "Roscar las ruedas de espiga en las tuercas soldadas de las placas base hasta el tope y bloquearlas "
                   f"con su contratuerca. {brake}",
            "BAL": "Colocar la balda sobre el bastidor inferior, con las escotaduras alrededor de las patas, y fijarla con "
                   "tornillos ISO 7380 M6 (8 N·m).",
            "ENC": f"Colocar la encimera sobre el bastidor superior{notch} y fijarla con tornillos ISO 7380 M6 (8 N·m)."}
        return st

    def _extra_dims(self, model, d):
        v = model.params.values
        H = v["ALTURA"]
        zmax = max(d["z_asa"] or 0.0, H + d["peto"])
        levels = [("ALTURA_BALDA", "BAL.BANDEJA")] if d["shelf"] else []
        if zmax > H + 1e-9:       # el asa o el peto sobresalen: la altura de trabajo se acota aparte
            levels.append(("ALTURA_ENCIMERA", "ENC.BANDEJA", H))
        levels += self._peto_level(d, H)
        zs = [0.0] + ([d["z_shelf"]] if d["shelf"] else []) + [H] + ([H + d["peto"]] if d["peto"] > 0 else [])
        model.dims["ALTURA_ENCIMERA"] = H
        if d["z_asa"] is not None:
            model.dims["ALTURA_ASA"] = d["z_asa"]
        model.dims.update({
            "envelope": {"ids": ["ENC.BANDEJA"] + [f"EST.PATA.{k}" for k in d["asa_corners"]], "dx": v["LONGITUD"],
                         "dy": v["ANCHURA"], "zmax": zmax, "names": ("LONGITUD", "ANCHURA")},
            "levels": levels,
            "drawing_expected": {f"DIST_NIVEL_{k + 1}": zs[k + 1] - zs[k] for k in range(len(levels))},
        })
