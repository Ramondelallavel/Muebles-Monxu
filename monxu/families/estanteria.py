"""Familia C: estantería industrial soldada de N niveles con bandejas de chapa plegada.

Sistema de coordenadas: X = anchura (frente), Y = profundidad (Y=0 frente de carga), Z = altura.

Reglas constructivas:

* Cuatro montantes de tubo cuadrado en las esquinas, enrasados con el contorno exterior.
* En cada nivel, un bastidor soldado (largueros delantero y trasero, travesaños laterales y
  travesaños intermedios dimensionados por el cálculo de la chapa) retranqueado ``t + holgura``
  respecto a la cara exterior de los montantes, para que las pestañas de la bandeja queden
  enrasadas con ellos.
* Bandeja de chapa plegada con pestañas hacia abajo y escotaduras alrededor de los montantes,
  atornillada al bastidor mediante tuercas remachables.
* Placas base con tuerca soldada y pie nivelador; anclaje al suelo opcional (sólo se calcula
  la tracción: la capacidad del anclaje queda pendiente de verificar).
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..cad.sheetmetal import EDGES, FlangeSpec, SheetMetalSpec, bend_deduction
from ..core.model import Joint, PlatePart, ProductModel, ProfilePart, SheetPart, StandardPart
from ..core.params import AUTO, ParamContext, ParameterSet, ParamSpec
from .base import register
from .mesa_industrial import ALLP, FEET, SHEET_MATERIALS, SHS, STRUCT_MATERIALS, MesaIndustrial

CANDIDATES = {
    "PERFIL_MONTANTE": ["SHS 40x40x2", "SHS 40x40x3", "SHS 50x50x2", "SHS 50x50x3", "SHS 60x60x3", "SHS 70x70x3",
                        "SHS 80x80x3", "SHS 80x80x4"],
    "PERFIL_LARGUERO": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2", "RHS 80x40x2", "RHS 60x40x3",
                        "RHS 80x40x3"],
    "PERFIL_TRAVESANO": ["RHS 40x20x2", "RHS 50x30x2", "RHS 60x30x2", "RHS 60x40x2"],
}
CONSTRUCTIVE_DEFAULTS = {"PERFIL_MONTANTE": "SHS 40x40x2", "PERFIL_LARGUERO": "RHS 40x20x2",
                         "PERFIL_TRAVESANO": "RHS 40x20x2", "ESPESOR_BALDA": 1.5}


@register
class Estanteria(MesaIndustrial):
    id = "estanteria"
    name = "Estantería industrial"
    prefix = "ES"
    category = "C"
    description = ("Estantería de montantes tubulares con N niveles de bandejas de chapa plegada sobre bastidores "
                   "soldados, dimensionada por la carga por nivel; pies niveladores y anclaje opcional.")
    configurations = ["Estantería ligera", "Estantería media", "Estantería multinivel"]
    verification_inputs = ["CARGA_POR_NIVEL"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    leg_param = "PERFIL_MONTANTE"
    frame_params = ("PERFIL_LARGUERO", "PERFIL_TRAVESANO")
    auto_in_construct = ("RADIO_PLEGADO", "FACTOR_K", "NUMERO_TRAVESANOS_BALDA", "HOLGURA_BALDA", "DISTANCIA_BALDAS")

    def param_for_role(self, role):
        if role == "montante":
            return "PERFIL_MONTANTE"
        if role.startswith("larguero"):
            return "PERFIL_LARGUERO"
        if role.startswith("travesano"):
            return "PERFIL_TRAVESANO"
        return None

    def vertical_load_present(self, v):
        return bool(v.get("CARGA_POR_NIVEL"))

    def plate_targets(self, v):
        if not v.get("CARGA_POR_NIVEL"):
            return []
        return [{"surface": "N1", "t_param": "ESPESOR_BALDA", "n_param": "NUMERO_TRAVESANOS_BALDA",
                 "load_param": "CARGA_POR_NIVEL", "trv_param": "PERFIL_TRAVESANO", "min_t_by_use": False}]

    def sheet_defaults_without_load(self, v):
        return {} if v.get("CARGA_POR_NIVEL") else {"ESPESOR_BALDA": CONSTRUCTIVE_DEFAULTS["ESPESOR_BALDA"]}

    # ------------------------------------------------------------------ parámetros
    def param_specs(self) -> list[ParamSpec]:
        P = ParamSpec
        return [
            P("ANCHURA", "Anchura (frente)", "float", 1500.0, "mm", "dimensiones", 600, 3000),
            P("PROFUNDIDAD", "Profundidad (fondo)", "float", 600.0, "mm", "dimensiones", 300, 1200),
            P("ALTURA", "Altura total", "float", 2000.0, "mm", "dimensiones", 800, 3000),
            P("NUMERO_NIVELES", "Número de niveles", "int", 5, "ud", "dimensiones", 2, 8),
            P("ALTURA_PRIMER_NIVEL", "Altura del primer nivel (cara superior)", "float", 150.0, "mm", "dimensiones",
              100, 800),
            P("DISTANCIA_BALDAS", "Distancia entre niveles", "float", AUTO, "mm", "dimensiones", 150, 1500,
              allow_auto=True, help="'auto': niveles equidistantes hasta la altura total."),
            P("MATERIAL_ESTRUCTURAL", "Material de la estructura", "choice", "S235JRH", None, "materiales",
              choices=STRUCT_MATERIALS),
            P("MATERIAL_CHAPA", "Material de chapa", "choice", "S235JR", None, "materiales", choices=SHEET_MATERIALS),
            P("ESPESOR_BALDA", "Espesor de chapa de bandejas", "float", AUTO, "mm", "materiales", 0.8, 4,
              allow_auto=True),
            P("ESPESOR_PLACA_BASE", "Espesor de placa base", "float", 5.0, "mm", "materiales", 3, 12),
            P("ACABADO", "Acabado", "choice", "RAL7035_POLVO", None, "materiales", choices=list(catalog.finishes())),
            P("PERFIL_MONTANTE", "Perfil de montantes", "choice", AUTO, None, "construccion", choices=SHS,
              allow_auto=True),
            P("PERFIL_LARGUERO", "Perfil de largueros", "choice", AUTO, None, "construccion", choices=ALLP,
              allow_auto=True),
            P("PERFIL_TRAVESANO", "Perfil de travesaños", "choice", AUTO, None, "construccion", choices=ALLP,
              allow_auto=True),
            P("NUMERO_TRAVESANOS_BALDA", "Travesaños intermedios por nivel", "int", AUTO, "ud", "construccion", 0, 20,
              allow_auto=True),
            P("SEPARACION_MAX_APOYOS", "Separación máxima entre apoyos de chapa (regla constructiva)", "float",
              600.0, "mm", "construccion", 150, 1200, advanced=True),
            P("ALA_BALDA", "Altura de pestaña de bandeja", "float", 30.0, "mm", "construccion", 15, 60),
            P("RADIO_PLEGADO", "Radio interior de plegado", "float", AUTO, "mm", "construccion", 0.5, 20,
              allow_auto=True, advanced=True),
            P("FACTOR_K", "Factor K", "float", AUTO, None, "construccion", 0.2, 0.5, allow_auto=True, advanced=True),
            P("HOLGURA_BALDA", "Holgura bastidor–pestaña", "float", AUTO, "mm", "construccion", 0.5, 5,
              allow_auto=True, advanced=True),
            P("HOLGURA_ESCOTADURA", "Holgura de escotadura", "float", 2.0, "mm", "construccion", 1, 6, advanced=True),
            P("PASO_FIJACIONES", "Paso máximo de fijaciones", "float", 500.0, "mm", "construccion", 150, 900,
              advanced=True),
            P("TOLERANCIAS", "Tolerancias generales", "choice", "ISO 2768-mK", None, "construccion",
              choices=["ISO 2768-mK", "ISO 2768-fH", "ISO 2768-cL"], advanced=True),
            P("CLASE_EJECUCION", "Clase de ejecución (EN 1090-2)", "choice", "EXC1", None, "construccion",
              choices=["EXC1", "EXC2"], advanced=True),
            P("TIPO_APOYO", "Tipo de apoyo", "choice", "pie_nivelador", None, "accesorios", choices=["pie_nivelador"]),
            P("PIE_NIVELADOR", "Pie nivelador", "choice", "PIE_NIV_M12_D60", None, "accesorios", choices=FEET),
            P("CARGA_POR_NIVEL", "Carga distribuida por nivel", "float", None, "kg", "cargas", 0, 2000, nullable=True),
            P("CARGA_HORIZONTAL", "Empuje horizontal en la parte superior", "float", 300.0, "N", "cargas", 0, 5000),
            P("ANCLAJE", "Anclaje", "choice", "ninguno", None, "cargas", choices=["ninguno", "al_suelo"]),
            P("ENTORNO", "Entorno", "choice", "interior_seco", None, "cargas",
              choices=["interior_seco", "interior_humedo", "exterior", "alimentario", "sala_limpia"]),
            P("TIPO_SUELO", "Tipo de suelo", "choice", "nivelado", None, "cargas", choices=["nivelado", "irregular"]),
        ]

    def templates(self):
        return [
            {"id": "ES-1000-4", "name": "Estantería de cuatro niveles 1.000 mm", "family": self.id,
             "values": {"ANCHURA": 1000.0, "PROFUNDIDAD": 500.0, "ALTURA": 1800.0, "NUMERO_NIVELES": 4,
                        "CARGA_POR_NIVEL": 100.0, "ANCLAJE": "al_suelo"}},
            {"id": "ES-1500-5", "name": "Estantería de cinco niveles 1.500 mm", "family": self.id,
             "values": {"ANCHURA": 1500.0, "PROFUNDIDAD": 600.0, "ALTURA": 2000.0, "NUMERO_NIVELES": 5,
                        "CARGA_POR_NIVEL": 150.0, "ANCLAJE": "al_suelo"}},
        ]

    # ------------------------------------------------------------------ construcción
    def construct(self, ps: ParameterSet) -> ProductModel:
        for k, v in ps.values.items():
            if v == AUTO and k not in self.auto_in_construct:
                raise ValueError(f"Parámetro sin resolver: {k}")
        ctx = ParamContext(ps)
        A, Pf, H = ps.values["ANCHURA"], ps.values["PROFUNDIDAD"], ps.values["ALTURA"]
        model = ProductModel(self.id, self.name, f"ES{A:.0f}-{Pf:.0f}-{H:.0f}", ps, ctx)
        model.requested = ps
        d = self._derive_shelf(ctx, model)
        mat_s, mat_c, fin = ps.values["MATERIAL_ESTRUCTURAL"], ps.values["MATERIAL_CHAPA"], ps.values["ACABADO"]
        model.add_subassembly("EST", "Estructura soldada", welded=True, step=1)
        model.add_subassembly("APO", "Apoyos niveladores", explode=(0, 0, -160), step=2)
        model.add_subassembly("BAL", "Bandejas", explode=(0, -0.9 * Pf, 0), step=3)
        leg, rail, trv, a = d["leg"], d["rail"], d["trv"], d["a"]
        corners = {"DI": (a / 2, a / 2), "DD": (A - a / 2, a / 2), "TI": (a / 2, Pf - a / 2), "TD": (A - a / 2, Pf - a / 2)}
        cname = {"DI": "delantero izquierdo", "DD": "delantero derecho", "TI": "trasero izquierdo",
                 "TD": "trasero derecho"}
        foot = catalog.component(ps.values["PIE_NIVELADOR"])
        thread = float(foot["thread"][1:])
        nut_code = f"TUERCA_SOLDAR_M{thread:.0f}"
        rn = catalog.component("TUERCA_REMACHABLE_M6")
        sc = catalog.component("TORNILLO_ISO7380_M6x12")
        weld = self._make_welder(model, d)
        legs: dict[str, str] = {}
        with ctx.feature("F10", "Estructura soldada"):
            with ctx.feature("F11", "Montantes, placas base y tuercas"):
                ctx.uses("LONGITUD_MONTANTE", "PERFIL_MONTANTE", "ANCHURA", "PROFUNDIDAD", "ESPESOR_PLACA_BASE",
                         "PIE_NIVELADOR", "MATERIAL_ESTRUCTURAL", "ACABADO")
                leg_part = ProfilePart("montante", f"Montante {leg.code}", leg.code, d["leg_len"], mat_s, fin)
                plate_mat = "S235JR" if catalog.material(mat_s).family == "acero_carbono" else mat_s
                plate = PlatePart("placa_base", f"Placa base {a:.0f}x{a:.0f}x{d['tp']:.0f}", a, a, d["tp"], plate_mat,
                                  fin, corner_r=min(3.0, a / 10), holes=((a / 2, a / 2, thread + 1.0),))
                nut = StandardPart("tuerca_soldar", nut_code)
                for k, (x, y) in corners.items():
                    iid = f"EST.MONT.{k}"
                    p0, p1 = np.array([x, y, d["z_leg0"]]), np.array([x, y, H])
                    model.add(iid, f"Montante {cname[k]}", leg_part, G.axis_frame(p0, p1, (0, 1, 0)), "EST",
                              axis=(p0, p1), up=np.array([0, 1.0, 0]), structural=True)
                    legs[k] = iid
                    model.add(f"EST.PLACA.{k}", f"Placa base {cname[k]}", plate,
                              G.translation(x - a / 2, y - a / 2, d["hn"]), "EST")
                    model.add(f"EST.TUERCA.{k}", f"Tuerca soldada {cname[k]}", nut,
                              G.translation(x, y, d["hn"] + d["tp"]), "EST")
                    model.add_joint(Joint(f"J.PLACA.{k}", "soldadura", (iid, f"EST.PLACA.{k}"), (x, y, d["z_leg0"]),
                                          "Placa base a montante",
                                          weld={"type": "fillet", "a": d["weld_a"](min(leg.t, d["tp"])),
                                                "all_around": True, "process": "135 (MAG)",
                                                "length": round(4 * a - (8 - 2 * math.pi) * leg.r_out, 1)}))
                    s = float(catalog.component(nut_code)["s"])
                    model.add_joint(Joint(f"J.TUERCA.{k}", "soldadura", (f"EST.TUERCA.{k}", f"EST.PLACA.{k}"),
                                          (x, y, d["hn"] + d["tp"]), "Tuerca de soldar a placa base",
                                          weld={"type": "fillet", "a": 2.0, "all_around": False, "process": "135 (MAG)",
                                                "length": round(3 * s / math.sqrt(3), 1),
                                                "note": "3 cordones en caras alternas de la tuerca"}))
            for i, (lid, z) in enumerate(zip(d["level_ids"], d["z_levels"]), start=1):
                with ctx.feature(f"F2{i}", f"Bastidor del nivel {i}"):
                    ctx.uses("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "N_TRAVESANOS_NIVEL", f"COTA_NIVEL_{i}", "ESP_BAL",
                             "HOLGURA_BAL", "ANCHURA", "PROFUNDIDAD", "PERFIL_MONTANTE", "PASO_FIJACIONES", "ALA_BALDA",
                             "MATERIAL_ESTRUCTURAL")
                    before = len(model.instances)
                    self._frame_level(model, d, ctx, level=lid, z_top=z - d["ts"], prof_long=rail, prof_end=trv,
                                      inset=d["e"], n_int=d["n_int"], legs=legs, fixings=d["fix"][lid], weld=weld,
                                      mat=mat_s, fin=fin, label="de nivel")
                    for inst in model.instances[before:]:
                        inst.name += f" (nivel {i})"
        with ctx.feature("F40", "Apoyos niveladores"):
            ctx.uses("PIE_NIVELADOR", "ANCHURA", "PROFUNDIDAD", "PERFIL_MONTANTE")
            fpart = StandardPart("pie_nivelador", ps.values["PIE_NIVELADOR"])
            for k, (x, y) in corners.items():
                model.add(f"APO.PIE.{k}", f"Pie nivelador {cname[k]}", fpart, G.translation(x, y, 0.0), "APO")
                model.add_joint(Joint(f"J.PIE.{k}", "roscada", (f"APO.PIE.{k}", f"EST.TUERCA.{k}"), (x, y, d["hn"]),
                                      f"Pie roscado {foot['thread']} en tuerca soldada"))
        tray = SheetPart("balda", f"Bandeja chapa {d['spec'].t:g} mm", d["spec"], mat_c, fin)
        for i, (lid, z) in enumerate(zip(d["level_ids"], d["z_levels"]), start=1):
            with ctx.feature(f"F3{i}", f"Bandeja del nivel {i}"):
                ctx.uses("ANCHURA", "PROFUNDIDAD", f"COTA_NIVEL_{i}", "ESP_BAL", "ALA_BALDA", "MATERIAL_CHAPA",
                         "PERFIL_MONTANTE", "HOLGURA_ESCOTADURA", "PERFIL_LARGUERO", "ACABADO")
                tid = f"BAL.BANDEJA.{i}"
                model.add(tid, f"Bandeja nivel {i}", tray, G.translation(0, 0, z), "BAL",
                          tags={"explode_extra": (0, 0, 0)})
                self._fasteners(model, d["fix"][lid], "BAL", rn, sc, ctx, prefix=f"BAL.N{i}", tray_id=tid)
        model.structure = self._shelf_structure(model, d, legs)
        n = len(d["z_levels"])
        q = ps.values.get("CARGA_POR_NIVEL")
        model.dims = {
            "ANCHURA": A, "PROFUNDIDAD": Pf, "ALTURA": H, "LONGITUD_MONTANTE": d["leg_len"],
            "envelope": {"ids": list(legs.values()) + [f"BAL.BANDEJA.{i}" for i in range(1, n + 1)], "dx": A, "dy": Pf,
                         "zmax": H, "names": ("ANCHURA", "PROFUNDIDAD")},
            "levels": [(f"NIVEL_{i}", f"BAL.BANDEJA.{i}") for i in range(1, n + 1)],
            "drawing_expected": {f"DIST_NIVEL_{k + 1}": (d["z_levels"][0] if k == 0 else d["z_levels"][k] -
                                                         d["z_levels"][k - 1]) for k in range(n)},
            "load_text": (f"Carga distribuida por nivel de proyecto: {q:g} kg ({n} niveles, total {n * q:g} kg)" if q
                          else "Carga por nivel: NO DEFINIDA"),
        }
        model.number_parts()
        return model

    # ------------------------------------------------------------------ derivados
    def _derive_shelf(self, ctx: ParamContext, model: ProductModel) -> dict:
        v = ctx.params.values
        d: dict = {}
        with ctx.feature("F00", "Parámetros derivados y reglas constructivas"):
            fam = catalog.material(v["MATERIAL_CHAPA"]).family
            rmin = catalog.sheet_data()["press_brake"]["min_inner_radius_factor"].get(fam, 1.0)
            ts = ctx.derive("ESP_BAL", lambda p: p["ESPESOR_BALDA"], "mm", "Espesor de bandeja")
            rs = ctx.derive("RADIO_BAL", lambda p: round(max(p["ESP_BAL"], rmin * p["ESP_BAL"]), 2)
                            if p["RADIO_PLEGADO"] == AUTO else p["RADIO_PLEGADO"], "mm", "Radio interior de plegado")
            Ks = ctx.derive("K_BAL", lambda p: round(catalog.din6935_k_factor(p["RADIO_BAL"], p["ESP_BAL"]), 4)
                            if p["FACTOR_K"] == AUTO else p["FACTOR_K"], None, "Factor K")
            ctx.derive("DEDUCCION_PLEGADO_BAL", lambda p: round(bend_deduction(p["ESP_BAL"], p["RADIO_BAL"], p["K_BAL"]), 4),
                       "mm", "Deducción de plegado 90°")
            leg = catalog.profile(ctx["PERFIL_MONTANTE"])
            rail = catalog.profile(ctx["PERFIL_LARGUERO"])
            trv = catalog.profile(ctx["PERFIL_TRAVESANO"])
            if leg.B != leg.H:
                raise ValueError("Los montantes deben ser de tubo cuadrado")
            a = leg.B
            foot = catalog.component(ctx["PIE_NIVELADOR"])
            hn, tp = float(foot["nominal_height"]), ctx["ESPESOR_PLACA_BASE"]
            A, Pf, H = ctx["ANCHURA"], ctx["PROFUNDIDAD"], ctx["ALTURA"]
            z_leg0 = ctx.derive("COTA_INICIO_MONTANTE", lambda p: float(catalog.component(p["PIE_NIVELADOR"])
                                                                         ["nominal_height"]) + p["ESPESOR_PLACA_BASE"],
                                "mm", "Cota inicio de montante")
            leg_len = ctx.derive("LONGITUD_MONTANTE", lambda p: p["ALTURA"] - p["COTA_INICIO_MONTANTE"], "mm",
                                 "Longitud de corte de montante")
            head_h = float(catalog.component("TUERCA_REMACHABLE_M6")["head_h"])
            g = ctx.derive("HOLGURA_BAL", lambda p: max(p["RADIO_BAL"], head_h) if p["HOLGURA_BALDA"] == AUTO
                           else p["HOLGURA_BALDA"], "mm", "Holgura bastidor–pestaña")
            if g < rs - 1e-9:
                model.note("error", "GEO-HOLGURA-RADIO", f"Holgura {g} mm menor que el radio de plegado {rs} mm.")
            if head_h > g + 1e-9:
                model.note("error", "DFM-HOLGURA-REMACHABLE", "La cabeza de la tuerca remachable no cabe en la holgura.")
            e = ts + g
            if e + max(rail.B, trv.B) > a:
                model.note("error", "DFM-BASTIDOR", "El bastidor retranqueado no cabe en la sección del montante.")
            n = ctx["NUMERO_NIVELES"]
            z1 = ctx["ALTURA_PRIMER_NIVEL"]
            dist = ctx.derive("DISTANCIA_NIVELES", lambda p: (p["ALTURA"] - p["ALTURA_PRIMER_NIVEL"]) /
                              (p["NUMERO_NIVELES"] - 1)
                              if p["DISTANCIA_BALDAS"] == AUTO else p["DISTANCIA_BALDAS"], "mm",
                              "Distancia entre niveles")
            zs = []
            for i in range(n):
                zs.append(ctx.derive(f"COTA_NIVEL_{i + 1}", lambda p, i=i: p["ALTURA_PRIMER_NIVEL"] +
                                     i * p["DISTANCIA_NIVELES"], "mm", f"Cota cara superior del nivel {i + 1}"))
            if zs[-1] > H + 1e-6 * H:
                raise ValueError(f"Los {n} niveles a {dist:g} mm superan la altura total de {H:g} mm")
            if z1 - ts - rail.H < z_leg0 + 20:
                model.note("error", "GEO-NIVEL-BAJO", "El primer nivel está demasiado bajo para su bastidor.")
            libre = dist - ts - max(rail.H, trv.H)
            ctx.set_derived("HUECO_LIBRE", round(libre, 1), "mm", "Altura libre entre niveles",
                            ["DISTANCIA_BALDAS", "ALTURA", "NUMERO_NIVELES", "PERFIL_LARGUERO"])
            if libre < 150:
                model.note("advertencia", "ERG-HUECO", f"Altura libre entre niveles de {libre:.0f} mm (< 150 mm).")
            xb0, xb1 = e + trv.B / 2, A - e - trv.B / 2
            n_int = ctx["NUMERO_TRAVESANOS_BALDA"]
            if n_int == AUTO:
                n_int = max(0, math.ceil((xb1 - xb0) / ctx["SEPARACION_MAX_APOYOS"]) - 1)
            ctx.set_derived("N_TRAVESANOS_NIVEL", n_int, "ud", "Travesaños intermedios por nivel",
                            ["NUMERO_TRAVESANOS_BALDA", "SEPARACION_MAX_APOYOS", "ANCHURA"])
            notch = a + ctx["HOLGURA_ESCOTADURA"]
            ala = ctx["ALA_BALDA"]
            rn = catalog.component("TUERCA_REMACHABLE_M6")
            sc = catalog.component("TORNILLO_ISO7380_M6x12")
            level_ids = [f"N{i}" for i in range(1, n)] + ["SUP"]
            d.update(Lx=A, Ly=Pf, c=0.0, a=a, leg=leg, rail=rail, trv=trv, hn=hn, tp=tp, z_leg0=z_leg0,
                     leg_len=leg_len, ts=ts, e=e, n_int=n_int, z_levels=zs, level_ids=level_ids)
            d["weld_a"] = lambda tmin: 3.0 if tmin >= 3 else float(tmin)
            fix = {}
            for lid, z in zip(level_ids, zs):
                f = self._fix_layout(model, ctx, A, Pf, 0.0, a, ts, rs + ts, ala, rail, trv, z_ref=z, inset=e,
                                     hole_d=sc["clearance_hole"], rn=rn, pitch=ctx["PASO_FIJACIONES"], short_min=1,
                                     tag=f"bandeja {lid}", notch=notch, offset=0.0)
                f["gap"] = g
                fix[lid] = f
            d["fix"] = fix
            f0 = fix[level_ids[0]]
            flanges = tuple(FlangeSpec(ed, ala, "down", tuple((s, f0["h"][ed], sc["clearance_hole"]) for s in f0["s"][ed]))
                            for ed in EDGES)
            d["spec"] = SheetMetalSpec(A, Pf, ts, rs, Ks, flanges, notch=(notch, notch))
        return d

    def _shelf_structure(self, model, d, legs):
        A, Pf = d["Lx"], d["Ly"]
        notch = d["spec"].notch[0]
        area = A * Pf - 4 * notch * notch
        surfaces = [{"id": lid, "label": f"Bandeja del nivel {i}", "level": lid, "load_param": "CARGA_POR_NIVEL",
                     "sheet_instance": f"BAL.BANDEJA.{i}", "area_mm2": area}
                    for i, lid in enumerate(d["level_ids"], start=1)]
        feet = [{"instance": f"APO.PIE.{k}", "leg": legs[k], "point": tuple(model.instance(legs[k]).axis[0]),
                 "component": model.params.values["PIE_NIVELADOR"]} for k in ("DI", "DD", "TI", "TD")]
        return {"levels": model.structure.get("levels", {}), "surfaces": surfaces, "supports": feet,
                "horizontal_points": [legs["DI"], legs["DD"]], "worktop_height": model.params.values["ALTURA"],
                "leg_ids": list(legs.values()), "product_word": "estantería",
                "member_roles": {i.id: i.part.role for i in model.instances if i.structural},
                "assembly_texts": {
                    "EST": "Recepción de la estructura soldada y pintada. Insertar las tuercas remachables M6 en los "
                           "taladros Ø9,1 de largueros y travesaños de todos los niveles.",
                    "APO": "Roscar los pies niveladores en las tuercas soldadas. Nivelar y, si está previsto, anclar al "
                           "suelo antes de cargar la estantería.",
                    "BAL": "Colocar las bandejas de abajo arriba sobre cada bastidor, con las escotaduras alrededor de "
                           "los montantes, y fijarlas con tornillos ISO 7380 M6x12 (8 N·m)."}}
