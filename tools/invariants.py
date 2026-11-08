"""Invariantes de lógica del motor de referencia (sin B-rep) sobre plantillas y casos realistas.

Uso: python tools/invariants.py N SEMILLA [familia1,familia2]

Cada caso se resuelve (dimensionado incluido), se calcula y se planifica su fabricación, y se comprueba que:

* parámetros: no queda ningún 'auto'; un valor dado por el usuario no se cambia salvo por una regla de diseño
  sobre un valor por defecto;
* cálculo: equilibrio global (suma de reacciones = cargas aplicadas) en cada combinación; la sobrecarga de cada
  superficie suma exactamente su carga; el estado de cada comprobación es coherente con su aprovechamiento;
  reacciones verticales simétricas en diseños simétricos;
* masas: BOM = suma de piezas = masa del modelo;
* corte de barras: cada pieza tantas veces como su cantidad, ninguna barra excedida, balance de longitudes;
* anidado: todas las piezas colocadas, dentro del formato útil y sin solapes;
* soldadura: longitud total = suma de las uniones;
* presupuesto: precio ≥ coste ≥ directo > 0 y precio unitario no creciente con el lote.
"""
from __future__ import annotations

import collections
import json
import math
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "webcheck"))
from cases import random_cases  # noqa: E402

from monxu.core.params import AUTO, ParamError  # noqa: E402
from monxu.docs.bom import build_bom  # noqa: E402
from monxu.engineering.analysis import analyze  # noqa: E402
from monxu.families import REGISTRY  # noqa: E402
from monxu.manufacturing.costing import quotation  # noqa: E402
from monxu.manufacturing.plan import manufacturing_plan  # noqa: E402

G = 9.81


def check_case(fid: str, values: dict) -> list[str]:
    fam = REGISTRY[fid]
    ps = fam.new_params()
    ps.update(values, "usuario")
    m = fam.build(ps)
    out: list[str] = []
    v, src = m.params.values, m.params.sources
    # ---- parámetros
    for k, val in v.items():
        if val == AUTO and k not in fam.auto_in_construct and k != "DISTANCIA_BALDAS":   # se resuelven al construir
            out.append(f"PARAM {k} sigue en 'auto'")
    for k, val in values.items():
        if k in v and val != AUTO and val is not None and v[k] != val and src.get(k) != "regla_diseno":
            out.append(f"PARAM {k}: el usuario pidió {val!r} y se resolvió {v[k]!r} ({src.get(k)})")
    # ---- cálculo
    eng = analyze(m)
    tot = {c["id"]: c["total_N"] for c in eng["load_cases"]}
    Hn = v.get("CARGA_HORIZONTAL") or 0.0
    q_total = sum(t for k, t in tot.items() if k.startswith("Q_"))
    for s in m.structure.get("surfaces", []):
        kg = v.get(s["load_param"])
        sid = f"Q_{s['id']}"
        if kg and sid in tot and abs(tot[sid] - kg * G) > max(0.2, 1e-4 * kg * G):
            out.append(f"CARGA {sid}: aplicada {tot[sid]} N frente a {kg * G:.1f} N")
    combos = {**eng["combinations"]["ELU"], **eng["combinations"]["ELS"]}
    reac = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in eng["reactions"]:
        acc = reac[r["combination"]]
        acc[0] += r["Rx_N"]
        acc[1] += r["Ry_N"]
        acc[2] += r["Rz_N"]
    for cname, f in combos.items():
        down = sum(fac * (q_total if case == "Q" else tot.get(case, 0.0)) for case, fac in f.items()
                   if case not in ("HX", "HY"))
        hx, hy = f.get("HX", 0.0) * Hn, f.get("HY", 0.0) * Hn
        rx, ry, rz = reac[cname]
        tol = max(1.0, 2e-4 * (abs(down) + abs(hx) + abs(hy)))       # las reacciones se redondean a 0,1 N
        if abs(rz - down) > tol or abs(rx + hx) > tol or abs(ry + hy) > tol:
            out.append(f"EQUILIBRIO {cname}: reacciones ({rx:.1f}, {ry:.1f}, {rz:.1f}) N frente a cargas "
                       f"({hx:.1f}, {hy:.1f}, {down:.1f}) N")
    for c in eng["checks"]:
        u, st = c["utilization"], c["status"]
        if u is None:
            continue
        if not math.isfinite(u):
            out.append(f"CHECK {c['id']}: aprovechamiento no finito")
        elif st == "NO_CUMPLE" and u <= 1.0 + 1e-9:
            out.append(f"CHECK {c['id']}: NO_CUMPLE con aprovechamiento {u}")
        elif st == "CUMPLE" and u > 1.0 + 1e-9:
            out.append(f"CHECK {c['id']}: CUMPLE con aprovechamiento {u}")
    # simetría izquierda-derecha de las reacciones verticales (sin accesorios asimétricos)
    asym = (v.get("ASA_EMPUJE") == "un_extremo" or fid in ("puesto_trabajo",)
            or (fid in ("carro_taller", "carro_estanteria") and v.get("ASA_EMPUJE") != "dos_extremos"))
    sups = m.structure.get("supports", [])
    if sups and not asym and "ELS-1" in combos:
        xs = [s["point"][0] for s in sups]
        x_mid = (min(xs) + max(xs)) / 2
        rz = {r["support"]: r["Rz_N"] for r in eng["reactions"] if r["combination"] == "ELS-1"}
        for s in sups:
            mx = 2 * x_mid - s["point"][0]
            twin = min(sups, key=lambda t: abs(t["point"][0] - mx) + abs(t["point"][1] - s["point"][1]))
            a, b = rz[s["instance"]], rz[twin["instance"]]
            if abs(a - b) > max(2.0, 0.01 * max(abs(a), abs(b))):
                out.append(f"SIMETRIA ELS-1: {s['instance']} {a:.1f} N frente a {twin['instance']} {b:.1f} N")
                break
    # ---- fabricación y BOM
    plan = manufacturing_plan(m)
    bom = build_bom(m, plan)
    counts = collections.Counter(i.part.key for i in m.instances)
    parts_mass = sum(p.mass * counts[k] for k, p in m.parts.items())
    if abs(bom["totals"]["total_mass"] - parts_mass) > max(0.01, 1e-5 * parts_mass):
        out.append(f"MASA BOM {bom['totals']['total_mass']} frente a piezas {parts_mass:.4f}")
    if abs(m.total_mass() - parts_mass) > max(0.01, 1e-5 * parts_mass):
        out.append(f"MASA modelo {m.total_mass():.4f} frente a piezas {parts_mass:.4f}")
    by_ref = {p.ref: (p, counts[k]) for k, p in m.parts.items()}
    for c in plan["cutting"]:
        cut = collections.Counter(x["ref"] for b in c["bars"] for x in b["cuts"])
        want = {p.ref: n for p, n in by_ref.values() if getattr(p, "profile", None) is not None
                and p.kind == "perfil" and p.profile.code == c["profile"] and p.material == c["material"]}
        if dict(cut) != want:
            out.append(f"CORTE {c['profile']}: piezas cortadas {dict(cut)} frente a {want}")
        for b in c["bars"]:
            s = sum(x["length"] for x in b["cuts"]) + b["kerf_loss"] + b["remnant"]
            if abs(s - c["bar_length"]) > 0.5 or b["remnant"] < -1e-6:
                out.append(f"CORTE {c['profile']} barra {b['bar']}: balance {s} frente a {c['bar_length']}")
    for n in plan["nesting"]:
        if not n.get("feasible"):
            continue
        placed = collections.Counter(pl["ref"] for sh in n["sheets"] for pl in sh["placements"])
        want = {p.ref: k for p, k in by_ref.values() if p.kind in ("chapa", "pletina") and p.material == n["material"]
                and abs((p.spec.t if p.kind == "chapa" else p.t) - n["thickness"]) < 1e-9}
        if dict(placed) != want:
            out.append(f"ANIDADO {n['material']} {n['thickness']}: colocadas {dict(placed)} frente a {want}")
        L, W, mg = n["length"], n["width"], n["margin"]
        for sh in n["sheets"]:
            rects = [(p["x"], p["y"], p["x"] + p["w"], p["y"] + p["h"]) for p in sh["placements"]]
            for r in rects:
                if r[0] < mg - 1e-6 or r[1] < mg - 1e-6 or r[2] > L - mg + 1e-6 or r[3] > W - mg + 1e-6:
                    out.append(f"ANIDADO {n['material']} {n['thickness']}: pieza fuera del formato útil {r}")
            for i, a in enumerate(rects):
                for b in rects[i + 1:]:
                    if a[0] < b[2] - 1e-6 and b[0] < a[2] - 1e-6 and a[1] < b[3] - 1e-6 and b[1] < a[3] - 1e-6:
                        out.append(f"ANIDADO {n['material']} {n['thickness']}: piezas solapadas {a} {b}")
    wl = sum(j.weld["length"] for j in m.joints if j.kind == "soldadura")
    if abs(plan["welding"]["total_length_mm"] - wl) > 0.5:
        out.append(f"SOLDADURA total {plan['welding']['total_length_mm']} frente a {wl:.1f}")
    q = quotation(m, plan)
    if not (q["direct"] > 0 and q["cost"] >= q["direct"] - 0.01 and q["price"] >= q["cost"] - 0.01):
        out.append(f"PRESUPUESTO directo {q['direct']} coste {q['cost']} precio {q['price']}")
    prices = [b["price"] for b in q["by_lot"]]
    if any(b > a + 0.01 for a, b in zip(prices, prices[1:])):
        out.append(f"PRESUPUESTO precio unitario creciente con el lote: {prices}")
    return out


def main():
    n, seed = int(sys.argv[1]), int(sys.argv[2])
    only = set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[3] else None
    cases = [{"id": t["id"], "family": fid, "values": t["values"]} for fid, f in REGISTRY.items() for t in f.templates()]
    cases += random_cases(n, seed)
    if only:
        cases = [c for c in cases if c["family"] in only]
    bad, kinds, t0 = 0, collections.Counter(), time.time()
    for c in cases:
        try:
            found = check_case(c["family"], c["values"])
        except ParamError as e:
            found = [] if c["id"].startswith("R") else [f"EXCEPCION ParamError en plantilla: {e}"]
        except Exception as e:
            found = [f"EXCEPCION {type(e).__name__}: {e} | {traceback.format_exc().splitlines()[-3].strip()}"]
        if found:
            bad += 1
            for f in found:
                kinds[f.split()[0]] += 1
            print(f"{c['id']:<20} {c['family']:<18} " + json.dumps(c["values"], ensure_ascii=False)[:160], flush=True)
            for f in found[:8]:
                print("    -", f, flush=True)
    print(f"CASOS {len(cases)} CON INCIDENCIAS {bad} POR TIPO {dict(kinds)} en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
