"""Familia D: carro plataforma (plataforma baja sobre ruedas, con asa de empuje).

Plataforma de chapa plegada atornillada sobre un bastidor soldado de largueros y travesaños, apoyado en cuatro patas
cortas con placa base y tuerca soldada, en las que se roscan ruedas giratorias de espiga (con freno en el lado del
asa). Es el carro de taller sin balda ni reposapiés y con la superficie a poca altura: las dos patas de un extremo
(o de los dos) se prolongan como montantes del asa de empuje, unidos arriba por el asa soldada, y la plataforma
lleva escotaduras alrededor de ellos. Sin asa es una plataforma rodante.

Altura de la plataforma: la cara superior debe dejar sitio al bastidor sobre las placas base de las ruedas. Con la
altura por defecto, si la rueda que exige la carga no cabe, la plataforma se eleva (regla de diseño); un valor del
usuario no se cambia nunca, se informa el error GEO-PLATAFORMA-BAJA con la altura mínima.

La fuerza de maniobra (``CARGA_HORIZONTAL``) se aplica donde se empuja: en el asa (la del extremo izquierdo si hay
dos), tanto en el modelo de barras como en la comprobación de vuelco del carro vacío, y el desplome se limita a la
altura del asa. Sin asa se aplica en el plano de la plataforma.
"""
from __future__ import annotations

import math

from ..core.params import ParamError, ParamSpec
from .base import register
from .carro_taller import CANDIDATES as CT_CANDIDATES, CONSTRUCTIVE_DEFAULTS as CT_DEFAULTS, CarroTaller

#: parámetros de la mesa que no existen en la plataforma (balda inferior y reposapiés)
DROPPED = ("NUMERO_BALDAS", "ALTURA_BALDA", "CARGA_BALDA", "ESPESOR_BALDA", "PERFIL_BASTIDOR",
           "NUMERO_TRAVESANOS_BALDA", "ALA_BALDA", "REPOSAPIES", "ALTURA_REPOSAPIES", "PERFIL_REPOSAPIES")
CANDIDATES = {k: v for k, v in CT_CANDIDATES.items() if k not in DROPPED}
CONSTRUCTIVE_DEFAULTS = {k: v for k, v in CT_DEFAULTS.items() if k not in DROPPED}
FRAME_CLEARANCE = 20.0      # mm libres entre el bastidor y la placa base (como el bastidor de la balda)
H_RANGE = (200.0, 500.0)    # altura de la plataforma


@register
class CarroPlataforma(CarroTaller):
    id = "carro_plataforma"
    name = "Carro plataforma"
    prefix = "CP"
    category = "D"
    description = ("Plataforma baja de chapa plegada sobre bastidor soldado y cuatro ruedas giratorias de espiga roscada "
                   "(con freno en el lado del asa), con asa de empuje soldada en un extremo, en los dos o sin asa. "
                   "Transporte interno de cargas de hasta 1.000 kg, comprobado frente al vuelco sin anclaje.")
    configurations = ["Carro plataforma", "Carro plataforma de dos asas", "Plataforma rodante sin asa"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    frame_params = ("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "PERFIL_ASA")
    auto_in_construct = tuple(k for k in CarroTaller.auto_in_construct if k not in DROPPED)
    top_label = "Plataforma"
    min_clear_height = None          # no hay puesto de trabajo bajo la plataforma

    def use_load_kg_m2(self, v) -> float:
        return 250.0

    # ------------------------------------------------------------------ parámetros
    def param_specs(self):
        P = ParamSpec
        out = []
        for s in super().param_specs():
            if s.name in DROPPED:
                continue
            if s.name == "ALTURA":
                s = P("ALTURA", "Altura de la plataforma (cara superior)", "float", 300.0, "mm", "dimensiones",
                      *H_RANGE, help="Cota de la cara superior desde el suelo. Debe dejar sitio al bastidor sobre las "
                                     "placas base de las ruedas: con el valor por defecto se eleva si la rueda no cabe.")
            elif s.name == "ALTURA_ASA":
                s = P("ALTURA_ASA", "Altura del asa de empuje", "float", 950.0, "mm", "dimensiones", 800, 1150,
                      help="Cota superior del asa desde el suelo (sin efecto si el carro no lleva asa).")
            elif s.name == "ESPESOR_CHAPA":
                s = P(s.name, "Espesor de chapa de la plataforma", s.type, s.default, s.unit, s.group, s.min, s.max,
                      allow_auto=s.allow_auto, help=s.help)
            elif s.name == "ALA_ENCIMERA":
                s = P(s.name, "Altura de pestaña de la plataforma", s.type, s.default, s.unit, s.group, s.min, s.max)
            elif s.name == "PETO_TRASERO":
                s = P(s.name, "Peto trasero (altura sobre la plataforma)", s.type, s.default, s.unit, s.group, s.min,
                      s.max, help="Borde elevado en el lado largo trasero (Y = ANCHURA) que retiene la carga.")
            elif s.name == "CARGA_TOTAL":
                s = P("CARGA_TOTAL", "Carga distribuida sobre la plataforma", "float", None, "kg", "cargas", 0, 1000,
                      nullable=True)
            elif s.name == "CARGA_PUNTUAL":
                s = P("CARGA_PUNTUAL", "Carga puntual sobre la plataforma", "float", None, "kg", "cargas", 0, 1000,
                      nullable=True, help=s.help)
            elif s.name == "CARGA_HORIZONTAL":
                s = P("CARGA_HORIZONTAL", "Fuerza de maniobra en el asa", "float", 50.0, "N", "cargas", 0, 1000,
                      help="Empuje o tirón horizontal con las ruedas frenadas o bloqueadas por un obstáculo, en la "
                           "dirección más desfavorable. Se aplica en el asa (sin asa, en el plano de la plataforma) y "
                           "es la acción que puede volcar el carro vacío.")
            out.append(s)
        return out

    def templates(self):
        return [
            {"id": "CP-1000x600", "name": "Carro plataforma 1.000 × 600 mm (250 kg)", "family": self.id,
             "values": {"LONGITUD": 1000.0, "ANCHURA": 600.0, "ALTURA": 300.0, "ALTURA_ASA": 950.0,
                        "CARGA_TOTAL": 250.0, "CARGA_HORIZONTAL": 50.0, "ACABADO": "RAL5010_POLVO"}},
            {"id": "CP-1200x800-500", "name": "Carro plataforma 1.200 × 800 mm (500 kg)", "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 800.0, "ALTURA": 320.0, "ALTURA_ASA": 950.0,
                        "CARGA_TOTAL": 500.0, "USO": "trabajo_pesado", "CARGA_HORIZONTAL": 60.0,
                        "ACABADO": "RAL7016_POLVO"}},
            {"id": "CP-1600x800-2ASAS", "name": "Carro plataforma de dos asas 1.600 × 800 mm (600 kg)",
             "family": self.id,
             "values": {"LONGITUD": 1600.0, "ANCHURA": 800.0, "ALTURA": 350.0, "ALTURA_ASA": 950.0,
                        "ASA_EMPUJE": "dos_extremos", "CARGA_TOTAL": 600.0, "USO": "trabajo_pesado",
                        "CARGA_HORIZONTAL": 60.0, "ACABADO": "RAL7016_POLVO"}},
            {"id": "PR-1200x800", "name": "Plataforma rodante sin asa 1.200 × 800 mm (400 kg)", "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 800.0, "ALTURA": 300.0, "ASA_EMPUJE": "ninguna",
                        "CARGA_TOTAL": 400.0, "CARGA_HORIZONTAL": 100.0, "ACABADO": "RAL7035_POLVO"}},
            {"id": "CP-800x500-INOX", "name": "Carro plataforma inoxidable 800 × 500 mm (alimentario)",
             "family": self.id,
             "values": {"LONGITUD": 800.0, "ANCHURA": 500.0, "ALTURA": 300.0, "ALTURA_ASA": 900.0,
                        "CARGA_TOTAL": 120.0, "MATERIAL_ESTRUCTURAL": "1.4301", "MATERIAL_CHAPA": "1.4301",
                        "ACABADO": "INOX_SATINADO", "ENTORNO": "alimentario", "CARGA_HORIZONTAL": 30.0}},
        ]

    # ------------------------------------------------------------------ ganchos de la mesa
    def plate_targets(self, v):
        return [{**t, "label": "la plataforma"} for t in super().plate_targets(v)]

    def _has_shelf(self, ctx) -> bool:
        return False

    def _derive(self, ctx, model):
        d = super()._derive(ctx, model)
        H, hb = ctx["ALTURA"], max(d["rail"].H, d["trv"].H)
        if d["z_tf"] - hb < d["z_leg0"] + FRAME_CLEARANCE - 1e-9:
            z_min = math.ceil((d["z_leg0"] + FRAME_CLEARANCE + hb + d["t"]) / 5) * 5
            code = ctx[self.support_param]
            if d["z_tf"] - d["z_leg0"] < 1.0:      # pata de longitud nula o negativa: geometría imposible
                raise ParamError(f"La plataforma ({H:g} mm) queda por debajo de la placa base de la rueda {code} "
                                 f"({d['z_leg0']:g} mm desde el suelo): ALTURA de {z_min:g} mm como mínimo.")
            if ctx.params.sources.get("ALTURA") == "defecto" and z_min <= H_RANGE[1]:
                model.rule_fixes["ALTURA"] = (
                    float(z_min), f"Plataforma a {z_min:g} mm (regla de diseño): a la altura por defecto, {H:g} mm, el "
                                  f"bastidor de {hb:g} mm de canto no cabía sobre las placas base de la rueda {code}.")
            model.note("error", "GEO-PLATAFORMA-BAJA", f"La plataforma ({H:g} mm) está demasiado baja para la rueda "
                       f"{code} ({d['hn']:g} mm) y el bastidor de {hb:g} mm de canto: ALTURA de {z_min:g} mm como mínimo.")
        return d

    def _structure(self, model, d, legs):
        st = super()._structure(model, d, legs)
        mode = d["asa_mode"]
        st["product_word"] = "carro" if mode != "ninguna" else "plataforma"
        if mode != "ninguna":     # se empuja por el asa (la del extremo izquierdo si hay dos)
            st["push_points"] = [{"member": legs[k], "z": d["z_asa"] - d["asa"].H / 2} for k in ("DI", "TI")]
            st["push_height"] = st["sway_height"] = d["z_asa"]
            st["push_label"] = "Fuerza de maniobra en el asa (direcciones X e Y)"
            st["push_where"] = "en el asa"
        else:
            st["push_label"] = "Empuje horizontal en el plano de la plataforma (direcciones X e Y)"
            st["push_where"] = "en el plano de la plataforma"
        st["push_note"] = ("hipótesis por defecto de empuje o tirón con las ruedas frenadas o bloqueadas por un "
                           "obstáculo; debe confirmarse según el uso real del carro.")
        brake = ("Las ruedas con freno van en el extremo del asa." if mode == "un_extremo" else
                 "Las ruedas con freno van en el extremo izquierdo (X = 0).")
        notch = {"un_extremo": ", con las escotaduras alrededor de los montantes del asa,",
                 "dos_extremos": ", con las escotaduras alrededor de los montantes de las asas,", "ninguna": ""}[mode]
        st["assembly_texts"] = {
            "RUE": "Roscar las ruedas de espiga en las tuercas soldadas de las placas base hasta el tope y bloquearlas "
                   f"con su contratuerca. {brake}",
            "ENC": f"Colocar la plataforma sobre el bastidor{notch} y fijarla con tornillos ISO 7380 M6 (8 N·m)."}
        return st

    def _extra_dims(self, model, d):
        super()._extra_dims(model, d)
        lv = model.dims["levels"]
        # la cota de la superficie se nombra como plataforma (la de la mesa es ALTURA_ENCIMERA)
        model.dims["levels"] = [("ALTURA_PLATAFORMA", *x[1:]) if x[0] == "ALTURA_ENCIMERA" else x for x in lv]
        if "ALTURA_ENCIMERA" in model.dims:
            model.dims["ALTURA_PLATAFORMA"] = model.dims.pop("ALTURA_ENCIMERA")
