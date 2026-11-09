"""Familia A: escalón de acceso con meseta (EN ISO 14122-3 / EN ISO 14122-2).

Uno a tres peldaños de chapa de acero soldada sobre bastidores de tubo, el último de ellos una meseta donde el operario
trabaja de pie, para subir a una máquina, una línea o un mostrador alto. Altura de la meseta hasta 500 mm: por encima,
EN ISO 14122-3 exige barandilla (no incluida).

Sistema de coordenadas: X = anchura de los peldaños, Y = fondo (Y=0 borde delantero del primer peldaño), Z = altura.

Reglas constructivas:

* Una línea de patas (izquierda y derecha) bajo el borde delantero de cada peldaño y otra al fondo de la meseta; cada
  línea sube hasta el bastidor del peldaño que sostiene por delante. Todas las patas llevan placa base, tuerca soldada y
  pie nivelador.
* Bastidor de cada peldaño: larguero delantero entre las patas de su borde, larguero trasero soldado a la cara de las
  patas del peldaño siguiente (o entre las patas traseras en la meseta), travesaños laterales enrasados y, en la meseta,
  travesaños intermedios si la anchura lo pide. La chapa de cada peldaño apoya en todo su contorno.
* Contrahuella h = altura / peldaños entre 150 y 250 mm y huella g con 2h + g entre 600 y 660 mm (EN ISO 14122-3).

Cargas (EN ISO 14122-2/-3): repartida de 2 kN/m² sobre cada peldaño y la meseta, y concentrada de 1,5 kN sobre
100 × 100 mm en el centro de cada peldaño (200 × 200 mm en la meseta); flecha de la chapa L/200.
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..core.model import Joint, PlatePart, ProductModel, ProfilePart, StandardPart
from ..core.params import AUTO, ParamContext, ParameterSet, ParamError, ParamSpec
from .base import fabrication_specs, register
from .mesa_industrial import ALLP, ANCHORS, CANDIDATES as MESA_CANDIDATES, FEET, SHS, MesaIndustrial, add_anchors, \
    weld_nut_code
from .mesa_soldadura import PLATE_CORNER_R, STITCH_L, STITCH_PITCH

STEEL = ["S235JRH", "S275J0H", "S355J2H"]          # la chapa de acero se suelda al bastidor: estructura de acero
DECK_MATERIALS = ["S235JR", "S275JR", "S355JR"]
DECK_THICKNESSES = [3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
RISER_MIN, RISER_MAX, RISER_PREF = 150.0, 250.0, 190.0   # EN ISO 14122-3: contrahuella h
STEP_RULE = (600.0, 660.0)                               # EN ISO 14122-3: 2h + g
STEP_RULE_TARGET = 630.0
GOING_MIN, GOING_MAX = 200.0, 350.0
MAX_HEIGHT = 500.0                                       # por encima, barandilla obligatoria (no incluida)
SERVICE_LOAD_KN_M2 = 2.0
POINT_LOAD_KG = 153.0                                    # 1,5 kN
TREAD_PATCH, LANDING_PATCH = 100.0, 200.0
CANDIDATES = {k: v for k, v in MESA_CANDIDATES.items() if k in ("PERFIL_PATA", "PERFIL_LARGUERO", "PERFIL_TRAVESANO")}
CONSTRUCTIVE_DEFAULTS = {"PERFIL_PATA": "SHS 40x40x2", "PERFIL_LARGUERO": "RHS 40x20x2", "PERFIL_TRAVESANO": "RHS 40x20x2",
                         "ESPESOR_PLACA": 4.0, "PIE_NIVELADOR": "PIE_NIV_M12_D60"}


def risers(H: float, n) -> int:
    """Número de peldaños (contando la meseta): el indicado o, en 'auto', el que da la contrahuella admisible más
    próxima a 190 mm (o la más próxima al intervalo de EN ISO 14122-3 si ninguna cabe)."""
    if n not in (None, AUTO):
        return int(n)
    ok = [k for k in (1, 2, 3) if RISER_MIN - 1e-9 <= H / k <= RISER_MAX + 1e-9]
    if ok:
        return min(ok, key=lambda k: abs(H / k - RISER_PREF))
    return min((1, 2, 3), key=lambda k: max(RISER_MIN - H / k, H / k - RISER_MAX))


def going(h: float, g) -> float:
    """Huella: la indicada o, en 'auto', la que da 2h + g = 630 mm, redondeada a 5 mm y dentro de 200–350 mm."""
    if g not in (None, AUTO):
        return float(g)
    return min(max(5.0 * round((STEP_RULE_TARGET - 2 * h) / 5.0), GOING_MIN), GOING_MAX)


@register
class Escalon(MesaIndustrial):
    id = "escalon"
    name = "Escalón de acceso"
    prefix = "EA"
    category = "A"
    description = ("Escalón de acceso de uno a tres peldaños con meseta (hasta 500 mm), de chapa de acero soldada sobre "
                   "bastidores de tubo y pies niveladores; contrahuella, huella y cargas de EN ISO 14122-2/-3.")
    configurations = ["Peldaño de acceso", "Escalón con meseta", "Acceso a máquina"]
    verification_inputs = ["CARGA_REPARTIDA"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    leg_param = "PERFIL_PATA"
    frame_params = ("PERFIL_LARGUERO", "PERFIL_TRAVESANO")
    auto_in_construct = ("NUMERO_PELDANOS", "HUELLA", "NUMERO_TRAVESANOS", "TACO_ANCLAJE")

    def leg_fits(self, v) -> bool:
        return True       # los anchos se igualan con frame_params (ningún larguero ni travesaño más ancho que la pata)

    def sway_beam_param(self, axis: int) -> str:
        return "PERFIL_LARGUERO" if axis == 0 else "PERFIL_TRAVESANO"

    def param_for_role(self, role):
        if role == "pata":
            return "PERFIL_PATA"
        if role.startswith("larguero"):
            return "PERFIL_LARGUERO"
        if role.startswith("travesano"):
            return "PERFIL_TRAVESANO"
        return None

    def default_loads(self, v):
        return {}

    def vertical_load_present(self, v):
        return bool(v.get("CARGA_REPARTIDA") or v.get("CARGA_PUNTUAL"))

    def plate_targets(self, v):
        if not self.vertical_load_present(v):
            return []
        avail = set(catalog.sheet_thicknesses(v["MATERIAL_PLACA"]))
        common = {"t_param": "ESPESOR_PLACA", "load_param": "CARGA_REPARTIDA", "trv_param": "PERFIL_TRAVESANO",
                  "min_t_by_use": False, "mat_param": "MATERIAL_PLACA",
                  "t_options": [t for t in DECK_THICKNESSES if t in avail], "t_max": DECK_THICKNESSES[-1]}
        n = risers(v["ALTURA"], v.get("NUMERO_PELDANOS"))
        out = [{**common, "surface": f"peldano_{k}", "n_param": None, "label": f"el peldaño {k}"} for k in range(1, n)]
        out.append({**common, "surface": "meseta", "n_param": "NUMERO_TRAVESANOS", "label": "la meseta"})
        return out

    def sheet_defaults_without_load(self, v):
        return {} if self.vertical_load_present(v) else {"ESPESOR_PLACA": CONSTRUCTIVE_DEFAULTS["ESPESOR_PLACA"]}

    # ------------------------------------------------------------------ parámetros
    def param_specs(self) -> list[ParamSpec]:
        P = ParamSpec
        return [
            P("ANCHURA", "Anchura de los peldaños", "float", 800.0, "mm", "dimensiones", 500, 1500,
              help="EN ISO 14122-3: 600 mm como mínimo (800 mm recomendado)."),
            P("ALTURA", "Altura de la meseta (superficie superior)", "float", 400.0, "mm", "dimensiones", 150,
              MAX_HEIGHT, help="Hasta 500 mm: por encima, EN ISO 14122-3 exige barandilla."),
            P("NUMERO_PELDANOS", "Número de peldaños (contando la meseta)", "int", AUTO, "ud", "dimensiones", 1, 3,
              allow_auto=True, help="'auto': el que da una contrahuella entre 150 y 250 mm, lo más próxima a 190 mm."),
            P("HUELLA", "Huella de los peldaños", "float", AUTO, "mm", "dimensiones", GOING_MIN, GOING_MAX,
              allow_auto=True, help="'auto': la que cumple 2h + g = 630 mm (EN ISO 14122-3: entre 600 y 660 mm)."),
            P("FONDO_MESETA", "Fondo de la meseta", "float", 600.0, "mm", "dimensiones", 300, 1200,
              help="Superficie de trabajo del operario en lo alto del escalón."),
            P("MATERIAL_ESTRUCTURAL", "Material de la estructura", "choice", "S235JRH", None, "materiales",
              choices=STEEL),
            P("MATERIAL_PLACA", "Material de la chapa de los peldaños", "choice", "S235JR", None, "materiales",
              choices=DECK_MATERIALS),
            P("ESPESOR_PLACA", "Espesor de la chapa de los peldaños", "float", AUTO, "mm", "materiales", 3, 10,
              allow_auto=True, help="'auto': el menor que verifica la carga repartida y la concentrada en todos los "
                                    "peldaños y la meseta."),
            P("ESPESOR_PLACA_BASE", "Espesor de placa base", "float", 5.0, "mm", "materiales", 3, 12),
            P("ACABADO", "Acabado", "choice", "RAL7035_POLVO", None, "materiales", choices=list(catalog.finishes())),
            P("PERFIL_PATA", "Perfil de patas", "choice", AUTO, None, "construccion", choices=SHS, allow_auto=True),
            P("PERFIL_LARGUERO", "Perfil de largueros (delanteros y traseros)", "choice", AUTO, None, "construccion",
              choices=ALLP, allow_auto=True),
            P("PERFIL_TRAVESANO", "Perfil de travesaños", "choice", AUTO, None, "construccion", choices=ALLP,
              allow_auto=True),
            P("NUMERO_TRAVESANOS", "Travesaños intermedios de la meseta", "int", AUTO, "ud", "construccion", 0, 10,
              allow_auto=True),
            P("SEPARACION_MAX_APOYOS", "Separación máxima entre apoyos de chapa (regla constructiva)", "float", 600.0,
              "mm", "construccion", 150, 1200, advanced=True),
            P("TOLERANCIAS", "Tolerancias generales", "choice", "ISO 2768-mK", None, "construccion",
              choices=["ISO 2768-mK", "ISO 2768-fH", "ISO 2768-cL"], advanced=True),
            P("CLASE_EJECUCION", "Clase de ejecución (EN 1090-2)", "choice", "EXC1", None, "construccion",
              choices=["EXC1", "EXC2"], advanced=True),
            P("TIPO_APOYO", "Tipo de apoyo", "choice", "pie_nivelador", None, "accesorios", choices=["pie_nivelador"]),
            P("PIE_NIVELADOR", "Pie nivelador", "choice", AUTO, None, "accesorios", choices=FEET, allow_auto=True,
              help="'auto': el de menor capacidad nominal que soporta la reacción de servicio calculada."),
            P("CARGA_REPARTIDA", "Carga repartida sobre peldaños y meseta", "float", SERVICE_LOAD_KN_M2, "kN/m²",
              "cargas", 0, 10, help="EN ISO 14122-2: no menos de 2 kN/m²."),
            P("CARGA_PUNTUAL", "Carga concentrada en cada peldaño", "float", POINT_LOAD_KG, "kg", "cargas", 0, 500,
              help="EN ISO 14122-3: 1,5 kN (153 kg) sobre 100 × 100 mm en los peldaños y 200 × 200 mm en la meseta."),
            P("CARGA_HORIZONTAL", "Empuje horizontal en el canto de la meseta", "float", 150.0, "N", "cargas", 0, 3000),
            P("ANCLAJE", "Anclaje", "choice", "ninguno", None, "cargas", choices=["ninguno", "al_suelo"],
              help="'ninguno' por defecto: si el escalón vacío volcara con el empuje, se ancla automáticamente."),
            P("TACO_ANCLAJE", "Taco de anclaje", "choice", AUTO, None, "cargas", choices=ANCHORS, allow_auto=True,
              help="'auto': el de menor capacidad que resiste la tracción de cálculo (sólo con anclaje al suelo)."),
            P("ENTORNO", "Entorno", "choice", "interior_seco", None, "cargas",
              choices=["interior_seco", "interior_humedo", "exterior"]),
            P("TIPO_SUELO", "Tipo de suelo", "choice", "nivelado", None, "cargas", choices=["nivelado", "irregular"]),
        ] + fabrication_specs()

    def templates(self):
        return [
            {"id": "EA-800-400", "name": "Escalón de dos peldaños 800 mm, meseta a 400 mm", "family": self.id,
             "values": {"ANCHURA": 800.0, "ALTURA": 400.0, "FONDO_MESETA": 600.0}},
            {"id": "EA-600-250", "name": "Peldaño de acceso 600 × 400 mm a 250 mm", "family": self.id,
             "values": {"ANCHURA": 600.0, "ALTURA": 250.0, "FONDO_MESETA": 400.0}},
            {"id": "EA-1000-500", "name": "Acceso a máquina de tres peldaños 1.000 mm, meseta de 800 mm a 500 mm",
             "family": self.id,
             "values": {"ANCHURA": 1000.0, "ALTURA": 500.0, "FONDO_MESETA": 800.0, "ANCLAJE": "al_suelo"}},
            {"id": "EA-1200-450-GALV", "name": "Escalón ancho galvanizado 1.200 mm a 450 mm (exterior)",
             "family": self.id,
             "values": {"ANCHURA": 1200.0, "ALTURA": 450.0, "FONDO_MESETA": 1000.0, "ACABADO": "GALVANIZADO",
                        "ENTORNO": "exterior", "ANCLAJE": "al_suelo"}},
        ]

    # ------------------------------------------------------------------ construcción
    def construct(self, ps: ParameterSet) -> ProductModel:
        for k, v in ps.values.items():
            if v == AUTO and k not in self.auto_in_construct:
                raise ValueError(f"Parámetro sin resolver: {k}")
        ctx = ParamContext(ps)
        W, H = ps.values["ANCHURA"], ps.values["ALTURA"]
        d = self._derive_step(ctx, None)
        n = d["n"]
        model = ProductModel(self.id, self.name, f"{self.prefix}{W:.0f}-{H:.0f}-{n}", ps, ctx)
        model.requested = ps
        for note in d.pop("notes"):
            model.note(*note)
        model.rule_fixes.update(d.pop("rule_fixes"))
        mat_s, fin = ps.values["MATERIAL_ESTRUCTURAL"], ps.values["ACABADO"]
        leg, rail, trv, a, t = d["leg"], d["rail"], d["trv"], d["a"], d["t"]
        model.add_subassembly("EST", "Estructura soldada", welded=True, step=1)
        g = self.support_group[0]
        model.add_subassembly(g, self.support_group[1], explode=(0, 0, -160), step=2)
        model.add_subassembly("PEL", "Chapas de peldaños y meseta", explode=(0, 0, 200), step=3)
        foot = catalog.component(ps.values[self.support_param])
        thread = float(foot["thread"][1:])
        nut_code = weld_nut_code(thread, mat_s)
        weld = self._make_welder(model, d)
        wa = d["weld_a"]
        legs: dict[str, str] = {}
        corners: dict[str, tuple[float, float]] = {}
        cname: dict[str, str] = {}
        Y = d["Y"]
        plate_mat = "S235JR"
        with ctx.feature("F10", "Estructura soldada"):
            with ctx.feature("F11", "Patas, placas base y tuercas"):
                ctx.uses("ALTURA", "NUMERO_PELDANOS", "HUELLA", "FONDO_MESETA", "ANCHURA", "PERFIL_PATA",
                         "ESPESOR_PLACA_BASE", self.support_param, "MATERIAL_ESTRUCTURAL", "ACABADO")
                bplate = PlatePart("placa_base", f"Placa base {a:.0f}x{a:.0f}x{d['tp']:g}", a, a, d["tp"], plate_mat,
                                   fin, corner_r=min(3.0, a / 10), holes=((a / 2, a / 2, thread + 1.0),))
                nut = StandardPart("tuerca_soldar", nut_code)
                for j in range(n + 1):
                    ztop = d["leg_top"][j]
                    lname = "delantera" if j == 0 else "trasera" if j == n else f"intermedia {j}"
                    part = ProfilePart("pata", f"Pata {leg.code}", leg.code, round(ztop - d["z_leg0"], 3), mat_s, fin)
                    for s, x in (("I", a / 2), ("D", W - a / 2)):
                        k = f"{j}{s}"
                        iid = f"EST.PATA.{k}"
                        p0, p1 = np.array([x, Y[j], d["z_leg0"]]), np.array([x, Y[j], ztop])
                        side = "izquierda" if s == "I" else "derecha"
                        model.add(iid, f"Pata {lname} {side}", part, G.axis_frame(p0, p1, (0, 1, 0)), "EST",
                                  axis=(p0, p1), up=np.array([0, 1.0, 0]), structural=True)
                        legs[k] = iid
                        corners[k] = (x, Y[j])
                        cname[k] = f"{lname} {side}"
                        model.add(f"EST.PLACA.{k}", f"Placa base {lname} {side}", bplate,
                                  G.translation(x - a / 2, Y[j] - a / 2, d["hn"]), "EST")
                        model.add(f"EST.TUERCA.{k}", f"Tuerca soldada {lname} {side}", nut,
                                  G.translation(x, Y[j], d["hn"] + d["tp"]), "EST")
                        model.add_joint(Joint(f"J.PLACA.{k}", "soldadura", (iid, f"EST.PLACA.{k}"),
                                              (x, Y[j], d["z_leg0"]), "Placa base a pata",
                                              weld={"type": "fillet", "a": wa(min(leg.t, d["tp"])), "all_around": True,
                                                    "process": "135 (MAG)",
                                                    "length": round(4 * a - (8 - 2 * math.pi) * leg.r_out, 1)}))
                        ns = float(catalog.component(nut_code)["s"])
                        model.add_joint(Joint(f"J.TUERCA.{k}", "soldadura", (f"EST.TUERCA.{k}", f"EST.PLACA.{k}"),
                                              (x, Y[j], d["hn"] + d["tp"]), "Tuerca de soldar a placa base",
                                              weld={"type": "fillet", "a": 2.0, "all_around": False,
                                                    "process": "135 (MAG)", "length": round(3 * ns / math.sqrt(3), 1),
                                                    "note": "3 cordones en caras alternas de la tuerca"}))
            for k in range(1, n + 1):
                lid = "SUP" if k == n else f"P{k}"
                with ctx.feature(f"F2{k}", "Bastidor de la meseta" if k == n else f"Bastidor del peldaño {k}"):
                    ctx.uses("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ANCHURA", "ALTURA", "NUMERO_PELDANOS", "HUELLA",
                             "FONDO_MESETA", "PERFIL_PATA", "ESPESOR_PLACA", "NUMERO_TRAVESANOS",
                             "SEPARACION_MAX_APOYOS", "MATERIAL_ESTRUCTURAL")
                    self._step_frame(model, d, k, lid, legs, weld, mat_s, fin)
        with ctx.feature("F30", "Chapas de peldaños y meseta"):
            ctx.uses("ANCHURA", "ALTURA", "NUMERO_PELDANOS", "HUELLA", "FONDO_MESETA", "ESPESOR_PLACA", "MATERIAL_PLACA",
                     "ACABADO", "PERFIL_PATA")
            for k in range(1, n + 1):
                y0 = Y[k - 1] - a / 2
                y1 = Y[k] - a / 2 if k < n else Y[n] + a / 2
                land = k == n
                part = PlatePart("chapa_meseta" if land else "chapa_peldano",
                                 f"Chapa de {'meseta' if land else 'peldaño'} {W:.0f}x{y1 - y0:.0f}x{t:g}", W, y1 - y0, t,
                                 ps.values["MATERIAL_PLACA"], fin, corner_r=PLATE_CORNER_R)
                pid = "PEL.MESETA" if land else f"PEL.PELDANO.{k}"
                model.add(pid, "Meseta" if land else f"Peldaño {k}", part, G.translation(0, y0, k * d["h"] - t), "PEL")
                self._plate_welds(model, d, pid, "SUP" if land else f"P{k}", t)
        with ctx.feature("F40", self.support_group[1]):
            ctx.uses(self.support_param, "ANCHURA", "NUMERO_PELDANOS", "HUELLA", "FONDO_MESETA")
            for k, (x, y) in corners.items():
                fpart, fname = self._support_part(k, ps)
                model.add(f"{g}.PIE.{k}", f"{fname} {cname[k]}", fpart, G.translation(x, y, 0.0), g)
                model.add_joint(Joint(f"J.PIE.{k}", "roscada", (f"{g}.PIE.{k}", f"EST.TUERCA.{k}"), (x, y, d["hn"]),
                                      f"Pie roscado {foot['thread']} en tuerca soldada"))
            add_anchors(model, ps, corners, cname, g)
        model.structure = self._step_structure(model, d, legs)
        q, Pk = ps.values["CARGA_REPARTIDA"], ps.values["CARGA_PUNTUAL"]
        area = W * d["D"] * 1e-6
        plates = [i.id for i in model.instances if i.group == "PEL"]
        hs = [k * d["h"] for k in range(1, n + 1)]
        model.dims = {
            "ANCHURA": W, "ALTURA": H, "FONDO": d["D"],
            "envelope": {"ids": list(legs.values()) + plates, "dx": W, "dy": d["D"], "zmax": H,
                         "names": ("ANCHURA", "FONDO")},
            "levels": [(f"PELDANO_{k}", pid, z) for k, (pid, z) in enumerate(zip(plates, hs), start=1)],
            "drawing_expected": {**{f"DIST_NIVEL_{k}": d["h"] for k in range(1, n + 1)},
                                 **{f"HUELLA_{k}": d["g"] for k in range(1, n)}, "FONDO_MESETA": d["P"]},
            "structure_profile": [(Y[k - 1] - a / 2, Y[k] - a / 2, f"HUELLA_{k}") for k in range(1, n)]
                                 + [(Y[n - 1] - a / 2, Y[n] + a / 2, "FONDO_MESETA")],
            "structure_notes": ["Estructura soldada (subconjunto EST).",
                                f"Clase de ejecución {ps.values['CLASE_EJECUCION']} según EN 1090-2.",
                                "Cotas a caras exteriores de perfil.",
                                f"Contrahuella {d['h']:.1f} mm y huella {d['g']:g} mm (EN ISO 14122-3).",
                                "Planitud de los apoyos de chapa: EN ISO 13920 clase F.",
                                "Detalle de uniones soldadas: plano 05.",
                                "Longitudes de corte y mecanizados: plano 02B."],
            "load_text": (f"Carga repartida de proyecto: {q:g} kN/m² ({q * area / 9.81e-3:.0f} kg sobre {area:.2f} m²) y "
                          f"{Pk:g} kg concentrados en cada peldaño" if q or Pk else "Sin carga de uso"),
        }
        model.number_parts()
        return model

    # ------------------------------------------------------------------ derivados
    def _derive_step(self, ctx: ParamContext, _model) -> dict:
        v = ctx.params.values
        notes: list[tuple] = []
        fixes: dict = {}
        d: dict = {"notes": notes, "rule_fixes": fixes}
        with ctx.feature("F00", "Parámetros derivados y reglas constructivas"):
            leg = catalog.profile(ctx["PERFIL_PATA"])
            rail = catalog.profile(ctx["PERFIL_LARGUERO"])
            trv = catalog.profile(ctx["PERFIL_TRAVESANO"])
            if leg.B != leg.H:
                raise ValueError("Las patas deben ser de tubo cuadrado")
            a = leg.B
            foot = catalog.component(ctx[self.support_param])
            hn, tp = float(foot["nominal_height"]), ctx["ESPESOR_PLACA_BASE"]
            W, H, P = ctx["ANCHURA"], ctx["ALTURA"], ctx["FONDO_MESETA"]
            t = ctx.derive("ESP_PLACA", lambda p: p["ESPESOR_PLACA"], "mm", "Espesor de la chapa de los peldaños")
            n = ctx.derive("N_PELDANOS", lambda p: risers(p["ALTURA"], p["NUMERO_PELDANOS"]), "ud",
                           "Número de peldaños (contando la meseta)")
            h = ctx.derive("CONTRAHUELLA", lambda p: p["ALTURA"] / p["N_PELDANOS"], "mm", "Contrahuella")
            g = ctx.derive("HUELLA_PELDANO", lambda p: going(p["CONTRAHUELLA"], p["HUELLA"]), "mm", "Huella")
            sp = self.support_param
            z_leg0 = ctx.derive("COTA_INICIO_PATA", lambda p: float(catalog.component(p[sp])["nominal_height"])
                                + p["ESPESOR_PLACA_BASE"], "mm", "Cota inicio de pata")
            if not RISER_MIN - 1e-9 <= h <= RISER_MAX + 1e-9:
                notes.append(("advertencia", "NORMA-14122-CONTRAHUELLA",
                              f"Contrahuella de {h:.0f} mm fuera del intervalo de 150 a 250 mm de EN ISO 14122-3: cambie "
                              "el número de peldaños ('auto' elige el adecuado) o la altura."))
            if n > 1 and not STEP_RULE[0] - 1e-9 <= 2 * h + g <= STEP_RULE[1] + 1e-9:
                notes.append(("advertencia", "NORMA-14122-PASO",
                              f"2h + g = {2 * h + g:.0f} mm fuera de 600–660 mm (EN ISO 14122-3): la huella cómoda con "
                              f"esta contrahuella es {going(h, None):g} mm ('auto')."))
            if W < 600:
                notes.append(("advertencia", "NORMA-14122-ANCHURA", f"Anchura de {W:g} mm: EN ISO 14122-3 pide al menos "
                              "600 mm (800 mm recomendado)."))
            if P < g:
                raise ParamError(f"FONDO_MESETA de {P:g} mm menor que la huella de {g:g} mm.")
            if rail.B > a or trv.B > a:
                notes.append(("error", "DFM-ANCHO-BASTIDOR", "El ancho de largueros/travesaños supera el de la pata: no "
                              "pueden enrasarse con su cara exterior."))
            frame_h = max(rail.H, trv.H)
            if h - t - frame_h < z_leg0 + 10:
                notes.append(("error", "GEO-ESCALON-BAJO", f"Contrahuella de {h:.0f} mm insuficiente para el bastidor "
                              f"de {frame_h:g} mm de canto sobre el pie y la placa base (bajo el primer peldaño): "
                              "menos peldaños, pies o perfiles más bajos."))
                if n > 1:
                    fixes["NUMERO_PELDANOS"] = (n - 1, f"{n - 1} peldaño(s) (regla de diseño): con {n} no cabía el "
                                                       "bastidor del primer peldaño sobre los apoyos.")
            if h - t - rail.H < 0:
                notes.append(("error", "GEO-PELDANO-SOLAPE", "El larguero delantero de un peldaño no cabe sobre el "
                              "peldaño anterior: perfiles de menos canto."))
            # líneas de patas: una bajo el borde delantero de cada peldaño y otra al fondo de la meseta
            Y = [a / 2 + k * g for k in range(n)] + [(n - 1) * g + P - a / 2]
            if Y[n] - Y[n - 1] < a + 2 * trv.B:
                raise ParamError(f"FONDO_MESETA de {P:g} mm demasiado corto para las patas y el bastidor.")
            leg_top = [(j + 1) * h - t for j in range(n)] + [n * h - t]
            D = (n - 1) * g + P
            ctx.set_derived("FONDO_TOTAL", D, "mm", "Fondo total del escalón", ["NUMERO_PELDANOS", "HUELLA",
                                                                                 "FONDO_MESETA", "ALTURA"])
            # travesaños intermedios de la meseta
            x_l, x_r = trv.B / 2, W - trv.B / 2
            n_int = ctx["NUMERO_TRAVESANOS"]
            if n_int == AUTO:
                n_int = max(0, math.ceil((x_r - x_l) / ctx["SEPARACION_MAX_APOYOS"]) - 1)
            ctx.set_derived("N_TRAVESANOS_MESETA", n_int, "ud", "Travesaños intermedios de la meseta",
                            ["NUMERO_TRAVESANOS", "SEPARACION_MAX_APOYOS", "ANCHURA"])
            q = v.get("CARGA_REPARTIDA")
            if q is not None and q < SERVICE_LOAD_KN_M2 - 1e-9:
                notes.append(("advertencia", "NORMA-14122-CARGA", f"Carga repartida de {q:g} kN/m², inferior a la de "
                              f"servicio de {SERVICE_LOAD_KN_M2:g} kN/m² de EN ISO 14122-2."))
            Pk = v.get("CARGA_PUNTUAL")
            if Pk is not None and Pk < POINT_LOAD_KG - 1e-9:
                notes.append(("advertencia", "NORMA-14122-PUNTUAL", f"Carga concentrada de {Pk:g} kg, inferior a la de "
                              f"1,5 kN ({POINT_LOAD_KG:g} kg) de EN ISO 14122-3."))
            notes.append(("advertencia", "ERG-ANTIDESLIZANTE", "Chapa lisa: EN ISO 14122-2/-3 exige peldaños "
                          "antideslizantes; prever chapa lagrimada, recubrimiento antideslizante o nariz de peldaño "
                          "contrastada (no modelado)."))
            d.update(leg=leg, rail=rail, trv=trv, a=a, hn=hn, tp=tp, t=t, n=n, h=h, g=g, P=P, D=D, W=W, H=H, Y=Y,
                     z_leg0=z_leg0, leg_top=leg_top, x_l=x_l, x_r=x_r, n_int=n_int)
            d["weld_a"] = lambda tmin: 3.0 if tmin >= 3 else float(tmin)
        return d

    def _step_frame(self, model, d, k, lid, legs, weld, mat, fin):
        """Bastidor del peldaño k (k = n: meseta): largueros delantero y trasero, travesaños laterales y, en la meseta,
        intermedios."""
        n, a, W, Y = d["n"], d["a"], d["W"], d["Y"]
        rail, trv = d["rail"], d["trv"]
        land = k == n
        lab = "de la meseta" if land else f"del peldaño {k}"
        zt = k * d["h"] - d["t"]
        zl, ze = zt - rail.H / 2, zt - trv.H / 2
        role = "sup" if land else "pel"
        # larguero delantero, entre las patas del borde del peldaño y enrasado con su cara delantera
        yf = Y[k - 1] - a / 2 + rail.B / 2
        fpart = ProfilePart(f"larguero_{role}", f"Larguero {rail.code}", rail.code, W - 2 * a, mat, fin)
        fid = f"EST.LAR_{lid}.D"
        p0, p1 = np.array([a, yf, zl]), np.array([W - a, yf, zl])
        model.add(fid, f"Larguero delantero {lab}", fpart, G.axis_frame(p0, p1, (0, 0, 1)), "EST", axis=(p0, p1),
                  up=np.array([0, 0, 1.0]), structural=True)
        weld(f"J.{fid}.0", fid, 0, legs[f"{k - 1}I"], rail, "Larguero a pata")
        weld(f"J.{fid}.1", fid, 1, legs[f"{k - 1}D"], rail, "Larguero a pata")
        # larguero trasero: en la meseta entre las patas traseras (enrasado detrás); en un peldaño, soldado a la cara
        # delantera de las patas del peldaño siguiente, a todo lo ancho
        rid = f"EST.LAR_{lid}.T"
        if land:
            yb = Y[n] + a / 2 - rail.B / 2
            p0, p1 = np.array([W - a, yb, zl]), np.array([a, yb, zl])
            rpart = fpart
        else:
            yb = Y[k] - a / 2 - rail.B / 2
            p0, p1 = np.array([W, yb, zl]), np.array([0.0, yb, zl])
            rpart = ProfilePart(f"larguero_{role}_t", f"Larguero trasero de peldaño {rail.code}", rail.code, W, mat, fin)
        model.add(rid, f"Larguero trasero {lab}", rpart, G.axis_frame(p0, p1, (0, 0, 1)), "EST", axis=(p0, p1),
                  up=np.array([0, 0, 1.0]), structural=True)
        weld(f"J.{rid}.0", rid, 0, legs[f"{k}D"], rail, "Larguero a pata" if land else "Larguero trasero a cara de pata")
        weld(f"J.{rid}.1", rid, 1, legs[f"{k}I"], rail, "Larguero a pata" if land else "Larguero trasero a cara de pata")
        # travesaños laterales, enrasados por fuera
        y0 = Y[k - 1] + a / 2
        y1 = Y[n] - a / 2 if land else yb - rail.B / 2
        tpart = ProfilePart(f"travesano_{role}", f"Travesaño {trv.code}", trv.code, round(y1 - y0, 3), mat, fin)
        end_ids = []
        for s, x in (("I", d["x_l"]), ("D", d["x_r"])):
            iid = f"EST.TRV_{lid}.{s}"
            p0, p1 = np.array([x, y0, ze]), np.array([x, y1, ze])
            model.add(iid, f"Travesaño {'izquierdo' if s == 'I' else 'derecho'} {lab}", tpart,
                      G.axis_frame(p0, p1, (0, 0, 1)), "EST", axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
            weld(f"J.{iid}.0", iid, 0, legs[f"{k - 1}{s}"], trv, "Travesaño a pata")
            weld(f"J.{iid}.1", iid, 1, legs[f"{k}{s}"] if land else rid, trv,
                 "Travesaño a pata" if land else "Travesaño a larguero trasero")
            end_ids.append(iid)
        int_ids, xs = [], []
        if land and d["n_int"]:
            xs = [d["x_l"] + i * (d["x_r"] - d["x_l"]) / (d["n_int"] + 1) for i in range(1, d["n_int"] + 1)]
            yi0, yi1 = yf + rail.B / 2, yb - rail.B / 2
            ipart = ProfilePart("travesano_int", f"Travesaño intermedio {trv.code}", trv.code, round(yi1 - yi0, 3),
                                mat, fin)
            for m_, x in enumerate(xs, start=1):
                iid = f"EST.TRI_{lid}.{m_:02d}"
                p0, p1 = np.array([x, yi0, ze]), np.array([x, yi1, ze])
                model.add(iid, f"Travesaño intermedio de la meseta {m_}", ipart, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                          axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
                weld(f"J.{iid}.0", iid, 0, fid, trv, "Travesaño intermedio a larguero")
                weld(f"J.{iid}.1", iid, 1, rid, trv, "Travesaño intermedio a larguero")
                int_ids.append(iid)
            if (d["x_r"] - d["x_l"]) / (d["n_int"] + 1) - trv.B < 5.0:
                model.note("error", "DFM-TRAVESANOS", f"Los {d['n_int']} travesaños intermedios de la meseta no caben: "
                           "se solapan o no dejan 5 mm para soldar.")
        model.structure.setdefault("levels", {})[lid] = {
            "long": [fid, rid], "end": end_ids, "int": int_ids, "grid_x": [d["x_l"]] + xs + [d["x_r"]],
            "grid_y": [yf, yb], "z": k * d["h"]}

    def _plate_welds(self, model, d, pid, lid, t):
        """Cordones discontinuos chapa–bastidor en largueros y travesaños laterales."""
        lv = model.structure["levels"][lid]
        for mid in lv["long"] + lv["end"]:
            inst = model.instance(mid)
            p0, p1 = inst.axis
            Lm = float(np.linalg.norm(p1 - p0))
            nw = max(2, math.ceil(Lm / STITCH_PITCH))
            loc = tuple(float(x) for x in (p0 + p1) / 2 + np.array([0, 0, inst.part.profile.H / 2]))
            model.add_joint(Joint(f"J.PLACA_SOLD.{mid.split('.', 1)[1]}", "soldadura", (pid, mid), loc,
                                  "Chapa de peldaño a bastidor",
                                  weld={"type": "fillet", "a": d["weld_a"](min(t, inst.part.profile.t)),
                                        "all_around": False, "process": "135 (MAG)", "length": round(nw * STITCH_L, 1),
                                        "note": f"{nw} cordones de {STITCH_L:g} mm cada {STITCH_PITCH:g} mm, alternos"}))

    def _step_structure(self, model, d, legs):
        ps = model.params.values
        n, W = d["n"], d["W"]
        q = ps.get("CARGA_REPARTIDA")
        surfaces = []
        for k in range(1, n + 1):
            land = k == n
            pid = "PEL.MESETA" if land else f"PEL.PELDANO.{k}"
            part = model.instance(pid).part
            area = part.w * part.h
            surfaces.append({"id": "meseta" if land else f"peldano_{k}", "label": "Meseta" if land else f"Peldaño {k}",
                             "level": "SUP" if land else f"P{k}", "load_param": "CARGA_REPARTIDA",
                             "load_kg": None if q is None else round(q * area * 1e-6 / 9.81e-3, 1),
                             "sheet_instance": pid, "area_mm2": area, "point_load": True,
                             "patch_mm": d.get("patch", {}).get(k, LANDING_PATCH if land else TREAD_PATCH),
                             **({"count_param": "NUMERO_TRAVESANOS"} if land else {})})
        g = self.support_group[0]
        feet = [{"instance": f"{g}.PIE.{k}", "leg": legs[k], "point": tuple(model.instance(legs[k]).axis[0]),
                 "component": model.instance(f"{g}.PIE.{k}").part.code} for k in legs]
        H = ps["ALTURA"]
        top_legs = [legs[f"{j}{s}"] for j in (n - 1, n) for s in ("I", "D")]
        return {"levels": model.structure.get("levels", {}), "surfaces": surfaces, "supports": feet,
                "push_points": [{"member": lid, "z": H} for lid in top_legs],
                "push_label": "Empuje horizontal en el canto de la meseta (direcciones X e Y)",
                "push_where": "en la meseta", "worktop_height": H, "push_height": H, "sway_height": H,
                "leg_ids": list(legs.values()), "product_word": "escalón",
                "member_roles": {i.id: i.role for i in model.instances if i.structural},
                "dfm_weld_notes": [
                    ("SOL-DEFORMACION", "Estructura soldada", "Riesgo de distorsión en bastidores de pared delgada: "
                     "puntear cada bastidor en mesa plana con escuadras, soldar en secuencia simétrica alterna y "
                     "verificar el nivel de cada peldaño y la planitud de los apoyos de chapa (EN ISO 13920 clase F).")],
                "weld_sequence": ("Secuencia: 1) puntear las patas sobre sus placas base y soldar las tuercas; 2) bastidor "
                                  "de la meseta y de cada peldaño en mesa plana con escuadras; 3) unir los bastidores con "
                                  "las patas verificando el nivel y la contrahuella; 4) soldar alternando lados; 5) chapas "
                                  "con cordones discontinuos alternos; 6) enderezar y verificar planitud."),
                "assembly_texts": {
                    "EST": "Recepción de la estructura soldada y pintada. Colocarla frente a la máquina o el puesto, con "
                           "la meseta hacia el lado de trabajo.",
                    "APO": "Roscar los pies niveladores en las tuercas soldadas. Nivelar la meseta y los peldaños (nivel de "
                           "burbuja) y, si está previsto, anclar al suelo antes de usar el escalón.",
                    "PEL": "Colocar las chapas sobre cada bastidor, enrasadas con él, y soldarlas con cordones "
                           f"discontinuos de {STITCH_L:g} mm cada {STITCH_PITCH:g} mm, alternos. Aplicar el "
                           "recubrimiento antideslizante antes del montaje."},
                "assembly_notes": ["HERRAMIENTAS:", "· Llave fija 17/19 para contratuerca de pies", "· Nivel de burbuja",
                                   "· Equipo de soldadura MAG (chapas)", "",
                                   "USO:", "· Carga de proyecto: personas con herramienta de mano",
                                   "· Mantener los peldaños limpios y secos", "",
                                   "SEGURIDAD:", "Por encima de 500 mm EN ISO 14122-3 exige barandilla.",
                                   "Señalizar el borde de los peldaños (contraste)."]}
