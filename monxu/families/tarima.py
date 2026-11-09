"""Familia A: tarima / plataforma baja de trabajo (EN ISO 14122-2).

Superficie de tránsito de chapa de acero de 3 a 10 mm soldada sobre un bastidor de tubo (largueros, travesaños
extremos e intermedios) con patas cortas, placas base y pies niveladores. Sirve para elevar al operario frente a una
máquina o una línea, como paso sobre conducciones o como podio de trabajo.

Cargas de proyecto (EN ISO 14122-2 §4.2.4): carga repartida de servicio no menor que 2 kN/m² y carga concentrada de
1,5 kN sobre 200 × 200 mm en la posición más desfavorable; flecha no mayor que L/200. La chapa se calcula con Navier en
cada panel entre travesaños; el bastidor, con el modelo de barras.

Límites: altura de la superficie hasta 500 mm (por encima, EN ISO 14122-3 exige barandilla, no incluida). La chapa se
modela lisa: la superficie antideslizante (chapa lagrimada o recubrimiento) queda como indicación, no se modela.
"""
from __future__ import annotations

import math

from .. import catalog
from ..cad import geometry as G
from ..cad.sheetmetal import EDGES
from ..core.model import PlatePart, ProductModel
from ..core.params import AUTO, ParamContext, ParamSpec
from .base import register
from .mesa_industrial import CANDIDATES as MESA_CANDIDATES
from .mesa_soldadura import PLATE_CORNER_R, STITCH_L, STITCH_PITCH, MesaSoldadura

DECK_MATERIALS = ["S235JR", "S275JR", "S355JR"]
DECK_THICKNESSES = [3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
SERVICE_LOAD_KN_M2 = 2.0       # EN ISO 14122-2: carga repartida mínima de plataformas y pasarelas
POINT_LOAD_KG = 153.0          # 1,5 kN
POINT_PATCH_MM = 200.0         # huella de la carga concentrada
GUARDRAIL_HEIGHT = 500.0       # EN ISO 14122-3: por encima, barandilla obligatoria

DROP = {"VUELO", "MATERIAL_CHAPA", "ESPESOR_BALDA", "SISTEMA_TALADROS", "PERFIL_BASTIDOR", "PERFIL_REPOSAPIES",
        "NUMERO_TRAVESANOS_BALDA", "ALA_BALDA", "RADIO_PLEGADO", "FACTOR_K", "HOLGURA_ENCIMERA", "HOLGURA_ESCOTADURA",
        "PASO_FIJACIONES", "REPOSAPIES", "ALTURA_REPOSAPIES", "NUMERO_BALDAS", "ALTURA_BALDA", "CARGA_BALDA", "USO"}
CANDIDATES = {k: v for k, v in MESA_CANDIDATES.items() if k in ("PERFIL_PATA", "PERFIL_LARGUERO", "PERFIL_TRAVESANO")}
CONSTRUCTIVE_DEFAULTS = {"PERFIL_PATA": "SHS 50x50x2", "PERFIL_LARGUERO": "RHS 60x40x2",
                         "PERFIL_TRAVESANO": "RHS 40x20x2", "ESPESOR_PLACA": 4.0, "PIE_NIVELADOR": "PIE_NIV_M12_D80"}


@register
class Tarima(MesaSoldadura):
    id = "tarima"
    name = "Tarima / plataforma de trabajo"
    prefix = "TA"
    category = "A"
    description = ("Plataforma baja de trabajo (hasta 500 mm) con superficie de chapa de acero soldada sobre bastidor de "
                   "tubo, patas cortas y pies niveladores; calculada con las cargas de EN ISO 14122-2 (2 kN/m² repartida "
                   "y 1,5 kN concentrada sobre 200 × 200 mm) y flecha L/200.")
    configurations = ["Tarima de operario", "Plataforma frente a máquina", "Podio de trabajo"]
    candidates = CANDIDATES
    constructive_defaults = CONSTRUCTIVE_DEFAULTS
    frame_params = ("PERFIL_LARGUERO", "PERFIL_TRAVESANO")
    top_iid, top_label = "ENC.PLACA", "Superficie de la tarima"

    def default_loads(self, v):
        L, W = v.get("LONGITUD") or 0, v.get("ANCHURA") or 0
        kg = float(max(10, math.ceil(SERVICE_LOAD_KN_M2 * L * W * 1e-6 / 9.81e-3 / 10) * 10))
        return {"CARGA_TOTAL": (kg, f"{SERVICE_LOAD_KN_M2:g} kN/m² de EN ISO 14122-2 sobre {L:g} × {W:g} mm")}

    # ------------------------------------------------------------------ cálculo
    def plate_targets(self, v):
        if not (v.get("CARGA_TOTAL") or v.get("CARGA_PUNTUAL")):
            return []
        avail = set(catalog.sheet_thicknesses(v["MATERIAL_PLACA"]))
        return [{"surface": "encimera", "t_param": "ESPESOR_PLACA", "n_param": "NUMERO_TRAVESANOS",
                 "load_param": "CARGA_TOTAL", "trv_param": "PERFIL_TRAVESANO", "min_t_by_use": False,
                 "mat_param": "MATERIAL_PLACA", "t_options": [t for t in DECK_THICKNESSES if t in avail],
                 "t_max": DECK_THICKNESSES[-1]}]

    def sheet_defaults_without_load(self, v):
        return {} if (v.get("CARGA_TOTAL") or v.get("CARGA_PUNTUAL")) else \
            {"ESPESOR_PLACA": CONSTRUCTIVE_DEFAULTS["ESPESOR_PLACA"]}

    def leg_fits(self, v) -> bool:
        return True

    # ------------------------------------------------------------------ parámetros
    def param_specs(self):
        P = ParamSpec
        out = []
        for s in super().param_specs():
            if s.name in DROP:
                continue
            if s.name == "LONGITUD":
                s = P("LONGITUD", "Longitud de la tarima", "float", 1200.0, "mm", "dimensiones", 600, 3000)
            elif s.name == "ANCHURA":
                # la chapa entera ha de caber en el formato de 4000 × 2000 con los márgenes de corte
                s = P("ANCHURA", "Anchura (fondo) de la tarima", "float", 800.0, "mm", "dimensiones", 500, 1800)
            elif s.name == "ALTURA":
                s = P("ALTURA", "Altura de la superficie de tránsito", "float", 200.0, "mm", "dimensiones", 120,
                      GUARDRAIL_HEIGHT, help="Hasta 500 mm: por encima, EN ISO 14122-3 exige barandilla.")
            elif s.name == "MATERIAL_PLACA":
                s = P("MATERIAL_PLACA", "Material de la chapa de la superficie", "choice", "S235JR", None, "materiales",
                      choices=DECK_MATERIALS)
            elif s.name == "ESPESOR_PLACA":
                s = P("ESPESOR_PLACA", "Espesor de la chapa de la superficie", "float", AUTO, "mm", "materiales", 3, 10,
                      allow_auto=True, help="'auto': el menor que verifica la carga repartida y la concentrada.")
            elif s.name == "CARGA_TOTAL":
                s = P("CARGA_TOTAL", "Carga repartida sobre la tarima (total)", "float", None, "kg", "cargas", 0, 8000,
                      nullable=True, help="EN ISO 14122-2: no menos de 2 kN/m² (≈ 204 kg por m² de superficie).")
            elif s.name == "CARGA_PUNTUAL":
                s = P("CARGA_PUNTUAL", "Carga concentrada (200 × 200 mm)", "float", POINT_LOAD_KG, "kg", "cargas", 0,
                      2000, nullable=True, help="EN ISO 14122-2: 1,5 kN (153 kg) en la posición más desfavorable.")
            elif s.name == "CARGA_HORIZONTAL":
                s = P("CARGA_HORIZONTAL", "Empuje horizontal en el canto de la superficie", "float", 150.0, "N",
                      "cargas", 0, 3000)
            elif s.name == "PERFIL_PATA":
                s = P("PERFIL_PATA", "Perfil de patas", "choice", AUTO, None, "construccion", choices=s.choices,
                      allow_auto=True)
            out.append(s)
        return out

    def templates(self):
        return [
            {"id": "TA-1200x800-200", "name": "Tarima de operario 1.200 × 800 mm, 200 mm de altura", "family": self.id,
             "values": {"LONGITUD": 1200.0, "ANCHURA": 800.0, "ALTURA": 200.0, "CARGA_TOTAL": 200.0,
                        "CARGA_PUNTUAL": POINT_LOAD_KG}},
            {"id": "TA-2000x1000-300", "name": "Plataforma frente a máquina 2.000 × 1.000 mm, 300 mm",
             "family": self.id,
             "values": {"LONGITUD": 2000.0, "ANCHURA": 1000.0, "ALTURA": 300.0, "CARGA_TOTAL": 410.0,
                        "CARGA_PUNTUAL": POINT_LOAD_KG, "ANCLAJE": "al_suelo"}},
            {"id": "TA-3000x1200-450", "name": "Podio de trabajo 3.000 × 1.200 mm, 450 mm (cargas de taller)",
             "family": self.id,
             "values": {"LONGITUD": 3000.0, "ANCHURA": 1200.0, "ALTURA": 450.0, "CARGA_TOTAL": 1100.0,
                        "CARGA_PUNTUAL": 250.0, "ANCLAJE": "al_suelo"}},
            {"id": "TA-800x600-150", "name": "Tarima pequeña de operario 800 × 600 mm, 150 mm de altura", "family": self.id,
             "values": {"LONGITUD": 800.0, "ANCHURA": 600.0, "ALTURA": 150.0, "CARGA_TOTAL": 100.0,
                        "CARGA_PUNTUAL": 153.0}},
            {"id": "TA-2400x1200-500", "name": "Plataforma de trabajo 2.400 × 1.200 mm, 500 mm (anclada)", "family": self.id,
             "values": {"LONGITUD": 2400.0, "ANCHURA": 1200.0, "ALTURA": 500.0, "CARGA_TOTAL": 590.0,
                        "CARGA_PUNTUAL": 153.0, "ANCLAJE": "al_suelo"}},
        ]

    # ------------------------------------------------------------------ derivados
    def _derive(self, ctx: ParamContext, model: ProductModel) -> dict:
        d: dict = {}
        with ctx.feature("F00", "Parámetros derivados y reglas constructivas"):
            t = ctx.derive("ESP_PLACA", lambda p: p["ESPESOR_PLACA"], "mm", "Espesor de la chapa de la superficie")
            c = ctx.derive("RETRANQUEO", lambda p: 0.0, "mm", "Retranqueo de la estructura (enrasada con la chapa)")
            leg = catalog.profile(ctx["PERFIL_PATA"])
            rail = catalog.profile(ctx["PERFIL_LARGUERO"])
            trv = catalog.profile(ctx["PERFIL_TRAVESANO"])
            if leg.B != leg.H:
                raise ValueError("Las patas deben ser de tubo cuadrado")
            a = leg.B
            ctx.set_derived("SECCION_PATA", f"{leg.B:g}x{leg.H:g}", "mm", "Sección de pata", ["PERFIL_PATA"])
            ctx.set_derived("ESPESOR_PERFIL_PATA", leg.t, "mm", "Espesor de pata", ["PERFIL_PATA"])
            foot = catalog.component(ctx[self.support_param])
            hn = float(foot["nominal_height"])
            tp = ctx["ESPESOR_PLACA_BASE"]
            z_tf = ctx.derive("COTA_BASTIDOR_SUP", lambda p: p["ALTURA"] - p["ESP_PLACA"], "mm",
                              "Cota cara superior del bastidor (apoyo de la chapa)")
            sp = self.support_param
            z_leg0 = ctx.derive("COTA_INICIO_PATA", lambda p: float(catalog.component(p[sp])["nominal_height"])
                                + p["ESPESOR_PLACA_BASE"], "mm", "Cota inicio de pata")
            leg_len = ctx.derive("LONGITUD_PATA", lambda p: p["COTA_BASTIDOR_SUP"] - p["COTA_INICIO_PATA"], "mm",
                                 "Longitud de corte de pata")
            L, W, H = ctx["LONGITUD"], ctx["ANCHURA"], ctx["ALTURA"]
            ctx.derive("LONGITUD_LARGUERO", lambda p: p["LONGITUD"] - 2 * catalog.profile(p["PERFIL_PATA"]).B, "mm",
                       "Longitud de largueros")
            ctx.derive("LONGITUD_TRAVESANO_EXT", lambda p: p["ANCHURA"] - 2 * catalog.profile(p["PERFIL_PATA"]).B, "mm",
                       "Longitud de travesaños extremos")
            ctx.derive("LONGITUD_TRAVESANO_INT", lambda p: p["ANCHURA"] - 2 * catalog.profile(p["PERFIL_LARGUERO"]).B,
                       "mm", "Longitud de travesaños intermedios")
            if rail.B > a or trv.B > a:
                model.note("error", "DFM-ANCHO-BASTIDOR", "El ancho de largueros/travesaños supera el de la pata: "
                           "no pueden enrasarse con la cara exterior.")
            frame_h = max(rail.H, trv.H)
            if z_tf - frame_h < z_leg0 + 10:
                h_min = math.ceil((z_leg0 + 10 + frame_h + t) / 5) * 5
                model.note("error", "GEO-TARIMA-BAJA", f"Con el pie {foot['name']} y el bastidor de {frame_h:g} mm de "
                           f"canto no cabe la tarima de {H:g} mm: altura mínima {h_min:g} mm, o pies y perfiles más "
                           "bajos.")
            xe0, xe1 = c + trv.B / 2, L - c - trv.B / 2
            n_top = ctx["NUMERO_TRAVESANOS"]
            if n_top == AUTO:
                n_top = max(0, math.ceil((xe1 - xe0) / ctx["SEPARACION_MAX_APOYOS"]) - 1)
            ctx.set_derived("N_TRAVESANOS_INT", n_top, "ud", "Travesaños intermedios", ["NUMERO_TRAVESANOS",
                            "SEPARACION_MAX_APOYOS", "LONGITUD"])
            ctx.set_derived("VANO_ENCIMERA", round((xe1 - xe0) / (n_top + 1), 2), "mm", "Vano entre apoyos de la chapa",
                            ["LONGITUD", "NUMERO_TRAVESANOS", "PERFIL_TRAVESANO"])
            q = ctx.params.values.get("CARGA_TOTAL")
            if q is not None:
                q_kn = q * 9.81e-3 / (L * W * 1e-6)
                ctx.set_derived("CARGA_SUPERFICIAL", round(q_kn, 3), "kN/m²", "Carga repartida por unidad de superficie",
                                ["CARGA_TOTAL", "LONGITUD", "ANCHURA"])
                if q_kn < SERVICE_LOAD_KN_M2 - 1e-9:
                    model.note("advertencia", "NORMA-14122-CARGA", f"Carga repartida de {q_kn:.2f} kN/m², inferior a la "
                               f"de servicio de {SERVICE_LOAD_KN_M2:g} kN/m² de EN ISO 14122-2 para plataformas de "
                               f"trabajo: use al menos {math.ceil(SERVICE_LOAD_KN_M2 * L * W * 1e-6 / 9.81e-3):g} kg.")
            P = ctx.params.values.get("CARGA_PUNTUAL")
            if P is not None and P < POINT_LOAD_KG - 1e-9:
                model.note("advertencia", "NORMA-14122-PUNTUAL", f"Carga concentrada de {P:g} kg, inferior a la de "
                           f"1,5 kN ({POINT_LOAD_KG:g} kg) de EN ISO 14122-2.")
            model.note("advertencia", "ERG-ANTIDESLIZANTE", "Superficie de chapa lisa: EN ISO 14122-2 exige una "
                       "superficie de tránsito antideslizante; prever chapa lagrimada o recubrimiento antideslizante "
                       "(no modelado).")
            if H > 250:
                model.note("advertencia", "ERG-ACCESO", f"Altura de {H:g} mm: valorar un peldaño de acceso (no incluido).")
            d.update(Lx=L, Ly=W, leg=leg, rail=rail, trv=trv, bas=None, a=a, c=c, t=t, hn=hn, tp=tp, z_tf=z_tf,
                     z_leg0=z_leg0, leg_len=leg_len, n_top=n_top, xe=(xe0, xe1), shelf=False, peto=0.0, footrest=None)
            d["weld_a"] = lambda tmin: 3.0 if tmin >= 3 else float(tmin)
            d["plate"] = {"holes": (), "eta": 1.0}
            d["top_surface"] = {"patch_mm": POINT_PATCH_MM}
            d["fix_top"] = {"s": {e: [] for e in EDGES}, "h": {e: 0.0 for e in EDGES}, "z_ref": H, "t": t,
                            "inset": 0.0, "offset": 0.0, "Lx": L, "Ly": W, "c": c,
                            "wall": {e: (rail if e in ("y0", "y1") else trv).t for e in EDGES}, "gap": 0.0}
            d["skirt"] = rail.H
        return d

    # ------------------------------------------------------------------ ganchos de la mesa
    def _top_frame_uses(self):
        return ("ESPESOR_PLACA",)

    def _build_top(self, model, ctx, d, H, mat_c, fin, rn, sc):
        v = model.params.values
        L, W, t = v["LONGITUD"], v["ANCHURA"], d["t"]
        with ctx.feature("F20", "Chapa de la superficie de tránsito"):
            ctx.uses("LONGITUD", "ANCHURA", "ALTURA", "ESP_PLACA", "MATERIAL_PLACA", "ACABADO")
            part = PlatePart("chapa_tarima", f"Chapa de la tarima {t:g} mm", L, W, t, v["MATERIAL_PLACA"], fin,
                             corner_r=PLATE_CORNER_R)
            model.add(self.top_iid, "Superficie de la tarima", part, G.translation(0, 0, H - t), "ENC")
            self._stitch_welds(model, d, t, "Chapa de la tarima a bastidor")

    def _structure(self, model, d, legs):
        st = super()._structure(model, d, legs)
        st["product_word"] = "tarima"
        st["assembly_texts"] = {
            "ENC": "Colocar la chapa sobre el bastidor, enrasada con él, y soldarla con cordones discontinuos "
                   f"a{d['weld_a'](min(d['t'], d['rail'].t)):g} de {STITCH_L:g} mm cada {STITCH_PITCH:g} mm, alternos "
                   "para limitar la deformación. Aplicar el recubrimiento antideslizante antes del montaje."}
        return st
