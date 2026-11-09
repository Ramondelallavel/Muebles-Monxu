"""Familia C: estantería cantilever soldada (columnas con brazos en voladizo) para barras, tubos, perfiles y tableros.

Sistema de coordenadas: X = longitud (columnas alineadas), Y = fondo (Y=0 borde delantero de las placas base, lado de
carga de los brazos delanteros), Z = altura (Z=0 suelo).

Reglas constructivas:

* Columnas de tubo rectangular con el canto (H) en la dirección de los brazos, cerradas en cabeza con una tapa, y
  soldadas sobre una base de tubo rectangular que apoya en el suelo por sus dos extremos.
* Brazos de tubo rectangular soldados a la cara de la columna, en voladizo, con un tope vertical en la punta que impide
  que la carga ruede o resbale (o una tapa de cierre si no se quiere tope).
* Arriostramiento horizontal entre columnas a media altura y en cabeza: pórtico en la dirección longitudinal (las bases
  apoyan en dos pies alineados con ellas y no dan empotramiento en esa dirección).
* Placas base soldadas bajo los extremos de cada base, con tuerca soldada y pie nivelador en el vuelo de la placa;
  anclaje al suelo automático si el conjunto vacío volcaría con el empuje.
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..core.model import Joint, PlatePart, ProductModel, ProfilePart, StandardPart
from ..core.params import AUTO, ParamContext, ParameterSet, ParamError, ParamSpec
from .base import fabrication_specs, register
from .mesa_industrial import ALLP, ANCHORS, FEET, STRUCT_MATERIALS, MesaIndustrial, add_anchors, r10, weld_nut_code

RHS = [c for c, p in catalog.profiles().items() if p.type == "RHS"]
CANDIDATES = {
    "PERFIL_COLUMNA": ["RHS 80x40x3", "RHS 100x50x3", "RHS 100x50x4", "RHS 120x60x4", "RHS 140x80x4", "RHS 160x80x5",
                       "RHS 200x100x5", "RHS 200x100x6"],
    "PERFIL_BRAZO": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2", "RHS 60x40x3", "RHS 80x40x3",
                     "RHS 100x50x3", "RHS 100x50x4", "RHS 120x60x4"],
    "PERFIL_BASE": ["RHS 80x40x3", "RHS 100x50x3", "RHS 100x50x4", "RHS 120x60x4", "RHS 140x80x4", "RHS 160x80x5",
                    "RHS 200x100x5", "RHS 200x100x6"],
    "PERFIL_ARRIOSTRAMIENTO": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2", "RHS 80x40x3"],
}
CONSTRUCTIVE_DEFAULTS = {"PERFIL_COLUMNA": "RHS 80x40x3", "PERFIL_BRAZO": "RHS 50x30x2", "PERFIL_BASE": "RHS 80x40x3",
                         "PERFIL_ARRIOSTRAMIENTO": "RHS 40x20x2", "PIE_NIVELADOR": "PIE_NIV_M12_D80"}
#: carga de uso por defecto de cada brazo (kg por metro de brazo) cuando no se indica
ARM_LOAD_KG_M = 250.0
#: espesor de la tapa de cabeza de columna (mm)
CAP_T = 3.0
#: base trasera mínima de una cantilever de una cara (mm desde el eje de la columna)
MIN_BACK_REACH = 250.0
#: fracción de la base delantera que se prolonga hacia atrás en una cantilever de una cara ('auto')
BACK_REACH_RATIO = 0.35
#: tamaño máximo razonable de un conjunto soldado de una pieza para transporte (mm)
TRANSPORT_MAX = 2600.0
SIDES = {"D": ("delantero", -1.0), "T": ("trasero", 1.0)}


def ceil5(x: float) -> float:
    return 5.0 * math.ceil(x / 5.0 - 1e-9)


@register
class Cantilever(MesaIndustrial):
    id = "cantilever"
    name = "Estantería cantilever"
    prefix = "CV"
    category = "C"
    description = ("Estantería de columnas con brazos en voladizo, a una o dos caras, para almacenar barras, tubos, "
                   "perfiles y tableros; columnas, brazos, bases y arriostramiento dimensionados por la carga por brazo, "
                   "con tope en la punta, pies niveladores y anclaje al suelo.")
    configurations = ["Cantilever a una cara", "Cantilever a dos caras", "Almacén de barras"]
    verification_inputs = ["CARGA_POR_BRAZO"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    leg_param = "PERFIL_COLUMNA"
    frame_params = ("PERFIL_BRAZO", "PERFIL_ARRIOSTRAMIENTO")
    auto_in_construct = ("DISTANCIA_NIVELES", "LONGITUD_BASE_TRASERA", "TACO_ANCLAJE")

    # ------------------------------------------------------------------ reglas para el dimensionado
    def leg_fits(self, v) -> bool:
        """Los brazos y el arriostramiento caben en la cara de la columna (para soldarlos a su contorno)."""
        if any(v.get(k) in (AUTO, None) for k in ("PERFIL_COLUMNA", "PERFIL_BRAZO", "PERFIL_ARRIOSTRAMIENTO")):
            return True
        col = catalog.profile(v["PERFIL_COLUMNA"])
        arm, rail = catalog.profile(v["PERFIL_BRAZO"]), catalog.profile(v["PERFIL_ARRIOSTRAMIENTO"])
        return arm.B <= col.B + 1e-9 and rail.H <= col.H + 1e-9 and rail.B <= col.H + 1e-9

    def fit_profiles(self, v, prof_autos) -> bool:
        """La base es al menos tan ancha como la columna que se suelda encima (sube la base 'auto' de la serie)."""
        if "PERFIL_BASE" not in prof_autos or v.get("PERFIL_COLUMNA") in (AUTO, None):
            return False
        series, changed = self.candidates["PERFIL_BASE"], False
        if v.get("PERFIL_BASE") not in series:
            return False
        col = catalog.profile(v["PERFIL_COLUMNA"])
        while catalog.profile(v["PERFIL_BASE"]).B < col.B - 1e-9 and series.index(v["PERFIL_BASE"]) + 1 < len(series):
            v["PERFIL_BASE"] = series[series.index(v["PERFIL_BASE"]) + 1]
            changed = True
        return changed

    def sway_beam_param(self, axis: int) -> str:
        """Desplome longitudinal (X): arriostramiento entre columnas; transversal (Y): la base que empotra la columna."""
        return "PERFIL_ARRIOSTRAMIENTO" if axis == 0 else "PERFIL_BASE"

    def param_for_role(self, role):
        return {"montante": "PERFIL_COLUMNA", "brazo": "PERFIL_BRAZO", "base": "PERFIL_BASE",
                "arriostramiento": "PERFIL_ARRIOSTRAMIENTO"}.get(role)

    def default_loads(self, v):
        la = v.get("LONGITUD_BRAZO") or 0
        return {"CARGA_POR_BRAZO": (r10(ARM_LOAD_KG_M * la * 1e-3), f"{ARM_LOAD_KG_M:g} kg por metro de brazo de "
                                                                   f"{la:g} mm, repartida uniformemente")}

    def vertical_load_present(self, v):
        return bool(v.get("CARGA_POR_BRAZO"))

    def plate_targets(self, v):
        return []

    def sheet_defaults_without_load(self, v):
        return {}

    # ------------------------------------------------------------------ parámetros
    def param_specs(self) -> list[ParamSpec]:
        P = ParamSpec
        return [
            P("NUMERO_COLUMNAS", "Número de columnas", "int", 3, "ud", "dimensiones", 2, 4),
            P("SEPARACION_COLUMNAS", "Separación entre ejes de columnas", "float", 1000.0, "mm", "dimensiones", 500,
              1200, help="Las piezas largas apoyan en todos los brazos de un nivel: separación ≤ la mitad de la pieza "
                         "más corta, para que no vuelque ni flecte en exceso."),
            P("ALTURA", "Altura total", "float", 2000.0, "mm", "dimensiones", 1000, 3000),
            P("LONGITUD_BRAZO", "Longitud útil de los brazos", "float", 600.0, "mm", "dimensiones", 250, 1200,
              help="Desde la cara de la columna hasta la punta del brazo."),
            P("CARAS", "Caras con brazos", "choice", "una", None, "dimensiones", choices=["una", "dos"],
              help="'dos': brazos a ambos lados de las columnas y base simétrica."),
            P("NUMERO_NIVELES", "Número de niveles de brazos", "int", 4, "ud", "dimensiones", 1, 8),
            P("ALTURA_PRIMER_NIVEL", "Altura del primer nivel (cara superior del brazo)", "float", 400.0, "mm",
              "dimensiones", 150, 1500),
            P("DISTANCIA_NIVELES", "Distancia entre niveles", "float", AUTO, "mm", "dimensiones", 150, 1500,
              allow_auto=True, help="'auto': niveles equidistantes con el último enrasado con la cabeza de la columna."),
            P("MATERIAL_ESTRUCTURAL", "Material de la estructura", "choice", "S235JRH", None, "materiales",
              choices=STRUCT_MATERIALS),
            P("ESPESOR_PLACA_BASE", "Espesor de placa base", "float", 8.0, "mm", "materiales", 5, 15),
            P("ESPESOR_TOPE", "Espesor del tope de brazo", "float", 5.0, "mm", "materiales", 3, 10, advanced=True),
            P("ACABADO", "Acabado", "choice", "RAL5010_POLVO", None, "materiales", choices=list(catalog.finishes())),
            P("PERFIL_COLUMNA", "Perfil de columnas", "choice", AUTO, None, "construccion", choices=RHS,
              allow_auto=True, help="Tubo rectangular con el canto en la dirección de los brazos."),
            P("PERFIL_BRAZO", "Perfil de brazos", "choice", AUTO, None, "construccion", choices=ALLP, allow_auto=True),
            P("PERFIL_BASE", "Perfil de bases", "choice", AUTO, None, "construccion", choices=RHS, allow_auto=True),
            P("PERFIL_ARRIOSTRAMIENTO", "Perfil de arriostramiento", "choice", AUTO, None, "construccion",
              choices=ALLP, allow_auto=True),
            P("VUELO_BASE", "Prolongación de la base por delante de la punta del brazo", "float", 0.0, "mm",
              "construccion", 0, 300, advanced=True,
              help="Aumenta la estabilidad frente al vuelco hacia delante y protege las puntas de los brazos."),
            P("LONGITUD_BASE_TRASERA", "Base trasera desde el eje de la columna (una cara)", "float", AUTO, "mm",
              "construccion", 150, 1200, allow_auto=True, advanced=True,
              help=f"'auto': {BACK_REACH_RATIO * 100:.0f} % de la base delantera (mínimo {MIN_BACK_REACH:g} mm). A dos "
                   "caras la base es simétrica y este valor no se usa."),
            P("TOLERANCIAS", "Tolerancias generales", "choice", "ISO 2768-mK", None, "construccion",
              choices=["ISO 2768-mK", "ISO 2768-fH", "ISO 2768-cL"], advanced=True),
            P("CLASE_EJECUCION", "Clase de ejecución (EN 1090-2)", "choice", "EXC1", None, "construccion",
              choices=["EXC1", "EXC2"], advanced=True),
            P("TOPE_BRAZO", "Tope en la punta de los brazos", "bool", True, None, "accesorios",
              help="Pletina vertical soldada en la punta que impide que la carga ruede; sin tope, tapa de cierre."),
            P("ALTURA_TOPE", "Altura del tope sobre el brazo", "float", 60.0, "mm", "accesorios", 20, 200,
              advanced=True),
            P("TIPO_APOYO", "Tipo de apoyo", "choice", "pie_nivelador", None, "accesorios", choices=["pie_nivelador"]),
            P("PIE_NIVELADOR", "Pie nivelador", "choice", AUTO, None, "accesorios", choices=FEET, allow_auto=True,
              help="'auto': el de menor capacidad nominal que soporta la reacción de servicio calculada."),
            P("CARGA_POR_BRAZO", "Carga uniforme por brazo", "float", None, "kg", "cargas", 0, 1000, nullable=True,
              help=f"Repartida a lo largo del brazo. Sin indicar: {ARM_LOAD_KG_M:g} kg por metro de brazo."),
            P("CARGA_HORIZONTAL", "Empuje horizontal en cabeza", "float", 300.0, "N", "cargas", 0, 5000),
            P("ANCLAJE", "Anclaje", "choice", "ninguno", None, "cargas", choices=["ninguno", "al_suelo"],
              help="'ninguno' por defecto: si el conjunto vacío volcara con el empuje, se ancla automáticamente."),
            P("TACO_ANCLAJE", "Taco de anclaje", "choice", AUTO, None, "cargas", choices=ANCHORS, allow_auto=True,
              help="'auto': el de menor capacidad que resiste la tracción de cálculo (sólo con anclaje al suelo)."),
            P("ENTORNO", "Entorno", "choice", "interior_seco", None, "cargas",
              choices=["interior_seco", "interior_humedo", "exterior"]),
            P("TIPO_SUELO", "Tipo de suelo", "choice", "nivelado", None, "cargas", choices=["nivelado", "irregular"]),
        ] + fabrication_specs()

    def templates(self):
        return [
            {"id": "CV-3-2000-600", "name": "Cantilever de 3 columnas, 4 niveles de brazos de 600 mm", "family": self.id,
             "values": {"NUMERO_COLUMNAS": 3, "SEPARACION_COLUMNAS": 1000.0, "ALTURA": 2000.0, "LONGITUD_BRAZO": 600.0,
                        "NUMERO_NIVELES": 4, "CARGA_POR_BRAZO": 150.0, "ANCLAJE": "al_suelo"}},
            {"id": "CV-2-1500-400-TALLER", "name": "Cantilever de taller para barras (2 columnas, brazos de 400 mm)",
             "family": self.id,
             "values": {"NUMERO_COLUMNAS": 2, "SEPARACION_COLUMNAS": 800.0, "ALTURA": 1500.0, "LONGITUD_BRAZO": 400.0,
                        "NUMERO_NIVELES": 4, "ALTURA_PRIMER_NIVEL": 300.0, "CARGA_POR_BRAZO": 80.0,
                        "ANCLAJE": "al_suelo", "ACABADO": "RAL7035_POLVO"}},
            {"id": "CV-3-2500-800-DOBLE", "name": "Cantilever a dos caras de 3 columnas, brazos de 800 mm",
             "family": self.id,
             "values": {"NUMERO_COLUMNAS": 3, "SEPARACION_COLUMNAS": 1000.0, "ALTURA": 2500.0, "LONGITUD_BRAZO": 800.0,
                        "CARAS": "dos", "NUMERO_NIVELES": 4, "CARGA_POR_BRAZO": 200.0, "ANCLAJE": "al_suelo"}},
            {"id": "CV-4-2200-1000-TABLEROS", "name": "Cantilever para tableros (4 columnas, brazos de 1.000 mm)",
             "family": self.id,
             "values": {"NUMERO_COLUMNAS": 4, "SEPARACION_COLUMNAS": 800.0, "ALTURA": 2200.0, "LONGITUD_BRAZO": 1000.0,
                        "NUMERO_NIVELES": 3, "ALTURA_PRIMER_NIVEL": 500.0, "CARGA_POR_BRAZO": 250.0,
                        "VUELO_BASE": 100.0, "ANCLAJE": "al_suelo"}},
        ]

    # ------------------------------------------------------------------ construcción
    def construct(self, ps: ParameterSet) -> ProductModel:
        for k, v in ps.values.items():
            if v == AUTO and k not in self.auto_in_construct:
                raise ValueError(f"Parámetro sin resolver: {k}")
        ctx = ParamContext(ps)
        nc, S, H = ps.values["NUMERO_COLUMNAS"], ps.values["SEPARACION_COLUMNAS"], ps.values["ALTURA"]
        La = ps.values["LONGITUD_BRAZO"]
        model = ProductModel(self.id, self.name, f"{self.prefix}{nc}-{H:.0f}-{La:.0f}"
                             + ("-D" if ps.values["CARAS"] == "dos" else ""), ps, ctx)
        model.requested = ps
        d = self._derive_cv(ctx, model)
        mat_s, fin = ps.values["MATERIAL_ESTRUCTURAL"], ps.values["ACABADO"]
        col, arm, base, rail = d["col"], d["arm"], d["base"], d["rail"]
        model.add_subassembly("EST", "Estructura soldada", welded=True, step=1)
        g = self.support_group[0]
        model.add_subassembly(g, self.support_group[1], explode=(0, 0, -160), step=2)
        foot = catalog.component(ps.values[self.support_param])
        thread = float(foot["thread"][1:])
        nut_code = weld_nut_code(thread, mat_s)
        weld = self._make_welder(model, d)
        wa = d["weld_a"]
        sides = d["sides"]
        cols: dict[int, str] = {}
        corners: dict[str, tuple[float, float]] = {}
        cname: dict[str, str] = {}
        plate_mat = "S235JR" if catalog.material(mat_s).family == "acero_carbono" else mat_s
        with ctx.feature("F10", "Estructura soldada"):
            for c in range(1, nc + 1):
                x = d["xs"][c - 1]
                with ctx.feature(f"F1{c}", f"Columna {c}: base, placas, columna y brazos"):
                    ctx.uses("PERFIL_COLUMNA", "PERFIL_BASE", "PERFIL_BRAZO", "ALTURA", "LONGITUD_BRAZO", "CARAS",
                             "VUELO_BASE", "LONGITUD_BASE_TRASERA", "ESPESOR_PLACA_BASE", self.support_param,
                             "SEPARACION_COLUMNAS", "MATERIAL_ESTRUCTURAL", "ACABADO", "TOPE_BRAZO", "ALTURA_TOPE",
                             "ESPESOR_TOPE")
                    # base: viga a lo largo de Y sobre las dos placas; su eje de cálculo va de pie a pie
                    bid = f"EST.BASE.C{c}"
                    zb = d["z_base0"] + base.H / 2
                    p0, p1 = np.array([x, d["y_base0"], zb]), np.array([x, d["y_base1"], zb])
                    model.add(bid, f"Base de la columna {c}",
                              ProfilePart("base", f"Base {base.code}", base.code, d["base_len"], mat_s, fin),
                              G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                              axis=(np.array([x, d["y_foot"]["D"], zb]), np.array([x, d["y_foot"]["T"], zb])),
                              up=np.array([0, 0, 1.0]), structural=True)
                    # columna sobre la base, con tapa en cabeza
                    cid = f"EST.COL.C{c}"
                    q0, q1 = np.array([x, d["yc"], d["z_col0"]]), np.array([x, d["yc"], d["z_col1"]])
                    model.add(cid, f"Columna {c}",
                              ProfilePart("montante", f"Columna {col.code}", col.code, d["col_len"], mat_s, fin),
                              G.axis_frame(q0, q1, (0, 1, 0)), "EST", axis=(q0, q1), up=np.array([0, 1.0, 0]),
                              structural=True)
                    cols[c] = cid
                    weld(f"J.{cid}.0", cid, 0, bid, col, "Columna a base")
                    cap = PlatePart("tapa_columna", f"Tapa de columna {col.B:.0f}x{col.H:.0f}x{CAP_T:g}", col.B, col.H,
                                    CAP_T, plate_mat, fin)
                    model.add(f"EST.TAPA.C{c}", f"Tapa de la columna {c}", cap,
                              G.translation(x - col.B / 2, d["yc"] - col.H / 2, d["z_col1"]), "EST")
                    model.add_joint(Joint(f"J.TAPA.C{c}", "soldadura", (f"EST.TAPA.C{c}", cid),
                                          (x, d["yc"], d["z_col1"]), "Tapa a columna",
                                          weld={"type": "fillet", "a": wa(min(col.t, CAP_T)), "all_around": True,
                                                "process": "135 (MAG)",
                                                "length": round(2 * (col.B + col.H), 1)}))
                    # placas base con tuerca soldada en el vuelo, delante y detrás
                    pw, pl, tp = d["plate_w"], d["plate_l"], d["tp"]
                    plate = PlatePart("placa_base", f"Placa base {pw:.0f}x{pl:.0f}x{tp:g}", pw, pl, tp, plate_mat, fin,
                                      corner_r=min(3.0, pw / 10),
                                      holes=((pw / 2, d["foot_off"], thread + 1.0),))
                    for s, (sname, sgn) in SIDES.items():
                        k = f"C{c}{s}"
                        yf = d["y_foot"][s]
                        corners[k] = (x, yf)
                        cname[k] = f"{sname} de la columna {c}"
                        # placa: el taladro del pie a foot_off del borde exterior (Y local hacia el interior)
                        if s == "D":
                            T = G.translation(x - pw / 2, yf - d["foot_off"], d["hn"])
                        else:
                            T = G.frame((x + pw / 2, yf + d["foot_off"], d["hn"]), (-1, 0, 0), (0, -1, 0))
                        model.add(f"EST.PLACA.{k}", f"Placa base {sname} de la columna {c}", plate, T, "EST")
                        model.add_joint(Joint(f"J.PLACA.{k}", "soldadura", (bid, f"EST.PLACA.{k}"),
                                              (x, d["y_base0"] if s == "D" else d["y_base1"], d["z_base0"]),
                                              "Placa base a base",
                                              weld={"type": "fillet", "a": wa(min(base.t, tp)), "all_around": False,
                                                    "process": "135 (MAG)",
                                                    "length": round(2 * d["plate_in"] + base.B, 1),
                                                    "note": "Cordón en U: laterales y testa de la base"}))
                        model.add(f"EST.TUERCA.{k}", f"Tuerca soldada {sname} de la columna {c}",
                                  StandardPart("tuerca_soldar", nut_code), G.translation(x, yf, d["hn"] + tp), "EST")
                        ns = float(catalog.component(nut_code)["s"])
                        model.add_joint(Joint(f"J.TUERCA.{k}", "soldadura", (f"EST.TUERCA.{k}", f"EST.PLACA.{k}"),
                                              (x, yf, d["hn"] + tp), "Tuerca de soldar a placa base",
                                              weld={"type": "fillet", "a": 2.0, "all_around": False,
                                                    "process": "135 (MAG)", "length": round(3 * ns / math.sqrt(3), 1),
                                                    "note": "3 cordones en caras alternas de la tuerca"}))
                    # brazos en voladizo con su tope
                    for i, z in enumerate(d["z_levels"], start=1):
                        zc = z - arm.H / 2
                        for s in sides:
                            sname, sgn = SIDES[s]
                            aid = f"EST.BRAZO.C{c}.N{i}.{s}"
                            y_root = d["yc"] + sgn * col.H / 2
                            y_tip = y_root + sgn * La
                            a0, a1 = np.array([x, y_root, zc]), np.array([x, y_tip, zc])
                            model.add(aid, f"Brazo {sname} de la columna {c} (nivel {i})",
                                      ProfilePart("brazo", f"Brazo {arm.code}", arm.code, La, mat_s, fin),
                                      G.axis_frame(a0, a1, (0, 0, 1)), "EST", axis=(a0, a1),
                                      up=np.array([0, 0, 1.0]), structural=True)
                            weld(f"J.{aid}.0", aid, 0, cid, arm, "Brazo a columna")
                            stop = d["stop"]
                            sid = f"EST.TOPE.C{c}.N{i}.{s}"
                            zb_arm = z - arm.H
                            if s == "D":
                                Tst = G.frame((x - arm.B / 2, y_tip, zb_arm), (1, 0, 0), (0, 0, 1))
                            else:
                                Tst = G.frame((x + arm.B / 2, y_tip, zb_arm), (-1, 0, 0), (0, 0, 1))
                            model.add(sid, f"{'Tope' if d['has_stop'] else 'Tapa'} del brazo {sname} de la columna {c} "
                                      f"(nivel {i})", stop, Tst, "EST")
                            model.add_joint(Joint(f"J.TOPE.C{c}.N{i}.{s}", "soldadura", (sid, aid), (x, y_tip, zc),
                                                  "Tope a punta de brazo" if d["has_stop"] else "Tapa a punta de brazo",
                                                  weld={"type": "fillet", "a": wa(min(arm.t, stop.t)),
                                                        "all_around": True, "process": "135 (MAG)",
                                                        "length": round(2 * (arm.B + arm.H), 1)}))
            # arriostramiento entre columnas (a media altura y en cabeza)
            with ctx.feature("F20", "Arriostramiento entre columnas"):
                ctx.uses("PERFIL_ARRIOSTRAMIENTO", "SEPARACION_COLUMNAS", "PERFIL_COLUMNA", "ALTURA", "NUMERO_COLUMNAS")
                for c in range(1, nc):
                    x0, x1 = d["xs"][c - 1] + col.B / 2, d["xs"][c] - col.B / 2
                    for j, zr in enumerate(d["z_rails"], start=1):
                        rid = f"EST.ARR.C{c}.{j}"
                        r0, r1 = np.array([x0, d["yc"], zr]), np.array([x1, d["yc"], zr])
                        model.add(rid, f"Arriostramiento {'superior' if j == len(d['z_rails']) else 'intermedio'} "
                                  f"entre columnas {c} y {c + 1}",
                                  ProfilePart("arriostramiento", f"Arriostramiento {rail.code}", rail.code, x1 - x0,
                                              mat_s, fin),
                                  G.axis_frame(r0, r1, (0, 0, 1)), "EST", axis=(r0, r1), up=np.array([0, 0, 1.0]),
                                  structural=True)
                        weld(f"J.{rid}.0", rid, 0, cols[c], rail, "Arriostramiento a columna")
                        weld(f"J.{rid}.1", rid, 1, cols[c + 1], rail, "Arriostramiento a columna")
        with ctx.feature("F40", self.support_group[1]):
            ctx.uses(self.support_param, "NUMERO_COLUMNAS", "SEPARACION_COLUMNAS", "LONGITUD_BRAZO")
            for k, (x, y) in corners.items():
                fpart, fname = self._support_part(k, ps)
                model.add(f"{g}.PIE.{k}", f"{fname} {cname[k]}", fpart, G.translation(x, y, 0.0), g)
                model.add_joint(Joint(f"J.PIE.{k}", "roscada", (f"{g}.PIE.{k}", f"EST.TUERCA.{k}"), (x, y, d["hn"]),
                                      f"Pie roscado {foot['thread']} en tuerca soldada"))
            add_anchors(model, ps, corners, cname, g)
        model.structure = self._cv_structure(model, d, cols, corners)
        q = ps.values.get("CARGA_POR_BRAZO")
        n_arms = nc * len(d["z_levels"]) * len(sides)
        n = len(d["z_levels"])
        env_ids = [i.id for i in model.instances if i.group == "EST"]
        model.dims = {
            "NUMERO_COLUMNAS": nc, "ALTURA": H, "LONGITUD_BRAZO": La,
            "envelope": {"ids": env_ids, "dx": d["dx"], "dy": d["dy"], "zmax": H, "names": ("LONGITUD", "FONDO")},
            "levels": [(f"NIVEL_{i}", f"EST.BRAZO.C1.N{i}.{sides[0]}", z) for i, z in enumerate(d["z_levels"], start=1)],
            "drawing_expected": {**{f"DIST_NIVEL_{k + 1}": (d["z_levels"][0] if k == 0 else d["z_levels"][k] -
                                                            d["z_levels"][k - 1]) for k in range(n)},
                                 **{f"PASO_COLUMNA_{c}": S for c in range(1, nc)},
                                 "LONGITUD_BRAZO": La},
            "structure_profile": [(d["yc"] - col.H / 2 - La, d["yc"] - col.H / 2, "LONGITUD_BRAZO")],
            "structure_notes": ["Estructura soldada (subconjunto EST).",
                                f"Clase de ejecución {ps.values['CLASE_EJECUCION']} según EN 1090-2.",
                                "Cotas a caras exteriores de perfil.",
                                "Brazos perpendiculares a la columna (±1 mm en la punta) y alineados entre columnas "
                                "(desnivel ≤ 2 mm por nivel).",
                                "Detalle de uniones soldadas: plano 05.",
                                "Longitudes de corte y mecanizados: plano 02B."],
            "load_text": (f"Carga uniforme por brazo de proyecto: {q:g} kg ({n_arms} brazos, total {n_arms * q:g} kg)"
                          if q else ("Sin carga de uso (0 kg por brazo)" if q == 0 else "Carga por brazo: NO DEFINIDA")),
        }
        for i, z in enumerate(d["z_levels"], start=1):
            model.dims[f"NIVEL_{i}"] = z
        if max(d["dx"], H) > TRANSPORT_MAX:
            model.note("advertencia", "DFM-TRANSPORTE",
                       f"Conjunto soldado de una pieza de {d['dx']:.0f} × {d['dy']:.0f} × {H:.0f} mm: prever el "
                       "transporte y el acceso al emplazamiento (o fabricarlo en dos tramos).")
        model.number_parts()
        return model

    # ------------------------------------------------------------------ derivados
    def _derive_cv(self, ctx: ParamContext, model: ProductModel) -> dict:
        v = ctx.params.values
        d: dict = {}
        with ctx.feature("F00", "Parámetros derivados y reglas constructivas"):
            col = catalog.profile(ctx["PERFIL_COLUMNA"])
            arm = catalog.profile(ctx["PERFIL_BRAZO"])
            base = catalog.profile(ctx["PERFIL_BASE"])
            rail = catalog.profile(ctx["PERFIL_ARRIOSTRAMIENTO"])
            sp = self.support_param
            foot = catalog.component(ctx[sp])
            thread = float(foot["thread"][1:])
            nut = catalog.component(weld_nut_code(thread, v["MATERIAL_ESTRUCTURAL"]))
            hn, tp = float(foot["nominal_height"]), ctx["ESPESOR_PLACA_BASE"]
            nc, S, H, La = ctx["NUMERO_COLUMNAS"], ctx["SEPARACION_COLUMNAS"], ctx["ALTURA"], ctx["LONGITUD_BRAZO"]
            two = ctx["CARAS"] == "dos"
            sides = ("D", "T") if two else ("D",)
            if base.B < col.B - 1e-9:
                model.note("error", "DFM-BASE-COLUMNA", f"La base {base.code} ({base.B:g} mm) es más estrecha que la "
                           f"columna {col.code} ({col.B:g} mm): use una base al menos tan ancha (o 'auto').")
            if arm.B > col.B + 1e-9:
                model.note("error", "DFM-BRAZO-COLUMNA", f"El brazo {arm.code} ({arm.B:g} mm) es más ancho que la cara "
                           f"de la columna {col.code} ({col.B:g} mm): no puede soldarse a su contorno.")
            if rail.H > col.H + 1e-9 or rail.B > col.H + 1e-9:
                model.note("error", "DFM-ARRIOSTRAMIENTO", f"El arriostramiento {rail.code} no cabe en el canto de la "
                           f"columna {col.code}.")
            # pie en el vuelo de la placa: la tuerca (entre caras) no toca la base y queda margen de soldadura
            nut_ac = float(nut["s"]) / math.cos(math.pi / 6)
            # del borde exterior de la placa al eje del pie: la tuerca con margen y la base del pie sin sobresalir
            foot_off = ceil5(max(nut_ac / 2 + 8, float(foot["base_d"]) / 2))
            plate_out = ceil5(foot_off + nut_ac / 2 + 8)   # vuelo de la placa más allá de la testa de la base
            plate_in = 50.0                               # apoyo de la base sobre la placa
            plate_w = max(ceil5(base.B + 20), ceil5(nut_ac + 20), ceil5(float(foot["base_d"])))
            plate_l = plate_out + plate_in
            ctx.set_derived("VUELO_PLACA_BASE", plate_out, "mm", "Vuelo de la placa base más allá de la base",
                            [sp, "PERFIL_BASE", "MATERIAL_ESTRUCTURAL"])
            reach_f = ctx.derive("BASE_DELANTERA", lambda p: catalog.profile(p["PERFIL_COLUMNA"]).H / 2 +
                                 p["LONGITUD_BRAZO"] + p["VUELO_BASE"], "mm",
                                 "Base delantera desde el eje de la columna (hasta la testa)")
            if two:
                reach_b = ctx.derive("BASE_TRASERA", lambda p: p["BASE_DELANTERA"], "mm",
                                     "Base trasera desde el eje de la columna (simétrica a dos caras)")
            else:
                reach_b = ctx.derive("BASE_TRASERA", lambda p: round(max(MIN_BACK_REACH, BACK_REACH_RATIO *
                                                                         p["BASE_DELANTERA"]), 0)
                                     if p["LONGITUD_BASE_TRASERA"] == AUTO else p["LONGITUD_BASE_TRASERA"], "mm",
                                     "Base trasera desde el eje de la columna")
                if reach_b < col.H / 2 + plate_in:
                    raise ParamError(f"LONGITUD_BASE_TRASERA de {reach_b:g} mm: menor que la media columna más el apoyo "
                                     f"de la placa ({col.H / 2 + plate_in:g} mm).")
            yc = plate_out + reach_f
            y_base0, y_base1 = yc - reach_f, yc + reach_b
            y_foot = {"D": foot_off, "T": y_base1 + plate_out - foot_off}
            z_base0 = hn + tp
            z_col0 = z_base0 + base.H
            z_col1 = H - CAP_T
            col_len = ctx.derive("LONGITUD_COLUMNA", lambda p: round(p["ALTURA"] - CAP_T - z_col0, 3), "mm",
                                 "Longitud de corte de columna")
            base_len = ctx.derive("LONGITUD_BASE", lambda p: p["BASE_DELANTERA"] + p["BASE_TRASERA"], "mm",
                                  "Longitud de corte de base")
            n = ctx["NUMERO_NIVELES"]
            z1 = ctx["ALTURA_PRIMER_NIVEL"]
            has_stop = bool(ctx["TOPE_BRAZO"])
            # el tope del último nivel queda enrasado con la cabeza de la columna
            z_max = ctx.derive("COTA_MAX_NIVEL", lambda p: p["ALTURA"] - (p["ALTURA_TOPE"] if p["TOPE_BRAZO"] else 0.0),
                               "mm", "Cota máxima de la cara superior del último nivel")
            dist = ctx.derive("PASO_NIVELES", lambda p: ((p["COTA_MAX_NIVEL"] - p["ALTURA_PRIMER_NIVEL"]) /
                                                         (p["NUMERO_NIVELES"] - 1) if p["NUMERO_NIVELES"] > 1 else 0.0)
                              if p["DISTANCIA_NIVELES"] == AUTO else p["DISTANCIA_NIVELES"], "mm",
                              "Distancia entre niveles de brazos")
            zs = [ctx.derive(f"COTA_NIVEL_{i + 1}", lambda p, i=i: p["ALTURA_PRIMER_NIVEL"] + i * p["PASO_NIVELES"],
                             "mm", f"Cota cara superior de los brazos del nivel {i + 1}") for i in range(n)]
            if zs[-1] > z_max + 1e-6 * H:
                raise ParamError(f"Los {n} niveles a {dist:g} mm superan la altura útil de {z_max:g} mm (altura total "
                                 f"menos el tope): reduzca DISTANCIA_NIVELES a {math.floor((z_max - z1) / max(n - 1, 1)):.0f} "
                                 "mm o menos, o use 'auto'.")
            if z1 > z_max + 1e-9:
                raise ParamError(f"ALTURA_PRIMER_NIVEL de {z1:g} mm por encima de la altura útil de {z_max:g} mm.")
            if n > 1 and dist < arm.H + 100:
                raise ParamError(f"Distancia entre niveles de {dist:.0f} mm: menor que el canto del brazo más 100 mm "
                                 f"de hueco ({arm.H + 100:g} mm).")
            if zs[0] - arm.H < z_col0 + 20:
                z1_min = ceil5(z_col0 + 20 + arm.H)
                fits = ctx["DISTANCIA_NIVELES"] == AUTO or z1_min + (n - 1) * dist <= H
                if z1_min <= 1500 and fits:
                    model.rule_fixes["ALTURA_PRIMER_NIVEL"] = (
                        float(z1_min), f"Primer nivel a {z1_min:g} mm (regla de diseño): a {z1:g} mm el brazo no cabía "
                                       "sobre la base y los apoyos.")
                model.note("error", "GEO-NIVEL-BAJO", f"El primer nivel de brazos está demasiado bajo: "
                           f"ALTURA_PRIMER_NIVEL de {z1_min:g} mm como mínimo.")
            if n > 1:
                ctx.set_derived("HUECO_LIBRE", round(dist - arm.H, 1), "mm", "Altura libre entre niveles de brazos",
                                ["DISTANCIA_NIVELES", "ALTURA", "NUMERO_NIVELES", "PERFIL_BRAZO"])
            # arriostramiento: en cabeza y a media altura de la columna
            z_top_rail = z_col1 - rail.H / 2
            z_mid_rail = z_col0 + 0.5 * (z_col1 - z_col0)
            z_rails = [z_mid_rail, z_top_rail] if z_top_rail - z_mid_rail > rail.H + 100 else [z_top_rail]
            t_stop = ctx["ESPESOR_TOPE"]
            h_stop = arm.H + (ctx["ALTURA_TOPE"] if has_stop else 0.0)
            plate_mat = "S235JR" if catalog.material(v["MATERIAL_ESTRUCTURAL"]).family == "acero_carbono" \
                else v["MATERIAL_ESTRUCTURAL"]
            stop = PlatePart("tope_brazo" if has_stop else "tapa_brazo",
                             f"{'Tope' if has_stop else 'Tapa'} de brazo {arm.B:.0f}x{h_stop:.0f}x{t_stop:g}", arm.B,
                             h_stop, t_stop, plate_mat, v["ACABADO"], corner_r=min(3.0, arm.B / 10) if has_stop else 0.0)
            wmax = max(col.B, base.B, plate_w, arm.B)
            xs = [wmax / 2 + c * S for c in range(nc)]          # X=0 en el canto izquierdo del conjunto
            dx = (nc - 1) * S + wmax
            # el vuelo de la placa (≥ 30 mm) es mayor que el tope: la punta de los brazos nunca sale de las placas
            dy = y_base1 + plate_out
            d.update(col=col, arm=arm, base=base, rail=rail, hn=hn, tp=tp, sides=sides, two=two, foot_off=foot_off,
                     plate_out=plate_out, plate_in=plate_in, plate_w=plate_w, plate_l=plate_l, yc=yc,
                     y_base0=y_base0, y_base1=y_base1, y_foot=y_foot, z_base0=z_base0, z_col0=z_col0, z_col1=z_col1,
                     col_len=col_len, base_len=base_len, z_levels=zs, z_rails=z_rails, stop=stop, has_stop=has_stop,
                     xs=xs, dx=dx, dy=dy, reach_f=reach_f, reach_b=reach_b)
            d["weld_a"] = lambda tmin: 3.0 if tmin >= 3 else float(tmin)
        return d

    def _cv_structure(self, model, d, cols, corners):
        g = self.support_group[0]
        sups = []
        for k in corners:
            c = int(k[1:-1])
            base = model.instance(f"EST.BASE.C{c}")
            pt = base.axis[0] if k.endswith("D") else base.axis[1]
            sups.append({"instance": f"{g}.PIE.{k}", "leg": base.id, "point": tuple(float(t) for t in pt),
                         "component": model.instance(f"{g}.PIE.{k}").part.code})
        H = model.params.values["ALTURA"]
        arms = [i.id for i in model.instances if i.role == "brazo"]
        col_h = d["col"].H
        line_loads = []
        for aid in arms:
            inst = model.instance(aid)
            y0, y1 = sorted((float(inst.axis[0][1]), float(inst.axis[1][1])))
            side = aid.rsplit(".", 1)[1]
            line_loads.append({"member": aid, "load_param": "CARGA_POR_BRAZO", "axis": 1, "span": (y0, y1),
                               "side": side})
        return {"levels": {}, "surfaces": [], "supports": sups, "line_loads": line_loads, "cantilevers": arms,
                "line_load_label": "Carga uniforme por brazo", "line_load_side_label": "brazos delanteros",
                "push_points": [{"member": cid, "z": H} for cid in cols.values()],
                "push_label": "Empuje horizontal en cabeza de columnas (direcciones X e Y)",
                "push_where": "en cabeza de columnas",
                "worktop_height": H, "push_height": H, "sway_height": H,
                "leg_ids": list(cols.values()), "product_word": "estantería",
                "member_roles": {i.id: i.role for i in model.instances if i.structural},
                "nuts_inside_legs": False,
                "dfm_weld_notes": [
                    ("SOL-DEFORMACION", "Estructura soldada", "Riesgo de distorsión de las columnas al soldar los brazos "
                     "por una cara: puntear con plantilla de nivel, soldar alternando niveles y caras y verificar la "
                     "perpendicularidad y el nivel de los brazos entre columnas (EN ISO 13920 clase F).")],
                "weld_details": [(f"J.EST.BRAZO.C1.N1.{d['sides'][0]}.0", (), "DETALLE A: BRAZO–COLUMNA", 70),
                                 ("J.EST.COL.C1.0", ("EST.PLACA.C1D",), "DETALLE B: COLUMNA–BASE", 70)],
                "weld_sequence": ("Secuencia: 1) puntear las bases sobre las placas base y soldar las tuercas; 2) puntear "
                                  "las columnas a escuadra sobre las bases; 3) puntear los brazos con plantilla de "
                                  "nivel y verificar su alineación entre columnas; 4) arriostramiento; 5) soldar "
                                  "alternando lados; 6) topes y tapas; 7) enderezar y verificar plomo y nivel."),
                "assembly_texts": {
                    "EST": "Recepción de la estructura soldada y pintada. Colocarla en su emplazamiento con los brazos "
                           "hacia la zona de carga, sin cargarla.",
                    "APO": "Roscar los pies niveladores en las tuercas soldadas de las placas base. Nivelar los brazos "
                           "(nivel de burbuja sobre los brazos de un mismo nivel) y anclar al suelo antes de cargar."},
                "assembly_notes": ["HERRAMIENTAS:", "· Llave fija 17/19 para contratuerca de pies", "· Nivel de burbuja",
                                   "· Taladro percutor y llave para los tacos de anclaje", "",
                                   "CARGA:", "· Repartir la carga por igual entre los brazos de un nivel",
                                   "· Cargar de abajo arriba y descargar de arriba abajo",
                                   "· Piezas largas apoyadas al menos en dos brazos", "",
                                   "SEGURIDAD:", "Señalizar la carga máxima por brazo en cada columna (EN 15635).",
                                   "No trepar por los brazos."]}
