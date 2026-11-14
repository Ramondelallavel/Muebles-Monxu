"""Caso de aceptación obligatorio (§23): mesa 2.000 × 800 × 900 mm → expediente → cambio a 2.400 mm.

Recorre los 20 pasos del criterio con el asistente, la API y el pipeline real, y comprueba que
los archivos regenerados coinciden con el modelo actualizado.
"""
import json
import time
import zipfile
from pathlib import Path

import cadquery as cq
import ezdxf
import pdfplumber
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from monxu.api import main
from monxu.storage.db import Store

REQUEST = ("Quiero una mesa industrial de 2.000 × 800 × 900 mm, con estructura tubular, encimera de chapa, "
           "una balda inferior y carga distribuida solicitada de 400 kg.")
ANSWER = ("La balda soportará 100 kg. Uso de montaje diario, interior, empujes ligeros, sin anclaje al suelo, "
          "acero pintado RAL 7035")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    main.set_store(Store(tmp_path_factory.mktemp("monxu")))
    return TestClient(main.app)


def _dossier(client, code, rev):
    job = client.post(f"/api/projects/{code}/revisions/{rev}/dossier").json()
    for _ in range(300):
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] != "running":
            return j
        time.sleep(1)
    raise TimeoutError


def _check_files(dossier: Path, design: dict, length: float, model_bbox=None):
    code = design["product_code"]
    folders = sorted(p.name for p in dossier.iterdir() if p.is_dir())
    assert folders == ["01_MODELO_3D", "02_PLANOS", "03_DXF_CORTE", "04_LISTA_MATERIALES", "05_OPTIMIZACION",
                       "06_DOCUMENTACION"]
    manifest = json.loads((dossier / "manifest.json").read_text())
    assert manifest["parameters"]["LONGITUD"] == length
    # STEP: geometría real reimportada
    shape = cq.importers.importStep(str(dossier / "01_MODELO_3D" / f"{code}_conjunto.step"))
    bb = shape.val().BoundingBox()
    top = next(r for r in design["bom"]["rows"] if r["description"].startswith("Encimera"))
    flat_exact = length + 2 * 40 - 2 * 3.837441      # desarrollo = L + 2·ala − 2·BD (t=2, Ri=2, K=0,325)
    assert top["length"] == pytest.approx(flat_exact, abs=0.05)                      # BOM redondeado a 0,1 mm
    if model_bbox is not None:                       # el STEP reimportado tiene la envolvente del modelo CAD
        assert bb.xmax - bb.xmin == pytest.approx(model_bbox[1][0] - model_bbox[0][0], abs=0.01)
        assert bb.zmax - bb.zmin == pytest.approx(model_bbox[1][2] - model_bbox[0][2], abs=0.01)
    assert bb.xmax - bb.xmin >= length
    # DXF de la encimera: 1:1 y medidas del desarrollo
    doc = ezdxf.readfile(dossier / "03_DXF_CORTE" / f"{top['ref']}.dxf")
    assert doc.header["$INSUNITS"] == 4
    ext = ezdxf.bbox.extents(e for e in doc.modelspace() if e.dxf.layer.startswith("CORTE"))
    assert ext.size.x == pytest.approx(flat_exact, abs=0.01)                         # DXF exacto 1:1
    assert {"CORTE_EXTERIOR", "CORTE_INTERIOR", "PLEGADO_ABAJO"} <= {e.dxf.layer for e in doc.modelspace()}
    # Excel con fórmulas y masa coherente
    wb = load_workbook(dossier / "04_LISTA_MATERIALES" / f"{code}_BOM.xlsx")
    ws = wb["BOM"]
    hdr = next(r for r in range(1, 20) if ws.cell(r, 1).value == "Posición")
    assert str(ws.cell(hdr + 1, 10).value).startswith("=H")
    # PDF de planos: cotas de geometría presentes
    with pdfplumber.open(dossier / "02_PLANOS" / f"{code}_planos.pdf") as pdf:
        text = pdf.pages[0].extract_text()
        assert str(int(length)) in text and "800" in text and "900" in text
        assert len(pdf.pages) == 12
    for f in ["06_DOCUMENTACION/informe_calculo_y_verificaciones.pdf", "06_DOCUMENTACION/instrucciones_montaje.pdf",
              "05_OPTIMIZACION/anidado_chapa.pdf", "05_OPTIMIZACION/plan_corte_perfiles.csv",
              "04_LISTA_MATERIALES/lista_compras.csv", "01_MODELO_3D/" + f"{code}_parametrico.json"]:
        assert (dossier / f).stat().st_size > 0, f
    return manifest


@pytest.mark.slow
def test_acceptance_2000_then_2400(client):
    # 1-4: interpretación, datos que faltan, aclaraciones y propuesta
    p = client.post("/api/projects", json={"name": "Mesa de montaje", "client": "Cliente", "designer": "Ingeniería"}).json()
    code = p["code"]
    r = client.post(f"/api/projects/{code}/assistant", json={"message": REQUEST}).json()
    assert r["family"] == "mesa_industrial" and r["ready_to_generate"]
    missing = {q["param"] for q in r["questions"]}
    assert {"CARGA_BALDA", "MATERIAL_ESTRUCTURAL", "CARGA_HORIZONTAL"} <= missing
    r = client.post(f"/api/projects/{code}/assistant", json={"message": ANSWER, "apply": True}).json()
    assert r["applied"] is not None and r["parameters"]["CARGA_BALDA"] == 100
    assert r["parameters"]["PERFIL_PATA"] == "auto"            # propuesta constructiva a dimensionar
    # 5-9: modelo CAD, 3D, componentes, interferencias y verificaciones
    d1 = client.post(f"/api/projects/{code}/design").json()
    des1, viewer = d1["design"], d1["viewer"]
    assert des1["status"]["geometry_complete"] and des1["qa"]["blocking"] == 0
    assert des1["interferences"]["interferences"] == [] and des1["interferences"]["pairs_checked"] > 100
    assert des1["engineering"]["status"] == "CUMPLE"
    assert len(viewer["instances"]) == des1["bom"]["totals"]["components"]
    n_cross_2000 = next(p["value"] for p in des1["parameters"] if p["name"] == "N_TRAVESANOS_INT")
    # 10-20: planos, desarrollos, despiece, pesos, BOM, corte, STEP, DXF, PDF, Excel, expediente
    client.post(f"/api/projects/{code}/revisions", json={"comment": "Emisión inicial", "author": "Ingeniería"})
    j = _dossier(client, code, "A")
    assert j["status"] == "ok", j
    assert j["result"]["qa"]["blocking"] == 0
    m1 = _check_files(Path(j["result"]["path"]), des1, 2000.0, viewer["bbox"])
    # cambio de longitud a 2.400 mm
    client.put(f"/api/projects/{code}/params", json={"values": {"LONGITUD": 2400}})
    r2 = client.post(f"/api/projects/{code}/design").json()
    d2, viewer2 = r2["design"], r2["viewer"]
    assert d2["product_code"] == "MI2400-800-900" and d2["qa"]["blocking"] == 0
    n_cross_2400 = next(p["value"] for p in d2["parameters"] if p["name"] == "N_TRAVESANOS_INT")
    assert n_cross_2400 > n_cross_2000                      # regeneración por reglas, no escalado
    lp = lambda d: next(p["value"] for p in d["parameters"] if p["name"] == "LONGITUD_LARGUERO")
    assert lp(d2) - lp(des1) == pytest.approx(400)
    assert d2["bom"]["totals"]["total_mass"] > des1["bom"]["totals"]["total_mass"]
    rv = client.post(f"/api/projects/{code}/revisions", json={"comment": "Longitud 2.400 mm", "author": "Ingeniería"}).json()
    assert rv["rev"] == "B"
    proj = client.get(f"/api/projects/{code}").json()
    assert proj["revisions"][1]["changes"]["LONGITUD"] == [2000.0, 2400.0]
    j2 = _dossier(client, code, "B")
    assert j2["status"] == "ok", j2
    m2 = _check_files(Path(j2["result"]["path"]), d2, 2400.0, viewer2["bbox"])
    # la revisión A no se ha sobrescrito y sigue describiendo 2.000 mm
    assert Path(j["result"]["path"]).exists() and m1["parameters"]["LONGITUD"] == 2000.0
    assert client.post(f"/api/projects/{code}/revisions/A/dossier").status_code == 409
    # coherencia plano ↔ geometría verificada en el expediente nuevo
    plano = next(i for i in j2["result"]["qa"]["items"] if i["code"] == "PLANO-GEOMETRIA")
    assert plano["level"] == "ok"
    with zipfile.ZipFile(j2["result"]["zip"]) as z:
        assert any(n.endswith("manifest.json") for n in z.namelist())
    # aprobación técnica obligatoria antes de fabricación: nueve estados con validaciones y firmas
    assert client.post(f"/api/projects/{code}/status", json={"status": "preparado_fabricacion"}).status_code == 409
    assert client.post(f"/api/projects/{code}/status", json={"status": "validado", "user": "x",
                                                             "validated_by": "Ing. Responsable"}).status_code == 409
    ap = client.get(f"/api/projects/{code}/approval").json()
    assert ap["state"] not in ("aprobado_tecnicamente", "liberado_fabricacion") and ap["open_validations"]
    assert client.post(f"/api/projects/{code}/signoff", json={"stage": "aprobacion", "by": "Ing. Jefe"}).status_code == 409
    for c in ap["open_validations"]:          # cada pendiente se cierra con su documento de referencia
        r = client.post(f"/api/projects/{code}/validations", json={"code": c, "by": "Ing. Calidad", "reference": f"DOC-{c}"})
        assert r.status_code == 200, r.json()
    for stage in ("fabricabilidad", "calculo", "aprobacion"):
        r = client.post(f"/api/projects/{code}/signoff", json={"stage": stage, "by": "Ing. Responsable"})
        assert r.status_code == 200, r.json()
    assert r.json()["state"] == "aprobado_tecnicamente"
    assert client.get(f"/api/projects/{code}").json()["status"] == "validado"
    # liberar exige un expediente generado después de aprobar (sus documentos llevan el sello de aprobación)
    assert client.post(f"/api/projects/{code}/signoff", json={"stage": "liberacion", "by": "Jefe de taller"}).status_code == 409
    j3 = _dossier(client, code, "B")
    assert j3["status"] == "ok", j3
    man = json.loads((Path(j3["result"]["path"]) / "manifest.json").read_text(encoding="utf-8"))
    assert man["approval_state"] == "aprobado_tecnicamente" and man["status"].startswith("APROBADO TÉCNICAMENTE")
    r = client.post(f"/api/projects/{code}/signoff", json={"stage": "liberacion", "by": "Jefe de taller"})
    assert r.status_code == 200 and r.json()["state"] == "liberado_fabricacion", r.json()
    assert client.get(f"/api/projects/{code}").json()["status"] == "preparado_fabricacion"
    assert m2["structural"] == "CUMPLE"
