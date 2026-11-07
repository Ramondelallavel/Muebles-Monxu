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
    assert lib["carro_estanteria"] == "implementada" and lib["mesa_soldadura"] == "implementada"
    assert lib["estanteria_bateria"] == "implementada"
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


def test_rear_upstand_table():
    v = {"LONGITUD": 1500, "ANCHURA": 750, "ALTURA": 900, "CARGA_TOTAL": 150, "NUMERO_BALDAS": 1, "CARGA_BALDA": 50,
         "PETO_TRASERO": 100, "ANCLAJE": "al_suelo"}
    r = regenerate("mesa_industrial", v)
    m = r.model
    top = m.instance("ENC.BANDEJA")
    fl = {f.edge: f for f in top.part.spec.flanges}
    assert fl["y1"].direction == "up" and fl["y1"].height == pytest.approx(100 + top.part.spec.t) and not fl["y1"].holes
    assert all(fl[e].direction == "down" and fl[e].holes for e in ("y0", "x0", "x1"))
    assert top.bbox[1][2] == pytest.approx(1000, abs=1e-3)                 # el peto sube 100 mm sobre la encimera
    assert m.dims["envelope"]["zmax"] == pytest.approx(1000) and ("ALTURA_ENCIMERA", "ENC.BANDEJA", 900) in m.dims["levels"]
    # sin fijaciones en el borde del peto: el larguero trasero es una pieza sin taladros
    front, rear = m.instance("EST.LAR_SUP.D").part, m.instance("EST.LAR_SUP.T").part
    assert front.holes and not rear.holes and front.ref != rear.ref
    screws = [i for i in m.instances if i.group == "ENC" and i.part.role == "tornillo"]
    assert all(i.T[1, 3] < 750 - 1 for i in screws)
    assert r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0
    # sin peto todo sigue como antes: largueros iguales y la encimera plegada hacia abajo
    r0 = regenerate("mesa_industrial", {**v, "PETO_TRASERO": 0})
    assert r0.model.instance("EST.LAR_SUP.D").part is r0.model.instance("EST.LAR_SUP.T").part
    assert all(f.direction == "down" for f in r0.model.instance("ENC.BANDEJA").part.spec.flanges)


@pytest.mark.parametrize("mode,n_mont,handles,notches", [
    ("un_extremo", 2, ["EST.ASA"], ("x0y0", "x0y1")),
    ("dos_extremos", 4, ["EST.ASA", "EST.ASA_D"], ("x0y0", "x0y1", "x1y0", "x1y1")),
    ("ninguna", 0, [], ()),
])
def test_cart_handle_modes(mode, n_mont, handles, notches):
    r = regenerate("carro_taller", {**CT, "ASA_EMPUJE": mode})
    m = r.model
    assert sum(i.role == "montante" for i in m.instances) == n_mont
    assert sorted(i.id for i in m.instances if i.role == "asa") == handles
    assert tuple(m.instance("ENC.BANDEJA").part.spec.notch_corners) == notches if notches else not \
        m.instance("ENC.BANDEJA").part.spec.notch[0]
    wheels = {i.id: i.part.code for i in m.instances if i.part.role == "rueda"}
    assert sum(c.endswith("_FRENO") for c in wheels.values()) == 2
    zmax = m.dims["envelope"]["zmax"]
    assert zmax == pytest.approx(1000 if handles else 900)
    assert m.structure["product_word"] == ("mesa" if mode == "ninguna" else "carro")
    assert r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0


def test_assistant_mobile_table_and_upstand():
    r = assistant.handle(assistant.new_state(), "Mesa con ruedas de 1200x700x900, 120 kg, con peto trasero de 60 mm")
    st = r["state"]
    assert st["family"] == "carro_taller" and st["values"]["ASA_EMPUJE"] == "ninguna"
    assert st["values"]["PETO_TRASERO"] == 60 and not st["unsupported"]
    r2 = assistant.handle(assistant.new_state(), "Carro de taller 1200x700x900 con dos asas, 150 kg")
    assert r2["state"]["values"]["ASA_EMPUJE"] == "dos_extremos"


CE = {"ANCHURA": 1200, "PROFUNDIDAD": 600, "ALTURA": 1600, "NUMERO_NIVELES": 4, "ALTURA_PRIMER_NIVEL": 250,
      "CARGA_POR_NIVEL": 40, "ALTURA_ASA": 1000, "ASA_EMPUJE": "dos_extremos", "CARGA_HORIZONTAL": 60}


def test_shelving_cart():
    r = regenerate("carro_estanteria", CE)
    m = r.model
    assert m.product_code == "CE1200-600-1600"
    assert sum(i.id.startswith("BAL.BANDEJA.") for i in m.instances) == 4
    wheels = {i.id: i.part.code for i in m.instances if i.role == "rueda"}
    assert len(wheels) == 4 and all(c.endswith("_FRENO") == k.endswith((".DI", ".TI")) for k, c in wheels.items())
    assert m.params.values["RUEDA"].startswith("RUEDA_ESP_")
    assert sorted(i.id for i in m.instances if i.role == "asa") == ["EST.ASA", "EST.ASA_D"]
    assert m.instance("EST.ASA").axis[0][2] == pytest.approx(1000 - catalog.profile(m.params.values["PERFIL_ASA"]).H / 2)
    assert m.structure["push_height"] == 1000 and m.structure["product_word"] == "carro"
    vuelco = next(c for c in r.eng["checks"] if c["id"] == "E.VUELCO")
    assert vuelco["status"] == "CUMPLE" and "carro" in vuelco["description"]
    assert r.eng["status"] == "CUMPLE" and r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0


def test_shelving_cart_handle_clearance():
    r = regenerate("carro_estanteria", {**CE, "NUMERO_NIVELES": 3, "ALTURA": 1400, "ALTURA_PRIMER_NIVEL": 300,
                                        "ALTURA_ASA": 860, "ASA_EMPUJE": "un_extremo"})
    assert any(n["code"] == "GEO-ASA-NIVEL" for n in r.model.design_notes)
    assert r.qa.result()["blocking"] > 0


def test_assistant_shelving_cart():
    r = assistant.handle(assistant.new_state(), "Carro de picking de 4 niveles 1200x600x1600, 40 kg por nivel, "
                                                "con asa en los dos extremos")
    st = r["state"]
    assert st["family"] == "carro_estanteria" and not st["unsupported"]
    assert st["values"]["ASA_EMPUJE"] == "dos_extremos" and st["values"]["NUMERO_NIVELES"] == 4
    assert st["values"]["CARGA_POR_NIVEL"] == 40 and st["values"]["PROFUNDIDAD"] == 600


@pytest.mark.slow
def test_shelving_cart_dossier(tmp_path):
    r = regenerate("carro_estanteria", CE)
    res = generate_dossier(r, {"code": "P-CE", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    assert any(i["code"] == "EXP-STEP" and i["level"] == "ok" for i in res["qa"]["items"])
    assert any(i["code"] == "PLANO-GEOMETRIA" and i["level"] == "ok" for i in res["qa"]["items"])


def _tpl(fid, tid):
    from monxu.families import REGISTRY
    return next(t["values"] for t in REGISTRY[fid].templates() if t["id"] == tid)


def test_footrest_is_verified():
    r = regenerate("mesa_industrial", _tpl("mesa_industrial", "PT-1200-ERG"))
    m = r.model
    bar = m.instance("EST.REPOSAPIES")
    assert bar.role == "reposapies" and bar.axis[0][2] == pytest.approx(250 - bar.part.profile.H / 2)
    assert {j.id for j in m.joints} >= {"J.EST.REPOSAPIES.0", "J.EST.REPOSAPIES.1"}
    assert any(c["id"] == "F" for c in r.eng["load_cases"])
    chk = {c["id"]: c for c in r.eng["checks"]}
    assert chk["B.EST.REPOSAPIES"]["combination"] == "ELU-F" and chk["B.EST.REPOSAPIES"]["status"] == "CUMPLE"
    assert chk["D.EST.REPOSAPIES"]["combination"] == "ELS-F" and chk["D.EST.REPOSAPIES"]["status"] == "CUMPLE"
    assert r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0
    # balda a la altura por defecto (200 mm, chocaba con el reposapiés a 250): la regla de diseño la recoloca
    base = {"LONGITUD": 1500, "ANCHURA": 750, "ALTURA": 900, "CARGA_TOTAL": 150, "NUMERO_BALDAS": 1, "CARGA_BALDA": 50,
            "REPOSAPIES": 1, "ALTURA_REPOSAPIES": 250}
    r2 = regenerate("mesa_industrial", base)
    codes = {n["code"] for n in r2.model.design_notes}
    assert "REGLA-ALTURA_BALDA" in codes and "GEO-REPOSAPIES-BALDA" not in codes
    assert r2.model.params.sources["ALTURA_BALDA"] == "regla_diseno" and r2.model.params.values["ALTURA_BALDA"] != 200
    assert r2.interferences["interferences"] == [] and r2.qa.result()["blocking"] == 0
    # si el usuario fija la balda a esa altura, no se toca y el choque se señala como error de geometría
    r3 = regenerate("mesa_industrial", {**base, "ALTURA_BALDA": 230})
    assert any(n["code"] == "GEO-REPOSAPIES-BALDA" for n in r3.model.design_notes)
    assert r3.model.params.values["ALTURA_BALDA"] == 230


@pytest.mark.parametrize("tid", ["MI-1500-INOX", "MI-2400-PESADA"])
def test_plate_sizing_matches_final_check(tid):
    """El dimensionado de chapas usa el mismo peso propio y la misma carga puntual que la verificación final."""
    r = regenerate("mesa_industrial", _tpl("mesa_industrial", tid))
    bad = [c["id"] for c in r.eng["checks"] if c["id"].startswith("PL.") and c["status"] == "NO_CUMPLE"]
    assert bad == [] and r.eng["status"] != "NO_CUMPLE"


def test_assistant_footrest():
    r = assistant.handle(assistant.new_state(), "Puesto de trabajo 1200x700x850 con reposapiés a 220 mm, 100 kg")
    v = r["state"]["values"]
    assert v["REPOSAPIES"] == 1 and v["ALTURA_REPOSAPIES"] == 220


def test_flange_lower_than_bend_is_reported_not_crashing():
    """Pestaña más baja que radio + espesor: se genera la zona de pliegue y el DFM lo señala (antes, fallo de OCC)."""
    r = regenerate("mesa_industrial", {"LONGITUD": 1200, "ANCHURA": 700, "ALTURA": 900, "CARGA_TOTAL": 150,
                                       "NUMERO_BALDAS": 0, "ESPESOR_CHAPA": 6.0, "RADIO_PLEGADO": 16.0,
                                       "ALA_ENCIMERA": 22.0})
    codes = {i["code"] for i in r.qa.result()["items"] if i["level"] == "bloqueante"}
    assert "PLG-ALA-MIN" in codes


def test_welding_table():
    r = regenerate("mesa_soldadura", _tpl("mesa_soldadura", "MS-2000-28"))
    m, v = r.model, r.model.params.values
    plate = m.instance("ENC.PLACA")
    assert plate.part.kind == "pletina" and len(plate.part.holes) == 200 and plate.part.holes[0][2] == 28
    assert plate.part.finish is None                                       # la placa no se pinta
    assert 15 <= v["ESPESOR_PLACA"] <= 20                                  # mínimo constructivo D28 y láser d ≥ t
    assert plate.bbox[1][2] == pytest.approx(850, abs=1e-3)
    assert next(rw["value"] for rw in m.parameter_table() if rw["name"] == "EFICIENCIA_LIGAMENTO") == pytest.approx(0.72)
    chk = {c["id"]: c for c in r.eng["checks"]}
    assert "placa perforada" in chk["PL.encimera.S"]["description"] and chk["PL.encimera.P"]["status"] == "CUMPLE"
    welds = [j for j in m.joints if j.id.startswith("J.PLACA_SOLD.")]
    assert len(welds) == 4 and all(not j.weld["all_around"] for j in welds)
    assert not [i for i in m.instances if i.group == "ENC" and i.part.role in ("tornillo", "tuerca_remachable")]
    assert not m.instance("EST.LAR_SUP.D").part.holes                      # bastidor sin taladros de fijación
    assert r.eng["status"] == "CUMPLE" and r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0


def test_welding_plate_ligament_efficiency():
    """La retícula reduce rigidez y resistencia de la placa en (p − d)/p frente a una placa lisa."""
    base = {**_tpl("mesa_soldadura", "MS-1200-16"), "ESPESOR_PLACA": 15.0, "NUMERO_TRAVESANOS": 1}
    rs = {}
    for system in ("D16_P50", "ninguno"):
        r = regenerate("mesa_soldadura", {**base, "SISTEMA_TALADROS": system})
        rs[system] = {c["id"]: c["value"] for c in r.eng["checks"]}
    ratio = rs["D16_P50"]["PL.encimera.D"] / rs["ninguno"]["PL.encimera.D"]
    assert ratio > 1 / 0.68 * 0.9 and ratio < 1 / 0.68 * 1.1      # mismo panel, peso propio algo menor con taladros


def test_assistant_welding_table():
    r = assistant.handle(assistant.new_state(), "Mesa de soldadura 2000x1000x850 sistema 28, placa de 20 mm, 1000 kg")
    st = r["state"]
    assert st["family"] == "mesa_soldadura" and st["values"]["SISTEMA_TALADROS"] == "D28_P100"
    assert st["values"]["ESPESOR_PLACA"] == 20 and "ESPESOR_CHAPA" not in st["values"] and "PETO_TRASERO" not in st["values"]


def test_point_load_parsing_is_local():
    from monxu.ai.interpreter import parse
    p = parse("Mesa 1200x800x900, 500 kg y 150 kg puntual")
    assert p.values["CARGA_TOTAL"] == 500 and p.values["CARGA_PUNTUAL"] == 150


@pytest.mark.slow
def test_welding_table_dossier(tmp_path):
    r = regenerate("mesa_soldadura", _tpl("mesa_soldadura", "MS-1200-16"))
    res = generate_dossier(r, {"code": "P-MS", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    assert any(i["code"] == "EXP-STEP" and i["level"] == "ok" for i in res["qa"]["items"])


# ---------------------------------------------------------------------------------------------- estantería en batería
def test_battery_shelving_shares_uprights():
    r = regenerate("estanteria_bateria", _tpl("estanteria_bateria", "EB-2x900-6-ARCHIVO"))
    m = r.model
    N, n = 2, 6
    assert m.product_code == "EB2x900-400-2200"
    assert len([i for i in m.instances if i.part.role == "montante"]) == 2 * (N + 1)
    trays = [i for i in m.instances if i.part.role == "balda"]
    assert len(trays) == N * n and len({i.part.key for i in trays}) == 1          # todas las bandejas iguales
    a = catalog.profile(m.params.values["PERFIL_MONTANTE"]).B
    assert m.dims["ANCHURA_TOTAL"] == pytest.approx(N * 900 + a)
    assert len(m.structure["surfaces"]) == N * n and len(m.structure["supports"]) == 2 * (N + 1)
    # el montante intermedio recibe los travesaños laterales de los dos módulos en cada nivel
    onto_mid = [j for j in m.joints if j.id.startswith("J.EST.TRV_") and "EST.MONT.D1" in j.members]
    assert len(onto_mid) == 2 * n
    # pestañas laterales enfrentadas: sin taladros ni tornillos (no caben las cabezas en la junta de 1 mm)
    spec = trays[0].part.spec
    assert all(not f.holes for f in spec.flanges if f.edge in ("x0", "x1"))
    assert all(f.holes for f in spec.flanges if f.edge in ("y0", "y1"))
    assert r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0
    assert r.eng["status"] != "NO_CUMPLE"
    assert not [c for c in r.eng["checks"] if c["status"] == "NO_CUMPLE"]


def test_battery_upright_sized_for_two_crossbars():
    """Los dos travesaños laterales deben caber en el montante común: el dimensionado lo aumenta si es 'auto'."""
    v = {"NUMERO_MODULOS": 2, "ANCHURA": 800.0, "PROFUNDIDAD": 400.0, "ALTURA": 1000.0, "NUMERO_NIVELES": 2,
         "CARGA_POR_NIVEL": 40.0, "ANCLAJE": "al_suelo", "ESPESOR_BALDA": 3.0}
    f = family("estanteria_bateria")
    r = regenerate("estanteria_bateria", v)
    assert f.leg_fits(r.model.params.values) and catalog.profile(r.model.params.values["PERFIL_MONTANTE"]).B >= 60
    assert not any(n["code"] == "DFM-BATERIA-MONTANTE" for n in r.model.design_notes)
    r2 = regenerate("estanteria_bateria", {**v, "PERFIL_MONTANTE": "SHS 50x50x2"})
    assert any(i["code"] == "DFM-BATERIA-MONTANTE" and i["level"] == "bloqueante" for i in r2.qa.result()["items"])


def test_assistant_battery_shelving():
    from monxu.ai.interpreter import parse
    p = parse("Estantería en batería de tres módulos de 1000 mm, 500 de fondo y 2 m de alto, 5 niveles con 100 kg por "
              "bandeja, anclada al suelo")
    assert p.family == "estanteria_bateria"
    assert p.values == {"ANCHURA": 1000.0, "PROFUNDIDAD": 500.0, "ALTURA": 2000.0, "NUMERO_NIVELES": 5,
                        "NUMERO_MODULOS": 3, "CARGA_POR_NIVEL": 100.0, "ANCLAJE": "al_suelo"}
    p = parse("Batería de estanterías de 3 módulos, 3600 mm de frente total, 600 de fondo, 2000 de alto")
    assert p.values["NUMERO_MODULOS"] == 3 and p.values["ANCHURA"] == 1200 and p.values["PROFUNDIDAD"] == 600
    p = parse("Estantería en batería de 4 m de largo con módulos de 1 m, 400 de profundidad y seis niveles")
    assert p.values["NUMERO_MODULOS"] == 4 and p.values["ANCHURA"] == 1000 and p.values["NUMERO_NIVELES"] == 6
    # el fondo no se toma también como anchura de frente
    assert "ANCHURA" not in parse("estantería de 600 de fondo y 2000 de alto").values
    r = assistant.handle(assistant.new_state(), "Estantería en batería de 2 módulos de 900 mm, 400 de fondo, 2200 de alto")
    assert r["state"]["family"] == "estanteria_bateria" and r["family_implemented"]


@pytest.mark.slow
def test_battery_shelving_dossier(tmp_path):
    r = regenerate("estanteria_bateria", _tpl("estanteria_bateria", "EB-3x1000-5"))
    res = generate_dossier(r, {"code": "P-EB", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    assert any(i["code"] == "EXP-STEP" and i["level"] == "ok" for i in res["qa"]["items"])
    assert any(i["code"] == "PLANO-GEOMETRIA" and i["level"] == "ok" for i in res["qa"]["items"])
