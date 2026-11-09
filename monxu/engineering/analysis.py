"""Motor de verificación estructural.

Construye el modelo de barras a partir de las instancias estructurales y de las uniones
declaradas por la familia, aplica los casos de carga, combina según EN 1990 y realiza las
comprobaciones (EN 1993-1-1 / 1-8 simplificadas y conservadoras). Cada comprobación indica
norma, hipótesis, valor, límite, aprovechamiento y estado. Si falta información el resultado
se marca como PENDIENTE: nunca se asigna una capacidad sin cálculo.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .. import catalog
from ..core.params import AUTO
from .fem import Frame3D, line_load_to_nodes
from .plate import navier

OK, FAIL, PENDING, WARN = "CUMPLE", "NO_CUMPLE", "PENDIENTE", "ADVERTENCIA"
G_ACC = 9.81
MAX_ELEMENT = 100.0
N_ZERO = 1e-3          # N: axil por debajo del cual la barra se considera sin compresión
MASCULINE_WORDS = ("carro", "puesto", "armario", "escalón")     # concordancia del texto de vuelco ("del carro vacío", "de la mesa vacía")
#: carros: la maniobra actúa en la dirección de la marcha; lateralmente (giros, empujes ocasionales) esta fracción
LATERAL_FACTOR_MOBILE = 0.5
DIRS = ("+X", "-X", "+Y", "-Y")


def own_weight(model) -> tuple[float, np.ndarray]:
    """Peso (N) y centro de gravedad del conjunto sin los tacos de anclaje, que quedan en el suelo."""
    own = [i for i in model.instances if i.part.role != "anclaje"]
    ms = np.array([i.part.mass for i in own])
    return float(ms.sum()) * G_ACC, (np.array([i.centroid for i in own]) * ms[:, None]).sum(axis=0) / ms.sum()


def support_levers(sups, cog) -> dict:
    pts = np.array([s["point"] for s in sups])
    xmin, xmax = pts[:, 0].min(), pts[:, 0].max()
    ymin, ymax = pts[:, 1].min(), pts[:, 1].max()
    return {"+X": xmax - cog[0], "-X": cog[0] - xmin, "+Y": ymax - cog[1], "-Y": cog[1] - ymin}


def dynamic_factor(ps: dict) -> float:
    """Coeficiente dinámico de las cargas de uso (carros rodando sobre juntas y umbrales); 1 si no se indica."""
    return max(1.0, float(ps.get("COEF_DINAMICO") or 1.0))


def patch_size(ps: dict, surf: dict) -> float:
    """Lado de la huella cuadrada de la carga puntual: el del proyecto, el de la superficie o el del criterio general."""
    return float(ps.get("HUELLA_CARGA_PUNTUAL") or surf.get("patch_mm") or catalog.criteria()["point_load_patch_mm"])


def deflection_ratios(ps: dict) -> tuple[float, float, float]:
    """Límites de flecha (L/…) de barras y chapas y de desplome (H/…): los del proyecto o los del criterio general."""
    dl = catalog.criteria()["deflection_limits"]
    return (float(ps.get("LIMITE_FLECHA_BARRAS") or dl["member_span_ratio"]),
            float(ps.get("LIMITE_FLECHA_CHAPA") or dl["panel_span_ratio"]),
            float(ps.get("LIMITE_DESPLOME") or dl["sway_height_ratio"]))


def _lc(name: str) -> str:
    """Nombre de catálogo en minúscula inicial, para usarlo dentro de una frase."""
    return name[:1].lower() + name[1:]


def class4_rho(prof, fy: float) -> float:
    """EN 1993-1-5 §4.4: factor de reducción de la pared más esbelta de un tubo rectangular en compresión uniforme
    (ψ = 1, kσ = 4); se aplica a toda la sección (área y módulos), del lado de la seguridad."""
    eps = math.sqrt(235.0 / fy)
    ct = max(prof.H - 3 * prof.t, prof.B - 3 * prof.t) / prof.t
    lp = ct / (28.4 * eps * 2.0)
    return 1.0 if lp <= 0.673 else min(1.0, (lp - 0.22) / lp ** 2)


def overturning(model, ps: dict, st: dict | None = None) -> dict | None:
    """Vuelco del conjunto vacío (EN 1990 EQU: γG,stb = 0,9 sobre el peso, γQ = 1,5 sobre el empuje) en las cuatro
    direcciones. Empuje CARGA_HORIZONTAL a la altura de empuje; en los carros ("mobile"), completo en la dirección de
    la marcha (X) y LATERAL_FACTOR_MOBILE en la lateral (Y). Devuelve la dirección determinante (mayor cociente
    Mdst/Mstb) y la tracción de anclaje necesaria (la mayor de las cuatro direcciones), o None sin apoyos o sin empuje."""
    st = st if st is not None else model.structure
    sups = st.get("supports", [])
    H_N = ps.get("CARGA_HORIZONTAL") or 0.0
    if not sups or not H_N:
        return None
    pf = catalog.criteria()["partial_factors"]
    Wtot, cog = own_weight(model)          # los tacos de anclaje quedan en el suelo: su peso no estabiliza
    levers = support_levers(sups, cog)
    pts = np.array([s["point"] for s in sups])
    hgt = st.get("push_height", st["worktop_height"])     # altura de empuje (carros: asa o mano)
    mobile = bool(st.get("mobile"))
    force = {d: H_N * (LATERAL_FACTOR_MOBILE if mobile and d in ("+Y", "-Y") else 1.0) for d in DIRS}
    # distancia de cada apoyo a la arista de vuelco de cada dirección
    dist = {"+X": pts[:, 0].max() - pts[:, 0], "-X": pts[:, 0] - pts[:, 0].min(),
            "+Y": pts[:, 1].max() - pts[:, 1], "-Y": pts[:, 1] - pts[:, 1].min()}
    res = {}
    for d in DIRS:
        Mstb = pf["gamma_G_stb"] * Wtot * levers[d]
        Mdst = pf["gamma_Q_dst"] * force[d] * hgt
        # giro rígido alrededor de la arista: tracción de cada taco proporcional a su distancia a ella
        # (T_i = M·d_i / Σd²). Con cuatro esquinas es M/base repartido entre los dos tacos del lado traccionado; con
        # más apoyos (baterías, cantilever) el taco más alejado lleva más que la media
        M_net = max(0.0, Mdst - Mstb)
        dd = [float(x) for x in dist[d]]            # suma en orden (igual que el motor del navegador)
        s2, s1 = 0.0, 0.0
        for x in dd:
            s2 += x * x
            s1 += x
        T_per = M_net * max(dd) / s2 if s2 > 0 else (float("inf") if M_net > 0 else 0.0)
        T = M_net * s1 / s2 if s2 > 0 else (float("inf") if M_net > 0 else 0.0)
        res[d] = {"ratio": Mdst / Mstb if Mstb > 0 else float("inf"), "Mstb": Mstb, "Mdst": Mdst, "T": T,
                  "T_per": T_per, "n": int((dist[d] > 1e-6).sum())}
    dirn = max(DIRS, key=lambda d: res[d]["ratio"])
    dT = max(DIRS, key=lambda d: res[d]["T_per"])
    r = res[dirn]
    return {"dirn": dirn, "ratio": r["ratio"], "Mstb": r["Mstb"], "Mdst": r["Mdst"], "lever": levers[dirn],
            "force": force[dirn], "H_N": H_N, "hgt": hgt, "mobile": mobile, "Wtot": Wtot, "cog": cog,
            "levers": levers, "T": res[dT]["T"], "dirn_T": dT, "n_anchor": max(1, res[dT]["n"]),
            "T_per": res[dT]["T_per"],
            "admissible_N": max(0, math.floor(r["Mstb"] / (pf["gamma_Q_dst"] * hgt) / (force[dirn] / H_N)))}


@dataclass
class Check:
    id: str
    category: str
    element: str
    description: str
    standard: str
    value: float | None
    limit: float | None
    unit: str
    utilization: float | None
    status: str
    combination: str = ""
    details: dict[str, Any] = field(default_factory=dict)



def surface_sheet(part) -> tuple[float, float]:
    """(masa en kg, espesor en mm) de la chapa plegada o placa de una superficie de carga."""
    from ..core.model import SheetPart
    if isinstance(part, SheetPart):
        return part.flat.net_area() * part.spec.t * 1e-9 * part.density, part.spec.t
    return part.analytic_volume * 1e-9 * part.density, part.t

def _status(u: float | None) -> str:
    if u is None:
        return PENDING
    return OK if u <= 1.0 + 1e-9 else FAIL


def buckling_chi(lam_bar: float, alpha: float) -> float:
    if lam_bar <= 0.2:
        return 1.0
    phi = 0.5 * (1 + alpha * (lam_bar - 0.2) + lam_bar ** 2)
    return min(1.0, 1.0 / (phi + math.sqrt(phi ** 2 - lam_bar ** 2)))


def section_class(prof, fy: float) -> int:
    eps = math.sqrt(235 / fy)
    c_t = max((prof.H - 3 * prof.t), (prof.B - 3 * prof.t)) / prof.t
    if c_t <= 33 * eps:
        return 1
    if c_t <= 38 * eps:
        return 2
    if c_t <= 42 * eps:
        return 3
    return 4


# ============================================================================ modelo de barras
class StructuralModel:
    def __init__(self, model, max_element: float = MAX_ELEMENT):
        self.model = model
        self.frame = Frame3D()
        self.members: dict[str, dict[str, Any]] = {}
        self.chains: dict[str, list[tuple[float, int]]] = {}   # miembro -> [(s, nodo)]
        self._build(max_element)

    def _build(self, max_element):
        m = self.model
        structural = [i for i in m.instances if i.structural]
        ends = {i.id: [np.array(i.axis[0], float), np.array(i.axis[1], float)] for i in structural}
        extra: dict[str, list[np.ndarray]] = {i.id: [] for i in structural}
        fem_joints = [j.weld["fem"] for j in m.joints if (j.weld or {}).get("fem")
                      and j.weld["fem"]["member"] in ends and j.weld["fem"]["onto"] in ends]
        for _ in range(3):      # varias pasadas: las barras de destino pueden haberse ajustado antes
            for fem in fem_joints:
                p0, p1 = ends[fem["onto"]]
                q = np.array(m.instance(fem["member"]).axis[fem["end"]], float)
                d = p1 - p0
                s = np.clip(np.dot(q - p0, d) / np.dot(d, d), 0, 1)
                ends[fem["member"]][fem["end"]] = p0 + s * d
        for fem in fem_joints:
            extra[fem["onto"]].append(ends[fem["member"]][fem["end"]])
        for sup in m.structure.get("supports", []):
            if sup["leg"] in extra:
                extra[sup["leg"]].append(np.array(sup["point"], float))
        for i in structural:
            mat = catalog.material(i.part.material)
            prof = i.part.profile
            sp = prof.props
            p0, p1 = ends[i.id]
            d = p1 - p0
            Lm = float(np.linalg.norm(d))
            x = d / Lm
            pts = sorted({round(float(np.dot(q - p0, x)), 3) for q in [p0, p1] + extra[i.id]} | {0.0, round(Lm, 3)})
            # (los puntos están redondeados a 0,001 mm: tolerancia acorde para no perder el extremo final)
            pts = [s for s in pts if -1e-3 <= s <= Lm + 1e-3]
            # subdivisión
            fine: list[float] = []
            for a, b in zip(pts[:-1], pts[1:]):
                n = max(1, math.ceil((b - a) / max_element))
                fine += [a + (b - a) * k / n for k in range(n)]
            fine.append(pts[-1])
            chain = []
            for s in fine:
                chain.append((s, self.frame.node(p0 + s * x)))
            dedup = []
            for s, n in chain:
                if not dedup or dedup[-1][1] != n:
                    dedup.append((s, n))
            self.chains[i.id] = dedup
            elems = []
            for (s0, n0), (s1, n1) in zip(dedup[:-1], dedup[1:]):
                elems.append(self.frame.element(n0, n1, mat.E, mat.G, sp.A, sp.Iy, sp.Iz, sp.It, i.up, i.id))
            self.members[i.id] = {"instance": i, "profile": prof, "props": sp, "material": mat, "length": Lm,
                                  "p0": p0, "p1": p1, "x": x, "elements": elems, "role": i.role}
        # Coacciones horizontales isostáticas: sin empujes hiperestáticos entre pies (conservador para
        # flexión de bastidores y para el desplome; el rozamiento real con el suelo no se cuenta). Tres coacciones
        # en planta: un pie fijo en X-Y y otro, alejado en X, deslizante en X (impide el giro). Antes había una
        # cuarta (otro pie deslizante en Y): hiperestática, y con bastidores asimétricos (reposapiés delantero)
        # creaba empujes falsos entre pies y descompensaba las reacciones verticales.
        sups = m.structure.get("supports", [])
        if sups:
            P = np.array([s["point"] for s in sups], float)
            k0 = int(np.argmin(P[:, 0] + P[:, 1]))
            d = P - P[k0]
            kx = int(np.argmax(np.abs(d[:, 0]) - np.abs(d[:, 1])))
            for k, sup in enumerate(sups):
                n = self.frame.node(sup["point"])
                fx = k == k0
                fy = k in (k0, kx)
                self.frame.support(n, (fx, fy, True, False, False, False))
                sup["node"] = n
                sup["restraint"] = ("X" if fx else "") + ("Y" if fy else "") + "Z"

    # -- utilidades de carga
    def self_weight(self, case: str = "G") -> float:
        total = 0.0
        for mid, mm in self.members.items():
            w = mm["props"].A * 1e-9 * mm["material"].density * G_ACC   # N/mm
            for k in mm["elements"]:
                e = self.frame.elements[k]
                P = w * e.L
                total += P
                self.frame.add_nodal_load(case, e.i, (0, 0, -P / 2))
                self.frame.add_nodal_load(case, e.j, (0, 0, -P / 2))
        return total

    def line_load(self, case: str, member: str, p, s0g: float, s1g: float, axis_coord: int, breaks=()) -> float:
        """Aplica una densidad vertical p(s) [N/mm] en coordenada global ``axis_coord`` ∈ [s0g, s1g]."""
        mm = self.members[member]
        chain = self.chains[member]
        coords = np.array([self.frame.nodes[n][axis_coord] for _, n in chain])
        order = np.argsort(coords)
        coords = coords[order]
        nodes = [chain[k][1] for k in order]
        F = line_load_to_nodes(coords, p, s0g, s1g, breaks=breaks)
        for f, n in zip(F, nodes):
            self.frame.add_nodal_load(case, n, (0, 0, -f))
        return float(F.sum())

    def surface_load(self, case: str, level: dict, q: float) -> float:
        """Reparto de una presión q [N/mm2] a las barras del emparrillado (regla de 45°)."""
        gx, (yf, yb) = level["grid_x"], level["grid_y"]
        b = yb - yf
        x_members = [level["end"][0]] + level["int"] + [level["end"][1]]
        total = 0.0
        for k in range(len(gx) - 1):
            x0, x1 = gx[k], gx[k + 1]
            a = x1 - x0
            for mem in level["long"]:
                total += self.line_load(case, mem, lambda s, x0=x0, x1=x1: q * min(s - x0, x1 - s, b / 2), x0, x1, 0,
                                        breaks=(x0 + b / 2, x1 - b / 2, (x0 + x1) / 2))
            for xm, mem in ((x0, x_members[k]), (x1, x_members[k + 1])):
                total += self.line_load(case, mem, lambda s, a=a: q * min(s - yf, yb - s, a / 2), yf, yb, 1,
                                        breaks=(yf + a / 2, yb - a / 2, (yf + yb) / 2))
        return total

    def cantilever_deflection(self, mid: str, u: np.ndarray) -> float:
        """Flecha propia de un voladizo: desplazamiento de la punta respecto a la tangente en su arranque (extremo 0),
        perpendicular a la barra. El giro de la columna que lo sostiene se comprueba aparte (desplome bajo carga)."""
        chain = self.chains[mid]
        x = self.members[mid]["x"]
        n0, n1 = chain[0][1], chain[-1][1]
        r = np.asarray(self.frame.nodes[n1], float) - np.asarray(self.frame.nodes[n0], float)
        rigid = np.asarray(u[6 * n0:6 * n0 + 3]) + np.cross(np.asarray(u[6 * n0 + 3:6 * n0 + 6]), r)
        rel = np.asarray(u[6 * n1:6 * n1 + 3]) - rigid
        return float(np.linalg.norm(rel - np.dot(rel, x) * x))

    def member_deflection(self, mid: str, u: np.ndarray) -> float:
        """Flecha relativa máxima respecto a la cuerda entre extremos (perpendicular a la barra)."""
        chain = self.chains[mid]
        x = self.members[mid]["x"]
        disp = np.array([u[6 * n:6 * n + 3] for _, n in chain])
        s = np.array([c[0] for c in chain])
        perp = disp - np.outer(disp @ x, x)
        Ls = s[-1] - s[0]
        chord = perp[0] + np.outer((s - s[0]) / Ls, perp[-1] - perp[0])
        return float(np.linalg.norm(perp - chord, axis=1).max())


# ============================================================================ análisis
def analyze(model, include_stability: bool = True, include_welds: bool = True) -> dict[str, Any]:
    crit = catalog.criteria()
    pf = crit["partial_factors"]
    ps = model.params.values
    st = model.structure
    checks: list[Check] = []
    hyp: list[str] = []
    pending: list[str] = []
    limitations = [
        "Análisis elástico lineal de primer orden (sin efectos P-Δ ni imperfecciones globales explícitas).",
        "Uniones soldadas consideradas rígidas; excentricidades de unión entre ejes no modeladas.",
        "Chapas de encimera y balda verificadas como placas simplemente apoyadas en el emparrillado "
        "(Navier); no se considera su contribución a la rigidez del bastidor.",
        "Comprobaciones de barras por el método simplificado lineal de EN 1993-1-1 §6.2.1(7) y §6.3.3 "
        "con coeficientes de interacción unitarios (conservador).",
        "No se analizan concentraciones de tensiones locales, fatiga ni comportamiento dinámico.",
    ]
    sm = StructuralModel(model)
    fr = sm.frame
    levels = st.get("levels", {})

    # ---------------------------------------------------------------- casos de carga
    cases: list[dict[str, Any]] = []
    Gm = sm.self_weight("G")
    # masas no estructurales colgadas de barras (p. ej. un panel atornillado a los montantes)
    for am in st.get("attached_masses", []):
        if am["member"] in sm.chains:
            q = np.array(am["point"], float)
            n = min(sm.chains[am["member"]], key=lambda c: float(np.linalg.norm(np.array(fr.nodes[c[1]]) - q)))[1]
            P = am["mass_kg"] * G_ACC
            fr.add_nodal_load("G", n, (0, 0, -P))
            Gm += P
    g_sheets = 0.0
    phi = dynamic_factor(ps)
    if phi > 1.0:
        hyp.append(f"Cargas de uso y carga puntual amplificadas por el coeficiente dinámico φ = {phi:g} (rodadura sobre "
                   "juntas, rampas o umbrales).")
    surfaces_info = []
    undefined_loads: list[str] = []
    for surf in st.get("surfaces", []):
        lvl = levels[surf["level"]]
        inst = model.instance(surf["sheet_instance"])
        part = inst.part
        sheet_mass, _t = surface_sheet(part)
        area = surf["area_mm2"]
        gx, gy = lvl["grid_x"], lvl["grid_y"]
        grid_area = (gx[-1] - gx[0]) * (gy[1] - gy[0])
        scale = area / grid_area
        q_g = sheet_mass * G_ACC / area
        g_sheets += sm.surface_load("G", lvl, q_g * scale)
        # carga propia de la superficie (p. ej. kN/m² por su área, en un peldaño) o la del parámetro de carga
        load_kg = surf["load_kg"] if "load_kg" in surf else ps.get(surf["load_param"])
        if load_kg:
            load_kg = load_kg * phi                 # coeficiente dinámico (carros)
        info = {"surface": surf, "level": lvl, "q_g": q_g, "sheet_mass": sheet_mass, "load_kg": load_kg,
                "scale": scale, "part": part}
        if load_kg:
            q = load_kg * G_ACC / area
            applied = sm.surface_load("Q", lvl, q * scale)
            info["q"] = q
            cases.append({"id": f"Q_{surf['id']}", "label": f"Sobrecarga de uso uniforme en {surf['label'].lower()}",
                          "value": f"{load_kg:g} kg ({q * 1e6:.0f} N/m²)", "total_N": round(applied, 1)})
        elif load_kg is not None:        # 0 kg indicado: sin sobrecarga de uso (se verifica con el peso propio)
            info["q"] = 0.0
            hyp.append(f"{surf['label']}: sin sobrecarga de uso (0 kg indicados); se verifica con su peso propio.")
        else:
            undefined_loads.append(surf["load_param"])
            pending.append(f"Carga de uso sobre {surf['label'].lower()} no definida ({surf['load_param']}): "
                           f"verificación de {surf['label'].lower()} pendiente.")
        surfaces_info.append(info)
    # cargas lineales uniformes sobre barras (p. ej. los brazos de una cantilever), en su tramo útil; a dos caras, además,
    # el caso asimétrico con sólo los brazos delanteros cargados (el que más flecta la columna)
    lls = st.get("line_loads", [])
    asym = any(ll.get("side") == "T" for ll in lls)
    ll_tot = {"Q": 0.0, "QA": 0.0}
    ll_kg = {}
    for ll in lls:
        kg = ps.get(ll["load_param"])
        if kg is None:
            if ll["load_param"] not in undefined_loads:
                undefined_loads.append(ll["load_param"])
                pending.append(f"{st.get('line_load_label', 'Carga lineal')} no definida ({ll['load_param']}): "
                               "verificación pendiente.")
            continue
        ll_kg[ll["load_param"]] = kg
        if not kg:
            continue
        y0, y1 = ll["span"]
        w = kg * phi * G_ACC / (y1 - y0)
        ll_tot["Q"] += sm.line_load("Q", ll["member"], lambda s, w=w: w, y0, y1, ll.get("axis", 1))
        if asym and ll.get("side") != "T":
            ll_tot["QA"] += sm.line_load("QA", ll["member"], lambda s, w=w: w, y0, y1, ll.get("axis", 1))
    for prm, kg in ll_kg.items():
        lab = st.get("line_load_label", "Carga lineal uniforme")
        if kg:
            n_ll = sum(1 for ll in lls if ll["load_param"] == prm)
            cases.append({"id": "Q_" + prm, "label": f"{lab} (todas las barras cargadas)",
                          "value": f"{kg * phi:g} kg × {n_ll}", "total_N": round(ll_tot["Q"], 1)})
            if ll_tot["QA"]:
                cases.append({"id": "QA", "label": f"{lab}: sólo {st.get('line_load_side_label', 'una cara')} "
                                                   "(carga asimétrica)",
                              "value": f"{kg * phi:g} kg × {n_ll // 2}", "total_N": round(ll_tot["QA"], 1)})
                hyp.append(f"Carga asimétrica: sólo {st.get('line_load_side_label', 'una cara')} cargados (descarga de "
                           "la cara opuesta), además de todos los brazos cargados.")
        else:
            hyp.append(f"{lab}: sin sobrecarga de uso (0 kg indicados); se verifica con el peso propio.")
    cases.insert(0, {"id": "G", "label": "Peso propio (perfiles y chapas, calculado desde la geometría)",
                     "value": f"{(Gm + g_sheets) / G_ACC:.1f} kg", "total_N": round(Gm + g_sheets, 1)})
    has_Q = "Q" in fr.loads
    # verificación completa si hay sobrecarga o si todas las cargas de uso están indicadas (0 kg incluidos)
    q_defined = has_Q or not undefined_loads
    P_kg = (ps.get("CARGA_PUNTUAL") or 0.0) * phi or None
    top_lvl = levels.get("SUP")
    if P_kg and top_lvl:
        front = top_lvl["long"][0]
        chain = sm.chains[front]
        smid = (chain[0][0] + chain[-1][0]) / 2
        n_mid = min(chain, key=lambda c: abs(c[0] - smid))[1]
        fr.add_nodal_load("P", n_mid, (0, 0, -P_kg * G_ACC))
        cases.append({"id": "P", "label": "Carga puntual en centro de vano del larguero delantero",
                      "value": f"{P_kg:g} kg", "total_N": round(P_kg * G_ACC, 1)})
    # cargas puntuales de accesorios (p. ej. apoyo del pie en el reposapiés) en el centro de su barra
    for pl in st.get("point_loads", []):
        if pl["member"] not in sm.chains:
            continue
        chain = sm.chains[pl["member"]]
        smid = (chain[0][0] + chain[-1][0]) / 2
        n_mid = min(chain, key=lambda c: abs(c[0] - smid))[1]
        fr.add_nodal_load(pl["id"], n_mid, (0, 0, -pl["load_N"]))
        cases.append({"id": pl["id"], "label": pl["label"], "value": f"{pl['load_N']:g} N", "total_N": pl["load_N"]})
        hyp.append(pl["hypothesis"])
    H_N = ps.get("CARGA_HORIZONTAL") or 0.0
    top_nodes = []
    push = st.get("push_points")      # puntos de empuje propios (p. ej. el asa de un carro): [{"member", "z"}]
    if H_N and (push or top_lvl):
        if push:
            for pp in push:
                chain = sm.chains[pp["member"]]
                top_nodes.append(min(chain, key=lambda c: abs(fr.nodes[c[1]][2] - pp["z"]))[1])
        else:
            for lid in st["leg_ids"]:
                chain = sm.chains[lid]
                z_top = top_lvl["z"] - model.instance(top_lvl["long"][0]).part.profile.H / 2
                top_nodes.append(min(chain, key=lambda c: abs(fr.nodes[c[1]][2] - z_top))[1])
        for n in top_nodes:
            fr.add_nodal_load("HX", n, (H_N / len(top_nodes), 0, 0))
            fr.add_nodal_load("HY", n, (0, H_N / len(top_nodes), 0))
        cases.append({"id": "HX/HY", "label": st.get("push_label", "Empuje horizontal en el plano de la encimera "
                                                                    "(direcciones X e Y)"),
                      "value": f"{H_N:g} N", "total_N": H_N})
        if model.params.sources.get("CARGA_HORIZONTAL") == "defecto":
            hyp.append(f"Empuje horizontal de {H_N:g} N: {st.get('push_note', crit['horizontal_service_load_note'])}")

    gG, gQ, psi = pf["gamma_G"], pf["gamma_Q"], pf["psi0_Q"]
    combos_uls = {"ELU-1": {"G": gG}}
    if has_Q:
        combos_uls["ELU-1"] = {"G": gG, "Q": gQ}
    if "HX" in fr.loads:
        combos_uls["ELU-2"] = {"G": gG, "Q": gQ * psi, "HX": gQ}
        combos_uls["ELU-3"] = {"G": gG, "Q": gQ * psi, "HY": gQ}
        if has_Q:
            combos_uls["ELU-4"] = {"G": gG, "Q": gQ, "HX": gQ * psi}
    if "P" in fr.loads:
        combos_uls["ELU-5"] = {"G": gG, "P": gQ}
    if "QA" in fr.loads:
        combos_uls["ELU-QA"] = {"G": gG, "QA": gQ}
    # sin sobrecarga (0 kg indicados) la combinación de servicio es la del peso propio: reacciones en los apoyos y
    # flechas también se comprueban
    combos_sls = {"ELS-1": {"G": 1.0, "Q": 1.0}} if has_Q else {"ELS-1": {"G": 1.0}}
    if "P" in fr.loads:
        combos_sls["ELS-2"] = {"G": 1.0, "P": 1.0}
    if "QA" in fr.loads:
        combos_sls["ELS-QA"] = {"G": 1.0, "QA": 1.0}
    for pl in st.get("point_loads", []):
        if pl["id"] in fr.loads:
            combos_uls[f"ELU-{pl['id']}"] = {"G": gG, pl["id"]: gQ}
            combos_sls[f"ELS-{pl['id']}"] = {"G": 1.0, pl["id"]: 1.0}
    if "HX" in fr.loads:
        combos_sls["ELS-3"] = {"HX": 1.0}
        combos_sls["ELS-4"] = {"HY": 1.0}

    res = fr.solve()
    U = {c: res.combine(f) for c, f in {**combos_uls, **combos_sls}.items()}

    # ---------------------------------------------------------------- barras
    alpha = crit["imperfection_factors"][crit["buckling_curve_cold_formed_hollow"]]
    beta_leg = crit["effective_length_factors"]["leg_sway"]
    member_results = []
    class4: set[str] = set()
    r_member, _r_panel, r_sway = deflection_ratios(ps)
    cantilevers = set(st.get("cantilevers", []))
    if cantilevers:
        hyp.append(f"Brazos en voladizo: flecha propia en punta (respecto a la tangente en el arranque) limitada a "
                   f"2L/{r_member:g} = L/{r_member / 2:g}; el desplome de las columnas bajo la carga vertical se limita "
                   f"a H/{r_sway:g}.")
    for mid, mm in sm.members.items():
        mat, prof, sp = mm["material"], mm["profile"], mm["props"]
        fy, gM0, gM1 = mat.fy, mat.gamma_M0, mat.gamma_M1
        cls = section_class(prof, fy)
        rho = class4_rho(prof, fy) if cls == 4 else 1.0           # clase 4: sección eficaz (EN 1993-1-5)
        A_eff = sp.A * rho
        Wy = sp.Wpl_y if cls <= 2 else sp.Wel_y * rho
        Wz = sp.Wpl_z if cls <= 2 else sp.Wel_z * rho
        NRd, MyRd, MzRd = A_eff * fy / gM0, Wy * fy / gM0, Wz * fy / gM0
        VzRd, VyRd = sp.Av_z * fy / math.sqrt(3) / gM0, sp.Av_y * fy / math.sqrt(3) / gM0
        is_leg = mm["role"] in ("pata", "montante")
        beta = beta_leg if is_leg else crit["effective_length_factors"]["braced_member"]
        Lcr = beta * mm["length"]
        lam1 = math.pi * math.sqrt(mat.E / fy)
        lam = Lcr / min(sp.iy, sp.iz) / lam1 * math.sqrt(rho)       # EN 1993-1-1 (6.51) con A_eff
        chi = buckling_chi(lam, alpha)
        best = {"u": -1}
        for cname, u in U.items():
            if cname not in combos_uls:
                continue
            Nc = 0.0
            Mmax_y = Mmax_z = Vmax = Tmax = 0.0
            ucs = 0.0
            for k in mm["elements"]:
                f = res.element_forces(k, u)
                for end in (0, 6):
                    N = f[6] if end == 6 else -f[0]
                    My, Mz = abs(f[end + 4]), abs(f[end + 5])
                    Vy, Vz, T = abs(f[end + 1]), abs(f[end + 2]), abs(f[end + 3])
                    ucs = max(ucs, abs(N) / NRd + My / MyRd + Mz / MzRd)
                    Nc = min(Nc, N)
                    Mmax_y, Mmax_z = max(Mmax_y, My), max(Mmax_z, Mz)
                    Vmax = max(Vmax, Vy / VyRd, Vz / VzRd)
                    Tmax = max(Tmax, T)
            # compresión real (umbral de 1 mN: el ruido numérico de barras sin axil no activa el pandeo)
            ub = (abs(Nc) / (chi * A_eff * fy / gM1) + Mmax_y / (Wy * fy / gM1) + Mmax_z / (Wz * fy / gM1)) \
                if Nc < -N_ZERO else 0
            u_all = max(ucs, ub, Vmax)
            if u_all > best["u"]:
                best = {"u": u_all, "ucs": ucs, "ub": ub, "uv": Vmax, "combo": cname, "Nc": Nc, "My": Mmax_y,
                        "Mz": Mmax_z}
        details = {"clase": cls, "N_Rd_kN": NRd / 1e3, "My_Rd_kNm": MyRd / 1e6, "Mz_Rd_kNm": MzRd / 1e6,
                   "L_mm": mm["length"], "Lcr_mm": Lcr, "lambda_rel": lam, "chi": chi,
                   "N_Ed_kN": best["Nc"] / 1e3, "My_Ed_kNm": best["My"] / 1e6, "Mz_Ed_kNm": best["Mz"] / 1e6,
                   "u_seccion": best["ucs"], "u_pandeo": best["ub"], "u_cortante": best["uv"]}
        if cls == 4:
            details["rho_clase4"] = rho
            class4.add(f"{prof.code} en {mat.code} (ρ = {rho:.3f})")
        status = _status(best["u"])
        if not q_defined and status == OK:
            status = PENDING
        checks.append(Check(f"B.{mid}", "resistencia" if not is_leg else "pandeo", mid,
                            f"{mm['instance'].name} ({prof.code}, {mat.code}): resistencia de sección"
                            + (" y pandeo por flexión" if best["Nc"] < -N_ZERO else ""),
                            "EN 1993-1-1 §6.2, §6.3.1, §6.3.3", round(best["u"], 4), 1.0, "-", round(best["u"], 4),
                            status, best["combo"], details))
        member_results.append((mid, best["u"]))
        # flecha
        if not is_leg and combos_sls:
            cant = mid in cantilevers
            dmax, cmax = 0.0, ""
            for cname in combos_sls:
                if cname in ("ELS-1", "ELS-2", "ELS-QA") or cname.startswith("ELS-F"):
                    dv = sm.cantilever_deflection(mid, U[cname]) if cant else sm.member_deflection(mid, U[cname])
                    if dv > dmax:
                        dmax, cmax = dv, cname
            if cmax:
                if cant:     # voladizo: luz física del brazo (desde la cara de la columna)
                    lim = 2 * mm["instance"].part.length / r_member
                    desc, std = f"{mm['instance'].name}: flecha en punta del voladizo", \
                        f"EN 1990 A1.4 (límite 2L/{r_member:g} adoptado en voladizo)"
                else:
                    lim = mm["length"] / r_member
                    desc, std = f"{mm['instance'].name}: flecha relativa", f"EN 1990 A1.4 (límite L/{r_member:g} adoptado)"
                checks.append(Check(f"D.{mid}", "deformacion", mid, desc, std,
                                    round(dmax, 3), round(lim, 3), "mm", round(dmax / lim, 4), _status(dmax / lim),
                                    cmax))
    if class4:
        hyp.append("Secciones clase 4 (" + ", ".join(sorted(class4)) + "): sección eficaz según EN 1993-1-5 §4.4 con la "
                   "reducción de la pared más esbelta en compresión uniforme aplicada a toda la sección (del lado de la "
                   "seguridad).")

    # ---------------------------------------------------------------- desplome
    if "ELS-3" in U and top_nodes:
        h = st.get("sway_height", st["worktop_height"])     # altura del punto de empuje (encimera o asa)
        lim = h / r_sway
        for cname, comp in (("ELS-3", 0), ("ELS-4", 1)):
            dx = max(abs(U[cname][6 * n + comp]) for n in top_nodes)
            checks.append(Check(f"S.{cname}", "deformacion", "Estructura", f"Desplome horizontal en dirección "
                                f"{'X' if comp == 0 else 'Y'} bajo empuje de servicio",
                                f"Criterio adoptado H/{r_sway:g}",
                                round(dx, 3), round(lim, 3), "mm", round(dx / lim, 4), _status(dx / lim), cname))

    # voladizos: las columnas se desploman bajo la propia carga vertical (brazos a una cara, o cargados a un lado)
    if cantilevers and st.get("push_points"):
        h = st.get("sway_height", st["worktop_height"])
        lim = h / r_sway
        cnodes = []
        for pp in st["push_points"]:
            chain = sm.chains[pp["member"]]
            cnodes.append(min(chain, key=lambda c: abs(fr.nodes[c[1]][2] - pp["z"]))[1])
        worst = (0.0, "", 1)
        for cname in ("ELS-1", "ELS-QA"):
            if cname in U:
                for comp in (0, 1):
                    dv = max(abs(U[cname][6 * n + comp]) for n in cnodes)
                    if dv > worst[0]:
                        worst = (dv, cname, comp)
        if worst[1]:
            dv, cname, comp = worst
            checks.append(Check("S.ELS-G", "deformacion", "Estructura", f"Desplome de las columnas en dirección "
                                f"{'X' if comp == 0 else 'Y'} bajo la carga vertical de servicio (brazos en voladizo)",
                                f"Criterio adoptado H/{r_sway:g}", round(dv, 3), round(lim, 3), "mm", round(dv / lim, 4),
                                _status(dv / lim), cname))

    # ---------------------------------------------------------------- reacciones y apoyos
    reactions = []
    sups = st.get("supports", [])
    for cname in list(combos_uls) + list(combos_sls):
        F = res.combine_loads({**combos_uls, **combos_sls}[cname])
        R = res.reactions(U[cname], F)
        for sup in sups:
            r = R[sup["node"]]
            reactions.append({"combination": cname, "support": sup["instance"], "Rx_N": round(r[0], 1),
                              "Ry_N": round(r[1], 1), "Rz_N": round(r[2], 1)})
    if sups:
        comp = catalog.component(sups[0]["component"])
        cap = comp["rated_load_kg"] * G_ACC
        sup_word = "Ruedas" if comp["category"].startswith("ruedas") else "Pies niveladores"
        # peor reacción de servicio con gravedad (uniforme, carga puntual, reposapiés...): antes sólo ELS-1, y una
        # carga puntual (p. ej. 153 kg sobre una tarima) que va a dos pies quedaba sin comprobar
        rmax, sls_v = float("-inf"), None
        for cname in (c for c, f in combos_sls.items() if "G" in f):
            for r in reactions:
                if r["combination"] == cname and r["Rz_N"] > rmax:
                    rmax, sls_v = r["Rz_N"], cname
        if sls_v:
            st_ = _status(rmax / cap)
            checks.append(Check("A.PIES", "apoyos", sup_word, f"Reacción máxima de servicio frente a la "
                                f"capacidad nominal de {comp['name']}", "Dato de catálogo genérico — confirmar con la "
                                "ficha técnica del proveedor", round(rmax, 1), round(cap, 1), "N",
                                round(rmax / cap, 4), st_ if st_ != OK else OK, sls_v,
                                {"fuente_capacidad": comp.get("rated_load_source")}))
            if comp.get("rated_load_source") == "catalogo_generico":
                hyp.append(f"Capacidad de {comp['name']}: {comp['rated_load_kg']} kg (catálogo genérico de referencia,"
                           " debe confirmarse con la ficha técnica del proveedor).")
        else:
            checks.append(Check("A.PIES", "apoyos", sup_word, f"Capacidad de los {sup_word.lower()}",
                                "—", None, cap, "N", None, PENDING, "", {}))

    # ---------------------------------------------------------------- placas (encimera / balda)
    dl = deflection_ratios(ps)[1]
    for info in surfaces_info:
        surf, lvl, part = info["surface"], info["level"], info["part"]
        mat = catalog.material(part.material)
        _m, t = surface_sheet(part)
        # placa perforada: rigidez y resistencia reducidas por la eficiencia de ligamento (p − d)/p
        eta = surf.get("ligament_efficiency", 1.0)
        perf = f" (placa perforada, η = {eta:.2f})" if eta < 1 else ""
        gx, (yf, yb) = lvl["grid_x"], lvl["grid_y"]
        a = max(gx[k + 1] - gx[k] for k in range(len(gx) - 1))
        b = yb - yf
        sid = surf["id"]
        if not mat.structural:
            checks.append(Check(f"PL.{sid}", "placa", surf["label"], f"{surf['label']}: material sin propiedades "
                                "resistentes en catálogo", "—", None, None, "-", None, PENDING))
            continue
        if not mat.fy_guaranteed:
            hyp.append(f"{mat.name}: la norma {mat.standard} no garantiza límite elástico mínimo; se adopta "
                       f"fy = {mat.fy} MPa como hipótesis (confirmar con certificado 3.1).")
        if info["load_kg"] is not None:
            q_uls = gG * info["q_g"] + gQ * info["q"]
            q_sls = info["q_g"] + info["q"]
            r_u = navier(a, b, t, mat.E, mat.nu, q=q_uls)
            r_s = navier(a, b, t, mat.E, mat.nu, q=q_sls)
            r_u = {**r_u, "sigma": r_u["sigma"] / eta}
            r_s = {**r_s, "w": r_s["w"] / eta}
            fyd = mat.fy / mat.gamma_M0
            checks.append(Check(f"PL.{sid}.S", "placa", surf["label"], f"{surf['label']}: tensión de flexión en "
                                f"panel {a:.0f}×{b:.0f} mm, t = {t:g} mm (carga uniforme){perf}",
                                "Teoría de placas (Navier) + EN 1993-1-1 §6.2.1", round(r_u["sigma"], 2),
                                round(fyd, 1), "MPa", round(r_u["sigma"] / fyd, 4), _status(r_u["sigma"] / fyd),
                                "ELU-1", {"a": a, "b": b, "q_MPa": q_uls}))
            lim = min(a, b) / dl
            d = {"a": a, "b": b, "q_MPa": q_sls}
            if r_s["w"] > t / 2:
                d["nota"] = ("Flecha superior a t/2: el efecto membrana (no considerado) reduce la flecha real; "
                             "el resultado lineal es conservador.")
            checks.append(Check(f"PL.{sid}.D", "placa", surf["label"], f"{surf['label']}: flecha del panel "
                                f"{a:.0f}×{b:.0f} mm", f"Criterio adoptado L/{dl:g}", round(r_s["w"], 3), round(lim, 3),
                                "mm", round(r_s["w"] / lim, 4), _status(r_s["w"] / lim), "ELS-1", d))
        else:
            checks.append(Check(f"PL.{sid}", "placa", surf["label"], f"{surf['label']}: verificación de chapa",
                                "—", None, None, "-", None, PENDING, "", {"motivo": f"{surf['load_param']} sin definir"}))
        if (sid == "encimera" or surf.get("point_load")) and P_kg:
            size = patch_size(ps, surf)        # huella de la carga concentrada
            r_p = navier(a, b, t, mat.E, mat.nu, q=gG * info["q_g"], patch=(gQ * P_kg * G_ACC, size, size, a / 2, b / 2),
                         terms=121)
            r_p = {**r_p, "sigma": r_p["sigma"] / eta}
            fyd = mat.fy / mat.gamma_M0
            checks.append(Check(f"PL.{sid}.P", "placa", surf["label"], f"{surf['label']}: carga puntual de {P_kg:g} kg "
                                f"sobre huella {size:g}×{size:g} mm en el centro del panel", "Navier + EN 1993-1-1 §6.2.1",
                                round(r_p["sigma"], 2), round(fyd, 1), "MPa", round(r_p["sigma"] / fyd, 4),
                                _status(r_p["sigma"] / fyd), "ELU-5"))

    # ---------------------------------------------------------------- soldaduras
    if include_welds:
        for j in model.joints:
            fem = (j.weld or {}).get("fem")
            if not fem or fem["member"] not in sm.members:
                continue
            mm = sm.members[fem["member"]]
            mat = mm["material"]
            prof = mm["profile"]
            a_w = j.weld["a"]
            chain = sm.chains[fem["member"]]
            node = chain[0][1] if fem["end"] == 0 else chain[-1][1]
            elem = next(k for k in mm["elements"] if node in (fr.elements[k].i, fr.elements[k].j))
            Aw = a_w * 2 * (prof.B + prof.H)
            Wy = a_w * (prof.B * prof.H + prof.H ** 2 / 3)
            Wz = a_w * (prof.H * prof.B + prof.B ** 2 / 3)
            Aenc = prof.B * prof.H
            fvw = mat.fu / (math.sqrt(3) * mat.beta_w * mat.gamma_M2)
            best = (0.0, "")
            for cname in combos_uls:
                f = res.element_forces(elem, U[cname])
                o = 0 if fr.elements[elem].i == node else 6
                N, Vy, Vz, T, My, Mz = (abs(v) for v in f[o:o + 6])
                sigma = N / Aw + My / Wy + Mz / Wz
                tau = math.hypot(Vy, Vz) / Aw + T / (2 * Aenc * a_w)
                s = math.hypot(sigma, tau)
                if s > best[0]:
                    best = (s, cname)
            if not q_defined:
                stt = PENDING
            else:
                stt = _status(best[0] / fvw)
            checks.append(Check(f"W.{j.id}", "soldadura", j.id, f"{j.description}: cordón en ángulo a{a_w:g} "
                                f"perimetral ({prof.code})", "EN 1993-1-8 §4.5.3.3 (método simplificado)",
                                round(best[0], 2), round(fvw, 1), "MPa", round(best[0] / fvw, 4), stt, best[1],
                                {"a_mm": a_w, "longitud_mm": j.weld["length"]}))
        if any((j.weld or {}).get("a", 3) < 3 for j in model.joints):
            hyp.append("Cordones con garganta a < 3 mm en perfiles de pared delgada: fuera del ámbito de EN 1993-1-8 "
                       "§4.5.2(2); requieren procedimiento de soldeo cualificado (EN ISO 15614-1) y verificación según "
                       "EN 1993-1-3.")

    # ---------------------------------------------------------------- estabilidad
    stability = None
    ov = overturning(model, ps, st) if include_stability else None
    if ov:
        what = st.get("product_word", "mesa")
        what = f"del {what} vacío" if what in MASCULINE_WORDS else f"de la {what} vacía"
        dirn, H_N = ov["dirn"], ov["H_N"]
        # empuje de servicio que el conjunto vacío resiste sin anclaje (EQU): γQ·H·h = γG,stb·W·brazo
        det = {"peso_N": ov["Wtot"], "cdg_mm": [round(v, 1) for v in ov["cog"]], "brazo_mm": ov["lever"],
               "empuje_admisible_N": ov["admissible_N"]}
        load_txt = (f"maniobra de {H_N:g} N en la dirección de la marcha y {H_N * LATERAL_FACTOR_MOBILE:g} N lateral"
                    if ov["mobile"] else f"empuje horizontal de {H_N:g} N")
        if ov["mobile"]:
            hyp.append(f"Maniobra del carro: {H_N:g} N en la dirección de la marcha y {LATERAL_FACTOR_MOBILE * 100:.0f} % "
                       "en la lateral (giros y empujes ocasionales), a la altura de empuje, con el carro vacío.")
        if ps.get("ANCLAJE") == "al_suelo":
            T, n_anchor, T_per = ov["T"], ov["n_anchor"], ov["T_per"]
            det.update({"traccion_total_N": round(T, 1), "anclajes_traccionados": n_anchor,
                        "traccion_por_anclaje_N": round(T_per, 1), "direccion_traccion": ov["dirn_T"]})
            code = ps.get("TACO_ANCLAJE")
            anchor = catalog.component(code) if code not in (None, AUTO) and code in catalog.components() else None
            if anchor:
                cap = float(anchor["tension_kN"]) * 1000.0
                u = T_per / cap
                hyp.append(f"Anclaje al suelo: un {_lc(anchor['name'])} por apoyo, a través de la base del pie; "
                           f"tracción admisible {anchor['tension_kN']:g} kN en hormigón C20/25 no fisurado (catálogo "
                           "genérico de referencia, a confirmar con la ETA del taco y el soporte real).")
                checks.append(Check("E.ANCLAJE", "estabilidad", "Anclajes", f"Tracción por taco de anclaje bajo {load_txt} "
                                    f"(dirección {ov['dirn_T']}, {n_anchor} tacos traccionados)",
                                    "EN 1990 EQU; capacidad del taco según catálogo (ETA)", round(T_per, 1),
                                    round(cap, 1), "N", round(u, 4), _status(u), "EQU", det))
            else:
                pending.append(f"Anclaje al suelo: tracción de cálculo {T_per:.0f} N por anclaje "
                               f"({n_anchor} anclajes en el lado traccionado). La capacidad del anclaje y del soporte "
                               "no está verificada (depende del taco y del suelo).")
                checks.append(Check("E.ANCLAJE", "estabilidad", "Anclajes", f"Vuelco impedido por anclaje al suelo: "
                                    f"tracción de cálculo por anclaje bajo {load_txt} (dirección {ov['dirn_T']})",
                                    "EN 1990 EQU + EN 1992-4 (anclajes, no evaluado)", round(T_per, 1), None,
                                    "N", None, PENDING, "EQU", det))
        else:
            checks.append(Check("E.VUELCO", "estabilidad", "Conjunto", f"Vuelco {what} bajo {load_txt} "
                                f"{st.get('push_where', 'en la parte superior')} (dirección {dirn})",
                                "EN 1990 EQU (γG,stb = 0,9; γQ = 1,5)", round(ov["Mdst"] / 1e3, 2),
                                round(ov["Mstb"] / 1e3, 2), "N·m", round(ov["ratio"], 4), _status(ov["ratio"]), "EQU",
                                det))
        stability = {"weight_N": ov["Wtot"], "cog": ov["cog"].tolist(), "levers": ov["levers"]}
    elif include_stability and sups:
        Wtot, cog = own_weight(model)
        stability = {"weight_N": Wtot, "cog": cog.tolist(), "levers": support_levers(sups, cog)}

    # ---------------------------------------------------------------- resultado global
    statuses = [c.status for c in checks]
    if FAIL in statuses:
        status = FAIL
    elif PENDING in statuses or pending:
        status = PENDING
    else:
        status = OK
    governing = max((c for c in checks if c.utilization is not None), key=lambda c: c.utilization, default=None)
    mats = {}
    for mm in sm.members.values():
        mats[mm["material"].code] = mm["material"]
    for info in surfaces_info:
        mats[info["part"].material] = catalog.material(info["part"].material)
    return {
        "status": status,
        "status_label": {OK: "Verificación estructural automatizada completa: CUMPLE (EN 1990 · EN 1993)",
                         FAIL: "NO CUMPLE: requiere modificación del diseño",
                         PENDING: "Verificación incompleta: datos pendientes"}[status],
        "validation_note": ("Cálculo automatizado según EN 1990 y EN 1993 con las hipótesis indicadas. El expediente lo "
                            "firma el responsable técnico del fabricante."),
        "governing": asdict(governing) if governing else None,
        "checks": [asdict(c) for c in checks],
        "load_cases": cases,
        "combinations": {"ELU": combos_uls, "ELS": combos_sls},
        "partial_factors": pf,
        "materials": [{"code": m.code, "name": m.name, "standard": m.standard, "E": m.E, "fy": m.fy, "fu": m.fu,
                       "density": m.density, "fy_guaranteed": m.fy_guaranteed, "design_code": m.design_code}
                      for m in mats.values()],
        "sections": sorted({(mm["profile"].code, round(mm["props"].A, 1), round(mm["props"].Iy / 1e4, 3),
                             round(mm["props"].Iz / 1e4, 3), round(mm["props"].Wpl_y / 1e3, 3),
                             round(mm["props"].Wpl_z / 1e3, 3)) for mm in sm.members.values()}),
        "hypotheses": list(dict.fromkeys(hyp)) + [          # sin repetir (p. ej. la de DC01, una por bandeja)
            "Apoyos: pies niveladores articulados con coacción horizontal isostática (un pie fijo en X-Y, otro "
            "deslizante en X que impide el giro en planta, y los demás sólo verticales); no se cuenta con el "
            "rozamiento.",
            f"Cargas de superficie repartidas al emparrillado mediante la regla de 45° (áreas tributarias).",
            f"Longitud de pandeo de patas: {beta_leg}·L (pórtico traslacional, conservador).",
            f"Curva de pandeo '{crit['buckling_curve_cold_formed_hollow']}' para perfiles huecos conformados en frío "
            "(EN 1993-1-1 tabla 6.2).",
        ],
        "boundary_conditions": [{"support": s["instance"], "node": s["node"], "point": list(map(float, s["point"])),
                                 "type": "articulado", "restraint": s.get("restraint")} for s in sups],
        "reactions": reactions,
        "pending": pending,
        "limitations": limitations,
        "stability": stability,
        "fem": {"nodes": len(fr.nodes), "elements": len(fr.elements), "dof": fr.ndof()},
        "member_utilization": dict(member_results),
        "standards": [f"{s['code']}:{s['version']}" for s in catalog.standards(model.family)
                      if "calculo" in s["scope"] or "soldadura" in s["scope"]],
    }
