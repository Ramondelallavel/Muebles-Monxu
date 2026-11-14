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
    assert lib["estanteria_bateria"] == "implementada" and lib["tarima"] == "implementada"
    assert lib["carro_plataforma"] == "implementada" and lib["armario"] == "implementada"
    assert lib["cantilever"] == "implementada" and lib["escalon"] == "implementada"


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


# ---------------------------------------------------------------------------------------------- tarima
def test_tarima_en_iso_14122_loads():
    r = regenerate("tarima", _tpl("tarima", "TA-1200x800-200"))
    m = r.model
    assert m.product_code == "TA1200-800-200" and r.eng["status"] == "CUMPLE"
    deck = m.instance("ENC.PLACA")
    assert deck.part.kind == "pletina" and deck.part.t in (3.0, 4.0, 5.0, 6.0, 8.0, 10.0)
    assert deck.T[2][3] == pytest.approx(200 - deck.part.t)                 # superficie a la altura pedida
    chk = {c["id"]: c for c in r.eng["checks"]}
    assert "200×200" in chk["PL.encimera.P"]["description"] and chk["PL.encimera.P"]["status"] == "CUMPLE"
    assert chk["PL.encimera.D"]["standard"].endswith("L/200")
    codes = {n["code"] for n in m.design_notes}
    assert "ERG-ANTIDESLIZANTE" in codes and "NORMA-14122-CARGA" not in codes       # 200 kg ≥ 2 kN/m² × 0,96 m²
    assert r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0
    assert {"MATERIAL_CHAPA", "NUMERO_BALDAS", "SISTEMA_TALADROS"}.isdisjoint(m.params.values)
    # carga por debajo de la de servicio de la norma: advertencia con el valor mínimo
    low = regenerate("tarima", {**_tpl("tarima", "TA-1200x800-200"), "CARGA_TOTAL": 100.0})
    msg = next(n["message"] for n in low.model.design_notes if n["code"] == "NORMA-14122-CARGA")
    assert "196 kg" in msg


def test_assistant_tarima():
    from monxu.ai.interpreter import parse
    p = parse("Necesito una tarima de 2000 x 1000 a 300 mm de altura para un operario, 2 kN/m2, anclada")
    assert p.family == "tarima"
    assert p.values == {"LONGITUD": 2000.0, "ANCHURA": 1000.0, "ALTURA": 300.0, "ANCLAJE": "al_suelo", "CARGA_TOTAL": 408.0}
    r = assistant.handle(assistant.new_state(), "tarima de 1200 x 800 x 200")
    # la carga repartida no se fija en la propuesta: el motor adopta la de EN ISO 14122-2 con las medidas finales
    assert r["family_implemented"] and r["ready_to_generate"] and "CARGA_TOTAL" not in r["parameters"]
    assert r["parameters"]["CARGA_PUNTUAL"] == 153.0 and "NUMERO_BALDAS" not in r["parameters"]
    a = next(x for x in r["assumptions"] if x["param"] == "CARGA_TOTAL")
    assert a["value"] == 200.0 and "EN ISO 14122-2" in a["text"]           # 2 kN/m² × 0,96 m², hacia arriba a 10 kg
    d = regenerate("tarima", r["parameters"])
    assert d.model.params.values["CARGA_TOTAL"] == 200.0 and d.model.params.sources["CARGA_TOTAL"] == "por_uso"
    assert d.eng["status"] == "CUMPLE"
    # sólo planta en cualquier familia: «1800 x 800» es largo × ancho
    assert parse("mesa de 1800 x 800 con 300 kg").values == {"LONGITUD": 1800.0, "ANCHURA": 800.0, "CARGA_TOTAL": 300.0}


def test_weld_nuts_match_the_structure_material():
    """Tuerca DIN 929 de acero soldada a placa base de aluminio o inoxidable: ahora del mismo material, y la regla de
    fabricación detecta uniones soldadas entre materiales incompatibles."""
    from monxu.core.model import StandardPart
    for mat, suffix in (("EN AW-6082 T6", "_AL"), ("1.4301", "_A2"), ("S235JRH", "")):
        r = regenerate("estanteria", {"ANCHURA": 1000, "PROFUNDIDAD": 400, "ALTURA": 1500, "NUMERO_NIVELES": 3,
                                      "MATERIAL_ESTRUCTURAL": mat,
                                      "MATERIAL_CHAPA": {"EN AW-6082 T6": "EN AW-5754 H22", "1.4301": "1.4301"}.get(mat, "S235JR")})
        nuts = {p.code for p in r.model.parts.values() if isinstance(p, StandardPart) and p.role == "tuerca_soldar"}
        assert nuts and all(c.endswith(suffix) if suffix else c[-3:] not in ("_AL", "_A2") for c in nuts), (mat, nuts)
        assert not [d for d in r.dfm if d["code"] in ("SOL-MATERIALES", "SOL-DISIMILAR")]
    # la mesa de soldadura y la tarima (placa de acero soldada) sólo admiten estructura de acero al carbono
    for fid in ("mesa_soldadura", "tarima"):
        mats = next(s.choices for s in family(fid).param_specs() if s.name == "MATERIAL_ESTRUCTURAL")
        assert mats and all(catalog.material(m).family == "acero_carbono" for m in mats)


def test_unnestable_part_still_gets_a_quotation():
    """Pieza mayor que cualquier formato de chapa: el anidado es inviable pero el presupuesto estima por superficie."""
    from monxu.manufacturing.optimization import best_format
    r = best_format([{"ref": "X", "w": 5000.0, "h": 2500.0, "qty": 2, "area": 5000.0 * 2500.0, "rotate": True}],
                    catalog.sheet_formats(), margin=10.0, spacing=8.0, kerf=0.3)
    assert not r["feasible"] and r["parts_area_m2"] == 25.0


@pytest.mark.slow
def test_tarima_dossier(tmp_path):
    r = regenerate("tarima", _tpl("tarima", "TA-2000x1000-300"))
    res = generate_dossier(r, {"code": "P-TA", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    assert any(i["code"] == "EXP-STEP" and i["level"] == "ok" for i in res["qa"]["items"])


# ------------------------------------------------------------------ carro plataforma
def _build(fid, values):
    from monxu.families import REGISTRY
    fam = REGISTRY[fid]
    ps = fam.new_params()
    ps.update(values, "usuario")
    return fam.build(ps)


@pytest.mark.parametrize("tid", [t["id"] for t in family("carro_plataforma").templates()])
def test_platform_templates_verify(tid):
    from monxu.engineering.analysis import analyze
    m = _build("carro_plataforma", _tpl("carro_plataforma", tid))
    assert not [n for n in m.design_notes if n["level"] == "error"]
    eng = analyze(m)
    assert eng["status"] == "CUMPLE", [c["id"] for c in eng["checks"] if c["status"] != "CUMPLE"]
    assert not any(n["code"] == "ERG-ALTURA" for n in m.design_notes)     # no hay puesto de trabajo bajo la plataforma
    assert "BAL" not in m.subassemblies and not any(i.part.role == "balda" for i in m.instances)


def test_platform_push_is_applied_at_the_handle():
    from monxu.engineering.analysis import analyze
    vals = {"LONGITUD": 1000, "ANCHURA": 600, "ALTURA": 300, "ALTURA_ASA": 950, "CARGA_TOTAL": 250,
            "CARGA_HORIZONTAL": 50}
    m = _build("carro_plataforma", vals)
    eng = analyze(m)
    st = next(c for c in eng["checks"] if c["id"] == "E.VUELCO")
    assert "del carro vacío" in st["description"] and "en el asa" in st["description"]
    assert st["value"] == pytest.approx(1.5 * 50 * 950 / 1e3, abs=0.01)        # γQ·H·h con h = altura del asa
    hx = next(c for c in eng["load_cases"] if c["id"] == "HX/HY")
    assert "asa" in hx["label"]
    sway = next(c for c in eng["checks"] if c["id"] == "S.ELS-3")
    assert sway["limit"] == pytest.approx(950 / 150, abs=1e-3)               # desplome referido a la altura del asa
    # sin asa: empuje en el plano de la plataforma
    eng2 = analyze(_build("carro_plataforma", {**vals, "ASA_EMPUJE": "ninguna"}))
    st2 = next(c for c in eng2["checks"] if c["id"] == "E.VUELCO")
    assert "de la plataforma vacía" in st2["description"] and st2["value"] == pytest.approx(1.5 * 50 * 300 / 1e3, abs=0.01)


def test_platform_height_rule_and_user_value():
    m = _build("carro_plataforma", {"LONGITUD": 1200, "ANCHURA": 800, "CARGA_TOTAL": 1000, "USO": "trabajo_pesado"})
    v, src = m.params.values, m.params.sources
    assert v["RUEDA"] == "RUEDA_ESP_M20_D200" and src["ALTURA"] == "regla_diseno" and v["ALTURA"] == 335.0
    assert any(n["code"] == "REGLA-ALTURA" for n in m.design_notes)
    assert not any(n["code"] == "GEO-PLATAFORMA-BAJA" for n in m.design_notes)
    # un valor del usuario no se cambia: se informa la altura mínima
    m2 = _build("carro_plataforma", {"LONGITUD": 1200, "ANCHURA": 800, "ALTURA": 280, "CARGA_TOTAL": 1000})
    assert m2.params.values["ALTURA"] == 280.0
    err = next(n for n in m2.design_notes if n["code"] == "GEO-PLATAFORMA-BAJA")
    assert "335 mm como mínimo" in err["message"]
    # por debajo de la placa base de la rueda la pata tendría longitud negativa: no se construye
    from monxu.core.params import ParamError
    with pytest.raises(ParamError, match="335 mm como mínimo"):
        _build("carro_plataforma", {"LONGITUD": 1200, "ANCHURA": 800, "ALTURA": 250, "CARGA_TOTAL": 1000})


def test_assistant_platform_and_lost_values():
    r = assistant.handle(assistant.new_state(), "carro plataforma de 1200x800 para 500 kg con asa a 950 mm y peto de 50 mm")
    assert r["family"] == "carro_plataforma" and r["ready_to_generate"]
    p = r["parameters"]
    assert p["LONGITUD"] == 1200 and p["ANCHURA"] == 800 and p["CARGA_TOTAL"] == 500
    assert p["ALTURA_ASA"] == 950 and p["PETO_TRASERO"] == 50 and "ALTURA" not in p
    # antes se perdían los datos interpretados que no estaban en una lista fija (asas, peto, reposapiés)
    r = assistant.handle(assistant.new_state(), "carro de taller 1000x600x900 con dos asas y peto de 60 mm, 150 kg, reposapies")
    p = r["parameters"]
    assert p["ASA_EMPUJE"] == "dos_extremos" and p["PETO_TRASERO"] == 60 and p["REPOSAPIES"] == 1
    # plataforma de trabajo para un operario: tarima (las ruedas no se generan)
    r = assistant.handle(assistant.new_state(), "plataforma de trabajo con ruedas para un operario 1500x800")
    assert r["family"] == "tarima"


@pytest.mark.parametrize("text,expected", [
    ("mesa 1800x800x900 400 kg en la encimera y 100 kg en la balda",
     {"ALTURA": 900.0, "CARGA_TOTAL": 400.0, "CARGA_BALDA": 100.0}),          # antes: 900.400 mm y kg
    ("mesa 1800x800x950 400 kg", {"ALTURA": 950.0, "CARGA_TOTAL": 400.0}),     # antes: 50.400 kg
    ("mesa de 1.500 x 800 x 900 con 1 500 kg", {"LONGITUD": 1500.0, "CARGA_TOTAL": 1500.0}),
    ("mesa 1800x800x900, 400 kg, balda de 100 kg", {"CARGA_TOTAL": 400.0, "CARGA_BALDA": 100.0}),
    ("mesa 1500x800x900 con balda de 80 kg y 200 kg en la encimera", {"CARGA_TOTAL": 200.0, "CARGA_BALDA": 80.0}),
    ("estanteria de 1500x600x2000 con 5 niveles de 100 kg", {"CARGA_POR_NIVEL": 100.0}),   # no 100 kg en total
    ("estanteria 1500x600x2000 5 baldas de 80 kg cada una", {"CARGA_POR_NIVEL": 80.0}),
    ("carro estanteria de 4 bandejas de 30 kg", {"NUMERO_NIVELES": 4, "CARGA_POR_NIVEL": 30.0}),
    ("plataforma con ruedas 1000x600, 300 kg, dos asas", {"LONGITUD": 1000.0, "ANCHURA": 600.0, "ASA_EMPUJE": "dos_extremos"}),
    ("plataforma rodante sin asa de 1200 x 800, 400 kg", {"LONGITUD": 1200.0, "ASA_EMPUJE": "ninguna"}),
])
def test_interpreter_numbers_and_loads(text, expected):
    from monxu.ai.interpreter import parse
    it = parse(text)
    for k, v in expected.items():
        assert it.values.get(k) == v, (k, it.values)
    if "sin asa" in text:
        assert "ALTURA_ASA" not in it.values


@pytest.mark.slow
def test_platform_dossier(tmp_path):
    r = regenerate("carro_plataforma", _tpl("carro_plataforma", "CP-1200x800-500"))
    res = generate_dossier(r, {"code": "P-CP", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    assert any(i["code"] == "EXP-STEP" and i["level"] == "ok" for i in res["qa"]["items"])


# ------------------------------------------------------------------ armario
@pytest.mark.parametrize("tid", [t["id"] for t in family("armario").templates()])
def test_cabinet_templates_verify(tid):
    from monxu.engineering.analysis import analyze
    m = _build("armario", _tpl("armario", tid))
    assert not [n for n in m.design_notes if n["level"] == "error"]
    eng = analyze(m)
    assert eng["status"] in ("CUMPLE", "PENDIENTE"), [c["id"] for c in eng["checks"] if c["status"] == "NO_CUMPLE"]
    assert not any(c["status"] == "NO_CUMPLE" for c in eng["checks"])


def test_cabinet_enclosure_doors_and_masses():
    from monxu.engineering.analysis import analyze
    m = _build("armario", {"ANCHURA": 1000, "PROFUNDIDAD": 500, "ALTURA": 1950, "NUMERO_NIVELES": 5, "CARGA_POR_NIVEL": 60})
    ids = {i.id for i in m.instances}
    assert {"PAN.LATERAL_I", "PAN.LATERAL_D", "PAN.FONDO", "PUE.PUERTA_I", "PUE.PUERTA_D"} <= ids
    assert m.instance("PAN.LATERAL_I").part is m.instance("PAN.LATERAL_D").part          # mismo lateral a los dos lados
    assert m.ctx.derived["N_PUERTAS"].value == 2 and m.ctx.derived["BISAGRAS_POR_PUERTA"].value == 4
    hinges = [i for i in m.instances if i.part.role == "bisagra"]
    assert len(hinges) == 8 and sum(i.part.role == "cerradura" for i in m.instances) == 1
    # chapa DC01 por defecto: paneles y puertas de 1 mm; el S235JR no existe en 1 mm
    assert m.instance("PAN.FONDO").part.t == 1.0 and m.instance("PUE.PUERTA_I").part.spec.t == 1.0
    # los paneles alojan las cabezas de los tornillos de las bandejas (taladros mayores que los de fijación)
    side = m.instance("PAN.LATERAL_I").part
    assert {d for _, _, d in side.holes} == {6.6, 12.5}
    # paneles, puertas y herrajes cuelgan de los montantes: el peso propio del cálculo los incluye
    am = m.structure["attached_masses"]
    enc = sum(i.part.mass for i in m.instances if i.group in ("PUE",) and i.part.role in ("puerta", "bisagra", "cerradura"))
    enc += sum(i.part.mass for i in m.instances if i.id in ("PAN.LATERAL_I", "PAN.LATERAL_D", "PAN.FONDO"))
    assert sum(a["mass_kg"] for a in am) == pytest.approx(enc, rel=1e-6)
    eng = analyze(m)
    st = next(c for c in eng["checks"] if c["id"] in ("E.VUELCO", "E.ANCLAJE"))
    assert "armario" in st["description"] or st["id"] == "E.ANCLAJE"
    # envolvente: laterales y fondo por fuera de los montantes y puertas superpuestas al frente
    assert m.dims["envelope"]["dx"] == pytest.approx(1000 + 2 * (1.5 + 1.0))
    assert m.dims["envelope"]["dy"] == pytest.approx(500 + 1.5 + 1.0 + 25.0)


@pytest.mark.parametrize("width,doors", [(600, 1), (601, 2), (1200, 2)])
def test_cabinet_auto_door_count(width, doors):
    m = _build("armario", {"ANCHURA": width, "PROFUNDIDAD": 450, "ALTURA": 1200, "NUMERO_NIVELES": 3})
    assert m.ctx.derived["N_PUERTAS"].value == doors
    assert sum(i.part.role == "puerta" for i in m.instances) == doors


def test_cabinet_without_doors_and_single_door_asymmetry():
    m = _build("armario", {"ANCHURA": 800, "PROFUNDIDAD": 400, "ALTURA": 1500, "NUMERO_NIVELES": 4, "NUMERO_PUERTAS": 0})
    assert not any(i.group == "PUE" for i in m.instances)
    assert m.dims["envelope"]["dy"] == pytest.approx(400 + 1.5 + 1.0)


def test_assistant_cabinet():
    r = assistant.handle(assistant.new_state(), "armario de 1000x500x1950 con 4 baldas de 50 kg y dos puertas")
    assert r["family"] == "armario" and r["family_implemented"] and r["ready_to_generate"]
    p = r["parameters"]
    assert p["NUMERO_NIVELES"] == 6 and p["NUMERO_PUERTAS"] == 2 and p["CARGA_POR_NIVEL"] == 50
    r = assistant.handle(assistant.new_state(), "mesa con armario inferior 1500x700x900")
    assert r["family"] == "mesa_industrial"


@pytest.mark.slow
def test_cabinet_dossier(tmp_path):
    r = regenerate("armario", _tpl("armario", "AR-1000x500-1950"))
    assert r.interferences["interferences"] == []
    res = generate_dossier(r, {"code": "P-AR", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    assert any(i["code"] == "EXP-STEP" and i["level"] == "ok" for i in res["qa"]["items"])


def test_crossbeams_that_do_not_fit_are_reported():
    """Travesaños intermedios elegidos a mano que se solapan: antes se generaban sin aviso (interferencias)."""
    import re
    vals = {"ANCHURA": 1000, "PROFUNDIDAD": 500, "ALTURA": 1800, "NUMERO_NIVELES": 4, "PERFIL_TRAVESANO": "SHS 100x100x3",
            "NUMERO_TRAVESANOS_BALDA": 10}
    m = _build("estanteria", vals)
    errs = [n for n in m.design_notes if n["code"] == "DFM-TRAVESANOS"]
    assert len(errs) == 1 and errs[0]["level"] == "error"           # una sola nota aunque haya cuatro niveles
    n_max = int(re.search(r"como máximo (\d+)", errs[0]["message"]).group(1))
    assert 0 < n_max < 10
    m2 = _build("estanteria", {**vals, "NUMERO_TRAVESANOS_BALDA": n_max})
    assert not any(n["code"] == "DFM-TRAVESANOS" for n in m2.design_notes)


def test_hot_dip_galvanizing_asks_for_vent_holes():
    from monxu.manufacturing.plan import dfm_check, manufacturing_plan
    m = _build("mesa_industrial", {"LONGITUD": 1500, "ANCHURA": 700, "ALTURA": 900, "CARGA_TOTAL": 200,
                                   "ACABADO": "GALVANIZADO", "ENTORNO": "exterior"})
    dfm = dfm_check(m, manufacturing_plan(m))
    assert any(f["code"] == "GAL-VENTEO" and f["level"] == "advertencia" for f in dfm)
    m2 = _build("mesa_industrial", {"LONGITUD": 1500, "ANCHURA": 700, "ALTURA": 900, "CARGA_TOTAL": 200})
    assert not any(f["code"] == "GAL-VENTEO" for f in dfm_check(m2, manufacturing_plan(m2)))


def test_workstation_shelf_too_shallow_for_its_frame_is_rejected():
    """Brazos del estante de longitud negativa (sólidos abiertos): ahora se rechaza con el fondo mínimo."""
    from monxu.core.params import ParamError
    vals = {"ESTANTE_SUPERIOR": 1, "PROFUNDIDAD_ESTANTE": 177, "PERFIL_ALTILLO": "SHS 120x120x4", "PERFIL_PATA": "SHS 70x70x3",
            "ALTURA_ESTANTE": 1600}
    with pytest.raises(ParamError, match="Fondo de estante 177 mm insuficiente"):
        _build("puesto_trabajo", vals)


def test_verified_corrections_for_fixed_values():
    """Diseños que no cumplen o no se pueden construir por valores fijados: se ofrece la corrección mínima, ya
    regenerada y verificada (sólo si con ella el diseño CUMPLE sin errores)."""
    # primer nivel demasiado bajo para su bastidor (fijado por el usuario): la altura válida más próxima
    v = {"ANCHURA": 1600, "PROFUNDIDAD": 750, "ALTURA": 1600, "NUMERO_NIVELES": 4, "ALTURA_PRIMER_NIVEL": 250,
         "ASA_EMPUJE": "un_extremo", "ALTURA_ASA": 900, "CARGA_HORIZONTAL": 60, "MATERIAL_ESTRUCTURAL": "EN AW-6082 T6",
         "MATERIAL_CHAPA": "EN AW-5754 H22", "ACABADO": "ANODIZADO_NATURAL"}
    d = regenerate("carro_estanteria", v, {k: "usuario" for k in v})
    assert any(n["code"] == "GEO-NIVEL-BAJO" for n in d.model.design_notes)
    assert d.fix and d.fix["params"] == {"ALTURA_PRIMER_NIVEL": 260.0} and d.fix["status"] == "CUMPLE"
    ok = regenerate("carro_estanteria", {**v, **d.fix["params"]})
    assert ok.eng["status"] == "CUMPLE" and not [n for n in ok.model.design_notes if n["level"] == "error"]
    # tarima más baja que su pie y su bastidor
    t = {"LONGITUD": 2100, "ANCHURA": 1300, "ALTURA": 150, "CARGA_TOTAL": 1391, "CARGA_PUNTUAL": 153,
         "ANCLAJE": "ninguno", "CARGA_HORIZONTAL": 100}
    d = regenerate("tarima", t, {k: "usuario" for k in t})
    assert d.fix and d.fix["params"] == {"ALTURA": 155.0}
    # mesa con chapa DC01 que no resiste la carga puntual: chapa S235JR con espesor por cálculo
    m = {"LONGITUD": 2100, "ANCHURA": 1150, "ALTURA": 1000, "CARGA_TOTAL": 400, "NUMERO_BALDAS": 0, "CARGA_PUNTUAL": 100,
         "ANCLAJE": "al_suelo", "MATERIAL_CHAPA": "DC01"}
    d = regenerate("mesa_industrial", m, {k: "usuario" for k in m})
    assert d.eng["status"] == "NO_CUMPLE" and d.fix["params"]["MATERIAL_CHAPA"] == "S235JR"
    # sin nada fijado que corregir no se ofrece nada
    assert regenerate("mesa_industrial", {}).fix is None


# ------------------------------------------------------------------ estantería cantilever
@pytest.mark.parametrize("tid", [t["id"] for t in family("cantilever").templates()])
def test_cantilever_templates_verify(tid):
    from monxu.engineering.analysis import analyze
    m = _build("cantilever", _tpl("cantilever", tid))
    assert not [n for n in m.design_notes if n["level"] == "error"]
    eng = analyze(m)
    assert eng["status"] == "CUMPLE", [c["id"] for c in eng["checks"] if c["status"] != "CUMPLE"]
    ids = {c["id"] for c in eng["checks"]}
    arms = m.structure["cantilevers"]
    assert arms and all(f"D.{a}" in ids for a in arms)          # flecha en punta de cada brazo
    assert "S.ELS-G" in ids                                     # desplome de las columnas bajo la carga vertical
    # la carga de los brazos es la indicada: suma de las fuerzas del caso Q = brazos × carga × g
    q = m.params.values["CARGA_POR_BRAZO"]
    case = next(c for c in eng["load_cases"] if c["id"] == "Q_CARGA_POR_BRAZO")
    assert case["total_N"] == pytest.approx(len(arms) * q * 9.81, rel=1e-6)


def test_cantilever_geometry_and_double_sided_load_pattern():
    from monxu.engineering.analysis import analyze
    vals = _tpl("cantilever", "CV-3-2500-800-DOBLE")
    m = _build("cantilever", vals)
    assert m.product_code == "CV3-2500-800-D"
    cols = [i for i in m.instances if i.role == "montante"]
    arms = [i for i in m.instances if i.role == "brazo"]
    assert len(cols) == 3 and len(arms) == 3 * 4 * 2
    # brazos de 800 mm desde la cara de la columna y base simétrica a dos caras
    col_h = cols[0].part.profile.H
    yc = cols[0].axis[0][1]
    for a in arms:
        assert a.part.length == 800.0
        assert abs(abs(a.axis[0][1] - yc) - col_h / 2) < 1e-6
    base = m.instance("EST.BASE.C1")
    assert base.axis[1][1] - yc == pytest.approx(yc - base.axis[0][1])
    # el último nivel deja el tope enrasado con la cabeza de la columna
    assert m.dims["levels"][-1][2] == pytest.approx(2500 - 60)
    eng = analyze(m)
    assert "ELU-QA" in eng["combinations"]["ELU"] and "ELS-QA" in eng["combinations"]["ELS"]
    qa = next(c for c in eng["load_cases"] if c["id"] == "QA")
    assert qa["total_N"] == pytest.approx(len(arms) / 2 * 200 * 9.81, rel=1e-6)
    r = regenerate("cantilever", vals)
    assert r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0
    assert not any(i["code"] == "SOL-TUERCA" for i in r.dfm)
    # el enrase ya no es un texto genérico: solo aparece si la geometría tiene caras enrasadas, con su número
    from monxu.manufacturing.plan import weld_face_conditions
    assert any(i["code"] == "SOL-ENRASE" for i in r.dfm) == (weld_face_conditions(r.model)["flush"] > 0)


def test_cantilever_base_follows_the_column_and_fixed_weak_arm_fails():
    """La base 'auto' nunca es más estrecha que la columna; un brazo fijado demasiado débil no cumple y se ofrece la
    corrección comprobada (devolverlo a 'auto')."""
    from monxu import catalog
    m = _build("cantilever", {"CARGA_POR_BRAZO": 300, "LONGITUD_BRAZO": 1000})
    v = m.params.values
    assert catalog.profile(v["PERFIL_BASE"]).B >= catalog.profile(v["PERFIL_COLUMNA"]).B
    r = regenerate("cantilever", {"CARGA_POR_BRAZO": 300, "LONGITUD_BRAZO": 1000, "PERFIL_BRAZO": "RHS 40x20x2",
                                  "ANCLAJE": "al_suelo"})
    assert r.eng["status"] == "NO_CUMPLE"
    assert r.fix and r.fix["params"].get("PERFIL_BRAZO") == "auto" and r.fix["status"] == "CUMPLE"


def test_anchor_tension_with_many_supports():
    """Tracción del taco más cargado con giro rígido alrededor de la arista de vuelco (T_i = M·d_i/Σd²): con cuatro
    esquinas es M/(2·base), como antes; con tres líneas de apoyos la del extremo lleva M·L/(L² + (L/2)²)/2."""
    from monxu.engineering.analysis import overturning

    class FakeModel:
        def __init__(self, pts):
            self.structure = {"supports": [{"point": p} for p in pts], "worktop_height": 1000.0}
            self.instances = []

    import monxu.engineering.analysis as A
    W = 1000.0
    orig = A.own_weight
    try:
        A.own_weight = lambda m: (W, __import__("numpy").array([500.0, 250.0, 300.0]))
        four = FakeModel([(0, 0, 0), (1000, 0, 0), (0, 500, 0), (1000, 500, 0)])
        ov = overturning(four, {"CARGA_HORIZONTAL": 2000.0})
        pf = catalog.criteria()["partial_factors"]
        Mnet = pf["gamma_Q_dst"] * 2000.0 * 1000.0 - pf["gamma_G_stb"] * W * 250.0      # vuelco en Y (brazo 250)
        assert ov["dirn_T"] in ("+Y", "-Y") and ov["T_per"] == pytest.approx(Mnet / (2 * 500.0))
        six = FakeModel([(x, y, 0) for x in (0, 500, 1000) for y in (0, 2000)])
        ov = overturning(six, {"CARGA_HORIZONTAL": 2000.0})
        Mnet = pf["gamma_Q_dst"] * 2000.0 * 1000.0 - pf["gamma_G_stb"] * W * 500.0       # vuelco en X (brazo 500)
        assert ov["dirn_T"] in ("+X", "-X")
        assert ov["T_per"] == pytest.approx(Mnet * 1000.0 / (2 * (1000.0 ** 2 + 500.0 ** 2)))
        assert ov["n_anchor"] == 4
    finally:
        A.own_weight = orig


def test_assistant_cantilever():
    r = assistant.handle(assistant.new_state(), "Necesito un portabarras de 3000 x 600 x 2000 con 4 niveles y 1200 kg en "
                                                "total, anclado")
    assert r["family"] == "cantilever" and r["family_implemented"]
    p = r["parameters"]
    assert p["NUMERO_COLUMNAS"] == 4 and p["SEPARACION_COLUMNAS"] == 970.0 and p["LONGITUD_BRAZO"] == 600.0
    assert p["CARGA_POR_BRAZO"] == 75.0 and p["ANCLAJE"] == "al_suelo" and p["PERFIL_BRAZO"] == "auto"
    r = assistant.handle(assistant.new_state(), "estantería cantilever con brazos de 800 a dos caras")
    assert r["parameters"]["CARAS"] == "dos" and r["parameters"]["LONGITUD_BRAZO"] == 800.0
    # sin carga indicada: el asistente adopta la de uso (250 kg por metro de brazo) y lo dice
    a = next(x for x in r["assumptions"] if x["param"] == "CARGA_POR_BRAZO")
    assert a["value"] == 200.0 and "250 kg por metro" in a["text"]


@pytest.mark.slow
def test_cantilever_dossier(tmp_path):
    r = regenerate("cantilever", _tpl("cantilever", "CV-3-2000-600"))
    res = generate_dossier(r, {"code": "P-CV", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    items = {i["code"]: i for i in res["qa"]["items"]}
    assert items["EXP-STEP"]["level"] == "ok" and items["PLANO-GEOMETRIA"]["level"] == "ok"


# ------------------------------------------------------------------ escalón de acceso
@pytest.mark.parametrize("tid", [t["id"] for t in family("escalon").templates()])
def test_step_templates_verify(tid):
    from monxu.engineering.analysis import analyze
    m = _build("escalon", _tpl("escalon", tid))
    assert not [n for n in m.design_notes if n["level"] == "error"]
    eng = analyze(m)
    assert eng["status"] == "CUMPLE", [c["id"] for c in eng["checks"] if c["status"] != "CUMPLE"]
    ids = {c["id"] for c in eng["checks"]}
    for s in m.structure["surfaces"]:          # cada peldaño y la meseta: chapa con carga repartida y concentrada
        assert {f"PL.{s['id']}.S", f"PL.{s['id']}.D", f"PL.{s['id']}.P"} <= ids


def test_step_geometry_follows_en_iso_14122_3():
    from monxu.families.escalon import going, risers
    assert risers(400, "auto") == 2 and risers(500, "auto") == 3 and risers(250, "auto") == 1
    assert going(200, "auto") == 230 and going(500 / 3, "auto") == 295
    m = _build("escalon", _tpl("escalon", "EA-1000-500"))
    assert m.product_code == "EA1000-500-3"
    plates = sorted((i for i in m.instances if i.group == "PEL"), key=lambda i: i.T[2][3])
    h = 500 / 3
    t = plates[0].part.t
    # peldaños a h, 2h y meseta a 3h; huella 295 mm visible en cada peldaño y meseta de 800 mm
    assert [round(i.T[2][3] + t, 6) for i in plates] == [round(k * h, 6) for k in (1, 2, 3)]
    assert [i.part.h for i in plates] == [295.0, 295.0, 800.0]
    assert plates[1].T[1][3] - plates[0].T[1][3] == pytest.approx(295.0)
    assert m.dims["FONDO"] == pytest.approx(2 * 295 + 800)
    # todas las líneas de patas llevan pie nivelador
    assert len([i for i in m.instances if i.part.role == "pie_nivelador"]) == 2 * 4
    r = regenerate("escalon", _tpl("escalon", "EA-1000-500"))
    assert r.interferences["interferences"] == [] and r.qa.result()["blocking"] == 0
    codes = {n["code"] for n in m.design_notes}
    assert "ERG-ANTIDESLIZANTE" in codes and "NORMA-14122-CONTRAHUELLA" not in codes and "NORMA-14122-PASO" not in codes


def test_step_shared_sheet_thickness_is_the_largest():
    """Un único espesor de chapa para peldaños y meseta: el mayor de los que pide cada superficie, y la meseta se
    recalcula con él (sus travesaños y su propuesta corresponden al espesor final)."""
    m = _build("escalon", {"ANCHURA": 1200.0, "ALTURA": 450.0, "FONDO_MESETA": 1000.0, "CARGA_PUNTUAL": 250.0})
    t = m.params.values["ESPESOR_PLACA"]
    assert {i.part.t for i in m.instances if i.group == "PEL"} == {t}
    props = {n["code"]: n["message"] for n in m.design_notes if n["code"].startswith("DIM-")}
    assert f"chapa de {t:g} mm" in props["DIM-MESETA"] and f"chapa de {t:g} mm" in props["DIM-PELDANO_1"]


def test_step_rules_and_warnings():
    m = _build("escalon", {"ALTURA": 480.0, "NUMERO_PELDANOS": 1})
    assert any(n["code"] == "NORMA-14122-CONTRAHUELLA" for n in m.design_notes)
    m = _build("escalon", {"ALTURA": 400.0, "HUELLA": 350.0})
    assert any(n["code"] == "NORMA-14122-PASO" for n in m.design_notes)
    with pytest.raises(Exception):
        _build("escalon", {"ALTURA": 400.0, "FONDO_MESETA": 300.0, "HUELLA": 350.0})     # meseta más corta que la huella


def test_assistant_step():
    r = assistant.handle(assistant.new_state(), "Necesito un escalón de acceso de 800 x 1000 x 400 para subir a una máquina")
    assert r["family"] == "escalon" and r["family_implemented"]
    p = r["parameters"]
    assert p["ANCHURA"] == 800.0 and p["ALTURA"] == 400.0 and p["FONDO_MESETA"] == 770.0 and p["ESPESOR_PLACA"] == "auto"
    r = assistant.handle(assistant.new_state(), "peldaño de acceso de 600 de ancho a 250 mm, 150 kg")
    assert r["parameters"]["ALTURA"] == 250.0 and r["parameters"]["CARGA_PUNTUAL"] == 150.0


@pytest.mark.slow
def test_step_dossier(tmp_path):
    r = regenerate("escalon", _tpl("escalon", "EA-800-400"))
    res = generate_dossier(r, {"code": "P-EA", "revision": "A"}, tmp_path / "exp")
    assert res["qa"]["blocking"] == 0
    items = {i["code"]: i for i in res["qa"]["items"]}
    assert items["EXP-STEP"]["level"] == "ok" and items["PLANO-GEOMETRIA"]["level"] == "ok"
