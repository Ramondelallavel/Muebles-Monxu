"""Familia D: armario industrial sobre estructura tubular soldada.

Es una estantería de cuatro montantes con N bandejas de chapa plegada (la primera es el suelo del armario y la
última, a la altura total, su techo) cerrada con paneles de chapa y con puertas batientes:

* **Laterales y fondo:** chapa lisa cortada por láser, atornillada con tornillos ISO 7380 a tuercas remachables en
  la cara exterior de los montantes (la cabeza de la remachable queda entre panel y montante). Donde asoman las
  cabezas de los tornillos de las bandejas, el panel lleva taladros de alojamiento. El fondo cubre también los
  cantos traseros de los laterales.
* **Puertas:** chapa plegada con pestañas de 20 mm hacia el armario, superpuestas al frente y separadas 5 mm del
  frente de los montantes (las cabezas de los tornillos de las bandejas asoman 3,3 mm). Una puerta hasta 600 mm de
  anchura y dos por encima ('auto'), con 3 mm de holgura entre ellas. Bisagras exteriores de pernio en el canto de
  giro (2 hasta 1.200 mm de altura de puerta, 3 hasta 1.800 mm y 4 por encima) y maneta con cerradura en el canto
  libre. Las bisagras y la maneta se modelan con su envolvente; sus remaches y taladros no se modelan.
* **Cálculo:** la estructura resiste las cargas de las bandejas como en la estantería. Paneles, puertas y herrajes
  son masas colgadas de los montantes, sin función resistente (no se cuenta su efecto de diafragma, del lado de la
  seguridad). Un armario alto se ancla al suelo por defecto.
"""
from __future__ import annotations

import math

import numpy as np

from .. import catalog
from ..cad.sheetmetal import EDGES, FlangeSpec, SheetMetalSpec, analytic_volume
from ..core.model import Joint, PlatePart, SheetPart, StandardPart
from ..core.params import AUTO, ParamSpec
from .base import register
from .estanteria import Estanteria
from .mesa_industrial import even_positions, flange_hole_d, frame_z

DOOR_FLANGE = 20.0      # pestaña de la puerta hacia el armario
DOOR_GAP = 5.0          # punta de la pestaña – frente de los montantes
DOOR_JOINT = 3.0        # holgura entre las dos puertas
DOOR_REVEAL = 1.0       # retranqueo de la puerta respecto al contorno exterior de los laterales
DOOR_END_GAP = 2.0      # holgura de la puerta arriba y abajo
MAX_DOOR_W = 650.0      # anchura de hoja a partir de la cual se recomienda partir la puerta
HEAD_CLEAR = 2.0        # holgura del taladro de alojamiento sobre el diámetro de la cabeza del tornillo


def hinge_count(h: float) -> int:
    """Bisagras por puerta según su altura."""
    return 2 if h <= 1200 else 3 if h <= 1800 else 4


@register
class Armario(Estanteria):
    id = "armario"
    name = "Armario industrial"
    prefix = "AR"
    category = "D"
    description = ("Armario de taller sobre estructura tubular soldada: bandejas de chapa plegada (suelo, baldas y "
                   "techo), laterales y fondo de chapa atornillados a los montantes y una o dos puertas batientes con "
                   "bisagras de pernio y maneta con cerradura. Calculado como estantería, anclado al suelo.")
    configurations = ["Armario de taller", "Armario de herramientas", "Armario de una puerta", "Armario bajo",
                      "Armario inoxidable"]
    auto_in_construct = Estanteria.auto_in_construct + ("NUMERO_PUERTAS", "ESPESOR_PANEL", "ESPESOR_PUERTA")
    level_load_kg_m2 = 100            # carga de uso por defecto de cada bandeja (kg/m²)

    # ------------------------------------------------------------------ parámetros
    def param_specs(self):
        P = ParamSpec
        out = []
        for s in super().param_specs():
            if s.name == "ANCHURA":
                s = P("ANCHURA", "Anchura (frente, estructura)", "float", 1000.0, "mm", "dimensiones", 500, 1200)
            elif s.name == "PROFUNDIDAD":
                s = P("PROFUNDIDAD", "Profundidad (estructura)", "float", 500.0, "mm", "dimensiones", 350, 800)
            elif s.name == "ALTURA":
                s = P("ALTURA", "Altura total (techo)", "float", 1950.0, "mm", "dimensiones", 800, 2200)
            elif s.name == "NUMERO_NIVELES":
                s = P("NUMERO_NIVELES", "Niveles de bandeja (suelo, baldas y techo)", "int", 5, "ud", "dimensiones",
                      2, 7, help="La primera bandeja es el suelo del armario y la última, a la altura total, su techo.")
            elif s.name == "CARGA_HORIZONTAL":
                s = P("CARGA_HORIZONTAL", "Empuje horizontal en la parte superior", "float", 150.0, "N", "cargas",
                      0, 5000)
            elif s.name == "MATERIAL_CHAPA":
                s = P("MATERIAL_CHAPA", s.label, s.type, "DC01", None, s.group, choices=s.choices,
                      help="Chapa laminada en frío DC01 por defecto, la habitual en armarios pintados.")
            elif s.name == "ANCLAJE":
                s = P("ANCLAJE", "Anclaje", "choice", "al_suelo", None, "cargas", choices=["ninguno", "al_suelo"],
                      help="Un armario alto y estrecho vuelca con empujes moderados: por defecto se ancla al suelo.")
            out.append(s)
            if s.name == "ESPESOR_BALDA":
                out.append(P("ESPESOR_PANEL", "Espesor de laterales y fondo", "float", AUTO, "mm", "materiales",
                             0.8, 2.0, allow_auto=True,
                             help="'auto': la chapa más fina de 1 mm o más disponible en el material de chapa."))
                out.append(P("ESPESOR_PUERTA", "Espesor de chapa de puertas", "float", AUTO, "mm", "materiales",
                             0.8, 2.0, allow_auto=True,
                             help="'auto': la chapa más fina de 1 mm o más disponible en el material de chapa."))
        idx = max(i for i, s in enumerate(out) if s.group == "accesorios") + 1
        out.insert(idx, P("NUMERO_PUERTAS", "Puertas batientes", "int", AUTO, "ud", "accesorios", 0, 2,
                          allow_auto=True, help="'auto': una hasta 600 mm de anchura y dos por encima. 0: armario "
                                                "abierto, sin puertas."))
        return out

    def templates(self):
        return [
            {"id": "AR-1000x500-1950", "name": "Armario de taller de dos puertas 1.000 × 500 × 1.950 mm",
             "family": self.id,
             "values": {"ANCHURA": 1000.0, "PROFUNDIDAD": 500.0, "ALTURA": 1950.0, "NUMERO_NIVELES": 5,
                        "CARGA_POR_NIVEL": 60.0, "ACABADO": "RAL7035_POLVO"}},
            {"id": "AR-600x500-1950", "name": "Armario de una puerta 600 × 500 × 1.950 mm", "family": self.id,
             "values": {"ANCHURA": 600.0, "PROFUNDIDAD": 500.0, "ALTURA": 1950.0, "NUMERO_NIVELES": 5,
                        "CARGA_POR_NIVEL": 40.0, "ACABADO": "RAL7035_POLVO"}},
            {"id": "AR-1200x600-2000-HERR", "name": "Armario de herramientas 1.200 × 600 × 2.000 mm (100 kg por balda)",
             "family": self.id,
             "values": {"ANCHURA": 1200.0, "PROFUNDIDAD": 600.0, "ALTURA": 2000.0, "NUMERO_NIVELES": 6,
                        "CARGA_POR_NIVEL": 100.0, "ACABADO": "RAL7016_POLVO"}},
            {"id": "AR-1000x500-1000-BAJO", "name": "Armario bajo de dos puertas 1.000 × 500 × 1.000 mm",
             "family": self.id,
             "values": {"ANCHURA": 1000.0, "PROFUNDIDAD": 500.0, "ALTURA": 1000.0, "NUMERO_NIVELES": 3,
                        "CARGA_POR_NIVEL": 50.0, "ANCLAJE": "ninguno", "CARGA_HORIZONTAL": 80.0,
                        "ACABADO": "RAL5010_POLVO"}},
            {"id": "AR-800x400-1800-INOX", "name": "Armario inoxidable de dos puertas 800 × 400 × 1.800 mm",
             "family": self.id,
             "values": {"ANCHURA": 800.0, "PROFUNDIDAD": 400.0, "ALTURA": 1800.0, "NUMERO_NIVELES": 5,
                        "CARGA_POR_NIVEL": 30.0, "MATERIAL_ESTRUCTURAL": "1.4301", "MATERIAL_CHAPA": "1.4301",
                        "ACABADO": "INOX_SATINADO", "ENTORNO": "alimentario"}},
        ]

    # ------------------------------------------------------------------ derivados
    def _derive_shelf(self, ctx, model):
        d = super()._derive_shelf(ctx, model)
        v = ctx.params.values
        A, Pf, H = v["ANCHURA"], v["PROFUNDIDAD"], v["ALTURA"]
        a, z0, leg = d["a"], d["z_leg0"], d["leg"]
        with ctx.feature("F05", "Cerramiento: paneles y puertas"):
            thin = min((t for t in catalog.sheet_thicknesses(v["MATERIAL_CHAPA"]) if t >= 1.0 - 1e-9), default=1.5)
            tp = ctx.derive("ESP_PANEL", lambda p: thin if p["ESPESOR_PANEL"] == AUTO else p["ESPESOR_PANEL"], "mm",
                            "Espesor de laterales y fondo")
            td = ctx.derive("ESP_PUERTA", lambda p: thin if p["ESPESOR_PUERTA"] == AUTO else p["ESPESOR_PUERTA"], "mm",
                            "Espesor de chapa de puertas")
            sel_rn = catalog.select_rivet_nut(leg.t)
            code_rn, rnd = sel_rn if sel_rn else ("TUERCA_REMACHABLE_M6", catalog.component("TUERCA_REMACHABLE_M6"))
            gp = float(rnd["head_h"])                  # la cabeza de la remachable queda entre panel y montante
            Hp = ctx.derive("ALTO_PANEL", lambda p: p["ALTURA"] - p["COTA_INICIO_MONTANTE"], "mm",
                            "Altura de laterales y fondo")
            ctx.derive("ANCHO_FONDO", lambda p: p["ANCHURA"] + 2 * (gp + p["ESP_PANEL"]), "mm",
                       "Anchura del fondo (cubre los cantos de los laterales)")
            pitch = ctx["PASO_FIJACIONES"]
            n_fix = max(2, math.ceil((Hp - 80) / pitch) + 1)
            zs_side = even_positions(40.0, Hp - 40.0, n_fix)
            step = (Hp - 80) / (n_fix - 1)
            # fondo: a media separación de los laterales (las remachables de dos caras no coinciden en el montante)
            zs_back = [round(z + step / 2, 3) for z in zs_side[:-1]]
            if len(zs_back) < 2:
                zs_back = even_positions(60.0, Hp - 60.0, 2)
            n = ctx["NUMERO_PUERTAS"]
            if n == AUTO:
                n = 1 if A <= 600 else 2
            ctx.set_derived("N_PUERTAS", n, "ud", "Puertas batientes", ["NUMERO_PUERTAS", "ANCHURA"])
            Wtot = A + 2 * (gp + tp)
            Hd = round(Hp - 2 * DOOR_END_GAP, 3)
            Wd = round((Wtot - 2 * DOOR_REVEAL - (n - 1) * DOOR_JOINT) / n, 3) if n else 0.0
            if n:
                ctx.set_derived("ANCHO_PUERTA", Wd, "mm", "Anchura de cada puerta", ["ANCHURA", "NUMERO_PUERTAS"])
                ctx.set_derived("ALTO_PUERTA", Hd, "mm", "Altura de puerta", ["ALTURA"])
                if Wd > MAX_DOOR_W:
                    model.note("advertencia", "DFM-PUERTA-ANCHA", f"Puerta de {Wd:.0f} mm de anchura: más de "
                               f"{MAX_DOOR_W:g} mm por hoja tiende a descolgarse; use dos puertas.")
            ctx.set_derived("BISAGRAS_POR_PUERTA", hinge_count(Hd) if n else 0, "ud", "Bisagras por puerta",
                            ["ALTURA"])
            face = {"DI": "-x", "TI": "-x", "DD": "+x", "TD": "+x"}
            holes = {k: [(face[k], z, 0.0, rnd["hole_d"]) for z in zs_side] for k in face}
            for k in ("TI", "TD"):
                holes[k] += [("+y", z, 0.0, rnd["hole_d"]) for z in zs_back]
            d["upright_holes"] = {k: tuple(h) for k, h in holes.items()}
            d.update(enc_tp=tp, enc_td=td, enc_gp=gp, enc_rn=(code_rn, rnd, sel_rn is not None), enc_Hp=Hp, enc_zs_side=zs_side,
                     enc_zs_back=zs_back, enc_n_doors=n, enc_Wtot=Wtot, enc_Wd=Wd, enc_Hd=Hd)
        return d

    # ------------------------------------------------------------------ cerramiento
    def _tray_screw_heads(self, model, A, Pf):
        """Cabezas de los tornillos de las bandejas que asoman por cada cara exterior: {cara: [(u, z)]}."""
        out = {"x0": [], "x1": [], "y1": []}
        for i in model.instances:
            if i.group != "BAL" or i.part.role != "tornillo":
                continue
            p, nz = i.T[:3, 3], i.T[:3, 2]
            if nz[0] < -0.9 and abs(p[0]) < 1.0:
                out["x0"].append((float(p[1]), float(p[2])))
            elif nz[0] > 0.9 and abs(p[0] - A) < 1.0:
                out["x1"].append((float(p[1]), float(p[2])))
            elif nz[1] > 0.9 and abs(p[1] - Pf) < 1.0:
                out["y1"].append((float(p[0]), float(p[2])))
        return out

    def _extras(self, model, ctx, d, legs, corners):
        v = model.params.values
        A, Pf, H = v["ANCHURA"], v["PROFUNDIDAD"], v["ALTURA"]
        a, z0, wall = d["a"], d["z_leg0"], d["leg"].t
        mat_c, fin = v["MATERIAL_CHAPA"], v["ACABADO"]
        tp, gp, Hp = d["enc_tp"], d["enc_gp"], d["enc_Hp"]
        code_rn, rnd, rn_found = d["enc_rn"]
        sel_sc = catalog.select_screw(tp + gp, tp + gp + rnd["body_l"])
        code_sc = sel_sc[0] if sel_sc else "TORNILLO_ISO7380_M6x12"
        sc = catalog.component(code_sc)
        hd = flange_hole_d(mat_c, tp, sc)
        heads = self._tray_screw_heads(model, A, Pf)
        tray_sc = next((i.part.data for i in model.instances if i.group == "BAL" and i.part.role == "tornillo"), sc)
        hclear = round(float(tray_sc["head_d"]) + HEAD_CLEAR, 2)
        rho = catalog.material(mat_c).density
        masses = model.structure.setdefault("attached_masses", [])

        def fix(prefix, panel_id, pts, nrm):
            """Remachables en el montante y tornillos a través del panel: pts = [(montante, punto en la cara del panel)]."""
            nrm = np.asarray(nrm, float)
            for n, (leg_id, pf) in enumerate(pts, start=1):
                pf = np.asarray(pf, float)
                pr = pf - nrm * (tp + gp)
                rid, sid = f"{prefix}.TREM.{n:02d}", f"{prefix}.TORN.{n:02d}"
                model.add(rid, f"Tuerca remachable {n}", StandardPart("tuerca_remachable", code_rn), frame_z(pr, nrm),
                          "PAN", tags={"explode_extra": tuple(nrm * 30)})
                model.add(sid, f"Tornillo {n}", StandardPart("tornillo", code_sc), frame_z(pf, nrm), "PAN",
                          tags={"explode_extra": tuple(nrm * 80)})
                model.add_joint(Joint(f"J.{sid}", "atornillada", (panel_id, rid), tuple(pf),
                                      f"Tornillo {sc['thread']} en tuerca remachable", fasteners=(sid, rid),
                                      data={"t_sheet": tp, "gap": gp, "wall": wall, "screw": code_sc, "rivet": code_rn,
                                            "rivet_found": rn_found, "screw_found": sel_sc is not None, "hole": hd}))

        model.add_subassembly("PAN", "Laterales y fondo", explode=(0, 0, 0), step=4)
        with ctx.feature("F37", "Laterales y fondo de chapa"):
            ctx.uses("ESP_PANEL", "ANCHURA", "PROFUNDIDAD", "ALTURA", "ALTO_PANEL", "ANCHO_FONDO", "PERFIL_MONTANTE",
                     "PASO_FIJACIONES", "MATERIAL_CHAPA", "ACABADO")
            zs = d["enc_zs_side"]
            # lateral: X local = Y (fondo), Y local = Z, espesor según +X; el izquierdo y el derecho son la misma pieza
            def head_holes(pts, du=0.0):
                return [(u, z, hclear) for u, z in sorted(set((round(u + du, 3), round(z - z0, 3)) for u, z in pts))]
            side_holes = [(a / 2, z, hd) for z in zs] + [(Pf - a / 2, z, hd) for z in zs]
            side_holes += head_holes(heads["x0"] + heads["x1"])
            side = PlatePart("lateral", f"Lateral chapa {tp:g} mm", Pf, Hp, tp, mat_c, fin, holes=tuple(side_holes))
            for iid, x0, sgn, name, legs_k in (("PAN.LATERAL_I", -gp - tp, -1, "Lateral izquierdo", ("DI", "TI")),
                                               ("PAN.LATERAL_D", A + gp, 1, "Lateral derecho", ("DD", "TD"))):
                T = np.array([[0, 0, 1.0, x0], [1.0, 0, 0, 0], [0, 1.0, 0, z0], [0, 0, 0, 1.0]])
                model.add(iid, name, side, T, "PAN", tags={"explode_extra": (sgn * 260.0, 0, 0)})
                xf = x0 if sgn < 0 else x0 + tp           # cara exterior del panel
                pts = [(legs[k], (xf, model.instance(legs[k]).axis[0][1], z0 + z)) for k in legs_k for z in zs]
                fix(iid, iid, pts, (sgn, 0, 0))
                pm = side.analytic_volume * 1e-9 * rho
                masses.extend({"member": legs[k], "point": (model.instance(legs[k]).axis[0][0],
                                                            model.instance(legs[k]).axis[0][1], z0 + z),
                               "mass_kg": pm / len(pts), "label": name} for k in legs_k for z in zs)
            # fondo: X local = X, Y local = Z, espesor según -Y; cubre los cantos traseros de los laterales
            zb = d["enc_zs_back"]
            Wb = A + 2 * (gp + tp)
            back_holes = [(gp + tp + a / 2, z, hd) for z in zb] + [(gp + tp + A - a / 2, z, hd) for z in zb]
            back_holes += head_holes(heads["y1"], gp + tp)
            back = PlatePart("fondo", f"Fondo chapa {tp:g} mm", Wb, Hp, tp, mat_c, fin, holes=tuple(back_holes))
            T = np.array([[1.0, 0, 0, -gp - tp], [0, 0, -1.0, Pf + gp + tp], [0, 1.0, 0, z0], [0, 0, 0, 1.0]])
            model.add("PAN.FONDO", "Fondo", back, T, "PAN", tags={"explode_extra": (0, 320.0, 0)})
            pts = [(legs[k], (model.instance(legs[k]).axis[0][0], Pf + gp + tp, z0 + z)) for k in ("TI", "TD") for z in zb]
            fix("PAN.FONDO", "PAN.FONDO", pts, (0, 1, 0))
            pm = back.analytic_volume * 1e-9 * rho
            masses.extend({"member": legs[k], "point": (model.instance(legs[k]).axis[0][0],
                                                        model.instance(legs[k]).axis[0][1], z0 + z),
                           "mass_kg": pm / len(pts), "label": "Fondo"} for k in ("TI", "TD") for z in zb)
        n = d["enc_n_doors"]
        if n:
            self._doors(model, ctx, d, legs, masses)

    def _doors(self, model, ctx, d, legs, masses):
        v = model.params.values
        A = v["ANCHURA"]
        z0, gp, tp = d["z_leg0"], d["enc_gp"], d["enc_tp"]
        n, Wd, Hd = d["enc_n_doors"], d["enc_Wd"], d["enc_Hd"]
        mat_c, fin = v["MATERIAL_CHAPA"], v["ACABADO"]
        inox = catalog.material(v["MATERIAL_ESTRUCTURAL"]).family == "acero_inoxidable"
        hinge_code = "BISAGRA_PERNIO_80_INOX" if inox else "BISAGRA_PERNIO_80"
        lock_code = "CERRADURA_MANETA_INOX" if inox else "CERRADURA_MANETA"
        hinge, lock = catalog.component(hinge_code), catalog.component(lock_code)
        model.add_subassembly("PUE", "Puertas", explode=(0, -380, 0), step=5)
        with ctx.feature("F38", "Puertas batientes de chapa plegada"):
            ctx.uses("NUMERO_PUERTAS", "N_PUERTAS", "ESP_PUERTA", "ANCHO_PUERTA", "ALTO_PUERTA", "ANCHURA", "ALTURA",
                     "MATERIAL_CHAPA", "ACABADO")
            t = d["enc_td"]
            fam = catalog.material(mat_c).family
            rmin = catalog.sheet_data()["press_brake"]["min_inner_radius_factor"].get(fam, 1.0)
            r = round(max(t, rmin * t), 2) if v["RADIO_PLEGADO"] == AUTO else v["RADIO_PLEGADO"]
            K = round(catalog.din6935_k_factor(r, t), 4) if v["FACTOR_K"] == AUTO else v["FACTOR_K"]
            # desarrollo con la altura según X: a lo largo de la chapa (pulido vertical en el inoxidable satinado, que
            # no se gira al anidar; antes una puerta de 2 m no cabía en ningún formato)
            spec = SheetMetalSpec(Hd, Wd, t, r, K, tuple(FlangeSpec(e, DOOR_FLANGE, "down") for e in EDGES))
            door = SheetPart("puerta", f"Puerta chapa {t:g} mm", spec, mat_c, fin)
            yF = -(DOOR_GAP + DOOR_FLANGE)               # cara exterior de la puerta; pestañas hacia +Y
            zd = z0 + DOOR_END_GAP
            x_left = -gp - tp + DOOR_REVEAL
            nh = hinge_count(Hd)
            zh = [zd + z for z in even_positions(150.0, Hd - 150.0, nh)]
            leaves = [("PUE.PUERTA_I" if n == 2 else "PUE.PUERTA", x_left, "izquierda" if n == 2 else "", "DI")]
            if n == 2:
                leaves.append(("PUE.PUERTA_D", x_left + Wd + DOOR_JOINT, "derecha", "DD"))
            zl = zd + min(Hd / 2, 1050.0 - zd) if Hd > 400 else zd + Hd / 2      # maneta a ~1.050 mm o a media altura
            pm = analytic_volume(spec) * 1e-9 * catalog.material(mat_c).density
            for k, (iid, x0, side, leg_k) in enumerate(leaves):
                # X local = Z (altura), Y local = -X (anchura), Z local = -Y: pestañas hacia el armario
                T = np.array([[0, -1.0, 0, x0 + Wd], [0, 0, -1.0, yF], [1.0, 0, 0, zd], [0, 0, 0, 1.0]])
                model.add(iid, f"Puerta {side}".strip(), door, T, "PUE")
                hinge_left = k == 0
                xe = x0 if hinge_left else x0 + Wd                                # canto de giro
                for j, z in enumerate(zh, start=1):
                    hid = f"{iid}.BISAGRA.{j}"
                    model.add(hid, f"Bisagra {j} puerta {side}".replace("  ", " ").strip(),
                              StandardPart("bisagra", hinge_code),
                              np.array([[1.0, 0, 0, xe], [0, 1.0, 0, yF - hinge["dims"][1] / 2], [0, 0, 1.0, z - 40.0],
                                        [0, 0, 0, 1.0]]), "PUE")
                    model.add_joint(Joint(f"J.{hid}", "remachada", (iid, hid), (xe, yF, z),
                                          "Bisagra de pernio remachada a puerta y lateral (remaches no modelados)"))
                if n == 1 or not hinge_left:                                      # maneta en el canto libre
                    xl = (x0 + Wd - 45.0) if hinge_left else (x0 + 45.0)
                    lid = f"{iid}.MANETA"
                    model.add(lid, f"Maneta con cerradura puerta {side}".strip(), StandardPart("cerradura", lock_code),
                              np.array([[1.0, 0, 0, xl], [0, 1.0, 0, yF - lock["dims"][1] / 2], [0, 0, 1.0, zl - 60.0],
                                        [0, 0, 0, 1.0]]), "PUE")
                    model.add_joint(Joint(f"J.{lid}", "remachada", (iid, lid), (xl, yF, zl),
                                          "Maneta con cerradura de cuarto de vuelta (montaje en taladro, no modelado)"))
                # la puerta cuelga del montante del lado de las bisagras
                extra = nh * float(hinge["mass_kg"]) + (float(lock["mass_kg"]) if (n == 1 or not hinge_left) else 0.0)
                inst = model.instance(legs[leg_k])
                masses.extend({"member": legs[leg_k], "point": (inst.axis[0][0], inst.axis[0][1], z),
                               "mass_kg": (pm + extra) / nh, "label": f"Puerta {side}".strip()} for z in zh)

    # ------------------------------------------------------------------ cálculo, cotas y montaje
    def _shelf_structure(self, model, d, legs):
        st = super()._shelf_structure(model, d, legs)
        st["attached_masses"] = model.structure.get("attached_masses", [])
        st["product_word"] = "armario"
        n = d["enc_n_doors"]
        st["assembly_texts"] = {
            **st.get("assembly_texts", {}),
            "PAN": "Presentar los laterales contra la cara exterior de los montantes y atornillarlos a las tuercas "
                   "remachables M6 (8 N·m), de abajo arriba; después, el fondo, que cubre los cantos traseros de los "
                   "laterales. Los taladros grandes de los paneles alojan las cabezas de los tornillos de las bandejas.",
            "PUE": ("Remachar las bisagras de pernio a la puerta y al lateral, con la puerta calzada a 2 mm del suelo del "
                    "armario; comprobar el cierre y montar la maneta con cerradura en el canto libre." if n == 1 else
                    "Remachar las bisagras de pernio a cada puerta y a su lateral, con las puertas calzadas a 2 mm del "
                    "suelo del armario y 3 mm de holgura entre ellas; montar la maneta con cerradura en la puerta "
                    "derecha.") if n else "Armario abierto: sin puertas.",
        }
        return st

    def _extra_dims(self, model, d):
        v = model.params.values
        A, Pf, H = v["ANCHURA"], v["PROFUNDIDAD"], v["ALTURA"]
        gp, tp = d["enc_gp"], d["enc_tp"]
        dx = round(A + 2 * (gp + tp), 3)
        y_front = -(DOOR_GAP + DOOR_FLANGE) if d["enc_n_doors"] else 0.0
        dy = round(Pf + gp + tp - y_front, 3)
        ids = ["PAN.LATERAL_I", "PAN.LATERAL_D", "PAN.FONDO"] + [i.id for i in model.instances
                                                                 if i.group == "PUE" and i.part.role == "puerta"]
        if not d["enc_n_doors"]:
            ids += [f"BAL.BANDEJA.{i + 1}" for i in range(len(d["z_levels"]))]
        model.dims["ANCHURA_TOTAL"], model.dims["PROFUNDIDAD_TOTAL"] = dx, dy
        model.dims["envelope"] = {"ids": ids, "dx": dx, "dy": dy, "zmax": H, "names": ("ANCHURA_TOTAL", "PROFUNDIDAD_TOTAL")}
