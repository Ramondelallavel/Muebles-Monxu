"""Fallos encontrados por el barrido realista (sólo datos de usuario, el resto 'auto') y corregidos."""
from monxu import catalog
from monxu.families import family
from monxu.pipeline import regenerate

ALU = {"MATERIAL_ESTRUCTURAL": "EN AW-6082 T6", "MATERIAL_CHAPA": "EN AW-5754 H22", "ACABADO": "ANODIZADO_NATURAL"}


def _blocking(r):
    return [i["code"] for i in r.qa.result()["items"] if i["level"] == "bloqueante"]


def test_point_load_alone_sizes_the_top():
    """Sólo carga puntual sobre la encimera: antes la chapa no se dimensionaba y PL.encimera.P no se cumplía."""
    r = regenerate("mesa_industrial", {"LONGITUD": 1200, "ANCHURA": 1150, "ALTURA": 1000, "NUMERO_BALDAS": 0,
                                       "CARGA_PUNTUAL": 100, "USO": "inspeccion"})
    assert r.model.params.sources["ESPESOR_CHAPA"] == "calculo"
    assert not [c["id"] for c in r.eng["checks"] if c["status"] == "NO_CUMPLE" and c["id"].startswith("PL.")]


def test_sway_sizes_the_weaker_portal_member():
    """Mesa de aluminio con empuje de 300 N: el desplome en Y lo gobiernan los travesaños, no la pata. Antes se
    agotaba la serie de patas (SHS 120x120x5) sin verificar; ahora basta un travesaño mayor."""
    r = regenerate("mesa_industrial", {"LONGITUD": 1100, "ANCHURA": 800, "ALTURA": 900, "NUMERO_BALDAS": 0,
                                       "CARGA_HORIZONTAL": 300, "ANCLAJE": "al_suelo", "PETO_TRASERO": 100,
                                       "REPOSAPIES": 1, "ALTURA_REPOSAPIES": 300, **ALU})
    v = r.model.params.values
    assert "DIM-PERFILES" not in _blocking(r)
    assert not [c for c in r.eng["checks"] if c["id"].startswith("S.") and c["status"] == "NO_CUMPLE"]
    assert catalog.profile(v["PERFIL_PATA"]).B <= 60 and v["PERFIL_TRAVESANO"] != "RHS 40x20x2"


def test_lower_frame_inset_fits_the_leg():
    """Balda de aluminio: el bastidor inferior retranqueado para la pestaña debe caber en la pata (antes sólo se
    comparaba el ancho del perfil: DFM-BASTIDOR-INF)."""
    r = regenerate("mesa_industrial", {"LONGITUD": 1500, "ANCHURA": 750, "ALTURA": 900, "CARGA_TOTAL": 150,
                                       "NUMERO_BALDAS": 1, "CARGA_BALDA": 200, **ALU})
    assert "DFM-BASTIDOR-INF" not in _blocking(r)
    assert family("mesa_industrial").leg_fits(r.model.params.values)


def test_cart_handle_moved_clear_of_a_level():
    """Asa a la altura por defecto (1000 mm) que no dejaba sitio para la mano con un nivel: se recoloca."""
    r = regenerate("carro_estanteria", {"ANCHURA": 1200, "PROFUNDIDAD": 500, "ALTURA": 1600, "NUMERO_NIVELES": 5,
                                        "ALTURA_PRIMER_NIVEL": 350, "CARGA_POR_NIVEL": 40, "ASA_EMPUJE": "dos_extremos",
                                        "CARGA_HORIZONTAL": 100})
    codes = {n["code"] for n in r.model.design_notes}
    assert "REGLA-ALTURA_ASA" in codes and "GEO-ASA-NIVEL" not in codes
    assert r.interferences["interferences"] == [] and not _blocking(r)
    # fijada por el usuario: se mantiene y el error propone la altura válida más próxima
    r2 = regenerate("carro_estanteria", {"ANCHURA": 1200, "PROFUNDIDAD": 500, "ALTURA": 1600, "NUMERO_NIVELES": 5,
                                         "ALTURA_PRIMER_NIVEL": 350, "CARGA_POR_NIVEL": 40, "ALTURA_ASA": 1000,
                                         "ASA_EMPUJE": "dos_extremos", "CARGA_HORIZONTAL": 100})
    msg = next(n["message"] for n in r2.model.design_notes if n["code"] == "GEO-ASA-NIVEL")
    assert r2.model.params.values["ALTURA_ASA"] == 1000 and "válida más próxima" in msg


def test_point_load_message_names_the_governing_load():
    """Chapa DC01 (máximo 3 mm) con una pieza de 100 kg: el mensaje dice que falla la carga puntual."""
    r = regenerate("mesa_industrial", {"LONGITUD": 1100, "ANCHURA": 900, "ALTURA": 950, "CARGA_TOTAL": 600,
                                       "NUMERO_BALDAS": 0, "CARGA_PUNTUAL": 100, "MATERIAL_CHAPA": "DC01"})
    msg = next(n["message"] for n in r.model.design_notes if n["code"] == "DIM-ENCIMERA" and n["level"] == "error")
    assert "carga puntual de 100 kg" in msg and "sí se verifica" in msg
