"""Verifica con las herramientas del servidor un expediente generado por el motor del navegador.

ZIP (integridad y SHA-256 del manifiesto), STEP (reimportación OpenCascade: sólidos, validez y volumen),
PDF (páginas y texto con pdfplumber), Excel (openpyxl: fórmulas y valores frente al BOM del servidor),
DXF (auditoría ezdxf, contornos cerrados, unidades y medidas frente a los desarrollos del servidor).
"""
import hashlib, io, json, struct, sys, tempfile, zipfile
from pathlib import Path

from monxu.docs.dxf import verify_dxf
from monxu.families import family

zpath, fam, values = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
z = zipfile.ZipFile(zpath)
assert z.testzip() is None, "ZIP corrupto"
names = z.namelist()
root = names[0].split("/")[0]
man = json.loads(z.read(f"{root}/manifest.json"))
bad_sha = [f["path"] for f in man["files"] if hashlib.sha256(z.read(f"{root}/{f['path']}")).hexdigest() != f["sha256"]]
methods = {i.compress_type for i in z.infolist()}
print(f"ZIP: {len(names)} archivos, {Path(zpath).stat().st_size / 1e6:.2f} MB, métodos {sorted(methods)}, SHA-256 incorrectos: {bad_sha}")
errs = len(bad_sha)
f = family(fam); ps = f.new_params(); ps.update(values, "usuario"); m = f.build(ps)
from monxu.engineering.analysis import analyze
from monxu.manufacturing.plan import manufacturing_plan
from monxu.docs.bom import build_bom
bom = build_bom(m, manufacturing_plan(m))
exp = {p.ref: ((p.flat.width, p.flat.height) if p.kind == "chapa" else (p.w, p.h)) for p in m.parts.values() if p.kind in ("chapa", "pletina")}
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    # ---------------- STEP
    import cadquery as cq
    from OCP.BRepCheck import BRepCheck_Analyzer
    st = next(n for n in names if n.endswith("_conjunto.step"))
    (td / "c.step").write_bytes(z.read(st))
    sol = cq.importers.importStep(str(td / "c.step")).solids().vals()
    vol = sum(s.Volume() for s in sol)
    valid = sum(BRepCheck_Analyzer(s.wrapped).IsValid() for s in sol)
    ref_vol = sum(i.part.volume for i in m.instances)
    occ = z.read(st).decode("latin-1").count("NEXT_ASSEMBLY_USAGE_OCCURRENCE(")
    print(f"STEP conjunto: {occ} ocurrencias (instancias del modelo servidor {len(m.instances)}), {len(sol)} sólidos, válidos {valid}, "
          f"volumen {vol:.0f} mm³ vs B-rep servidor {ref_vol:.0f} ({(vol / ref_vol - 1) * 100:+.3f} %)")
    # una pieza puede tener varios cuerpos (las ruedas: horquilla, espiga, cabezal y rueda)
    errs += occ != len(m.instances) or len(sol) < len(m.instances) or valid != len(sol) or abs(vol / ref_vol - 1) > 0.005
    comps = [n for n in names if "/componentes/" in n and n.endswith(".step")]
    okc = 0
    for n in comps:
        (td / "p.step").write_bytes(z.read(n))
        ss = cq.importers.importStep(str(td / "p.step")).solids().vals()
        okc += len(ss) >= 1 and all(BRepCheck_Analyzer(x.wrapped).IsValid() for x in ss)
    print(f"STEP por pieza: {okc}/{len(comps)} con sus sólidos válidos")
    errs += okc != len(comps)
    # ---------------- PDF
    import pdfplumber
    for n in [x for x in names if x.endswith(".pdf")]:
        with pdfplumber.open(io.BytesIO(z.read(n))) as pdf:
            txt = pdf.pages[0].extract_text() or ""
            print(f"PDF {n.split('/', 1)[1]}: {len(pdf.pages)} páginas A3={round(pdf.pages[0].width / 72 * 25.4)}x{round(pdf.pages[0].height / 72 * 25.4)} mm, "
                  f"cajetín {'sí' if 'Nº de plano' in txt else 'NO'}, ref {'sí' if m.product_code in txt else 'NO'}")
            errs += "Nº de plano" not in txt
    # ---------------- Excel
    from openpyxl import load_workbook
    xn = next(n for n in names if n.endswith(".xlsx"))
    (td / "b.xlsx").write_bytes(z.read(xn))
    wbf = load_workbook(td / "b.xlsx")                    # fórmulas
    wbv = load_workbook(td / "b.xlsx", data_only=True)    # valores en caché
    ws, wv = wbf["BOM"], wbv["BOM"]
    rows = [r for r in ws.iter_rows(min_row=9) if isinstance(r[0].value, int)]
    formulas = sum(1 for r in rows if isinstance(r[9].value, str) and r[9].value.startswith("="))
    qty = sum(r[7].value for r in rows)
    mass = sum(wv.cell(r[0].row, 10).value for r in rows)
    print(f"Excel: hojas {wbf.sheetnames}; BOM {len(rows)} filas, {formulas} fórmulas, {qty} uds (servidor {bom['totals']['components']}), "
          f"{mass:.3f} kg (servidor {bom['totals']['total_mass']:.3f})")
    errs += qty != bom["totals"]["components"] or abs(mass - bom["totals"]["total_mass"]) > max(0.00005 * qty + 0.002, 2e-4 * mass) or formulas != len(rows)
    # ---------------- DXF
    for n in names:
        if n.endswith(".dxf"):
            p = td / Path(n).name
            p.write_bytes(z.read(n))
            r = verify_dxf(p)
            ref = Path(n).stem
            line = f"DXF {n.split('/', 1)[1]:<55} errores {r['errors']} · cerrados {r['closed_contours']} · {r['width']}×{r['height']}"
            if ref in exp:
                ok = abs(r["width"] - exp[ref][0]) < 0.01 and abs(r["height"] - exp[ref][1]) < 0.01
                line += f" · servidor {exp[ref][0]:.3f}×{exp[ref][1]:.3f} {'OK' if ok else 'DIFERENTE'}"
                errs += not ok
            errs += r["errors"] > 0 or not r["closed_contours"] or r["insunits"] != 4
            print(line)
    stl = next(n for n in names if n.endswith(".stl"))
    data = z.read(stl)
    ntri = struct.unpack("<I", data[80:84])[0]
    print("STL:", ntri, "triángulos, tamaño coherente:", len(data) == 84 + 50 * ntri)
# ---------------- CSV: mismas filas, celdas y formato que los del servidor
import re
from monxu import pipeline as PL
from monxu.manufacturing.costing import quotation
NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def csv_diffs(got: str, exp: str, rel: float = 2e-3) -> list[str]:
    """Diferencias entre un CSV del navegador y el del servidor. Las celdas deben ser idénticas salvo los números,
    que admiten la tolerancia entre el sólido B-rep del servidor y la definición analítica del navegador (y un
    escalón de redondeo); un número con punto decimal en una celda numérica es un error de formato."""
    out = []
    gr, er = [ln.split(";") for ln in got.splitlines()], [ln.split(";") for ln in exp.splitlines()]
    if len(gr) != len(er):
        return [f"{len(gr)} filas frente a {len(er)}"]
    for k, (a, b) in enumerate(zip(gr, er), 1):
        if len(a) != len(b):
            out.append(f"fila {k}: {len(a)} celdas frente a {len(b)}")
            continue
        for x, y in zip(a, b):
            if x == y:
                continue
            if any(re.fullmatch(r"-?\d+\.\d+", c) for c in (x, y)):
                out.append(f"fila {k}: número con punto decimal ({x!r} / {y!r})")
                continue
            nx, ny = NUM.findall(x), NUM.findall(y)
            same = NUM.sub("#", x) == NUM.sub("#", y)
            for p_, q_ in zip(nx, ny):
                u, v = float(p_.replace(",", ".")), float(q_.replace(",", "."))
                step = 10.0 ** -min(len(t.replace(",", ".").partition(".")[2]) for t in (p_, q_))
                same = same and abs(u - v) <= rel * max(abs(u), abs(v)) + 1.01 * step
            if not same:
                out.append(f"fila {k}: {x!r} frente a {y!r}")
    return out


plan = manufacturing_plan(m)
cost = quotation(m, plan)
L = "04_LISTA_MATERIALES"
expected_csv = {f"{L}/lista_compras.csv": (PL.PURCHASE_HEADER, PL.purchase_rows(bom, plan.get("lot", 1)), False),
                f"{L}/presupuesto_estimado.csv": (PL.QUOTE_HEADER, PL.quote_rows(cost), False),
                f"{L}/pesos_materiales.csv": (PL.WEIGHT_HEADER, PL.weight_rows(bom), False),
                "05_OPTIMIZACION/plan_corte_perfiles.csv": (PL.CUT_PLAN_HEADER, PL.cut_plan_rows(plan), True),
                "05_OPTIMIZACION/balance_material.csv": (PL.BALANCE_HEADER, PL.balance_rows(plan), True)}
for n, (header, rows, exact) in expected_csv.items():
    got, exp_txt = z.read(f"{root}/{n}").decode("utf-8"), PL.csv_text(header, rows)
    dif = ([] if got == exp_txt else ["no es idéntico byte a byte"] + csv_diffs(got, exp_txt)[:3]) if exact else csv_diffs(got, exp_txt)
    print(f"CSV {n:<45} {'idéntico al servidor' if got == exp_txt else 'igual al servidor dentro de tolerancia' if not dif else 'DIFERENTE: ' + '; '.join(dif[:4])}")
    errs += bool(dif)
qa = json.loads(z.read(f"{root}/06_DOCUMENTACION/informe_verificaciones.json"))["qa"]
print("QA del navegador:", qa["summary"])
print("ERRORES", errs)
sys.exit(1 if errs else 0)
