"""Barrido realista con el motor del navegador: casos con sólo los datos de usuario (cases.random_cases) y todo lo
demás por defecto o 'auto'. Un error bloqueante o una excepción en estos casos es un fallo del generador.

Uso: python tools/webcheck/realistic.py BUNDLE_run.mjs N SEMILLA [salida.json]
"""
import collections
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cases import random_cases  # noqa: E402

bundle, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
cases = random_cases(n, seed)
res = json.loads(subprocess.run(["node", bundle], input=json.dumps(cases), capture_output=True, text=True,
                                check=True).stdout)
by_fam = collections.defaultdict(lambda: collections.Counter())
examples = collections.defaultdict(list)
for c, r in zip(cases, res):
    f = c["family"]
    by_fam[f]["casos"] += 1
    if not r["ok"]:
        key = "EXCEPCION: " + r["error"].split("\n")[0][:120]
    else:
        blocking = sorted({code for lvl, code in r["qa"] if lvl == "bloqueante"})
        fails = sorted({cid.split(".")[0] + "." + cid.split(".")[-1] for cid, (st, _, _) in r["checks"].items()
                        if st == "NO_CUMPLE"})
        by_fam[f][r["status"]] += 1
        if fails and r.get("fix"):              # no cumple por valores fijados y tiene corrección comprobada
            by_fam[f]["con corrección comprobada"] += 1
        key = ("BLOQ " + ",".join(blocking)) if blocking else (
            ("NO_CUMPLE " + ",".join(fails) + ("" if r.get("fix") else " (SIN CORRECCIÓN)")) if fails else None)
    if key:
        by_fam[f][key] += 1
        if len(examples[(f, key)]) < 3:
            examples[(f, key)].append(c["values"])
for f, cnt in sorted(by_fam.items()):
    print(f, dict(cnt))
print()
for (f, key), ex in sorted(examples.items()):
    print(f"{f} | {key}\n    p.ej. {json.dumps(ex[0], ensure_ascii=False)}")
if len(sys.argv) > 4:
    Path(sys.argv[4]).write_text(json.dumps({"cases": cases, "results": res}, ensure_ascii=False))
