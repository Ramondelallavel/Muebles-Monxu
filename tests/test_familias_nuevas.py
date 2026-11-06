"""Familias puesto de trabajo y carro de taller: geometría, cálculo, apoyos, asistente y expediente."""
import pytest

from monxu import catalog
from monxu.ai import assistant
from monxu.cad.sheetmetal import FlangeSpec, SheetMetalSpec
from monxu.families import family, library
from monxu.pipeline import generate_dossier, regenerate

PT = {"LONGITUD": 1500, "ANCHURA": 750, "ALTURA": 900, "ALTURA_TOTAL": 1800, "CARGA_TOTAL": 200, "NUMERO_BALDAS": 1,
      "CARGA_BALDA": 80, "CARGA_ESTANTE": 40, "ANCLAJE": "al_suelo"}
CT = {"LONGITUD": 1000, "ANCHURA": 600, "ALTURA": 900, "CARGA_TOTAL": 100, "NUMERO_BALDAS": 1, "CARGA_BALDA": 80,
      "CARGA_HORIZONTAL": 80}


def test_registered_and_implemented():
    lib = {f["id"]: f["status"] for f in library()}
    assert lib["puesto_trabajo"] == "implementada" and lib["carro_taller"] == "implementada"
    assert lib["armario"] == "en_desarrollo"


def test_notch_only_in_selected_corners():
    fl = tuple(FlangeSpec(e, 30, "down") for e in ("x0", "x1", "y0", "y1"))
    s = SheetMetalSpec(1000, 600, 2, 2, 0.4, fl, notch=(50, 50), notch_corners=("x0y1", "x1y1"))
    assert s.base_region().area == pytest.approx((1000 - 8) * (600 - 8) - 2 * (50 - 4) ** 2)
    assert s.flange_extent("y0") == (4, 996) and s.flange_extent("y1") == (50, 950)
    assert s.flange_extent("x0") == (4, 550)


def test_workstation_superstructure():
    r = regenerate("puesto_trabajo", PT)
    m = r.model
    assert m.product_code == "PT1500-750-900"
    rear = [i for i in m.instances if i.part.role == "montante"]
    assert len(rear) == 2 and all(i.axis[1][2] == pytest.approx(1800) for i in rear)
    assert "ALTO" in m.structure["levels"] and any(s["id"] == "estante" for s in m.structure["surfaces"])
    panel = m.instance("PAN.PANEL")
    holes = [h for h in panel.part.spec.holes if h[0] == "rect"]
    assert len(holes) > 100                                       # perforación 10x10 a paso 38
    assert m.structure["attached_masses"] and r.interferences["interferences"] == []
    assert r.qa.result()["blocking"] == 0
    top = m.instance("ENC.BANDEJA").part.spec
    assert top.notch_corners == ("x0y1", "x1y1")
    # el estante superior se verifica como placa con su carga
    assert {"PL.estante.S", "PL.estante.D"} <= {c["id"] for c in r.eng["checks"]}


def test_cart_castors_and_handle():
    r = regenerate("carro_taller", CT)
    m = r.model
    assert m.product_code == "CT1000-600-900"
    wheels = {i.id: i.part.code for i in m.instances if i.part.role == "rueda"}
    assert len(wheels) == 4
    assert all(c.endswith("_FRENO") for k, c in wheels.items() if k.endswith((".DI", ".TI")))
    assert not any(c.endswith("_FRENO") for k, c in wheels.items() if k.endswith((".DD", ".TD")))
    assert m.params.values["RUEDA"].startswith("RUEDA_ESP_")            # seleccionada por cálculo
    pies = next(c for c in r.eng["checks"] if c["id"] == "A.PIES")
    cap = catalog.component(m.params.values["RUEDA"])["rated_load_kg"] * 9.81
    assert pies["element"] == "Ruedas" and pies["limit"] == pytest.approx(cap, rel=1e-6) and pies["utilization"] <= 1
    assert m.instance("EST.ASA").axis[0][2] == pytest.approx(1000 - catalog.profile(m.params.values["PERFIL_ASA"]).H / 2)
    assert r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0
    assert r.eng["status"] == "CUMPLE"


def test_assistant_recognises_new_families():
    s = assistant.new_state()
    r = assistant.handle(s, "Puesto de trabajo de 1600x750x900 con estante superior y panel perforado, 200 kg")
    assert r["state"]["family"] == "puesto_trabajo" and not r["state"]["unsupported"]
    r2 = assistant.handle(assistant.new_state(), "Carro de taller 1000x600x900 con ruedas, 100 kg")
    assert r2["state"]["family"] == "carro_taller" and not r2["state"]["unsupported"]
    assert any(q["param"] == "CARGA_HORIZONTAL" and "maniobra" in q["question"] for q in r2["questions"])


@pytest.mark.slow
def test_cart_dossier(tmp_path):
    r = regenerate("carro_taller", CT)
    res = generate_dossier(r, {"code": "P-CT", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    assert any(i["code"] == "EXP-STEP" and i["level"] == "ok" for i in res["qa"]["items"])
