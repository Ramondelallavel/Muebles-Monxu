"""Familia estantería: geometría paramétrica, dimensionado, estabilidad/anclaje, asistente y expediente."""
import pytest
from fastapi.testclient import TestClient

from monxu.ai import assistant
from monxu.api import main
from monxu.cad.interference import check_interferences
from monxu.families import family, library
from monxu.pipeline import generate_dossier, regenerate
from monxu.storage.db import Store

BASE = {"ANCHURA": 1500, "PROFUNDIDAD": 600, "ALTURA": 2000, "NUMERO_NIVELES": 5}


def test_registered_in_library():
    lib = {f["id"]: f["status"] for f in library()}
    assert lib["estanteria"] == "implementada" and lib["mesa_industrial"] == "implementada"


def test_levels_geometry_and_no_interference():
    F = family("estanteria")
    m = F.build(F.new_params({**BASE, "CARGA_POR_NIVEL": 150}))
    trays = [i for i in m.instances if i.id.startswith("BAL.BANDEJA.")]
    assert len(trays) == 5
    tops = sorted(t.bbox[1][2] for t in trays)
    assert tops[0] == pytest.approx(150) and tops[-1] == pytest.approx(2000)
    assert tops[1] - tops[0] == pytest.approx((2000 - 150) / 4)
    assert len([i for i in m.instances if i.part.role == "montante"]) == 4
    assert check_interferences(m)["interferences"] == []
    lo, hi = trays[0].bbox
    assert hi[0] - lo[0] == pytest.approx(1500, abs=1e-6) and hi[1] - lo[1] == pytest.approx(600, abs=1e-6)


def test_more_levels_regenerates_structure():
    F = family("estanteria")
    a = F.build(F.new_params({**BASE, "NUMERO_NIVELES": 4}))
    b = F.build(F.new_params({**BASE, "NUMERO_NIVELES": 6}))
    count = lambda m: len([i for i in m.instances if i.id.startswith("BAL.BANDEJA.")])
    assert (count(a), count(b)) == (4, 6)
    assert len(b.joints) > len(a.joints)


def test_unanchored_tips_anchored_reports_anchor_tension():
    free = regenerate("estanteria", {**BASE, "CARGA_POR_NIVEL": 150, "ANCLAJE": "ninguno"})
    assert next(c for c in free.eng["checks"] if c["id"] == "E.VUELCO")["status"] == "NO_CUMPLE"
    anch = regenerate("estanteria", {**BASE, "CARGA_POR_NIVEL": 150, "ANCLAJE": "al_suelo"})
    c = next(c for c in anch.eng["checks"] if c["id"] == "E.ANCLAJE")
    assert c["status"] == "PENDIENTE" and c["value"] > 0
    assert anch.eng["status"] == "PENDIENTE" and anch.qa.result()["blocking"] == 0
    assert all(x["status"] != "NO_CUMPLE" for x in anch.eng["checks"])


def test_heavier_load_sizes_up():
    light = family("estanteria").build(family("estanteria").new_params({**BASE, "CARGA_POR_NIVEL": 80}))
    heavy = family("estanteria").build(family("estanteria").new_params({**BASE, "CARGA_POR_NIVEL": 400}))
    from monxu import catalog
    mass = lambda m: sum(catalog.profile(m.params.values[k]).props.A for k in
                         ("PERFIL_MONTANTE", "PERFIL_LARGUERO", "PERFIL_TRAVESANO"))
    assert mass(heavy) > mass(light) or heavy.params.values["ESPESOR_BALDA"] > light.params.values["ESPESOR_BALDA"] \
        or heavy.params.values["NUMERO_TRAVESANOS_BALDA"] > light.params.values["NUMERO_TRAVESANOS_BALDA"]
    assert heavy.params.sources["PERFIL_MONTANTE"] == "calculo"


def test_assistant_shelving_flow():
    r = assistant.handle(assistant.new_state(), "Quiero una estantería industrial de 2 metros de altura, 1.500 mm de "
                                                "ancho, 600 mm de profundidad y cinco niveles. Cada nivel debe soportar 150 kg")
    assert r["family_implemented"] and r["ready_to_generate"]
    assert {"ANCLAJE"} <= {q["param"] for q in r["questions"]}
    p = r["parameters"]
    assert (p["ANCHURA"], p["PROFUNDIDAD"], p["ALTURA"], p["NUMERO_NIVELES"], p["CARGA_POR_NIVEL"]) == \
        (1500, 600, 2000, 5, 150)
    assert all(k in {s.name for s in family("estanteria").param_specs()} for k in p)


@pytest.mark.slow
def test_shelving_dossier_via_api(tmp_path):
    main.set_store(Store(tmp_path))
    c = TestClient(main.app)
    p = c.post("/api/projects", json={"name": "Estantería almacén", "family": "estanteria",
                                      "template_id": "ES-1500-5"}).json()
    d = c.post(f"/api/projects/{p['code']}/design").json()["design"]
    assert d["qa"]["blocking"] == 0 and d["product_code"] == "ES1500-600-2000"
    r = regenerate("estanteria", {**BASE, "CARGA_POR_NIVEL": 150, "ANCLAJE": "al_suelo"})
    res = generate_dossier(r, {"code": "P-T", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    plano = next(i for i in res["qa"]["items"] if i["code"] == "PLANO-GEOMETRIA")
    assert plano["level"] == "ok" and "DIST_NIVEL" in str(res["verification"]) or plano["level"] == "ok"
