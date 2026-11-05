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
from .fem import Frame3D, line_load_to_nodes
from .plate import navier

OK, FAIL, PENDING, WARN = "CUMPLE", "NO_CUMPLE", "PENDIENTE", "ADVERTENCIA"
G_ACC = 9.81
MAX_ELEMENT = 100.0


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
            pts = [s for s in pts if -1e-6 <= s <= Lm + 1e-6]
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
                                  "p0": p0, "p1": p1, "x": x, "elements": elems, "role": i.part.role}
        # Coacciones horizontales isostáticas: sin empujes hiperestáticos entre pies (conservador para
        # flexión de bastidores y para el desplome; el rozamiento real con el suelo no se cuenta).
        sups = m.structure.get("supports", [])
        if sups:
            P = np.array([s["point"] for s in sups], float)
            k0 = int(np.argmin(P[:, 0] + P[:, 1]))
            d = P - P[k0]
            kx = int(np.argmax(np.abs(d[:, 0]) - np.abs(d[:, 1])))
            ky = int(np.argmax(np.abs(d[:, 1]) - np.abs(d[:, 0])))
            for k, sup in enumerate(sups):
                n = self.frame.node(sup["point"])
                fx = k in (k0, ky)
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

    def line_load(self, case: str, member: str, p, s0g: float, s1g: float, axis_coord: int) -> float:
        """Aplica una densidad vertical p(s) [N/mm] en coordenada global ``axis_coord`` ∈ [s0g, s1g]."""
        mm = self.members[member]
        chain = self.chains[member]
        coords = np.array([self.frame.nodes[n][axis_coord] for _, n in chain])
        order = np.argsort(coords)
        coords = coords[order]
        nodes = [chain[k][1] for k in order]
        F = line_load_to_nodes(coords, p, s0g, s1g)
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
                total += self.line_load(case, mem, lambda s, x0=x0, x1=x1: q * min(s - x0, x1 - s, b / 2), x0, x1, 0)
            for xm, mem in ((x0, x_members[k]), (x1, x_members[k + 1])):
                total += self.line_load(case, mem, lambda s, a=a: q * min(s - yf, yb - s, a / 2), yf, yb, 1)
        return total

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
    g_sheets = 0.0
    surfaces_info = []
    for surf in st.get("surfaces", []):
        lvl = levels[surf["level"]]
        inst = model.instance(surf["sheet_instance"])
        part = inst.part
        sheet_mass = part.flat.net_area() * part.spec.t * 1e-9 * part.density
        area = surf["area_mm2"]
        gx, gy = lvl["grid_x"], lvl["grid_y"]
        grid_area = (gx[-1] - gx[0]) * (gy[1] - gy[0])
        scale = area / grid_area
        q_g = sheet_mass * G_ACC / area
        g_sheets += sm.surface_load("G", lvl, q_g * scale)
        load_kg = ps.get(surf["load_param"])
        info = {"surface": surf, "level": lvl, "q_g": q_g, "sheet_mass": sheet_mass, "load_kg": load_kg,
                "scale": scale, "part": part}
        if load_kg:
            q = load_kg * G_ACC / area
            applied = sm.surface_load("Q", lvl, q * scale)
            info["q"] = q
            cases.append({"id": f"Q_{surf['id']}", "label": f"Sobrecarga de uso uniforme en {surf['label'].lower()}",
                          "value": f"{load_kg:g} kg ({q * 1e6:.0f} N/m²)", "total_N": round(applied, 1)})
        else:
            pending.append(f"Carga de uso sobre {surf['label'].lower()} no definida ({surf['load_param']}): "
                           f"verificación de {surf['label'].lower()} pendiente.")
        surfaces_info.append(info)
    cases.insert(0, {"id": "G", "label": "Peso propio (perfiles y chapas, calculado desde la geometría)",
                     "value": f"{(Gm + g_sheets) / G_ACC:.1f} kg", "total_N": round(Gm + g_sheets, 1)})
    has_Q = "Q" in fr.loads
    P_kg = ps.get("CARGA_PUNTUAL")
    top_lvl = levels.get("SUP")
    if P_kg and top_lvl:
        front = top_lvl["long"][0]
        chain = sm.chains[front]
        smid = (chain[0][0] + chain[-1][0]) / 2
        n_mid = min(chain, key=lambda c: abs(c[0] - smid))[1]
        fr.add_nodal_load("P", n_mid, (0, 0, -P_kg * G_ACC))
        cases.append({"id": "P", "label": "Carga puntual en centro de vano del larguero delantero",
                      "value": f"{P_kg:g} kg", "total_N": round(P_kg * G_ACC, 1)})
    H_N = ps.get("CARGA_HORIZONTAL") or 0.0
    top_nodes = []
    if H_N and top_lvl:
        for lid in st["leg_ids"]:
            chain = sm.chains[lid]
            z_top = top_lvl["z"] - model.instance(top_lvl["long"][0]).part.profile.H / 2
            top_nodes.append(min(chain, key=lambda c: abs(fr.nodes[c[1]][2] - z_top))[1])
        for n in top_nodes:
            fr.add_nodal_load("HX", n, (H_N / len(top_nodes), 0, 0))
            fr.add_nodal_load("HY", n, (0, H_N / len(top_nodes), 0))
        cases.append({"id": "HX/HY", "label": "Empuje horizontal en el plano de la encimera (direcciones X e Y)",
                      "value": f"{H_N:g} N", "total_N": H_N})
        if model.params.sources.get("CARGA_HORIZONTAL") == "defecto":
            hyp.append(f"Empuje horizontal de {H_N:g} N: {crit['horizontal_service_load_note']}")

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
    combos_sls = {"ELS-1": {"G": 1.0, "Q": 1.0}} if has_Q else {}
    if "P" in fr.loads:
        combos_sls["ELS-2"] = {"G": 1.0, "P": 1.0}
    if "HX" in fr.loads:
        combos_sls["ELS-3"] = {"HX": 1.0}
        combos_sls["ELS-4"] = {"HY": 1.0}

    res = fr.solve()
    U = {c: res.combine(f) for c, f in {**combos_uls, **combos_sls}.items()}

    # ---------------------------------------------------------------- barras
    alpha = crit["imperfection_factors"][crit["buckling_curve_cold_formed_hollow"]]
    beta_leg = crit["effective_length_factors"]["leg_sway"]
    member_results = []
    for mid, mm in sm.members.items():
        mat, prof, sp = mm["material"], mm["profile"], mm["props"]
        fy, gM0, gM1 = mat.fy, mat.gamma_M0, mat.gamma_M1
        cls = section_class(prof, fy)
        Wy = sp.Wpl_y if cls <= 2 else sp.Wel_y
        Wz = sp.Wpl_z if cls <= 2 else sp.Wel_z
        NRd, MyRd, MzRd = sp.A * fy / gM0, Wy * fy / gM0, Wz * fy / gM0
        VzRd, VyRd = sp.Av_z * fy / math.sqrt(3) / gM0, sp.Av_y * fy / math.sqrt(3) / gM0
        is_leg = mm["role"] in ("pata", "montante")
        beta = beta_leg if is_leg else crit["effective_length_factors"]["braced_member"]
        Lcr = beta * mm["length"]
        lam1 = math.pi * math.sqrt(mat.E / fy)
        lam = Lcr / min(sp.iy, sp.iz) / lam1
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
            ub = (abs(Nc) / (chi * sp.A * fy / gM1) + Mmax_y / (Wy * fy / gM1) + Mmax_z / (Wz * fy / gM1)) if Nc < 0 else 0
            u_all = max(ucs, ub, Vmax)
            if u_all > best["u"]:
                best = {"u": u_all, "ucs": ucs, "ub": ub, "uv": Vmax, "combo": cname, "Nc": Nc, "My": Mmax_y,
                        "Mz": Mmax_z}
        details = {"clase": cls, "N_Rd_kN": NRd / 1e3, "My_Rd_kNm": MyRd / 1e6, "Mz_Rd_kNm": MzRd / 1e6,
                   "L_mm": mm["length"], "Lcr_mm": Lcr, "lambda_rel": lam, "chi": chi,
                   "N_Ed_kN": best["Nc"] / 1e3, "My_Ed_kNm": best["My"] / 1e6, "Mz_Ed_kNm": best["Mz"] / 1e6,
                   "u_seccion": best["ucs"], "u_pandeo": best["ub"], "u_cortante": best["uv"]}
        status = _status(best["u"])
        if cls == 4:
            status = PENDING
            pending.append(f"{mm['instance'].name}: sección clase 4, requiere sección eficaz (no implementado).")
        if not has_Q and status == OK:
            status = PENDING
        checks.append(Check(f"B.{mid}", "resistencia" if not is_leg else "pandeo", mid,
                            f"{mm['instance'].name} ({prof.code}, {mat.code}): resistencia de sección"
                            + (" y pandeo por flexión" if best["Nc"] < 0 else ""),
                            "EN 1993-1-1 §6.2, §6.3.1, §6.3.3", round(best["u"], 4), 1.0, "-", round(best["u"], 4),
                            status, best["combo"], details))
        member_results.append((mid, best["u"]))
        # flecha
        if not is_leg and combos_sls:
            dmax, cmax = 0.0, ""
            for cname in combos_sls:
                if cname in ("ELS-1", "ELS-2"):
                    dv = sm.member_deflection(mid, U[cname])
                    if dv > dmax:
                        dmax, cmax = dv, cname
            if cmax:
                lim = mm["length"] / crit["deflection_limits"]["member_span_ratio"]
                checks.append(Check(f"D.{mid}", "deformacion", mid, f"{mm['instance'].name}: flecha relativa",
                                    f"EN 1990 A1.4 (límite L/{crit['deflection_limits']['member_span_ratio']} adoptado)",
                                    round(dmax, 3), round(lim, 3), "mm", round(dmax / lim, 4), _status(dmax / lim),
                                    cmax))

    # ---------------------------------------------------------------- desplome
    if "ELS-3" in U and top_nodes:
        h = st["worktop_height"]
        lim = h / crit["deflection_limits"]["sway_height_ratio"]
        for cname, comp in (("ELS-3", 0), ("ELS-4", 1)):
            dx = max(abs(U[cname][6 * n + comp]) for n in top_nodes)
            checks.append(Check(f"S.{cname}", "deformacion", "Estructura", f"Desplome horizontal en dirección "
                                f"{'X' if comp == 0 else 'Y'} bajo empuje de servicio",
                                f"Criterio adoptado H/{crit['deflection_limits']['sway_height_ratio']}",
                                round(dx, 3), round(lim, 3), "mm", round(dx / lim, 4), _status(dx / lim), cname))

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
        sls_v = "ELS-1" if "ELS-1" in combos_sls else None
        if sls_v:
            rmax = max(r["Rz_N"] for r in reactions if r["combination"] == sls_v)
            st_ = _status(rmax / cap)
            checks.append(Check("A.PIES", "apoyos", "Pies niveladores", f"Reacción máxima de servicio frente a la "
                                f"capacidad nominal de {comp['name']}", "Dato de catálogo genérico — confirmar con la "
                                "ficha técnica del proveedor", round(rmax, 1), round(cap, 1), "N",
                                round(rmax / cap, 4), st_ if st_ != OK else OK, sls_v,
                                {"fuente_capacidad": comp.get("rated_load_source")}))
            if comp.get("rated_load_source") == "catalogo_generico":
                hyp.append(f"Capacidad de {comp['name']}: {comp['rated_load_kg']} kg (catálogo genérico de referencia,"
                           " debe confirmarse con la ficha técnica del proveedor).")
        else:
            checks.append(Check("A.PIES", "apoyos", "Pies niveladores", "Capacidad de los pies niveladores",
                                "—", None, cap, "N", None, PENDING, "", {}))

    # ---------------------------------------------------------------- placas (encimera / balda)
    dl = crit["deflection_limits"]["panel_span_ratio"]
    for info in surfaces_info:
        surf, lvl, part = info["surface"], info["level"], info["part"]
        mat = catalog.material(part.material)
        t = part.spec.t
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
        if info["load_kg"]:
            q_uls = gG * info["q_g"] + gQ * info["q"]
            q_sls = info["q_g"] + info["q"]
            r_u = navier(a, b, t, mat.E, mat.nu, q=q_uls)
            r_s = navier(a, b, t, mat.E, mat.nu, q=q_sls)
            fyd = mat.fy / mat.gamma_M0
            checks.append(Check(f"PL.{sid}.S", "placa", surf["label"], f"{surf['label']}: tensión de flexión en "
                                f"panel {a:.0f}×{b:.0f} mm, t = {t:g} mm (carga uniforme)",
                                "Teoría de placas (Navier) + EN 1993-1-1 §6.2.1", round(r_u["sigma"], 2),
                                round(fyd, 1), "MPa", round(r_u["sigma"] / fyd, 4), _status(r_u["sigma"] / fyd),
                                "ELU-1", {"a": a, "b": b, "q_MPa": q_uls}))
            lim = min(a, b) / dl
            d = {"a": a, "b": b, "q_MPa": q_sls}
            if r_s["w"] > t / 2:
                d["nota"] = ("Flecha superior a t/2: el efecto membrana (no considerado) reduce la flecha real; "
                             "el resultado lineal es conservador.")
            checks.append(Check(f"PL.{sid}.D", "placa", surf["label"], f"{surf['label']}: flecha del panel "
                                f"{a:.0f}×{b:.0f} mm", f"Criterio adoptado L/{dl}", round(r_s["w"], 3), round(lim, 3),
                                "mm", round(r_s["w"] / lim, 4), _status(r_s["w"] / lim), "ELS-1", d))
        else:
            checks.append(Check(f"PL.{sid}", "placa", surf["label"], f"{surf['label']}: verificación de chapa",
                                "—", None, None, "-", None, PENDING, "", {"motivo": f"{surf['load_param']} sin definir"}))
        if sid == "encimera" and P_kg:
            size = crit["point_load_patch_mm"]
            r_p = navier(a, b, t, mat.E, mat.nu, q=gG * info["q_g"], patch=(gQ * P_kg * G_ACC, size, size, a / 2, b / 2),
                         terms=121)
            fyd = mat.fy / mat.gamma_M0
            checks.append(Check(f"PL.{sid}.P", "placa", surf["label"], f"{surf['label']}: carga puntual de {P_kg:g} kg "
                                f"sobre huella {size}×{size} mm en el centro del panel", "Navier + EN 1993-1-1 §6.2.1",
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
            if not has_Q:
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
    if include_stability and sups:
        Wtot = model.total_mass() * G_ACC
        cog = model.center_of_mass()
        pts = np.array([s["point"] for s in sups])
        xmin, xmax = pts[:, 0].min(), pts[:, 0].max()
        ymin, ymax = pts[:, 1].min(), pts[:, 1].max()
        levers = {"+X": xmax - cog[0], "-X": cog[0] - xmin, "+Y": ymax - cog[1], "-Y": cog[1] - ymin}
        hgt = st["worktop_height"]
        dirn, lev = min(levers.items(), key=lambda kv: kv[1])
        if H_N:
            Mstb = pf["gamma_G_stb"] * Wtot * lev
            Mdst = pf["gamma_Q_dst"] * H_N * hgt
            ratio = Mdst / Mstb if Mstb > 0 else float("inf")
            what = st.get("product_word", "mesa")
            det = {"peso_N": Wtot, "cdg_mm": [round(v, 1) for v in cog], "brazo_mm": lev}
            if ps.get("ANCLAJE") == "al_suelo":
                # base de vuelco: distancia entre líneas de apoyo en la dirección más desfavorable
                base = (ymax - ymin) if dirn in ("+Y", "-Y") else (xmax - xmin)
                T = max(0.0, (Mdst - Mstb) / base) if base > 0 else float("inf")
                n_anchor = max(1, len(sups) // 2)
                det.update({"traccion_total_N": round(T, 1), "anclajes_traccionados": n_anchor,
                            "traccion_por_anclaje_N": round(T / n_anchor, 1)})
                pending.append(f"Anclaje al suelo: tracción de cálculo {T / n_anchor:.0f} N por anclaje "
                               f"({n_anchor} anclajes en el lado traccionado). La capacidad del anclaje y del soporte "
                               "no está verificada (depende del taco y del suelo).")
                checks.append(Check("E.ANCLAJE", "estabilidad", "Anclajes", f"Vuelco impedido por anclaje al suelo: "
                                    f"tracción de cálculo por anclaje bajo empuje de {H_N:g} N (dirección {dirn})",
                                    "EN 1990 EQU + EN 1992-4 (anclajes, no evaluado)", round(T / n_anchor, 1), None,
                                    "N", None, PENDING, "EQU", det))
            else:
                checks.append(Check("E.VUELCO", "estabilidad", "Conjunto", f"Vuelco de la {what} vacía bajo empuje "
                                    f"horizontal de {H_N:g} N en la parte superior (dirección {dirn})",
                                    "EN 1990 EQU (γG,stb = 0,9; γQ = 1,5)", round(Mdst / 1e3, 2), round(Mstb / 1e3, 2),
                                    "N·m", round(ratio, 4), _status(ratio), "EQU", det))
        stability = {"weight_N": Wtot, "cog": cog.tolist(), "levers": levers}

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
        "status_label": {OK: "Verificación preliminar automatizada: CUMPLE",
                         FAIL: "NO CUMPLE: requiere modificación del diseño",
                         PENDING: "Verificación incompleta: datos pendientes"}[status],
        "validation_note": ("Resultado de cálculo preliminar automatizado. La validación definitiva del producto "
                            "estructural corresponde a un técnico competente."),
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
        "hypotheses": hyp + [
            "Apoyos: pies niveladores articulados con coacción horizontal isostática (un pie fijo en X-Y, uno "
            "deslizante en X, uno deslizante en Y y el cuarto sólo vertical); no se cuenta con el rozamiento.",
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
