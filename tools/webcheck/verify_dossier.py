"""Verifica un expediente generado por el motor del navegador con las herramientas del servidor."""
import hashlib, io, json, sys, tempfile, zipfile
from pathlib import Path
from monxu.docs.dxf import verify_dxf
from monxu.families import family

zpath, fam, values = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
z = zipfile.ZipFile(zpath)
assert z.testzip() is None, "ZIP corrupto"
names = z.namelist()
root = names[0].split("/")[0]
man = json.loads(z.read(f"{root}/manifest.json"))
bad = [f["path"] for f in man["files"] if hashlib.sha256(z.read(f"{root}/{f['path']}")).hexdigest() != f["sha256"]]
print("archivos", len(names), "· SHA-256 incorrectos:", bad)
f = family(fam); ps = f.new_params(); ps.update(values, "usuario"); m = f.build(ps)
exp = {p.ref: ((p.flat.width, p.flat.height) if p.kind == "chapa" else (p.w, p.h)) for p in m.parts.values() if p.kind in ("chapa", "pletina")}
errs = 0
with tempfile.TemporaryDirectory() as td:
    for n in names:
        if n.endswith(".dxf"):
            p = Path(td) / Path(n).name
            p.write_bytes(z.read(n))
            r = verify_dxf(p)
            ref = Path(n).stem
            line = f"{n.split('/', 1)[1]:<60} errores {r['errors']} · cerrados {r['closed_contours']} · INSUNITS {r['insunits']} · {r['width']}×{r['height']}"
            if ref in exp:
                ok = abs(r["width"] - exp[ref][0]) < 0.01 and abs(r["height"] - exp[ref][1]) < 0.01
                line += f" · servidor {exp[ref][0]:.3f}×{exp[ref][1]:.3f} {'OK' if ok else 'DIFERENTE'}"
                errs += not ok
            errs += r["errors"] > 0 or not r["closed_contours"] or r["insunits"] != 4
            print(line)
    stl = next(n for n in names if n.endswith(".stl"))
    data = z.read(stl)
    import struct
    ntri = struct.unpack("<I", data[80:84])[0]
    print("STL", len(data), "bytes,", ntri, "triángulos, tamaño coherente:", len(data) == 84 + 50 * ntri)
print("ERRORES", errs)
