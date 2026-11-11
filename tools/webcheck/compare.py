"""Validación cruzada: motor del navegador (TypeScript, ejecutado en node) frente al motor de referencia (Python).

Uso: python tools/webcheck/compare.py BUNDLE.mjs N_ALEATORIOS SEMILLA
(COMPARE_ONLY=familia1,familia2 limita los casos a esas familias.)
Compara parámetros resueltos por el dimensionado, derivados, piezas, masas, comprobaciones estructurales,
reacciones, plan de corte, anidado, soldadura, pintura, DFM y totales del BOM.
"""
import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

from monxu.families import REGISTRY

sys.path.insert(0, str(Path(__file__).parent))
from cases import random_cases  # noqa: E402

bundle, n_rand, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
cases = []
for fid, f in REGISTRY.items():
    for t in f.templates():
        cases.append({"id": t["id"], "family": fid, "values": t["values"]})
cases.append({"id": "ACEPT-2000", "family": "mesa_industrial", "values": {"LONGITUD": 2000, "ANCHURA": 800, "ALTURA": 900, "CARGA_TOTAL": 400}})
cases.append({"id": "ACEPT-2400", "family": "mesa_industrial", "values": {"LONGITUD": 2400, "ANCHURA": 800, "ALTURA": 900, "CARGA_TOTAL": 400}})
cases.append({"id": "SIN-CARGA", "family": "mesa_industrial", "values": {}})
cases.append({"id": "EST-DEF", "family": "estanteria", "values": {}})
# parámetros avanzados de fabricación y criterio (barra, sierra, formato, pintura, lote, flechas y desplome)
cases.append({"id": "AVANZ-MESA", "family": "mesa_industrial", "values": {
    "LONGITUD_BARRA": 6500, "CORTE_SIERRA": 4, "FORMATO_CHAPA": "3000x1500", "ESPESOR_PINTURA": 120,
    "LOTE_FABRICACION": 10, "LIMITE_FLECHA_BARRAS": 500, "LIMITE_FLECHA_CHAPA": 400, "LIMITE_DESPLOME": 300}})
cases.append({"id": "AVANZ-EST", "family": "estanteria", "values": {
    "CARGA_POR_NIVEL": 200, "LIMITE_FLECHA_CHAPA": 300, "LIMITE_FLECHA_BARRAS": 400, "LONGITUD_BARRA": 12000,
    "FORMATO_CHAPA": "2500x1250", "LOTE_FABRICACION": 25}})
cases.append({"id": "AVANZ-CARRO", "family": "carro_taller", "values": {"CARGA_TOTAL": 150, "COEF_DINAMICO": 1.5}})
cases.append({"id": "AVANZ-HUELLA", "family": "mesa_industrial", "values": {"CARGA_PUNTUAL": 120, "HUELLA_CARGA_PUNTUAL": 50}})
cases.append({"id": "AVANZ-REPOSA", "family": "puesto_trabajo", "values": {"REPOSAPIES": 1, "CARGA_REPOSAPIES": 1500}})
cases.append({"id": "AVANZ-CE", "family": "carro_estanteria", "values": {"CARGA_POR_NIVEL": 40, "COEF_DINAMICO": 1.3}})
cases += random_cases(n_rand, seed)

if os.environ.get("COMPARE_ONLY"):
    keep = set(os.environ["COMPARE_ONLY"].split(","))
    cases = [c for c in cases if c["family"] in keep]
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
                a = [[x[0], x[1], round(x[2], 3), x[3], round(x[4], 1), round(x[5], 1)] for x in a]
                b = [[x[0], x[1], round(x[2], 3), x[3], round(x[4], 1), round(x[5], 1)] for x in b]
            if a != b:
                d.append(f"{k}: JS={a} PY={b}")
        if J.get("weld_faces") != P.get("weld_faces"):
            d.append(f"caras de soldeo: JS={J.get('weld_faces')} PY={P.get('weld_faces')}")
        # veredicto, validaciones pendientes (con su motivo), hipótesis del cálculo y corrección automática propuesta
        if J.get("verdict") != P.get("verdict"):
            d.append(f"veredicto: JS={J.get('verdict')} PY={P.get('verdict')}")
        if J.get("val_pending") != P.get("val_pending"):
            d.append(f"validaciones pendientes: JS={J.get('val_pending')} PY={P.get('val_pending')}")
        jh, ph = J.get("hypotheses") or [], P.get("hypotheses") or []
        if jh != ph:
            k = next((i for i, (a, b) in enumerate(zip(jh, ph)) if a != b), min(len(jh), len(ph)))
            d.append(f"hipótesis {k} ({len(jh)}/{len(ph)}): JS={jh[k] if k < len(jh) else None!r} PY={ph[k] if k < len(ph) else None!r}")
        jf, pf_ = J.get("fix"), P.get("fix")
        if (jf is None) != (pf_ is None):
            d.append(f"corrección automática: JS={jf} PY={pf_}")
        elif jf is not None:
            if set(jf["params"]) != set(pf_["params"]) or any(not num_eq(jf["params"][k], pf_["params"][k], 1e-9, 1e-9) for k in pf_["params"]):
                d.append(f"corrección automática (parámetros): JS={jf['params']} PY={pf_['params']}")
            for k in ("reasons", "verdict", "validation_pending"):
                if jf.get(k) != pf_.get(k):
                    d.append(f"corrección automática ({k}): JS={jf.get(k)} PY={pf_.get(k)}")
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
                # los aprovechamientos se redondean a 4 decimales: admite un escalón de redondeo (0,0001)
                if e > 2e-3 and abs(jc[1] - u) > 1.01e-4:
                    d.append(f"aprovechamiento {cid}: JS={jc[1]} PY={u}")
        for cid in J["checks"]:
            if cid not in P["checks"]:
                d.append(f"comprobación {cid} sobrante en JS")
        for a, b in zip(J["reactions"], P["reactions"]):
            if a["support"] != b["support"] or any(abs(a[k] - b[k]) > max(0.5, 1e-3 * abs(b[k])) for k in ("Rx_N", "Ry_N", "Rz_N")):
                d.append(f"reacción {b['combination']} {b['support']}: JS={a} PY={b}")
        for a, b in zip(J["nesting"], P["nesting"]):
            if a[:4] != b[:4] or not close(a[4], b[4], 2e-3, 1e-4) or a[5:7] != b[5:7] or \
                    any(not num_eq(x, y, 1e-6, 1e-6) for x, y in zip(a[7:], b[7:])):
                d.append(f"anidado: JS={a} PY={b}")
        for k in P["balance"]:
            if not num_eq(J["balance"][k], P["balance"][k], 1e-6, 2e-3):
                d.append(f"balance {k}: JS={J['balance'][k]} PY={P['balance'][k]}")
        if [x[:3] for x in J["purchases"]] != [x[:3] for x in P["purchases"]] or \
                any(not num_eq(x[3], y[3], 1e-6, 2e-3) for x, y in zip(J["purchases"], P["purchases"])):
            d.append(f"compras: JS={J['purchases']} PY={P['purchases']}")
        for k in P["welding"]:
            if not num_eq(J["welding"][k], P["welding"][k], 1e-6, 1e-3):
                d.append(f"soldadura {k}: JS={J['welding'][k]} PY={P['welding'][k]}")
        for k in P["painting"]:
            if not num_eq(J["painting"][k], P["painting"][k], 2e-3, 1e-3):
                d.append(f"pintura {k}: JS={J['painting'][k]} PY={P['painting'][k]}")
        for k in ("components", "distinct_parts", "manufactured_parts", "standard_parts", "standard_units"):
            if J["bom_totals"][k] != P["bom_totals"][k]:
                d.append(f"BOM {k}: JS={J['bom_totals'][k]} PY={P['bom_totals'][k]}")
        for k in ("mass_manufactured_kg", "mass_commercial_kg", "mass_purchased_kg", "mass_waste_kg", "mass_reusable_kg"):
            if not num_eq(J["bom_totals"].get(k), P["bom_totals"][k], 1e-4, 2e-3):
                d.append(f"BOM {k}: JS={J['bom_totals'].get(k)} PY={P['bom_totals'][k]}")
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
