"""Barrido aleatorio de parámetros: busca excepciones, interferencias y errores bloqueantes.

Uso: python tools/fuzz.py N [semilla] [familia]
"""
import json
import random
import sys
import time
import traceback

from monxu.core.params import AUTO
from monxu.families import REGISTRY
from monxu.pipeline import regenerate

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
only = sys.argv[3] if len(sys.argv) > 3 else None
SKIP = {"TOLERANCIAS", "CLASE_EJECUCION", "TIPO_APOYO", "FIJACION_ENCIMERA"}


def sample(fam):
    v = {}
    for s in fam.param_specs():
        if s.name in SKIP or rng.random() < 0.45:          # muchos parámetros se dejan por defecto
            continue
        if s.type == "choice":
            opts = list(s.choices) + ([AUTO] if s.allow_auto else [])
            v[s.name] = rng.choice(opts)
        elif s.type == "int":
            v[s.name] = AUTO if s.allow_auto and rng.random() < 0.5 else rng.randint(int(s.min), int(min(s.max, 10)))
        elif s.type == "float":
            if s.allow_auto and rng.random() < 0.5:
                v[s.name] = AUTO
            elif s.nullable and rng.random() < 0.3:
                v[s.name] = None
            else:
                lo, hi = s.min, s.max
                if s.name.startswith("CARGA"):
                    hi = min(hi, 800)
                x = rng.uniform(lo, hi)
                v[s.name] = (round(x / 0.5) * 0.5 if s.name.startswith("ESPESOR") else
                             round(x, 3) if hi - lo < 10 else round(x))
    return v


results = []
for k in range(N):
    fid = only or rng.choice(list(REGISTRY))
    fam = REGISTRY[fid]
    vals = sample(fam)
    t0 = time.time()
    rec = {"i": k, "family": fid, "values": vals}
    try:
        d = regenerate(fid, vals)
        q = d.qa.result()
        rec.update(ok=True, secs=round(time.time() - t0, 1), qa_blocking=q["blocking"], status=d.eng["status"],
                   interferences=len(d.interferences["interferences"]),
                   blocking=[(i["code"], i["message"][:160]) for i in q["items"] if i["level"] == "bloqueante"],
                   mass=d.bom["totals"]["total_mass"])
    except Exception as e:
        rec.update(ok=False, error=f"{type(e).__name__}: {e}", tb=traceback.format_exc()[-1500:])
    results.append(rec)
    flag = "EXC" if not rec["ok"] else ("BLOQ" if rec["qa_blocking"] else "ok")
    print(k, fid, flag, rec.get("error", "") or rec.get("blocking", ""), flush=True)
json.dump(results, open(sys.argv[4] if len(sys.argv) > 4 else "/dev/stdout", "w"), indent=1, default=str) \
    if len(sys.argv) > 4 else None
