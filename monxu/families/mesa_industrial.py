"""Familia B: mesa industrial de estructura tubular soldada con encimera y balda de chapa plegada.

Sistema de coordenadas del conjunto: X = longitud, Y = anchura (fondo, Y=0 frente de trabajo),
Z = altura (Z=0 suelo). Todas las cotas en milímetros.

Reglas constructivas principales:

* La encimera es una bandeja de chapa con pestañas hacia abajo en los 4 bordes. La estructura
  queda retranqueada ``c = t + holgura`` respecto al canto exterior, de modo que las pestañas
  cubren el bastidor y se atornillan a él mediante tuercas remachables.
* Patas de tubo cuadrado en las esquinas, bastidor superior (largueros + travesaños extremos)
  enrasado con la cara exterior de las patas y travesaños intermedios que dividen el vano
  apoyando la chapa.
* Bastidor inferior opcional para la balda; la balda lleva escotaduras alrededor de las patas.
* Placas base soldadas con tuerca de soldar y pie nivelador roscado.
* Las uniones soldadas declaran la conectividad estructural utilizada por el modelo de cálculo.
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..cad.sheetmetal import EDGES, FlangeSpec, SheetMetalSpec
from ..core.model import Joint, PlatePart, ProductModel, ProfilePart, SheetPart, StandardPart
from ..core.params import AUTO, ParamContext, ParameterSet, ParamSpec
from .base import ProductFamily, fabrication_specs, register

SHS = [c for c, p in catalog.profiles().items() if p.type == "SHS"]
ALLP = list(catalog.profiles())
STRUCT_MATERIALS = [c for c, m in catalog._load("materials")["materials"].items() if "tubo" in m.get("forms", [])]
SHEET_MATERIALS = [c for c, m in catalog._load("materials")["materials"].items() if "chapa" in m.get("forms", [])]
FEET = [c for c, d in catalog.components().items() if d["category"] == "patas"]
ANCHORS = [c for c, d in catalog.components().items() if d["category"] == "anclajes"]
#: carga de uso por defecto sobre la superficie de trabajo según el uso previsto (kg/m²), cuando no se indica
USE_LOAD_KG_M2 = {"montaje_ligero": 100, "inspeccion": 100, "laboratorio": 100, "embalaje": 100, "montaje": 150,
                  "trabajo_pesado": 300}


def r10(x: float) -> float:
    """Carga redondeada a 10 kg (mínimo 10 kg), con el redondeo de Math.round (el motor web da el mismo valor)."""
    return float(max(10, math.floor(x / 10 + 0.5) * 10))


def add_anchors(model, ps, corners: dict, names: dict, group: str) -> None:
    """Tacos de anclaje al suelo (uno bajo cada pie, embebidos en el hormigón) cuando ANCLAJE = al_suelo."""
    v = ps.values if hasattr(ps, "values") else ps
    code = v.get("TACO_ANCLAJE")
    if v.get("ANCLAJE") != "al_suelo" or code in (None, AUTO):
        return
    c = catalog.component(code)
    part = StandardPart("anclaje", code)
    for k, (x, y) in corners.items():
        iid = f"{group}.ANC.{k}"
        model.add(iid, f"Taco de anclaje {names[k]}", part, G.translation(x, y, -float(c["embed_mm"])), group,
                  tags={"explode_extra": (0.0, 0.0, -60.0)})
        model.add_joint(Joint(f"J.ANC.{k}", "roscada", (iid, f"{group}.PIE.{k}"), (x, y, 0.0),
                              f"Taco de anclaje {c['thread']} en el suelo a través de la base del pie"))
NUT_SUFFIX = {"acero_carbono": "", "acero_inoxidable": "_A2", "aluminio": "_AL"}


def weld_nut_code(thread: float, mat_s: str) -> str:
    """Tuerca de soldar del mismo material que la estructura: una tuerca de acero no puede soldarse a una placa de
    aluminio, y en inoxidable sería una soldadura disimilar y un punto de corrosión."""
    return f"TUERCA_SOLDAR_M{thread:.0f}{NUT_SUFFIX.get(catalog.material(mat_s).family, '')}"

# Candidatos de dimensionado (orden creciente de masa por metro)
CANDIDATES = {
    "PERFIL_PATA": ["SHS 40x40x2", "SHS 40x40x3", "SHS 50x50x2", "SHS 50x50x3", "SHS 60x60x3", "SHS 70x70x3",
                    "SHS 80x80x3", "SHS 80x80x4", "SHS 90x90x4", "SHS 100x100x4", "SHS 100x100x5", "SHS 120x120x4", "SHS 120x120x5"],
    "PERFIL_LARGUERO": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2", "RHS 80x40x2", "RHS 60x40x3",
                        "RHS 80x40x3", "RHS 100x50x3", "RHS 100x50x4", "RHS 120x60x4"],
    "PERFIL_TRAVESANO": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2", "RHS 80x40x2"],
    "PERFIL_BASTIDOR": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2"],
    # hasta 40 mm de ancho (cabe en la pata más pequeña); los de 80 y 100 mm de canto, para aluminio o vanos largos
    "PERFIL_REPOSAPIES": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2", "RHS 80x40x2", "RHS 80x40x3",
                          "RHS 100x40x3"],
}
FOOTREST_LOAD_N = 1000.0     # apoyo del pie en el centro del reposapiés (criterio de ensayo habitual de 1 kN)
FOOT_CLEARANCE = 100.0       # hueco libre mínimo sobre el reposapiés para apoyar el pie
CROSSBEAM_GAP = 5.0          # hueco mínimo entre travesaños intermedios, y con las patas, para soldarlos
RADIUS_MARGIN = 1.0          # margen del taladro de la remachable respecto al radio de esquina del perfil
CONSTRUCTIVE_DEFAULTS = {"PERFIL_PATA": "SHS 40x40x2", "PERFIL_LARGUERO": "RHS 60x40x2",
                         "PERFIL_TRAVESANO": "RHS 40x20x2", "PERFIL_BASTIDOR": "RHS 40x20x2",
                         "PERFIL_REPOSAPIES": "RHS 40x20x2",
                         "ESPESOR_CHAPA": 2.0, "ESPESOR_BALDA": 1.5, "PIE_NIVELADOR": "PIE_NIV_M12_D60"}


def frame_z(origin, zdir) -> np.ndarray:
    z = np.asarray(zdir, float)
    z /= np.linalg.norm(z)
    x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = x - z * np.dot(x, z)
    x /= np.linalg.norm(x)
    return G.frame(origin, x, np.cross(z, x))


def flange_hole_d(mat_code: str, t: float, screw: dict) -> float:
    """Diámetro de taladro de pestaña: holgura del tornillo, pero nunca menor que el mínimo del láser."""
    fam = catalog.material(mat_code).family
    dmin = catalog.sheet_data()["laser"]["min_hole_diameter_factor"].get(fam, 1.0) * t
    return round(max(screw["clearance_hole"], math.ceil(dmin * 10) / 10), 1)


def rounded_perimeter(B: float, H: float, r: float) -> float:
    return 2 * (B + H) - (8 - 2 * math.pi) * r


def even_positions(a: float, b: float, n: int) -> list[float]:
    if n == 1:
        return [(a + b) / 2]
    return [a + i * (b - a) / (n - 1) for i in range(n)]


@register
class MesaIndustrial(ProductFamily):
    id = "mesa_industrial"
    name = "Mesa industrial"
    prefix = "MI"
    category = "B"
    description = ("Mesa de estructura tubular soldada con encimera de chapa plegada, balda inferior opcional, "
                   "pies niveladores y fijación atornillada de chapas.")
    configurations = ["Mesa abierta", "Mesa con balda inferior", "Mesa de montaje", "Mesa de trabajo pesado"]
    verification_inputs = ["CARGA_TOTAL"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    leg_param = "PERFIL_PATA"
    frame_params = ("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "PERFIL_BASTIDOR", "PERFIL_REPOSAPIES")
    top_iid, top_label = "ENC.BANDEJA", "Encimera"          # instancia y subconjunto de la superficie de trabajo
    #: altura libre mínima bajo la encimera para trabajar sentado o de pie (None: no aplica, p. ej. una plataforma)
    min_clear_height: float | None = 600.0
    auto_in_construct = ("RADIO_PLEGADO", "FACTOR_K", "NUMERO_TRAVESANOS", "NUMERO_TRAVESANOS_BALDA", "HOLGURA_ENCIMERA",
                         "TACO_ANCLAJE")
    #: parámetro que elige el componente de apoyo (pie nivelador o rueda de espiga roscada)
    support_param = "PIE_NIVELADOR"
    support_category = "patas"
    support_group = ("APO", "Apoyos niveladores")
    #: dirección (y desplazamiento mínimo) de la encimera en el explosionado
    top_explode = (0.0, 0.0, 380.0)

    @staticmethod
    def sheet_inset(v, t_param, gap_param) -> float:
        """Retranqueo bastidor–cara exterior para una chapa plegada: espesor + holgura (igual que en la derivación)."""
        t = v[t_param]
        fam = catalog.material(v["MATERIAL_CHAPA"]).family
        rmin = catalog.sheet_data()["press_brake"]["min_inner_radius_factor"].get(fam, 1.0)
        r = round(max(t, rmin * t), 2) if v["RADIO_PLEGADO"] == AUTO else v["RADIO_PLEGADO"]
        head_h = float(catalog.component("TUERCA_REMACHABLE_M6")["head_h"])
        return t + (max(r, head_h) if v[gap_param] == AUTO else v[gap_param])

    def leg_fits(self, v) -> bool:
        """El bastidor inferior, retranqueado para la pestaña de la balda, cabe en la sección de la pata (el
        dimensionado aumenta la pata 'auto' si no; antes sólo se comparaban los anchos: DFM-BASTIDOR-INF)."""
        if not (v.get("NUMERO_BALDAS") or 0) >= 1:
            return True
        if any(v.get(k) in (AUTO, None) for k in (self.leg_param, "PERFIL_BASTIDOR", "ESPESOR_BALDA")):
            return True
        return (self.sheet_inset(v, "ESPESOR_BALDA", "HOLGURA_ENCIMERA") + catalog.profile(v["PERFIL_BASTIDOR"]).B
                <= catalog.profile(v[self.leg_param]).B + 1e-9)

    def sway_beam_param(self, axis: int) -> str:
        """Perfil de las vigas que forman pórtico con las patas en la dirección X (largueros) o Y (travesaños)."""
        return "PERFIL_LARGUERO" if axis == 0 else "PERFIL_TRAVESANO"

    def param_for_role(self, role: str) -> str | None:
        return {"pata": "PERFIL_PATA", "larguero_sup": "PERFIL_LARGUERO", "travesano_ext_sup": "PERFIL_TRAVESANO",
                "travesano_int_sup": "PERFIL_TRAVESANO", "larguero_inf": "PERFIL_BASTIDOR",
                "travesano_ext_inf": "PERFIL_BASTIDOR", "travesano_int_inf": "PERFIL_BASTIDOR",
                "reposapies": "PERFIL_REPOSAPIES"}.get(role)

    #: carga de uso de la balda inferior respecto de la de la encimera
    shelf_load_ratio = 0.5

    def use_load_kg_m2(self, v) -> float:
        return USE_LOAD_KG_M2.get(v.get("USO") or "montaje", 150)

    def default_loads(self, v):
        q = self.use_load_kg_m2(v)
        L, W = v.get("LONGITUD") or 0, v.get("ANCHURA") or 0
        uso = f", uso {v['USO']}" if v.get("USO") else ""
        out = {"CARGA_TOTAL": (r10(q * (L * W * 1e-6)), f"{q:g} kg/m² sobre {L:g} × {W:g} mm{uso}")}
        if (v.get("NUMERO_BALDAS") or 0) >= 1 and "CARGA_BALDA" in {s.name for s in self.param_specs()}:
            qb = q * self.shelf_load_ratio
            out["CARGA_BALDA"] = (r10(qb * (L * W * 1e-6)), f"{qb:g} kg/m² sobre la balda")
        return out

    def vertical_load_present(self, v) -> bool:
        # una carga puntual sobre la encimera también exige dimensionar (antes sólo la carga repartida)
        return bool(v.get("CARGA_TOTAL") or v.get("CARGA_PUNTUAL"))

    def plate_targets(self, v) -> list[dict]:
        out = []
        if v.get("CARGA_TOTAL") or v.get("CARGA_PUNTUAL"):
            out.append({"surface": "encimera", "t_param": "ESPESOR_CHAPA", "n_param": "NUMERO_TRAVESANOS",
                        "load_param": "CARGA_TOTAL", "trv_param": "PERFIL_TRAVESANO", "min_t_by_use": True})
        if v.get("CARGA_BALDA") and v.get("NUMERO_BALDAS", 0) >= 1:
            out.append({"surface": "balda", "t_param": "ESPESOR_BALDA", "n_param": "NUMERO_TRAVESANOS_BALDA",
                        "load_param": "CARGA_BALDA", "trv_param": "PERFIL_BASTIDOR", "min_t_by_use": False})
        return out

    def sheet_defaults_without_load(self, v) -> dict:
        """Espesores por defecto cuando no hay carga para dimensionar."""
        out = {}
        if not (v.get("CARGA_TOTAL") or v.get("CARGA_PUNTUAL")):
            out["ESPESOR_CHAPA"] = CONSTRUCTIVE_DEFAULTS["ESPESOR_CHAPA"]
        if not (v.get("CARGA_BALDA") and v.get("NUMERO_BALDAS", 0) >= 1):
            out["ESPESOR_BALDA"] = CONSTRUCTIVE_DEFAULTS["ESPESOR_BALDA"]
        return out

    # ------------------------------------------------------------------ parámetros
    def param_specs(self) -> list[ParamSpec]:
        P = ParamSpec
        return [
            P("LONGITUD", "Longitud", "float", 1800.0, "mm", "dimensiones", 600, 3000),
            P("ANCHURA", "Anchura (fondo)", "float", 800.0, "mm", "dimensiones", 400, 1200),
            P("ALTURA", "Altura de la superficie de trabajo", "float", 900.0, "mm", "dimensiones", 600, 1200,
              help="Medida desde el suelo con los pies niveladores en su posición nominal."),
            P("MATERIAL_ESTRUCTURAL", "Material de la estructura", "choice", "S235JRH", None, "materiales",
              choices=STRUCT_MATERIALS),
            P("MATERIAL_CHAPA", "Material de chapa", "choice", "S235JR", None, "materiales", choices=SHEET_MATERIALS),
            P("ESPESOR_CHAPA", "Espesor de chapa de encimera", "float", AUTO, "mm", "materiales", 0.8, 6,
              allow_auto=True),
            P("ESPESOR_BALDA", "Espesor de chapa de balda", "float", AUTO, "mm", "materiales", 0.8, 4,
              allow_auto=True),
            P("ESPESOR_PLACA_BASE", "Espesor de placa base", "float", 5.0, "mm", "materiales", 3, 12),
            P("ACABADO", "Acabado", "choice", "RAL7035_POLVO", None, "materiales", choices=list(catalog.finishes())),
            P("PERFIL_PATA", "Perfil de patas", "choice", AUTO, None, "construccion", choices=SHS,
              allow_auto=True),
            P("PERFIL_LARGUERO", "Perfil de largueros superiores", "choice", AUTO, None, "construccion",
              choices=ALLP, allow_auto=True),
            P("PERFIL_TRAVESANO", "Perfil de travesaños superiores", "choice", AUTO, None, "construccion",
              choices=ALLP, allow_auto=True),
            P("PERFIL_BASTIDOR", "Perfil del bastidor inferior", "choice", AUTO, None, "construccion",
              choices=ALLP, allow_auto=True),
            P("PERFIL_REPOSAPIES", "Perfil del reposapiés", "choice", AUTO, None, "construccion", choices=ALLP,
              allow_auto=True),
            P("NUMERO_TRAVESANOS", "Travesaños intermedios bajo encimera", "int", AUTO, "ud", "construccion", 0, 20,
              allow_auto=True, help="'auto': mínimo número que verifica la chapa (o la separación máxima si no "
                                    "hay carga definida)."),
            P("NUMERO_TRAVESANOS_BALDA", "Travesaños intermedios bajo balda", "int", AUTO, "ud", "construccion", 0,
              20, allow_auto=True),
            P("SEPARACION_MAX_APOYOS", "Separación máxima entre apoyos de chapa (regla constructiva)", "float",
              600.0, "mm", "construccion", 150, 1200, advanced=True),
            P("ALA_ENCIMERA", "Altura de pestaña de encimera", "float", 40.0, "mm", "construccion", 20, 100),
            P("ALA_BALDA", "Altura de pestaña de balda", "float", 25.0, "mm", "construccion", 15, 60),
            P("RADIO_PLEGADO", "Radio interior de plegado", "float", AUTO, "mm", "construccion", 0.5, 20,
              allow_auto=True, advanced=True),
            P("FACTOR_K", "Factor K", "float", AUTO, None, "construccion", 0.2, 0.5, allow_auto=True, advanced=True,
              help="'auto': DIN 6935."),
            P("HOLGURA_ENCIMERA", "Holgura estructura–pestaña", "float", AUTO, "mm", "construccion", 0.5, 5,
              allow_auto=True, advanced=True,
              help="'auto': máx(radio interior de plegado, cabeza de tuerca remachable). Con holgura menor que el "
                   "radio, las aristas vivas del bastidor interfieren con la zona de plegado."),
            P("HOLGURA_ESCOTADURA", "Holgura de escotadura de balda", "float", 2.0, "mm", "construccion", 1, 6,
              advanced=True),
            P("PASO_FIJACIONES", "Paso máximo de fijaciones", "float", 400.0, "mm", "construccion", 150, 800,
              advanced=True),
            P("FIJACION_ENCIMERA", "Fijación de chapas", "choice", "atornillada", None, "construccion",
              choices=["atornillada"]),
            P("TIPO_APOYO", "Tipo de apoyo", "choice", "pie_nivelador", None, "accesorios",
              choices=["pie_nivelador"]),
            P("PIE_NIVELADOR", "Pie nivelador", "choice", AUTO, None, "accesorios", choices=FEET, allow_auto=True,
              help="'auto': el de menor capacidad nominal que soporta la reacción de servicio calculada."),
            P("PETO_TRASERO", "Peto trasero (altura sobre la encimera)", "float", 0.0, "mm", "accesorios", 0, 200,
              help="Borde trasero de la encimera plegado hacia arriba como tope de piezas y herramientas. "
                   "0 = sin peto. Ese borde queda sin fijaciones: la encimera se atornilla por delante y por los "
                   "extremos."),
            P("REPOSAPIES", "Reposapiés delantero", "int", 0, "ud", "accesorios", 0, 1,
              help="Barra soldada entre las patas delanteras para apoyar los pies (trabajo sentado o en taburete). "
                   "Se verifica con 1 kN en el centro."),
            P("ALTURA_REPOSAPIES", "Altura del reposapiés (cara superior)", "float", 250.0, "mm", "accesorios", 100, 450),
            P("CARGA_REPOSAPIES", "Carga de apoyo en el reposapiés", "float", FOOTREST_LOAD_N, "N", "accesorios", 0, 3000,
              advanced=True, help="Fuerza vertical en el centro de la barra (apoyo o subida de una persona); 1 kN es el "
                                  "criterio de ensayo habitual."),
            P("NUMERO_BALDAS", "Balda inferior", "int", 1, "ud", "accesorios", 0, 1),
            P("ALTURA_BALDA", "Altura de la balda (cara superior)", "float", 200.0, "mm", "accesorios", 100, 600),
            P("TOLERANCIAS", "Tolerancias generales", "choice", "ISO 2768-mK", None, "construccion",
              choices=["ISO 2768-mK", "ISO 2768-fH", "ISO 2768-cL"], advanced=True),
            P("CLASE_EJECUCION", "Clase de ejecución (EN 1090-2)", "choice", "EXC1", None, "construccion",
              choices=["EXC1", "EXC2"], advanced=True),
            P("CARGA_TOTAL", "Carga distribuida sobre encimera", "float", None, "kg", "cargas", 0, 5000,
              nullable=True),
            P("CARGA_BALDA", "Carga distribuida sobre balda", "float", None, "kg", "cargas", 0, 3000, nullable=True),
            P("CARGA_PUNTUAL", "Carga puntual sobre encimera", "float", None, "kg", "cargas", 0, 2000, nullable=True,
              help="Aplicada sobre una huella cuadrada (lado HUELLA_CARGA_PUNTUAL) en la posición más desfavorable."),
            P("HUELLA_CARGA_PUNTUAL", "Huella de la carga puntual (lado del cuadrado)", "float", 100.0, "mm", "cargas",
              25, 500, advanced=True, help="Superficie de apoyo de la pieza concentrada: cuanto menor, mayor la flexión "
                                           "local de la chapa (100 mm: pieza pequeña; 200 mm: EN ISO 14122-2)."),
            P("CARGA_HORIZONTAL", "Empuje horizontal en canto de encimera", "float", 300.0, "N", "cargas", 0, 5000),
            P("USO", "Uso previsto", "choice", "montaje", None, "cargas",
              choices=["montaje_ligero", "montaje", "trabajo_pesado", "inspeccion", "laboratorio", "embalaje"]),
            P("FRECUENCIA", "Frecuencia de trabajo", "choice", "diaria", None, "cargas",
              choices=["ocasional", "diaria", "intensiva"]),
            P("ENTORNO", "Entorno", "choice", "interior_seco", None, "cargas",
              choices=["interior_seco", "interior_humedo", "exterior", "alimentario", "sala_limpia"]),
            P("TIPO_SUELO", "Tipo de suelo", "choice", "nivelado", None, "cargas", choices=["nivelado", "irregular"]),
            P("ANCLAJE", "Anclaje al suelo", "choice", "ninguno", None, "cargas", choices=["ninguno", "al_suelo"],
              help="'ninguno' por defecto: si el conjunto vacío volcara con el empuje, se ancla automáticamente."),
            P("TACO_ANCLAJE", "Taco de anclaje", "choice", AUTO, None, "cargas", choices=ANCHORS, allow_auto=True,
              help="'auto': el de menor capacidad que resiste la tracción de cálculo (sólo con anclaje al suelo)."),
        ] + fabrication_specs()

    def templates(self):
        base = {"CARGA_TOTAL": 300.0, "NUMERO_BALDAS": 1, "ANCLAJE": "al_suelo"}     # 300 N de empuje: anclada
        return [
            {"id": "MI-1200", "name": "Mesa industrial de 1.200 mm", "family": self.id,
             "values": {**base, "LONGITUD": 1200.0, "ANCHURA": 700.0, "ALTURA": 900.0, "CARGA_TOTAL": 200.0}},
            {"id": "MI-1800", "name": "Mesa industrial de 1.800 mm", "family": self.id,
             "values": {**base, "LONGITUD": 1800.0, "ANCHURA": 800.0, "ALTURA": 900.0}},
            {"id": "MI-2200", "name": "Mesa industrial de 2.200 mm", "family": self.id,
             "values": {**base, "LONGITUD": 2200.0, "ANCHURA": 800.0, "ALTURA": 900.0, "CARGA_TOTAL": 400.0}},
            {"id": "MI-1500-INOX", "name": "Mesa de inspección inoxidable 1.500 mm (alimentaria)", "family": self.id,
             "values": {"LONGITUD": 1500.0, "ANCHURA": 700.0, "ALTURA": 900.0, "CARGA_TOTAL": 150.0, "NUMERO_BALDAS": 1,
                        "CARGA_BALDA": 50.0, "MATERIAL_ESTRUCTURAL": "1.4301", "MATERIAL_CHAPA": "1.4301",
                        "ACABADO": "INOX_SATINADO", "USO": "inspeccion", "ENTORNO": "alimentario",
                        "CARGA_HORIZONTAL": 100.0}},
            {"id": "MI-1500-LAB", "name": "Mesa de laboratorio inoxidable 1.500 mm con peto trasero", "family": self.id,
             "values": {"LONGITUD": 1500.0, "ANCHURA": 750.0, "ALTURA": 900.0, "CARGA_TOTAL": 150.0, "NUMERO_BALDAS": 1,
                        "CARGA_BALDA": 60.0, "MATERIAL_ESTRUCTURAL": "1.4301", "MATERIAL_CHAPA": "1.4301",
                        "ACABADO": "INOX_SATINADO", "USO": "laboratorio", "ENTORNO": "interior_humedo",
                        "PETO_TRASERO": 100.0, "CARGA_HORIZONTAL": 100.0, "ANCLAJE": "ninguno"}},
            {"id": "MI-2400-PESADA", "name": "Mesa de trabajo pesado 2.400 mm", "family": self.id,
             "values": {"LONGITUD": 2400.0, "ANCHURA": 900.0, "ALTURA": 900.0, "CARGA_TOTAL": 800.0,
                        "CARGA_PUNTUAL": 150.0, "NUMERO_BALDAS": 1, "CARGA_BALDA": 200.0, "USO": "trabajo_pesado",
                        "ESPESOR_CHAPA": AUTO, "ESPESOR_BALDA": AUTO, "PERFIL_PATA": AUTO, "PERFIL_LARGUERO": AUTO,
                        "PERFIL_TRAVESANO": AUTO, "PERFIL_BASTIDOR": AUTO, "ACABADO": "RAL7016_POLVO",
                        "ANCLAJE": "al_suelo"}},
            {"id": "PT-1200-ERG", "name": "Puesto de montaje ligero 1.200 mm con reposapiés (galvanizado + polvo)",
             "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 750.0, "ALTURA": 850.0, "CARGA_TOTAL": 100.0,
                        "NUMERO_BALDAS": 0, "REPOSAPIES": 1, "ALTURA_REPOSAPIES": 250.0, "USO": "montaje_ligero",
                        "MATERIAL_CHAPA": "S250GD+Z",
                        "ACABADO": "RAL5015_POLVO", "CARGA_HORIZONTAL": 100.0, "ANCLAJE": "al_suelo"}},
            {"id": "BM-1500", "name": "Banco de montaje 1.500 mm (trabajo pesado)", "family": self.id,
             "values": {"LONGITUD": 1500.0, "ANCHURA": 750.0, "ALTURA": 850.0, "CARGA_TOTAL": 500.0,
                        "CARGA_PUNTUAL": 100.0, "ESPESOR_CHAPA": 3.0, "USO": "trabajo_pesado",
                        "NUMERO_BALDAS": 1, "CARGA_BALDA": 150.0, "ANCLAJE": "al_suelo"}},
            {"id": "MI-3000-LINEA", "name": "Mesa de línea 3.000 mm con balda (anclada)", "family": self.id,
             "values": {"LONGITUD": 3000.0, "ANCHURA": 800.0, "ALTURA": 900.0, "CARGA_TOTAL": 500.0,
                        "NUMERO_BALDAS": 1, "CARGA_BALDA": 150.0, "CARGA_HORIZONTAL": 300.0, "ANCLAJE": "al_suelo",
                        "ACABADO": "RAL7035_POLVO"}},
            {"id": "MI-1200-ALU", "name": "Mesa de aluminio 1.200 mm para sala limpia", "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 700.0, "ALTURA": 900.0, "CARGA_TOTAL": 100.0,
                        "NUMERO_BALDAS": 1, "CARGA_BALDA": 40.0, "MATERIAL_ESTRUCTURAL": "EN AW-6082 T6",
                        "MATERIAL_CHAPA": "EN AW-5754 H22", "ACABADO": "ANODIZADO_NATURAL",
                        "ENTORNO": "sala_limpia", "USO": "inspeccion", "CARGA_HORIZONTAL": 40.0}},
            {"id": "MI-1000-MAQUINA", "name": "Mesa soporte de máquina 1.000 mm (anclada, con carga puntual)", "family": self.id,
             "values": {"LONGITUD": 1000.0, "ANCHURA": 700.0, "ALTURA": 800.0, "CARGA_TOTAL": 300.0,
                        "CARGA_PUNTUAL": 150.0, "NUMERO_BALDAS": 0, "USO": "trabajo_pesado", "ANCLAJE": "al_suelo",
                        "CARGA_HORIZONTAL": 300.0, "ACABADO": "RAL7016_POLVO"}},
            {"id": "MI-1600-SENTADO", "name": "Mesa de montaje sentado 1.600 mm con reposapiés", "family": self.id,
             "values": {"LONGITUD": 1600.0, "ANCHURA": 800.0, "ALTURA": 750.0, "CARGA_TOTAL": 150.0,
                        "NUMERO_BALDAS": 0, "REPOSAPIES": 1, "ALTURA_REPOSAPIES": 200.0, "CARGA_HORIZONTAL": 120.0,
                        "ACABADO": "RAL7035_POLVO"}},
        ]

    # ------------------------------------------------------------------ construcción
    def construct(self, ps: ParameterSet) -> ProductModel:
        for k, v in ps.values.items():
            if v == AUTO and k not in self.auto_in_construct:
                raise ValueError(f"Parámetro sin resolver: {k}")
        ctx = ParamContext(ps)
        L, W, H = ps.values["LONGITUD"], ps.values["ANCHURA"], ps.values["ALTURA"]
        model = ProductModel(self.id, self.name, f"{self.prefix}{L:.0f}-{W:.0f}-{H:.0f}", ps, ctx)
        model.requested = ps
        d = self._derive(ctx, model)
        mat_s, mat_c, fin = ps.values["MATERIAL_ESTRUCTURAL"], ps.values.get("MATERIAL_CHAPA"), ps.values["ACABADO"]

        model.add_subassembly("EST", "Estructura soldada", welded=True, step=1)
        model.add_subassembly(self.support_group[0], self.support_group[1], explode=(0, 0, -160), step=2)
        if d["shelf"]:
            model.add_subassembly("BAL", "Balda inferior", explode=(0, -100, 0), step=3)     # sale por delante
        model.add_subassembly("ENC", self.top_label, explode=self.top_explode, step=4)

        leg, rail, trv, bas = d["leg"], d["rail"], d["trv"], d["bas"]
        c, a = d["c"], d["a"]
        legs: dict[str, str] = {}
        corners = {"DI": (c + a / 2, c + a / 2), "DD": (L - c - a / 2, c + a / 2),
                   "TI": (c + a / 2, W - c - a / 2), "TD": (L - c - a / 2, W - c - a / 2)}
        corner_names = {"DI": "delantera izquierda", "DD": "delantera derecha", "TI": "trasera izquierda",
                        "TD": "trasera derecha"}
        foot = catalog.component(ps.values[self.support_param])
        thread = float(foot["thread"][1:])
        nut_code = weld_nut_code(thread, mat_s)
        rn = catalog.component("TUERCA_REMACHABLE_M6")
        sc = catalog.component("TORNILLO_ISO7380_M6x12")

        weld = self._make_welder(model, d)
        leg_parts: dict = {}

        # ---------------------------------------------------------------- estructura
        with ctx.feature("F10", "Estructura soldada"):
            with ctx.feature("F11", "Patas, placas base y tuercas"):
                ctx.uses("LONGITUD_PATA", "PERFIL_PATA", "RETRANQUEO", "LONGITUD", "ANCHURA", "ESPESOR_PLACA_BASE",
                         self.support_param, "MATERIAL_ESTRUCTURAL", "ACABADO", *self._leg_uses())
                plate_mat = "S235JR" if catalog.material(mat_s).family == "acero_carbono" else mat_s
                plate = PlatePart("placa_base", f"Placa base {a:.0f}x{a:.0f}x{d['tp']:.0f}", a, a, d["tp"],
                                  plate_mat, fin, corner_r=min(3.0, a / 10), holes=((a / 2, a / 2, thread + 1.0),))
                nut = StandardPart("tuerca_soldar", nut_code)
                for k, (x, y) in corners.items():
                    iid = f"EST.PATA.{k}"
                    role, pname, z_top, holes = self._leg_def(k, d, leg)
                    pk = (role, round(z_top, 4), holes)
                    if pk not in leg_parts:
                        leg_parts[pk] = ProfilePart(role, f"{pname} {leg.code}", leg.code, z_top - d["z_leg0"], mat_s, fin,
                                                    holes=holes)
                    p0, p1 = np.array([x, y, d["z_leg0"]]), np.array([x, y, z_top])
                    model.add(iid, f"{pname} {corner_names[k]}", leg_parts[pk], G.axis_frame(p0, p1, (0, 1, 0)), "EST",
                              axis=(p0, p1), up=np.array([0, 1.0, 0]), structural=True)
                    legs[k] = iid
                    model.add(f"EST.PLACA.{k}", f"Placa base {corner_names[k]}", plate,
                              G.translation(x - a / 2, y - a / 2, d["hn"]), "EST")
                    model.add(f"EST.TUERCA.{k}", f"Tuerca soldada {corner_names[k]}", nut,
                              G.translation(x, y, d["hn"] + d["tp"]), "EST")
                    model.add_joint(Joint(f"J.PLACA.{k}", "soldadura", (iid, f"EST.PLACA.{k}"), (x, y, d["z_leg0"]),
                                          "Placa base a pata", weld={"type": "fillet", "a": d["weld_a"](min(leg.t, d["tp"])),
                                                                     "all_around": True, "process": "135 (MAG)",
                                                                     "length": round(rounded_perimeter(a, a, leg.r_out), 1)}))
                    s = float(catalog.component(nut_code)["s"])
                    model.add_joint(Joint(f"J.TUERCA.{k}", "soldadura", (f"EST.TUERCA.{k}", f"EST.PLACA.{k}"),
                                          (x, y, d["hn"] + d["tp"]), "Tuerca de soldar a placa base",
                                          weld={"type": "fillet", "a": 2.0, "all_around": False, "process": "135 (MAG)",
                                                "length": round(3 * s / math.sqrt(3), 1),
                                                "note": "3 cordones en caras alternas de la tuerca"}))

            with ctx.feature("F12", "Bastidor superior"):
                ctx.uses("LONGITUD_LARGUERO", "LONGITUD_TRAVESANO_EXT", "LONGITUD_TRAVESANO_INT", "N_TRAVESANOS_INT",
                         "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "COTA_BASTIDOR_SUP", *self._top_frame_uses(),
                         "MATERIAL_ESTRUCTURAL", "ACABADO")
                self._frame_level(model, d, ctx, level="SUP", z_top=d["z_tf"], prof_long=rail, prof_end=trv,
                                  inset=0.0, n_int=d["n_top"], legs=legs, fixings=d["fix_top"], weld=weld,
                                  mat=mat_s, fin=fin)
            if d["shelf"]:
                with ctx.feature("F13", "Bastidor inferior"):
                    ctx.uses("PERFIL_BASTIDOR", "N_TRAVESANOS_BALDA", "COTA_BALDA", "ESP_BAL", "LONGITUD", "ANCHURA",
                             "RETRANQUEO", "PERFIL_PATA", "PASO_FIJACIONES", "ALA_BALDA", "MATERIAL_ESTRUCTURAL")
                    self._frame_level(model, d, ctx, level="INF", z_top=d["z_lf"], prof_long=bas, prof_end=bas,
                                      inset=d["e_shelf"], n_int=d["n_shelf"], legs=legs, fixings=d["fix_shelf"],
                                      weld=weld, mat=mat_s, fin=fin)

        # ---------------------------------------------------------------- apoyos
        with ctx.feature("F40", self.support_group[1]):
            ctx.uses(self.support_param, "LONGITUD", "ANCHURA", "RETRANQUEO", "PERFIL_PATA")
            g = self.support_group[0]
            for k, (x, y) in corners.items():
                fpart, fname = self._support_part(k, ps)
                model.add(f"{g}.PIE.{k}", f"{fname} {corner_names[k]}", fpart, G.translation(x, y, 0.0), g)
                model.add_joint(Joint(f"J.PIE.{k}", "roscada", (f"{g}.PIE.{k}", f"EST.TUERCA.{k}"),
                                      (x, y, d["hn"]), f"{fname} roscad{'a' if fpart.role == 'rueda' else 'o'} "
                                                       f"{foot['thread']} en tuerca soldada"))
            add_anchors(model, ps, corners, corner_names, g)

        # ---------------------------------------------------------------- chapas
        self._build_top(model, ctx, d, H, mat_c, fin, rn, sc)
        if d["shelf"]:
            with ctx.feature("F30", "Balda inferior de chapa plegada"):
                ctx.uses("LONGITUD", "ANCHURA", "COTA_BALDA", "ESP_BAL", "ALA_BALDA", "MATERIAL_CHAPA", "PERFIL_PATA",
                         "HOLGURA_ESCOTADURA", "PERFIL_BASTIDOR", "ACABADO")
                spec = d["shelf_spec"]
                tray = SheetPart("balda", f"Balda chapa {spec.t:g} mm", spec, mat_c, fin)
                model.add("BAL.BANDEJA", "Balda inferior", tray, G.translation(c, c, d["z_shelf"]), "BAL")
                self._fasteners(model, d["fix_shelf"], "BAL", rn, sc, ctx)

        if d["footrest"]:
            with ctx.feature("F17", "Reposapiés soldado"):
                ctx.uses("REPOSAPIES", "ALTURA_REPOSAPIES", "PERFIL_REPOSAPIES", "LONGITUD", "RETRANQUEO", "PERFIL_PATA",
                         "MATERIAL_ESTRUCTURAL", "ACABADO")
                fp, zr = d["footrest"]["prof"], d["footrest"]["z"]
                y, zc = c + a / 2, zr - fp.H / 2
                p0, p1 = np.array([c + a, y, zc]), np.array([L - c - a, y, zc])
                part = ProfilePart("reposapies", f"Reposapiés {fp.code}", fp.code, L - 2 * c - 2 * a, mat_s, fin)
                model.add("EST.REPOSAPIES", "Reposapiés delantero", part, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                          axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
                weld("J.EST.REPOSAPIES.0", "EST.REPOSAPIES", 0, legs["DI"], fp, "Reposapiés a pata")
                weld("J.EST.REPOSAPIES.1", "EST.REPOSAPIES", 1, legs["DD"], fp, "Reposapiés a pata")
        self._extras(model, ctx, d, legs, corners)

        # ---------------------------------------------------------------- datos estructurales
        model.structure = self._structure(model, d, legs)
        peto = d["peto"]
        levels = [("ALTURA_BALDA", "BAL.BANDEJA")] if d["shelf"] else []
        if peto > 0:      # el peto sobresale: la altura de trabajo y el peto se acotan en la cadena de niveles
            levels += [("ALTURA_ENCIMERA", self.top_iid, H)] + self._peto_level(d, H)
        model.dims = {"LONGITUD": L, "ANCHURA": W, "ALTURA": H, "ALTURA_BALDA": d["z_shelf"] if d["shelf"] else None,
                      "LONGITUD_PATA": d["leg_len"],
                      "envelope": {"ids": [self.top_iid], "dx": L, "dy": W, "zmax": H + peto, "names": ("LONGITUD", "ANCHURA")},
                      "levels": levels,
                      "load_text": f"Carga distribuida de proyecto sobre {self.top_label.lower()}: "
                                   f"{(str(ps.values['CARGA_TOTAL']) + ' kg') if ps.values.get('CARGA_TOTAL') else 'NO DEFINIDA'}"}
        if peto > 0:
            zs = [0.0] + ([d["z_shelf"]] if d["shelf"] else []) + [H, H + peto]
            model.dims["ALTURA_ENCIMERA"] = H
            model.dims["drawing_expected"] = {f"DIST_NIVEL_{k + 1}": zs[k + 1] - zs[k] for k in range(len(levels))}
        self._extra_dims(model, d)
        model.number_parts()
        return model

    # ------------------------------------------------------------------ ganchos para familias derivadas
    def _leg_uses(self) -> tuple:
        return ()

    def _has_shelf(self, ctx) -> bool:
        """¿Lleva balda inferior? (las familias sin balda no tienen los parámetros de la balda)."""
        return ctx["NUMERO_BALDAS"] >= 1

    def _leg_def(self, corner: str, d: dict, leg):
        """(rol, nombre, cota superior, taladros) de la pata de cada esquina."""
        return "pata", "Pata", d["z_tf"], ()

    def _support_part(self, corner: str, ps: ParameterSet):
        return StandardPart("pie_nivelador", ps.values[self.support_param]), "Pie nivelador"

    def _top_frame_uses(self) -> tuple:
        """Parámetros de la superficie de trabajo que intervienen en el bastidor superior."""
        return ("PASO_FIJACIONES", "ALA_ENCIMERA")

    def _build_top(self, model, ctx, d, H, mat_c, fin, rn, sc) -> None:
        """Superficie de trabajo: encimera de chapa plegada atornillada al bastidor superior."""
        with ctx.feature("F20", f"{self.top_label} de chapa plegada"):
            ctx.uses("LONGITUD", "ANCHURA", "ALTURA", "ESP_ENC", "RADIO_ENC", "K_ENC", "ALA_ENCIMERA", "MATERIAL_CHAPA",
                     "PASO_FIJACIONES", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ACABADO", "PETO_TRASERO")
            spec = d["top_spec"]
            tray = SheetPart("encimera", f"{self.top_label} chapa {spec.t:g} mm", spec, mat_c, fin)
            model.add("ENC.BANDEJA", self.top_label, tray, G.translation(0, 0, H), "ENC")
            self._fasteners(model, d["fix_top"], "ENC", rn, sc, ctx)

    def _top_notch(self, ctx: ParamContext, d: dict):
        """Escotaduras de la encimera: ((nx, ny), esquinas) o None."""
        return None

    def _extras(self, model, ctx, d, legs, corners) -> None:
        """Elementos adicionales de familias derivadas (superestructura, asa...)."""

    def _extra_dims(self, model, d) -> None:
        pass

    @staticmethod
    def _peto_level(d, H) -> list:
        """Nivel de cota de la cara superior del peto trasero (vacío si no hay peto)."""
        return [("COTA_PETO", "ENC.BANDEJA", H + d["peto"])] if d["peto"] > 0 else []

    # ------------------------------------------------------------------ utilidades comunes
    @staticmethod
    def _make_welder(model, d):
        def weld(jid, a_id, end, b_id, prof, desc):
            tmin = min(model.instance(a_id).part.profile.t, model.instance(b_id).part.profile.t)
            loc = model.instance(a_id).axis[end]
            model.add_joint(Joint(jid, "soldadura", (a_id, b_id), tuple(float(v) for v in loc), desc,
                                  weld={"type": "fillet", "a": d["weld_a"](tmin), "all_around": True,
                                        "length": round(rounded_perimeter(prof.B, prof.H, prof.r_out), 1),
                                        "process": "135 (MAG)", "fem": {"member": a_id, "end": end, "onto": b_id}}))
        return weld

    # ------------------------------------------------------------------ derivados
    def _derive(self, ctx: ParamContext, model: ProductModel) -> dict:
        v = ctx.params.values
        d: dict = {}
        with ctx.feature("F00", "Parámetros derivados y reglas constructivas"):
            mat_c = catalog.material(v["MATERIAL_CHAPA"])
            fam = mat_c.family
            rules = catalog.sheet_data()["press_brake"]
            rmin = rules["min_inner_radius_factor"].get(fam, 1.0)

            def radius(t):
                return v["RADIO_PLEGADO"] if v["RADIO_PLEGADO"] != AUTO else round(max(t, rmin * t), 2)

            def kf(r, t):
                return v["FACTOR_K"] if v["FACTOR_K"] != AUTO else round(catalog.din6935_k_factor(r, t), 4)

            t = ctx.derive("ESP_ENC", lambda c: c["ESPESOR_CHAPA"], "mm", "Espesor encimera")
            r = ctx.derive("RADIO_ENC", lambda c: radius(c["ESP_ENC"]) if c["RADIO_PLEGADO"] == AUTO else c["RADIO_PLEGADO"],
                           "mm", "Radio interior de plegado (encimera)")
            K = ctx.derive("K_ENC", lambda c: kf(c["RADIO_ENC"], c["ESP_ENC"]) if c["FACTOR_K"] == AUTO else c["FACTOR_K"],
                           None, "Factor K (encimera)")
            from ..cad.sheetmetal import bend_deduction
            ctx.derive("DEDUCCION_PLEGADO_ENC", lambda c: round(bend_deduction(c["ESP_ENC"], c["RADIO_ENC"], c["K_ENC"]), 4),
                       "mm", "Deducción de plegado 90° (encimera)")
            head_h = float(catalog.component("TUERCA_REMACHABLE_M6")["head_h"])
            g = ctx.derive("HOLGURA_ENC", lambda p: max(p["RADIO_ENC"], head_h) if p["HOLGURA_ENCIMERA"] == AUTO
                           else p["HOLGURA_ENCIMERA"], "mm", "Holgura estructura–pestaña (encimera)")
            if g < r - 1e-9:
                model.note("error", "GEO-HOLGURA-RADIO", f"Holgura {g} mm menor que el radio interior de plegado "
                           f"{r} mm: las aristas del bastidor interfieren con el pliegue de la encimera.")
            c = ctx.derive("RETRANQUEO", lambda p: p["ESP_ENC"] + p["HOLGURA_ENC"], "mm",
                           "Retranqueo de la estructura respecto al canto exterior")
            leg = catalog.profile(ctx["PERFIL_PATA"])
            rail = catalog.profile(ctx["PERFIL_LARGUERO"])
            trv = catalog.profile(ctx["PERFIL_TRAVESANO"])
            bas = catalog.profile(ctx["PERFIL_BASTIDOR"]) if "PERFIL_BASTIDOR" in v else None   # sin balda: no existe
            if leg.B != leg.H:
                raise ValueError("Las patas deben ser de tubo cuadrado")
            a = leg.B
            ctx.set_derived("SECCION_PATA", f"{leg.B:g}x{leg.H:g}", "mm", "Sección de pata", ["PERFIL_PATA"])
            ctx.set_derived("ESPESOR_PERFIL_PATA", leg.t, "mm", "Espesor de pata", ["PERFIL_PATA"])
            foot = catalog.component(ctx[self.support_param])
            hn = float(foot["nominal_height"])
            tp = ctx["ESPESOR_PLACA_BASE"]
            z_tf = ctx.derive("COTA_BASTIDOR_SUP", lambda p: p["ALTURA"] - p["ESP_ENC"], "mm",
                              "Cota cara superior del bastidor")
            sp = self.support_param
            z_leg0 = ctx.derive("COTA_INICIO_PATA", lambda p: float(catalog.component(p[sp])["nominal_height"])
                                + p["ESPESOR_PLACA_BASE"], "mm", "Cota inicio de pata")
            leg_len = ctx.derive("LONGITUD_PATA", lambda p: p["COTA_BASTIDOR_SUP"] - p["COTA_INICIO_PATA"], "mm",
                                 "Longitud de corte de pata")
            L, W, H = ctx["LONGITUD"], ctx["ANCHURA"], ctx["ALTURA"]
            ctx.derive("LONGITUD_LARGUERO", lambda p: p["LONGITUD"] - 2 * p["RETRANQUEO"]
                       - 2 * catalog.profile(p["PERFIL_PATA"]).B, "mm",
                       "Longitud de largueros")
            ctx.derive("LONGITUD_TRAVESANO_EXT", lambda p: p["ANCHURA"] - 2 * p["RETRANQUEO"]
                       - 2 * catalog.profile(p["PERFIL_PATA"]).B, "mm",
                       "Longitud de travesaños extremos")
            ctx.derive("LONGITUD_TRAVESANO_INT", lambda p: p["ANCHURA"] - 2 * p["RETRANQUEO"]
                       - 2 * catalog.profile(p["PERFIL_LARGUERO"]).B, "mm",
                       "Longitud de travesaños intermedios")
            if rail.B > a or trv.B > a:
                model.note("error", "DFM-ANCHO-BASTIDOR", "El ancho de largueros/travesaños supera el de la pata: "
                           "no pueden enrasarse con la cara exterior.")
            # vanos y número de travesaños
            xe0, xe1 = c + trv.B / 2, L - c - trv.B / 2
            n_top = ctx["NUMERO_TRAVESANOS"]
            if n_top == AUTO:   # regla constructiva sin carga
                n_top = max(0, math.ceil((xe1 - xe0) / ctx["SEPARACION_MAX_APOYOS"]) - 1)
            ctx.set_derived("N_TRAVESANOS_INT", n_top, "ud", "Travesaños intermedios", ["NUMERO_TRAVESANOS",
                            "SEPARACION_MAX_APOYOS", "LONGITUD"])
            ctx.set_derived("VANO_ENCIMERA", round((xe1 - xe0) / (n_top + 1), 2), "mm", "Vano entre apoyos de encimera",
                            ["LONGITUD", "NUMERO_TRAVESANOS", "PERFIL_TRAVESANO", "RETRANQUEO"])
            shelf = self._has_shelf(ctx)
            d.update(Lx=L, Ly=W, leg=leg, rail=rail, trv=trv, bas=bas, a=a, c=c, t=t, r=r, K=K, hn=hn, tp=tp, z_tf=z_tf,
                     z_leg0=z_leg0, leg_len=leg_len, n_top=n_top, xe=(xe0, xe1), shelf=shelf)
            d["weld_a"] = lambda tmin: 3.0 if tmin >= 3 else float(tmin)

            rn = catalog.component("TUERCA_REMACHABLE_M6")
            sc = catalog.component("TORNILLO_ISO7380_M6x12")
            if rn["head_h"] > g + 1e-9:
                model.note("error", "DFM-HOLGURA-REMACHABLE", f"La cabeza de la tuerca remachable ({rn['head_h']} mm) "
                           f"no cabe en la holgura de {g} mm.")

            # ---- encimera y fijaciones
            ala = ctx["ALA_ENCIMERA"]
            pitch = ctx["PASO_FIJACIONES"]
            fix_top = self._fix_layout(model, ctx, L, W, c, a, t, r + t, ala, rail, trv, z_ref=H, inset=0.0,
                                       hole_d=flange_hole_d(v["MATERIAL_CHAPA"], t, sc), rn=rn, pitch=pitch,
                                       short_min=2, tag="encimera")
            fix_top["gap"] = g
            peto = v.get("PETO_TRASERO") or 0.0
            if peto > 0:      # peto trasero: pestaña hacia arriba, sin fijaciones en ese borde
                fix_top["s"]["y1"] = []
                ctx.derive("COTA_PETO", lambda p: p["ALTURA"] + p["PETO_TRASERO"], "mm", "Cota superior del peto trasero")
            d["peto"] = peto
            flanges = []
            for e in EDGES:
                if e == "y1" and peto > 0:
                    flanges.append(FlangeSpec(e, peto + t, "up", ()))
                    continue
                holes = tuple((s, fix_top["h"][e], flange_hole_d(v["MATERIAL_CHAPA"], t, sc)) for s in fix_top["s"][e])
                flanges.append(FlangeSpec(e, ala, "down", holes))
            tn = self._top_notch(ctx, d)
            d["top_spec"] = SheetMetalSpec(L, W, t, r, K, tuple(flanges), **({"notch": tn[0], "notch_corners": tn[1]} if tn else {}))
            d["fix_top"] = fix_top

            # ---- balda
            d["skirt"] = ctx["ALA_ENCIMERA"]
            if shelf:
                self._derive_shelf(ctx, model, d)
            if self.min_clear_height and H - ctx["ALA_ENCIMERA"] < self.min_clear_height:
                model.note("advertencia", "ERG-ALTURA", f"Altura libre bajo encimera inferior a {self.min_clear_height:g} mm.")
            self._derive_footrest(ctx, model, d)
        return d

    def _derive_shelf(self, ctx: ParamContext, model: ProductModel, d: dict) -> None:
        """Balda inferior de chapa plegada sobre su bastidor (dentro de la operación F00)."""
        v = ctx.params.values
        L, W, c, a, bas, z_leg0 = d["Lx"], d["Ly"], d["c"], d["a"], d["bas"], d["z_leg0"]
        fam = catalog.material(v["MATERIAL_CHAPA"]).family
        rmin = catalog.sheet_data()["press_brake"]["min_inner_radius_factor"].get(fam, 1.0)

        def radius(t):
            return v["RADIO_PLEGADO"] if v["RADIO_PLEGADO"] != AUTO else round(max(t, rmin * t), 2)

        def kf(r, t):
            return v["FACTOR_K"] if v["FACTOR_K"] != AUTO else round(catalog.din6935_k_factor(r, t), 4)

        head_h = float(catalog.component("TUERCA_REMACHABLE_M6")["head_h"])
        rn = catalog.component("TUERCA_REMACHABLE_M6")
        sc = catalog.component("TORNILLO_ISO7380_M6x12")
        pitch = ctx["PASO_FIJACIONES"]
        ts = ctx.derive("ESP_BAL", lambda p: p["ESPESOR_BALDA"], "mm", "Espesor balda")
        rs = radius(ts)
        Ks = kf(rs, ts)
        z_s = ctx.derive("COTA_BALDA", lambda p: p["ALTURA_BALDA"], "mm", "Cota cara superior de balda")
        g_s = ctx.derive("HOLGURA_BAL", lambda p: max(rs, head_h) if p["HOLGURA_ENCIMERA"] == AUTO
                         else p["HOLGURA_ENCIMERA"], "mm", "Holgura bastidor–pestaña (balda)")
        if g_s < rs - 1e-9:
            model.note("error", "GEO-HOLGURA-RADIO-BAL", "Holgura menor que el radio de plegado de la balda.")
        e_sh = ts + g_s
        z_lf = z_s - ts
        notch = a + ctx["HOLGURA_ESCOTADURA"]
        xb0, xb1 = c + e_sh + bas.B / 2, L - c - e_sh - bas.B / 2
        n_sh = ctx["NUMERO_TRAVESANOS_BALDA"]
        if n_sh == AUTO:
            n_sh = max(0, math.ceil((xb1 - xb0) / ctx["SEPARACION_MAX_APOYOS"]) - 1)
        ctx.set_derived("N_TRAVESANOS_BALDA", n_sh, "ud", "Travesaños bajo balda",
                        ["NUMERO_TRAVESANOS_BALDA", "LONGITUD"])
        if e_sh + bas.B > a:
            model.note("error", "DFM-BASTIDOR-INF", "El bastidor inferior retranqueado no cabe en la sección de la pata.")
        if z_lf - bas.H < z_leg0 + 20:
            z_min = math.ceil((z_leg0 + 20 + bas.H + ts) / 5) * 5
            if ctx.params.sources.get("ALTURA_BALDA") == "defecto" and z_min <= 600 \
                    and z_min <= d["z_tf"] - d["skirt"] - 150:
                model.rule_fixes["ALTURA_BALDA"] = (
                    float(z_min), f"Balda inferior a {z_min:g} mm (regla de diseño): a la altura por defecto, {z_s:g} mm, su "
                                  "bastidor no cabía sobre las placas base y los apoyos.")
            model.note("error", "GEO-BALDA-BAJA", f"La balda está demasiado baja para el bastidor inferior: ALTURA_BALDA de "
                       f"{z_min:g} mm como mínimo.")
        ala_b = ctx["ALA_BALDA"]
        fix_sh = self._fix_layout(model, ctx, L - 2 * c, W - 2 * c, 0.0, a, ts, rs + ts, ala_b, bas, bas,
                                  z_ref=z_s, inset=e_sh, hole_d=flange_hole_d(v["MATERIAL_CHAPA"], ts, sc), rn=rn, pitch=pitch * 1.5,
                                  short_min=1, tag="balda", notch=notch, offset=c)
        fix_sh["gap"] = g_s
        flanges = []
        for e in EDGES:
            holes = tuple((s, fix_sh["h"][e], flange_hole_d(v["MATERIAL_CHAPA"], ts, sc)) for s in fix_sh["s"][e])
            flanges.append(FlangeSpec(e, ala_b, "down", holes))
        d["shelf_spec"] = SheetMetalSpec(L - 2 * c, W - 2 * c, ts, rs, Ks, tuple(flanges), notch=(notch, notch))
        d.update(z_shelf=z_s, z_lf=z_lf, e_shelf=e_sh, n_shelf=n_sh, xb=(xb0, xb1), fix_shelf=fix_sh)
        if z_s > d["z_tf"] - d["skirt"] - 150:
            model.note("advertencia", "ERG-BALDA-ALTA", "Hueco libre entre balda y encimera inferior a 150 mm.")

    def _derive_footrest(self, ctx: ParamContext, model: ProductModel, d: dict) -> None:
        """Reposapiés delantero entre patas (dentro de la operación F00)."""
        v = ctx.params.values
        a, z_leg0, shelf, bas = d["a"], d["z_leg0"], d["shelf"], d["bas"]
        d["footrest"] = None
        if v.get("REPOSAPIES"):
            fp = catalog.profile(ctx["PERFIL_REPOSAPIES"])
            zr = ctx.derive("COTA_REPOSAPIES", lambda p: p["ALTURA_REPOSAPIES"], "mm", "Cota superior del reposapiés")
            d["footrest"] = {"prof": fp, "z": zr}
            if fp.B > a:
                model.note("error", "DFM-REPOSAPIES-ANCHO", f"El perfil del reposapiés {fp.code} es más ancho que "
                           "la pata.")
            if zr - fp.H < z_leg0 + 20:
                model.note("error", "GEO-REPOSAPIES-BAJO", f"El reposapiés ({zr:g} mm) queda demasiado bajo para "
                           "soldarse a las patas por encima de la placa base.")
            if shelf:
                lo_s = d["z_shelf"] - max(ctx["ALA_BALDA"], d["z_shelf"] - d["z_lf"] + bas.H)
                above = zr - fp.H >= d["z_shelf"] + 40
                below = zr + FOOT_CLEARANCE <= lo_s
                if not (above or below):
                    z_fix = self._shelf_clear_of_footrest(ctx, d, zr, fp)
                    if z_fix is not None:
                        model.rule_fixes["ALTURA_BALDA"] = (
                            z_fix, f"Balda inferior a {z_fix:g} mm (regla de diseño): a la altura por defecto, "
                                   f"{d['z_shelf']:g} mm, chocaba con el reposapiés a {zr:g} mm.")
                    model.note("error", "GEO-REPOSAPIES-BALDA",
                               f"El reposapiés ({zr - fp.H:g}–{zr:g} mm) choca con la balda inferior o no deja "
                               f"{FOOT_CLEARANCE:g} mm para el pie bajo ella ({lo_s:g}–{d['z_shelf']:g} mm): cambie "
                               "ALTURA_REPOSAPIES o ALTURA_BALDA.")

    @staticmethod
    def _shelf_clear_of_footrest(ctx, d, zr, fp):
        """Cota de balda compatible con el reposapiés: por debajo (el pie apoya sobre él con la balda debajo) o por
        encima dejando el hueco para el pie; la más próxima a la actual. None si ninguna cabe."""
        ts, bas, z_s = d["z_shelf"] - d["z_lf"], d["bas"], d["z_shelf"]
        lo = math.floor((zr - fp.H - 40) / 5) * 5                       # balda bajo el reposapiés
        hi = math.ceil((zr + FOOT_CLEARANCE + max(ctx["ALA_BALDA"], ts + bas.H)) / 5) * 5   # balda sobre él
        ok = []
        if lo >= 100 and lo - ts - bas.H >= d["z_leg0"] + 20:
            ok.append(float(lo))
        if hi <= 600 and hi <= d["z_tf"] - d["skirt"] - 150:
            ok.append(float(hi))
        return min(ok, key=lambda z: abs(z - z_s)) if ok else None

    def _fix_layout(self, model, ctx, Lx, Ly, c, a, t, R, ala, prof_long, prof_end, z_ref, inset, hole_d, rn,
                    pitch, short_min, tag, notch=0.0, offset=0.0, ranges=None, profs=None):
        """Posiciones de fijación por borde en coordenadas de la chapa y altura del taladro.

        ``offset`` traslada coordenadas de chapa a coordenadas globales (balda situada en x=c, y=c; admite (ox, oy)).
        ``ranges`` fija, por borde, el tramo útil y el número mínimo de fijaciones {borde: (s0, s1, nmin)}.
        ``profs`` fija, por borde, el perfil sobre el que se atornilla (por defecto largueros en y0/y1)."""
        margin = 60.0
        # rango útil a lo largo de cada borde (coordenadas de chapa): sobre largueros/travesaños, fuera de patas
        long_rng = (c + a + margin, Lx - c - a - margin)
        short_rng = (c + a + margin / 2, Ly - c - a - margin / 2)

        def count(span, nmin):
            return max(nmin, math.ceil(span / pitch) + 1)

        n_long = count(long_rng[1] - long_rng[0], 2)
        n_short = count(short_rng[1] - short_rng[0], short_min)
        s = {"y0": even_positions(*long_rng, n_long), "y1": even_positions(*long_rng, n_long),
             "x0": even_positions(*short_rng, n_short), "x1": even_positions(*short_rng, n_short)}
        for e, (s0, s1, nmin) in (ranges or {}).items():
            s[e] = even_positions(s0, s1, count(s1 - s0, nmin))
        h = {}
        for e in EDGES:
            prof = (profs or {}).get(e) or (prof_long if e in ("y0", "y1") else prof_end)
            fl_lo, fl_hi = R + 2 * t + hole_d / 2, ala - max(t, 3.0) - hole_d / 2
            depth0 = t    # la cara superior del bastidor está a 't' bajo la cara superior de la chapa
            # el taladro de la remachable, al menos a RADIUS_MARGIN del radio de esquina (antes podía quedar en la
            # tangente: el cuerpo de la remachable rozaba la esquina interior del tubo)
            rail_lo = depth0 + prof.r_out + rn["hole_d"] / 2 + RADIUS_MARGIN
            rail_hi = depth0 + prof.H - prof.r_out - rn["hole_d"] / 2 - RADIUS_MARGIN
            lo, hi = max(fl_lo, rail_lo), min(fl_hi, rail_hi)
            if lo > hi:
                ala_min = max(fl_lo, rail_lo) + max(t, 3.0) + hole_d / 2
                fix = (f"Aumentar la pestaña a {ala_min:.0f} mm como mínimo" if rail_hi >= fl_lo else
                       f"El perfil {prof.code} es demasiado bajo para el taladro: usar un perfil de mayor canto")
                code = f"DFM-FIJ-{tag.split()[0].upper()}"
                if not any(n["code"] == code for n in model.design_notes):
                    model.note("error", code, f"No hay zona válida para el taladro de fijación de {tag.split()[0]}: "
                               f"pestaña de {ala:g} mm, chapa de {t:g} mm (Ri+t = {R:g} mm) y perfil {prof.code}. "
                               f"{fix}.", min_flange=round(ala_min, 1))
                h[e] = round((rail_lo + rail_hi) / 2, 1)
            else:
                h[e] = round((lo + hi) / 2, 1)
        wall = {e: ((profs or {}).get(e) or (prof_long if e in ("y0", "y1") else prof_end)).t for e in EDGES}
        return {"s": s, "h": h, "z_ref": z_ref, "t": t, "inset": inset, "offset": offset, "Lx": Lx, "Ly": Ly,
                "c": c, "wall": wall}

    # ------------------------------------------------------------------ bastidores
    def _frame_level(self, model, d, ctx, level, z_top, prof_long, prof_end, inset, n_int, legs, fixings, weld,
                     mat, fin, label=None):
        L, W = d["Lx"], d["Ly"]
        c, a = d["c"], d["a"]
        lab = label or ("superior" if level == "SUP" else "inferior")
        # ---- largueros (frontal en +X, trasero en -X para que ambos sean la misma pieza)
        zl = z_top - prof_long.H / 2
        y_f = c + inset + prof_long.B / 2
        y_b = W - c - inset - prof_long.B / 2
        x0, x1 = c + a, L - c - a
        hz = fixings["z_ref"] - fixings["h"]["y0"]
        offs = fixings["offset"]
        holes_long = tuple(("-x", s + offs - x0, hz - zl, catalog.component("TUERCA_REMACHABLE_M6")["hole_d"])
                           for s in fixings["s"]["y0"])
        lp = ProfilePart(f"larguero_{level.lower()}", f"Larguero {lab} {prof_long.code}", prof_long.code, x1 - x0,
                         mat, fin, holes=holes_long)
        lp_rear = lp
        if fixings["s"]["y1"] != fixings["s"]["y0"] or fixings["h"]["y1"] != fixings["h"]["y0"]:
            # fijaciones traseras distintas de las delanteras (p. ej. peto trasero sin fijaciones): pieza propia
            hz_b = fixings["z_ref"] - fixings["h"]["y1"]
            holes_rear = tuple(("-x", x1 - (s + offs), hz_b - zl, catalog.component("TUERCA_REMACHABLE_M6")["hole_d"])
                               for s in reversed(fixings["s"]["y1"]))
            lp_rear = ProfilePart(f"larguero_{level.lower()}", f"Larguero {lab} trasero {prof_long.code}", prof_long.code,
                                  x1 - x0, mat, fin, holes=holes_rear)
        specs = [("D", "delantero", (x0, y_f, zl), (x1, y_f, zl), "DI", "DD", lp),
                 ("T", "trasero", (x1, y_b, zl), (x0, y_b, zl), "TD", "TI", lp_rear)]
        long_ids = []
        for k, nm, p0, p1, l0, l1, part in specs:
            iid = f"EST.LAR_{level}.{k}"
            p0, p1 = np.array(p0, float), np.array(p1, float)
            model.add(iid, f"Larguero {lab} {nm}", part, G.axis_frame(p0, p1, (0, 0, 1)), "EST", axis=(p0, p1),
                      up=np.array([0, 0, 1.0]), structural=True)
            weld(f"J.{iid}.0", iid, 0, legs[l0], prof_long, f"Larguero {lab} {nm} a pata")
            weld(f"J.{iid}.1", iid, 1, legs[l1], prof_long, f"Larguero {lab} {nm} a pata")
            long_ids.append(iid)
        # ---- travesaños extremos
        ze = z_top - prof_end.H / 2
        x_l = c + inset + prof_end.B / 2
        x_r = L - c - inset - prof_end.B / 2
        y0, y1 = c + a, W - c - a
        hz = fixings["z_ref"] - fixings["h"]["x0"]
        holes_end = tuple(("+x", s + offs - y0, hz - ze, catalog.component("TUERCA_REMACHABLE_M6")["hole_d"])
                          for s in fixings["s"]["x0"])
        ep = ProfilePart(f"travesano_ext_{level.lower()}", f"Travesaño extremo {lab} {prof_end.code}", prof_end.code,
                         y1 - y0, mat, fin, holes=holes_end)
        end_ids = []
        for k, nm, p0, p1, l0, l1 in [("I", "izquierdo", (x_l, y0, ze), (x_l, y1, ze), "DI", "TI"),
                                       ("D", "derecho", (x_r, y1, ze), (x_r, y0, ze), "TD", "DD")]:
            iid = f"EST.TRV_{level}.{k}"
            p0, p1 = np.array(p0, float), np.array(p1, float)
            model.add(iid, f"Travesaño extremo {lab} {nm}", ep, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                      axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
            weld(f"J.{iid}.0", iid, 0, legs[l0], prof_end, f"Travesaño extremo {lab} {nm} a pata")
            weld(f"J.{iid}.1", iid, 1, legs[l1], prof_end, f"Travesaño extremo {lab} {nm} a pata")
            end_ids.append(iid)
        # ---- travesaños intermedios
        xs = [x_l + i * (x_r - x_l) / (n_int + 1) for i in range(1, n_int + 1)]
        yi0, yi1 = c + inset + prof_long.B, W - c - inset - prof_long.B

        def fits(n):
            """Los n travesaños no se solapan entre sí ni con las patas (si llegan a su altura en Y)."""
            pitch = (x_r - x_l) / (n + 1)
            if pitch - prof_end.B < CROSSBEAM_GAP - 1e-9:
                return False
            return not (inset + prof_long.B < a and x_l + pitch - prof_end.B / 2 < c + a + CROSSBEAM_GAP - 1e-9)
        if n_int and not fits(n_int):        # antes se generaban solapados sin aviso (sólo con valores manuales)
            n_max = max((n for n in range(n_int) if fits(n)), default=0)
            msg = (f"Los {n_int} travesaños intermedios {lab} de {prof_end.code} no caben entre los travesaños extremos "
                   f"y las patas o montantes (se solapan o no dejan {CROSSBEAM_GAP:g} mm para soldar): como máximo {n_max}.")
            if not any(n["code"] == "DFM-TRAVESANOS" and n["message"] == msg for n in model.design_notes):
                model.note("error", "DFM-TRAVESANOS", msg)
        int_ids = []
        if n_int:
            ip = ProfilePart(f"travesano_int_{level.lower()}", f"Travesaño intermedio {lab} {prof_end.code}",
                             prof_end.code, yi1 - yi0, mat, fin)
            for n, x in enumerate(xs, start=1):
                iid = f"EST.TRI_{level}.{n:02d}"
                p0, p1 = np.array([x, yi0, ze]), np.array([x, yi1, ze])
                model.add(iid, f"Travesaño intermedio {lab} {n}", ip, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                          axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
                weld(f"J.{iid}.0", iid, 0, long_ids[0], prof_end, f"Travesaño intermedio {lab} a larguero")
                weld(f"J.{iid}.1", iid, 1, long_ids[1], prof_end, f"Travesaño intermedio {lab} a larguero")
                int_ids.append(iid)
        model.structure.setdefault("levels", {})[level] = {
            "long": long_ids, "end": end_ids, "int": int_ids, "grid_x": [x_l] + xs + [x_r], "grid_y": [y_f, y_b],
            "z": z_top}

    def _fasteners(self, model, fix, group, rn, sc, ctx, prefix=None, tray_id=None):
        """Tuercas remachables en el bastidor y tornillos a través de las pestañas.

        La tuerca se elige por el espesor de pared del perfil (rango de agarre) y el tornillo por el paquete
        apretado (pestaña + holgura) con al menos 1·d de rosca útil sin sobrepasar la tuerca."""
        t, off, Lx, Ly = fix["t"], fix["offset"], fix["Lx"], fix["Ly"]
        ox, oy = off if isinstance(off, (tuple, list)) else (off, off)
        gap = fix["gap"]
        n = 0
        for e in EDGES:
            wall = fix.get("wall", {}).get(e, 2.0)
            sel_rn = catalog.select_rivet_nut(wall)
            if sel_rn is None:
                code_rn, rnd = "TUERCA_REMACHABLE_M6", catalog.component("TUERCA_REMACHABLE_M6")
            else:
                code_rn, rnd = sel_rn
            sel_sc = catalog.select_screw(t + gap, t + gap + rnd["body_l"])
            code_sc = sel_sc[0] if sel_sc else "TORNILLO_ISO7380_M6x12"
            rn_part = StandardPart("tuerca_remachable", code_rn)
            sc_part = StandardPart("tornillo", code_sc)
            for s in fix["s"][e]:
                n += 1
                z = fix["z_ref"] - fix["h"][e]
                p_flange, nrm = {"y0": ((ox + s, oy, z), (0, -1, 0)), "y1": ((ox + s, oy + Ly, z), (0, 1, 0)),
                                 "x0": ((ox, oy + s, z), (-1, 0, 0)), "x1": ((ox + Lx, oy + s, z), (1, 0, 0))}[e]
                nrm = np.array(nrm, float)
                pf = np.array(p_flange, float)
                pr = pf - nrm * (t + gap)       # cara exterior del perfil = cara interior de la pestaña + holgura
                pre = prefix or group
                sid = f"{pre}.TORN.{n:02d}"
                rid = f"{pre}.TREM.{n:02d}"
                model.add(rid, f"Tuerca remachable {n}", rn_part, frame_z(pr, nrm), group,
                          tags={"explode_extra": tuple(nrm * 30)})
                model.add(sid, f"Tornillo {n}", sc_part, frame_z(pf, nrm), group,
                          tags={"explode_extra": tuple(nrm * 80)})
                model.add_joint(Joint(f"J.{sid}", "atornillada", (tray_id or f"{group}.BANDEJA", rid), tuple(pf),
                                      f"Tornillo {sc_part.data['thread']} en tuerca remachable", fasteners=(sid, rid),
                                      data={"t_sheet": t, "gap": gap, "wall": wall, "screw": code_sc,
                                            "rivet": code_rn, "rivet_found": sel_rn is not None,
                                            "screw_found": sel_sc is not None}))

    # ------------------------------------------------------------------ modelo estructural
    def _structure(self, model, d, legs):
        ps = model.params.values
        lv = model.structure.get("levels", {})
        surfaces = [{"id": "encimera", "label": self.top_label, "level": "SUP", "load_param": "CARGA_TOTAL",
                     "sheet_instance": self.top_iid, "area_mm2": ps["LONGITUD"] * ps["ANCHURA"], **d.get("top_surface", {}),
                     "count_param": "NUMERO_TRAVESANOS"}]
        if d["shelf"]:
            surfaces.append({"id": "balda", "label": "Balda inferior", "level": "INF", "load_param": "CARGA_BALDA",
                             "sheet_instance": "BAL.BANDEJA",
                             "area_mm2": (ps["LONGITUD"] - 2 * d["c"]) * (ps["ANCHURA"] - 2 * d["c"]),
                             "count_param": "NUMERO_TRAVESANOS_BALDA"})
        feet = [{"instance": f"{self.support_group[0]}.PIE.{k}", "leg": legs[k], "point": tuple(model.instance(legs[k]).axis[0]),
                 "component": model.instance(f"{self.support_group[0]}.PIE.{k}").part.code} for k in ("DI", "DD", "TI", "TD")]
        point_loads = []
        if d.get("footrest"):
            f_n = float(ps.get("CARGA_REPOSAPIES") or FOOTREST_LOAD_N)
            point_loads.append({"id": "F", "member": "EST.REPOSAPIES", "load_N": f_n,
                                "label": "Apoyo del pie en el centro del reposapiés",
                                "hypothesis": f"Reposapiés: {f_n:g} N verticales en el centro de la barra "
                                              "(apoyo de una persona), como acción variable."})
        return {"levels": lv, "surfaces": surfaces, "supports": feet, "point_loads": point_loads,
                "horizontal_points": [legs["DI"], legs["DD"]], "worktop_height": ps["ALTURA"],
                "leg_ids": list(legs.values()), "member_roles": {
                    i.id: i.role for i in model.instances if i.structural}}
