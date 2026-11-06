"""Validación cruzada: motor del navegador (TypeScript, ejecutado en node) frente al motor de referencia (Python).

Uso: python tools/webcheck/compare.py BUNDLE.mjs N_ALEATORIOS SEMILLA
Compara parámetros resueltos por el dimensionado, derivados, piezas, masas, comprobaciones estructurales,
reacciones, plan de corte, anidado, soldadura, pintura, DFM y totales del BOM.
"""
import json
import math
import random
import subprocess
import sys

from monxu.families import REGISTRY

bundle, n_rand, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
cases = []
for fid, f in REGISTRY.items():
    for t in f.templates():
        cases.append({"id": t["id"], "family": fid, "values": t["values"]})
cases.append({"id": "ACEPT-2000", "family": "mesa_industrial", "values": {"LONGITUD": 2000, "ANCHURA": 800, "ALTURA": 900, "CARGA_TOTAL": 400}})
cases.append({"id": "ACEPT-2400", "family": "mesa_industrial", "values": {"LONGITUD": 2400, "ANCHURA": 800, "ALTURA": 900, "CARGA_TOTAL": 400}})
cases.append({"id": "SIN-CARGA", "family": "mesa_industrial", "values": {}})
cases.append({"id": "EST-DEF", "family": "estanteria", "values": {}})
rng = random.Random(seed)
MATS = [("S235JRH", "S235JR", "RAL7035_POLVO"), ("1.4301", "1.4301", "INOX_SATINADO"),
        ("S235JRH", "DC01", "RAL5010_POLVO"), ("EN AW-6082 T6", "EN AW-5754 H22", "ANODIZADO_NATURAL")]
for k in range(n_rand):
    m = rng.choice(MATS)
    u = rng.random()
    if u >= 0.9:
        fid = "carro_taller"
        H = rng.choice(range(800, 1001, 50))
        v = {"LONGITUD": rng.choice(range(700, 1601, 100)), "ANCHURA": rng.choice(range(450, 801, 50)), "ALTURA": H,
             "ALTURA_ASA": H + rng.choice([100, 150, 200]), "CARGA_TOTAL": rng.choice([None, 50, 100, 200]),
             "NUMERO_BALDAS": rng.choice([0, 1]), "CARGA_BALDA": rng.choice([None, 50, 100]),
             "CARGA_HORIZONTAL": rng.choice([50, 100, 150])}
    elif u >= 0.7:
        fid = "puesto_trabajo"
        H = rng.choice(range(800, 1001, 50))
        top = rng.choice(range(1500, 2201, 100))
        v = {"LONGITUD": rng.choice(range(1000, 2401, 100)), "ANCHURA": rng.choice(range(600, 901, 50)), "ALTURA": H,
             "ALTURA_TOTAL": top, "ESTANTE_SUPERIOR": rng.choice([0, 1]), "ALTURA_ESTANTE": rng.choice(range(H + 400, top - 149, 50)),
             "PROFUNDIDAD_ESTANTE": rng.choice(range(200, 401, 50)), "PANEL_HERRAMIENTAS": rng.choice([0, 1]),
             "CARGA_TOTAL": rng.choice([None, 100, 200, 400]), "CARGA_ESTANTE": rng.choice([None, 20, 50, 80]),
             "NUMERO_BALDAS": rng.choice([0, 1]), "CARGA_BALDA": rng.choice([None, 50, 100]),
             "CARGA_HORIZONTAL": rng.choice([100, 200, 300]), "ANCLAJE": rng.choice(["ninguno", "al_suelo"])}
    elif u < 0.4:
        fid = "mesa_industrial"
        v = {"LONGITUD": rng.choice(range(800, 3001, 100)), "ANCHURA": rng.choice(range(500, 1201, 50)),
             "ALTURA": rng.choice(range(700, 1101, 50)), "CARGA_TOTAL": rng.choice([None, 100, 200, 300, 400, 600, 800]),
             "NUMERO_BALDAS": rng.choice([0, 1]), "CARGA_BALDA": rng.choice([None, 0, 50, 100, 200]),
             "CARGA_PUNTUAL": rng.choice([None, None, 50, 100]),
             "USO": rng.choice(["montaje", "trabajo_pesado", "inspeccion"]), "CARGA_HORIZONTAL": rng.choice([100, 200, 300]),
             "ANCLAJE": rng.choice(["ninguno", "al_suelo"])}
    else:
        fid = "estanteria"
        v = {"ANCHURA": rng.choice(range(800, 3001, 100)), "PROFUNDIDAD": rng.choice(range(300, 1001, 50)),
             "ALTURA": rng.choice(range(1200, 3001, 100)), "NUMERO_NIVELES": rng.randint(2, 7),
             "CARGA_POR_NIVEL": rng.choice([None, 50, 100, 150, 250, 400]), "ANCLAJE": rng.choice(["al_suelo", "ninguno"])}
    v.update({"MATERIAL_ESTRUCTURAL": m[0], "MATERIAL_CHAPA": m[1], "ACABADO": m[2]})
    cases.append({"id": f"R{k:03d}", "family": fid, "values": v})

payload = json.dumps(cases)
js = json.loads(subprocess.run(["node", bundle], input=payload, capture_output=True, text=True, check=True).stdout)
py = json.loads(subprocess.run([sys.executable, "tools/webcheck/ref.py"], input=payload, capture_output=True, text=True,
                               check=True).stdout)

def close(a, b, rel=1e-6, ab=1e-9):
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        return a == b
    return abs(a - b) <= max(ab, rel * max(abs(a), abs(b)))

def num_eq(a, b, rel, ab):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return close(a, b, rel, ab)
    return a == b

total_diffs, worst = 0, {}
for J, P in zip(js, py):
    d = []
    if J["ok"] != P["ok"]:
        d.append(f"ok JS={J.get('error', 'ok')[:300]} PY={P.get('error', 'ok')}")
    elif not J["ok"]:
        if J["error"].split(":")[0].split("\n")[0][-20:] and P["error"]:
            pass
    else:
        for k in P["params"]:
            if not num_eq(J["params"].get(k), P["params"][k], 1e-9, 1e-9):
                d.append(f"param {k}: JS={J['params'].get(k)} PY={P['params'][k]}")
            if J["sources"].get(k) != P["sources"][k]:
                d.append(f"fuente {k}: JS={J['sources'].get(k)} PY={P['sources'][k]}")
        for k in P["derived"]:
            if not num_eq(J["derived"].get(k), P["derived"][k], 1e-9, 1e-9):
                d.append(f"derivado {k}: JS={J['derived'].get(k)} PY={P['derived'][k]}")
        for k in ("product_code", "n_instances", "n_parts", "status", "notes", "cutting", "dfm"):
            a, b = J[k], P[k]
            if k == "cutting":
                a = [[x[0], x[1], round(x[2], 3)] for x in a]; b = [[x[0], x[1], round(x[2], 3)] for x in b]
            if a != b:
                d.append(f"{k}: JS={a} PY={b}")
        if J["fem"] != P["fem"]:
            d.append(f"fem: JS={J['fem']} PY={P['fem']}")
        for ref, pp in P["parts"].items():
            jp = J["parts"].get(ref)
            def norm(k):
                out = []
                for seg in k.rsplit("|", 1)[0].split("|"):
                    try:
                        out.append(f"{float(seg):.4f}")
                    except ValueError:
                        out.append(seg)
                return out
            if not jp or norm(jp["key"]) != norm(pp["key"]):
                d.append(f"pieza {ref}: JS={jp and jp['key']} PY={pp['key']}")
            elif not close(jp["mass"], pp["mass"], 2e-3):
                d.append(f"masa {ref}: JS={jp['mass']:.5f} PY={pp['mass']:.5f}")
        jc, pc = J.get("cost"), P.get("cost")
        if not jc or not pc:
            d.append("presupuesto ausente")
        else:
            for k in ("direct", "cost", "price"):
                if not close(jc[k], pc[k], 2e-4, 0.02):
                    d.append(f"presupuesto {k}: JS={jc[k]} PY={pc[k]}")
            if [x[0] for x in jc["by_lot"]] != [x[0] for x in pc["by_lot"]] or any(not close(a[1], b[1], 2e-4, 0.02) for a, b in zip(jc["by_lot"], pc["by_lot"])):
                d.append(f"presupuesto por lote: JS={jc['by_lot']} PY={pc['by_lot']}")
            if [x[:2] for x in jc["lines"]] != [x[:2] for x in pc["lines"]]:
                d.append(f"partidas del presupuesto distintas: JS={[x[1] for x in jc['lines']][:6]} PY={[x[1] for x in pc['lines']][:6]}")
        if not close(J["mass"], P["mass"], 1e-3):
            d.append(f"masa total: JS={J['mass']} PY={P['mass']}")
        for cid, (st, u, val) in P["checks"].items():
            jc = J["checks"].get(cid)
            if not jc:
                d.append(f"comprobación {cid} ausente en JS"); continue
            if jc[0] != st:
                d.append(f"estado {cid}: JS={jc[0]} PY={st} (u JS={jc[1]} PY={u})")
            if u is not None and jc[1] is not None:
                e = abs(jc[1] - u) / max(abs(u), 1e-3)
                worst[cid.split(".")[0]] = max(worst.get(cid.split(".")[0], 0), e)
                if e > 2e-3:
                    d.append(f"aprovechamiento {cid}: JS={jc[1]} PY={u}")
        for cid in J["checks"]:
            if cid not in P["checks"]:
                d.append(f"comprobación {cid} sobrante en JS")
        for a, b in zip(J["reactions"], P["reactions"]):
            if a["support"] != b["support"] or any(abs(a[k] - b[k]) > max(0.5, 1e-3 * abs(b[k])) for k in ("Rx_N", "Ry_N", "Rz_N")):
                d.append(f"reacción {b['combination']} {b['support']}: JS={a} PY={b}")
        for a, b in zip(J["nesting"], P["nesting"]):
            if a[:4] != b[:4] or not close(a[4], b[4], 2e-3, 1e-4):
                d.append(f"anidado: JS={a} PY={b}")
        for k in P["welding"]:
            if not num_eq(J["welding"][k], P["welding"][k], 1e-6, 1e-3):
                d.append(f"soldadura {k}: JS={J['welding'][k]} PY={P['welding'][k]}")
        for k in P["painting"]:
            if not num_eq(J["painting"][k], P["painting"][k], 2e-3, 1e-3):
                d.append(f"pintura {k}: JS={J['painting'][k]} PY={P['painting'][k]}")
        for k in ("components", "distinct_parts", "manufactured_parts", "standard_parts", "standard_units"):
            if J["bom_totals"][k] != P["bom_totals"][k]:
                d.append(f"BOM {k}: JS={J['bom_totals'][k]} PY={P['bom_totals'][k]}")
        for k in ("profile_meters", "sheet_area_m2"):
            a, b = J["bom_totals"][k], P["bom_totals"][k]
            if set(a) != set(b) or any(not close(a[x], b[x], 1e-6, 1e-3) for x in b):
                d.append(f"BOM {k}: JS={a} PY={b}")
    total_diffs += len(d)
    print(f"{J['id']:<22} {'OK ' if not d else 'DIF'} {J.get('status', J.get('error', '')[:60]):<10} JS {J.get('ms', '-')} ms"
          + "".join(f"\n    - {x}" for x in d[:25]))
print("Máximo error relativo de aprovechamiento por tipo:", {k: f"{v:.1e}" for k, v in sorted(worst.items())})
print("CASOS", len(cases), "DIFERENCIAS", total_diffs)
sys.exit(1 if total_diffs else 0)
