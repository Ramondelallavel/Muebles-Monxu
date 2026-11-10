"""Familia C: estantería en batería (N módulos contiguos que comparten montantes).

Cada módulo es un vano de estantería con su bastidor soldado por nivel (largueros delantero y trasero entre caras de
montante, travesaños laterales e intermedios) y su bandeja de chapa plegada atornillada. Los montantes intermedios
son comunes a los dos módulos contiguos: cada uno recibe a su altura los dos travesaños laterales, uno a cada lado de
su eje, dentro de su sección. Las bandejas van de eje a eje de montante (con 1 mm de junta) y llevan escotaduras de
medio montante en X y montante completo en Y; todos los módulos son iguales y comparten referencias. Las pestañas
laterales de bandejas contiguas quedan enfrentadas con 1 mm de junta, por lo que las bandejas se atornillan sólo por
las pestañas delantera y trasera (las laterales sólo posicionan).

Restricción constructiva: los dos travesaños laterales deben caber en la sección del montante común
(junta/2 + retranqueo + ancho de travesaño ≤ medio montante); el dimensionado aumenta el montante si hace falta.
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad import geometry as G
from ..cad.sheetmetal import EDGES, FlangeSpec, SheetMetalSpec
from ..core.model import Joint, PlatePart, ProductModel, ProfilePart, SheetPart, StandardPart
from ..core.params import AUTO, ParamContext, ParameterSet, ParamSpec
from .base import register
from .estanteria import CANDIDATES as EST_CANDIDATES, CONSTRUCTIVE_DEFAULTS as EST_DEFAULTS, Estanteria
from .mesa_industrial import add_anchors, flange_hole_d, weld_nut_code

BAY_GAP = 1.0                 # junta entre bandejas de módulos contiguos
FIX_MARGIN = 60.0             # margen de fijaciones respecto a la cara del montante (como _fix_layout)
CANDIDATES = {**EST_CANDIDATES,
              "PERFIL_MONTANTE": ["SHS 50x50x2", "SHS 50x50x3", "SHS 60x60x3", "SHS 70x70x3", "SHS 80x80x3",
                                  "SHS 80x80x4", "SHS 90x90x4", "SHS 100x100x4", "SHS 100x100x5", "SHS 120x120x4",
                                  "SHS 120x120x5"]}
CONSTRUCTIVE_DEFAULTS = {**EST_DEFAULTS, "PERFIL_MONTANTE": "SHS 50x50x2"}


@register
class EstanteriaBateria(Estanteria):
    id = "estanteria_bateria"
    name = "Estantería en batería"
    prefix = "EB"
    category = "C"
    description = ("Estantería de N módulos contiguos con montantes compartidos, bastidores soldados por módulo y nivel "
                   "y bandejas de chapa plegada iguales en todos los módulos; dimensionada por la carga de cada "
                   "bandeja, con pies niveladores y anclaje opcional.")
    configurations = ["Estantería de almacén en batería", "Estantería de archivo en batería", "Estantería pesada en batería"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS

    # ------------------------------------------------------------------ parámetros
    def param_specs(self):
        P = ParamSpec
        out = []
        for s in super().param_specs():
            if s.name == "ANCHURA":
                s = P("ANCHURA", "Anchura de módulo (entre ejes de montantes)", "float", 1000.0, "mm", "dimensiones",
                      600, 2000)
                out.append(s)
                out.append(P("NUMERO_MODULOS", "Número de módulos", "int", 3, "ud", "dimensiones", 2, 8,
                             help="Módulos contiguos que comparten los montantes intermedios."))
                continue
            if s.name == "CARGA_POR_NIVEL":
                s = P("CARGA_POR_NIVEL", "Carga distribuida por bandeja (cada módulo y nivel)", "float", None, "kg",
                      "cargas", 0, 2000, nullable=True)
            out.append(s)
        return out

    def templates(self):
        return [
            {"id": "EB-3x1000-5", "name": "Estantería en batería de 3 módulos de 1.000 mm, cinco niveles",
             "family": self.id,
             "values": {"NUMERO_MODULOS": 3, "ANCHURA": 1000.0, "PROFUNDIDAD": 500.0, "ALTURA": 2000.0,
                        "NUMERO_NIVELES": 5, "CARGA_POR_NIVEL": 100.0, "ANCLAJE": "al_suelo"}},
            {"id": "EB-4x1200-4-PESADA", "name": "Estantería pesada en batería de 4 módulos de 1.200 mm",
             "family": self.id,
             "values": {"NUMERO_MODULOS": 4, "ANCHURA": 1200.0, "PROFUNDIDAD": 800.0, "ALTURA": 2500.0,
                        "NUMERO_NIVELES": 4, "CARGA_POR_NIVEL": 250.0, "ANCLAJE": "al_suelo",
                        "ACABADO": "RAL5010_POLVO"}},
            {"id": "EB-2x900-6-ARCHIVO", "name": "Estantería de archivo en batería de 2 módulos de 900 mm",
             "family": self.id,
             "values": {"NUMERO_MODULOS": 2, "ANCHURA": 900.0, "PROFUNDIDAD": 400.0, "ALTURA": 2200.0,
                        "NUMERO_NIVELES": 6, "CARGA_POR_NIVEL": 60.0, "ANCLAJE": "al_suelo"}},
            {"id": "EB-5x1000-5", "name": "Estantería en batería de 5 módulos de 1.000 mm, cinco niveles", "family": self.id,
             "values": {"NUMERO_MODULOS": 5, "ANCHURA": 1000.0, "PROFUNDIDAD": 500.0, "ALTURA": 2000.0,
                        "NUMERO_NIVELES": 5, "CARGA_POR_NIVEL": 120.0, "ANCLAJE": "al_suelo",
                        "ACABADO": "RAL7035_POLVO"}},
            {"id": "EB-2x1500-4", "name": "Estantería en batería de 2 módulos de 1.500 mm (200 kg por bandeja)", "family": self.id,
             "values": {"NUMERO_MODULOS": 2, "ANCHURA": 1500.0, "PROFUNDIDAD": 600.0, "ALTURA": 2000.0,
                        "NUMERO_NIVELES": 4, "CARGA_POR_NIVEL": 200.0, "ANCLAJE": "al_suelo",
                        "ACABADO": "RAL5010_POLVO"}},
        ]

    # ------------------------------------------------------------------ regla de montante común (dimensionado)
    def leg_fits(self, v) -> bool:
        """Además de la regla de la estantería, los dos travesaños laterales caben en el montante común."""
        if not super().leg_fits(v):
            return False
        if any(v.get(k) in (AUTO, None) for k in ("PERFIL_MONTANTE", "PERFIL_TRAVESANO", "ESPESOR_BALDA")):
            return True
        a = catalog.profile(v["PERFIL_MONTANTE"]).B
        return BAY_GAP / 2 + self.bay_inset(v) + catalog.profile(v["PERFIL_TRAVESANO"]).B <= a / 2 + 1e-9

    # ------------------------------------------------------------------ derivados
    def _derive_shelf(self, ctx: ParamContext, model: ProductModel) -> dict:
        d = super()._derive_shelf(ctx, model)
        v = ctx.params.values
        with ctx.feature("F01", "Disposición en batería"):
            N, M, Pf = ctx["NUMERO_MODULOS"], ctx["ANCHURA"], ctx["PROFUNDIDAD"]
            a, e, trv, ts = d["a"], d["e"], d["trv"], d["ts"]
            A_tot = ctx.derive("ANCHURA_TOTAL", lambda p: p["NUMERO_MODULOS"] * p["ANCHURA"]
                               + catalog.profile(p["PERFIL_MONTANTE"]).B, "mm", "Anchura total de la batería")
            ctx.derive("N_MONTANTES", lambda p: 2 * (p["NUMERO_MODULOS"] + 1), "ud", "Montantes")
            xs = [a / 2 + k * M for k in range(N + 1)]
            if BAY_GAP / 2 + e + trv.B > a / 2 + 1e-9:
                model.note("error", "DFM-BATERIA-MONTANTE",
                           f"Los dos travesaños laterales ({trv.code}) no caben en el montante común {d['leg'].code}: "
                           f"hacen falta {2 * (BAY_GAP / 2 + e + trv.B):.0f} mm de sección. Aumente PERFIL_MONTANTE o "
                           "reduzca PERFIL_TRAVESANO.")
            if A_tot > 3000:
                model.note("advertencia", "ERG-TRANSPORTE", f"Estructura soldada de {A_tot:.0f} mm de longitud: "
                           "comprobar transporte, acceso y manipulación.")
            Lt = M - BAY_GAP
            notch = (a / 2 + ctx["HOLGURA_ESCOTADURA"] - BAY_GAP / 2, a + ctx["HOLGURA_ESCOTADURA"])
            sc = catalog.component("TORNILLO_ISO7380_M6x12")
            rn = catalog.component("TUERCA_REMACHABLE_M6")
            ala = ctx["ALA_BALDA"]
            rs, Ks = d["spec"].r, d["spec"].K
            hd = flange_hole_d(v["MATERIAL_CHAPA"], ts, sc)
            s0 = a / 2 - BAY_GAP / 2 + FIX_MARGIN
            fix = {}
            for lid, z in zip(d["level_ids"], d["z_levels"]):
                f = self._fix_layout(model, ctx, Lt, Pf, 0.0, a, ts, rs + ts, ala, d["rail"], trv, z_ref=z, inset=e,
                                     hole_d=hd, rn=rn, pitch=ctx["PASO_FIJACIONES"], short_min=1, tag=f"bandeja {lid}",
                                     offset=(0.0, 0.0), ranges={"y0": (s0, Lt - s0, 2), "y1": (s0, Lt - s0, 2)})
                f["gap"] = d["fix"][lid]["gap"]
                # pestañas laterales enfrentadas a la de la bandeja contigua (junta de 1 mm): sin tornillería, la
                # cabeza del tornillo no cabe; la bandeja se fija por las pestañas delantera y trasera
                f["s"]["x0"], f["s"]["x1"] = [], []
                fix[lid] = f
            f0 = fix[d["level_ids"][0]]
            flanges = tuple(FlangeSpec(ed, ala, "down", tuple((s, f0["h"][ed], hd) for s in f0["s"][ed])) for ed in EDGES)
            d.update(N=N, M=M, xs=xs, A_tot=A_tot, fix=fix, Lt=Lt,
                     spec=SheetMetalSpec(Lt, Pf, ts, rs, Ks, flanges, notch=notch))
            # vano de los travesaños de un módulo (para el número de intermedios)
            d["xb"] = (BAY_GAP / 2 + e + trv.B / 2, M - BAY_GAP / 2 - e - trv.B / 2)
        return d

    # ------------------------------------------------------------------ construcción
    def construct(self, ps: ParameterSet) -> ProductModel:
        for k, val in ps.values.items():
            if val == AUTO and k not in self.auto_in_construct:
                raise ValueError(f"Parámetro sin resolver: {k}")
        from ..core.params import ParamContext as _PC
        ctx = _PC(ps)
        v = ps.values
        M, Pf, H = v["ANCHURA"], v["PROFUNDIDAD"], v["ALTURA"]
        N = v["NUMERO_MODULOS"]
        model = ProductModel(self.id, self.name, f"{self.prefix}{N}x{M:.0f}-{Pf:.0f}-{H:.0f}", ps, ctx)
        model.requested = ps
        d = self._derive_shelf(ctx, model)
        mat_s, mat_c, fin = v["MATERIAL_ESTRUCTURAL"], v["MATERIAL_CHAPA"], v["ACABADO"]
        model.add_subassembly("EST", "Estructura soldada", welded=True, step=1)
        model.add_subassembly(self.support_group[0], self.support_group[1], explode=(0, 0, -160), step=2)
        model.add_subassembly("BAL", "Bandejas", explode=(0, -0.9 * Pf, 0), step=3)
        leg, a, xs = d["leg"], d["a"], d["xs"]
        corners, cname = {}, {}
        for k, x in enumerate(xs):
            corners[f"D{k}"], cname[f"D{k}"] = (x, a / 2), f"delantero {k + 1}"
            corners[f"T{k}"], cname[f"T{k}"] = (x, Pf - a / 2), f"trasero {k + 1}"
        foot = catalog.component(v[self.support_param])
        thread = float(foot["thread"][1:])
        nut_code = weld_nut_code(thread, mat_s)
        rn = catalog.component("TUERCA_REMACHABLE_M6")
        sc = catalog.component("TORNILLO_ISO7380_M6x12")
        weld = self._make_welder(model, d)
        legs: dict[str, str] = {}
        with ctx.feature("F10", "Estructura soldada"):
            with ctx.feature("F11", "Montantes, placas base y tuercas"):
                ctx.uses("LONGITUD_MONTANTE", "PERFIL_MONTANTE", "ANCHURA", "NUMERO_MODULOS", "PROFUNDIDAD",
                         "ESPESOR_PLACA_BASE", self.support_param, "MATERIAL_ESTRUCTURAL", "ACABADO")
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
                with ctx.feature(f"F2{i}", f"Bastidores del nivel {i}"):
                    ctx.uses("PERFIL_LARGUERO", "PERFIL_TRAVESANO", "N_TRAVESANOS_NIVEL", f"COTA_NIVEL_{i}", "ESP_BAL",
                             "HOLGURA_BAL", "ANCHURA", "NUMERO_MODULOS", "PROFUNDIDAD", "PERFIL_MONTANTE",
                             "PASO_FIJACIONES", "ALA_BALDA", "MATERIAL_ESTRUCTURAL")
                    for j in range(N):
                        self._bay_frame(model, d, lid, i, j, z - d["ts"], legs, weld, mat_s, fin)
        with ctx.feature("F40", self.support_group[1]):
            ctx.uses(self.support_param, "ANCHURA", "NUMERO_MODULOS", "PROFUNDIDAD", "PERFIL_MONTANTE")
            g = self.support_group[0]
            for k, (x, y) in corners.items():
                fpart, fname = self._support_part(k, ps)
                model.add(f"{g}.PIE.{k}", f"{fname} {cname[k]}", fpart, G.translation(x, y, 0.0), g)
                desc = (f"Pie roscado {foot['thread']} en tuerca soldada" if fpart.role == "pie_nivelador" else
                        f"{fname} roscad{'a' if fpart.role == 'rueda' else 'o'} {foot['thread']} en tuerca soldada")
                model.add_joint(Joint(f"J.PIE.{k}", "roscada", (f"{g}.PIE.{k}", f"EST.TUERCA.{k}"), (x, y, d["hn"]), desc))
            add_anchors(model, ps, corners, cname, g)
        tray = SheetPart("balda", f"Bandeja chapa {d['spec'].t:g} mm", d["spec"], mat_c, fin)
        for i, (lid, z) in enumerate(zip(d["level_ids"], d["z_levels"]), start=1):
            with ctx.feature(f"F3{i}", f"Bandejas del nivel {i}"):
                ctx.uses("ANCHURA", "NUMERO_MODULOS", "PROFUNDIDAD", f"COTA_NIVEL_{i}", "ESP_BAL", "ALA_BALDA",
                         "MATERIAL_CHAPA", "PERFIL_MONTANTE", "HOLGURA_ESCOTADURA", "PERFIL_LARGUERO", "ACABADO")
                for j in range(N):
                    ox = xs[j] + BAY_GAP / 2
                    tid = f"BAL.BANDEJA.{i}" if j == 0 else f"BAL.BANDEJA.{i}.M{j + 1}"
                    model.add(tid, f"Bandeja nivel {i}, módulo {j + 1}", tray, G.translation(ox, 0, z), "BAL",
                              tags={"explode_extra": (0, 0, 0)})
                    fx = {**d["fix"][lid], "offset": (ox, 0.0)}
                    self._fasteners(model, fx, "BAL", rn, sc, ctx, prefix=f"BAL.N{i}" + (f"M{j + 1}" if j else ""),
                                    tray_id=tid)
        model.structure = self._shelf_structure(model, d, legs)
        n = len(d["z_levels"])
        q = v.get("CARGA_POR_NIVEL")
        model.dims = {
            "ANCHURA": M, "ANCHURA_TOTAL": d["A_tot"], "PROFUNDIDAD": Pf, "ALTURA": H, "LONGITUD_MONTANTE": d["leg_len"],
            "envelope": {"ids": list(legs.values()) + [f"BAL.BANDEJA.{i}" for i in range(1, n + 1)], "dx": d["A_tot"],
                         "dy": Pf, "zmax": H, "names": ("ANCHURA_TOTAL", "PROFUNDIDAD")},
            "levels": [(f"NIVEL_{i}", f"BAL.BANDEJA.{i}") for i in range(1, n + 1)],
            "drawing_expected": {f"DIST_NIVEL_{k + 1}": (d["z_levels"][0] if k == 0 else d["z_levels"][k] -
                                                         d["z_levels"][k - 1]) for k in range(n)},
            "load_text": (f"Carga distribuida por bandeja de proyecto: {q:g} kg ({N} módulos × {n} niveles, total "
                          f"{N * n * q:g} kg)" if q else "Carga por bandeja: NO DEFINIDA"),
        }
        model.number_parts()
        return model

    def _bay_frame(self, model, d, lid, i, j, z_top, legs, weld, mat, fin):
        """Bastidor de un módulo en un nivel: largueros entre montantes y travesaños dentro de su sección."""
        rail, trv, a, e, Pf, n_int = d["rail"], d["trv"], d["a"], d["e"], d["Ly"], d["n_int"]
        xj, xk = d["xs"][j], d["xs"][j + 1]
        fx = d["fix"][lid]
        ox = xj + BAY_GAP / 2
        hole = catalog.component("TUERCA_REMACHABLE_M6")["hole_d"]
        lkey = lid if j == 0 else f"{lid}_M{j + 1}"
        tag = f" (nivel {i}, módulo {j + 1})"
        # ---- largueros (delantero en +X y trasero en −X: misma pieza)
        zl = z_top - rail.H / 2
        y_f, y_b = e + rail.B / 2, Pf - e - rail.B / 2
        x0, x1 = xj + a / 2, xk - a / 2
        hz = fx["z_ref"] - fx["h"]["y0"]
        lp = ProfilePart(f"larguero_{lid.lower()}", f"Larguero de nivel {rail.code}", rail.code, x1 - x0, mat, fin,
                         holes=tuple(("-x", s + ox - x0, hz - zl, hole) for s in fx["s"]["y0"]))
        long_ids = []
        for k, nm, p0, p1, l0, l1 in (("D", "delantero", (x0, y_f, zl), (x1, y_f, zl), f"D{j}", f"D{j + 1}"),
                                      ("T", "trasero", (x1, y_b, zl), (x0, y_b, zl), f"T{j + 1}", f"T{j}")):
            iid = f"EST.LAR_{lkey}.{k}"
            p0, p1 = np.array(p0, float), np.array(p1, float)
            model.add(iid, f"Larguero de nivel {nm}{tag}", lp, G.axis_frame(p0, p1, (0, 0, 1)), "EST", axis=(p0, p1),
                      up=np.array([0, 0, 1.0]), structural=True)
            weld(f"J.{iid}.0", iid, 0, legs[l0], rail, f"Larguero de nivel {nm} a montante")
            weld(f"J.{iid}.1", iid, 1, legs[l1], rail, f"Larguero de nivel {nm} a montante")
            long_ids.append(iid)
        # ---- travesaños laterales, dentro de la sección de cada montante
        ze = z_top - trv.H / 2
        x_l, x_r = xj + BAY_GAP / 2 + e + trv.B / 2, xk - BAY_GAP / 2 - e - trv.B / 2
        y0, y1 = a, Pf - a
        hz = fx["z_ref"] - fx["h"]["x0"]
        ep = ProfilePart(f"travesano_ext_{lid.lower()}", f"Travesaño extremo de nivel {trv.code}", trv.code, y1 - y0,
                         mat, fin, holes=tuple(("+x", s - y0, hz - ze, hole) for s in fx["s"]["x0"]))
        end_ids = []
        for k, nm, p0, p1, l0, l1 in (("I", "izquierdo", (x_l, y0, ze), (x_l, y1, ze), f"D{j}", f"T{j}"),
                                      ("D", "derecho", (x_r, y1, ze), (x_r, y0, ze), f"T{j + 1}", f"D{j + 1}")):
            iid = f"EST.TRV_{lkey}.{k}"
            p0, p1 = np.array(p0, float), np.array(p1, float)
            model.add(iid, f"Travesaño extremo de nivel {nm}{tag}", ep, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                      axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
            weld(f"J.{iid}.0", iid, 0, legs[l0], trv, f"Travesaño extremo de nivel {nm} a montante")
            weld(f"J.{iid}.1", iid, 1, legs[l1], trv, f"Travesaño extremo de nivel {nm} a montante")
            end_ids.append(iid)
        # ---- travesaños intermedios entre largueros
        xs_i = [x_l + q * (x_r - x_l) / (n_int + 1) for q in range(1, n_int + 1)]
        yi0, yi1 = e + rail.B, Pf - e - rail.B
        int_ids = []
        if n_int:
            ip = ProfilePart(f"travesano_int_{lid.lower()}", f"Travesaño intermedio de nivel {trv.code}", trv.code,
                             yi1 - yi0, mat, fin)
            for q, x in enumerate(xs_i, start=1):
                iid = f"EST.TRI_{lkey}.{q:02d}"
                p0, p1 = np.array([x, yi0, ze]), np.array([x, yi1, ze])
                model.add(iid, f"Travesaño intermedio de nivel {q}{tag}", ip, G.axis_frame(p0, p1, (0, 0, 1)), "EST",
                          axis=(p0, p1), up=np.array([0, 0, 1.0]), structural=True)
                weld(f"J.{iid}.0", iid, 0, long_ids[0], trv, "Travesaño intermedio de nivel a larguero")
                weld(f"J.{iid}.1", iid, 1, long_ids[1], trv, "Travesaño intermedio de nivel a larguero")
                int_ids.append(iid)
        model.structure.setdefault("levels", {})[lkey] = {
            "long": long_ids, "end": end_ids, "int": int_ids, "grid_x": [x_l] + xs_i + [x_r], "grid_y": [y_f, y_b],
            "z": z_top}

    def _shelf_structure(self, model, d, legs):
        N, Lt, Pf = d["N"], d["Lt"], d["Ly"]
        nx, ny = d["spec"].notch
        area = Lt * Pf - 4 * nx * ny
        surfaces = []
        for i, lid in enumerate(d["level_ids"], start=1):
            for j in range(N):
                sid = lid if j == 0 else f"{lid}_M{j + 1}"
                surfaces.append({"id": sid, "label": f"Bandeja del nivel {i}, módulo {j + 1}", "level": sid,
                                 "load_param": "CARGA_POR_NIVEL",
                                 "sheet_instance": f"BAL.BANDEJA.{i}" if j == 0 else f"BAL.BANDEJA.{i}.M{j + 1}",
                                 "area_mm2": area})
        g = self.support_group[0]
        order = [f"D0", f"D{N}", "T0", f"T{N}"] + [f"D{k}" for k in range(1, N)] + [f"T{k}" for k in range(1, N)]
        feet = [{"instance": f"{g}.PIE.{k}", "leg": legs[k], "point": tuple(model.instance(legs[k]).axis[0]),
                 "component": model.instance(f"{g}.PIE.{k}").part.code} for k in order]
        st = {"levels": model.structure.get("levels", {}), "surfaces": surfaces, "supports": feet,
              "horizontal_points": [legs["D0"], legs[f"D{N}"]], "worktop_height": model.params.values["ALTURA"],
              "leg_ids": [legs[k] for k in order], "product_word": "estantería",
              "member_roles": {i.id: i.role for i in model.instances if i.structural},
              "assembly_texts": {
                  "EST": f"Recepción de la estructura soldada de {N} módulos (montantes intermedios comunes). Insertar las "
                         "tuercas remachables en los taladros de largueros y travesaños de todos los niveles.",
                  "APO": "Roscar los pies niveladores en las tuercas soldadas. Nivelar y, si está previsto, anclar al "
                         "suelo antes de cargar la estantería.",
                  "BAL": "Colocar las bandejas de abajo arriba y de un extremo al otro, con las escotaduras alrededor de "
                         "los montantes, y fijarlas con la tornillería indicada."}}
        return st
