"""Barrido realista: sólo los datos que daría un usuario (dimensiones, cargas, niveles, material, anclaje)."""
import collections, json, random, sys, time, traceback
from monxu.pipeline import regenerate
N = int(sys.argv[1]); rng = random.Random(int(sys.argv[2]))
MATS = [("S235JRH", "S235JR", "RAL7035_POLVO"), ("1.4301", "1.4301", "INOX_SATINADO"),
        ("S235JRH", "DC01", "RAL5010_POLVO"), ("EN AW-6082 T6", "EN AW-5754 H22", "ANODIZADO_NATURAL")]
out = []
for k in range(N):
    m = rng.choice(MATS)
    if rng.random() < 0.5:
        fid = "mesa_industrial"
        v = {"LONGITUD": rng.choice(range(800, 3001, 100)), "ANCHURA": rng.choice(range(500, 1201, 50)),
             "ALTURA": rng.choice(range(700, 1101, 50)), "CARGA_TOTAL": rng.choice([None, 100, 200, 300, 400, 600, 800]),
             "NUMERO_BALDAS": rng.choice([0, 1]), "CARGA_BALDA": rng.choice([None, 0, 50, 100, 200]),
             "USO": rng.choice(["montaje", "trabajo_pesado", "inspeccion"]),
             "CARGA_HORIZONTAL": rng.choice([100, 200, 300]),
             "PERFIL_PATA": "auto", "PERFIL_LARGUERO": "auto", "PERFIL_TRAVESANO": "auto", "PERFIL_BASTIDOR": "auto",
             "ESPESOR_CHAPA": "auto", "ESPESOR_BALDA": "auto"}
    else:
        fid = "estanteria"
        v = {"ANCHURA": rng.choice(range(800, 3001, 100)), "PROFUNDIDAD": rng.choice(range(300, 1001, 50)),
             "ALTURA": rng.choice(range(1200, 3001, 100)), "NUMERO_NIVELES": rng.randint(2, 7),
             "CARGA_POR_NIVEL": rng.choice([None, 50, 100, 150, 250, 400]), "ANCLAJE": rng.choice(["al_suelo", "ninguno"])}
    v.update({"MATERIAL_ESTRUCTURAL": m[0], "MATERIAL_CHAPA": m[1], "ACABADO": m[2]})
    t0 = time.time()
    try:
        d = regenerate(fid, v); q = d.qa.result()
        rec = {"family": fid, "values": v, "ok": True, "blocking": [(i["code"], i["message"][:200]) for i in q["items"]
                if i["level"] == "bloqueante"], "status": d.eng["status"], "secs": round(time.time() - t0, 1),
               "fails": [c["description"][:90] for c in d.eng["checks"] if c["status"] == "NO_CUMPLE"]}
    except Exception as e:
        rec = {"family": fid, "values": v, "ok": False, "error": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()[-1200:]}
    out.append(rec)
    print(k, fid, "EXC " + rec["error"][:120] if not rec["ok"] else (rec["status"], [c for c, _ in rec["blocking"]]), flush=True)
json.dump(out, open(sys.argv[3], "w"), indent=1, default=str)
