"""Referencia Python para la validación cruzada del motor del navegador (mismos campos que run.ts)."""
import json
import sys

from monxu.manufacturing.costing import quotation
from monxu.engineering.analysis import analyze
from monxu.families import family
from monxu.manufacturing.plan import dfm_check, manufacturing_plan
from monxu.docs.bom import build_bom


def run(c):
    fam = family(c["family"])
    ps = fam.new_params()
    ps.update(c["values"], "usuario")
    m = fam.build(ps)
    eng = analyze(m)
    plan = manufacturing_plan(m)
    dfm = dfm_check(m, plan)
    bom = build_bom(m, plan)
    rows = m.parameter_table()
    return {"id": c["id"], "ok": True, "product_code": m.product_code,
            "params": {r["name"]: r["value"] for r in rows if not r["derived"]},
            "sources": {r["name"]: r["source"] for r in rows if not r["derived"]},
            "derived": {r["name"]: r["value"] for r in rows if r["derived"]},
            "n_instances": len(m.instances), "n_parts": len(m.parts), "mass": bom["totals"]["total_mass"],
            "parts": {p.ref: {"key": p.key, "mass": p.mass, "vol": p.volume} for p in m.parts.values()},
            "cost": (lambda q: {"direct": q["direct"], "cost": q["cost"], "price": q["price"],
                                "by_lot": [[b["lot"], b["price"]] for b in q["by_lot"]],
                                "lines": [[ln["group"], ln["concept"], ln["eur"]] for ln in q["lines"]]})(quotation(m, plan)),
            "status": eng["status"], "fem": eng["fem"],
            "checks": {k["id"]: [k["status"], k["utilization"], k["value"]] for k in eng["checks"]},
            "reactions": [r for r in eng["reactions"] if r["combination"] in ("ELS-1", "ELU-1")],
            "notes": [[n["level"], n["code"]] for n in m.design_notes],
            "cutting": [[k["profile"], k["n_bars"], k["utilization"]] for k in plan["cutting"]],
            "nesting": [[k["material"], k["thickness"], k.get("n_sheets"), k.get("format"), k.get("utilization")] for k in plan["nesting"]],
            "welding": plan["welding"], "painting": plan["painting"],
            "dfm": [[d["level"], d["code"], d["element"]] for d in dfm], "bom_totals": bom["totals"]}


out = []
for c in json.load(sys.stdin):
    try:
        out.append(run(c))
    except Exception as e:  # noqa: BLE001
        out.append({"id": c["id"], "ok": False, "error": f"{type(e).__name__}: {e}"})
print(json.dumps(out, default=str))
