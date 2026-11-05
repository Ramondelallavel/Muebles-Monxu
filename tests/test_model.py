"""Pruebas del modelo paramétrico de la mesa: geometría, dependencias, interferencias, BOM, QA y bloqueos."""
import pytest

from monxu.cad.interference import check_interferences
from monxu.families import family
from monxu.pipeline import DossierError, generate_dossier, regenerate

F = family("mesa_industrial")


def build(**v):
    return F.build(F.new_params({"LONGITUD": 2000, "ANCHURA": 800, "ALTURA": 900, **v}))


def test_geometry_follows_parameters_and_rules():
    m = build()
    top = m.instance("ENC.BANDEJA")
    lo, hi = top.bbox
    assert hi[0] - lo[0] == pytest.approx(2000, abs=1e-6) and hi[2] == pytest.approx(900, abs=1e-6)
    d = m.ctx.derived
    leg = m.instance("EST.PATA.DI").part
    assert leg.length == pytest.approx(d["LONGITUD_PATA"].value)
    assert d["LONGITUD_LARGUERO"].value == pytest.approx(2000 - 2 * d["RETRANQUEO"].value - 2 * 40)
    assert d["HOLGURA_ENC"].value >= d["RADIO_ENC"].value      # regla anti-interferencia de pliegue


def test_change_regenerates_not_scales():
    a, b = build(CARGA_TOTAL=400), build(LONGITUD=2400, CARGA_TOTAL=400)
    la = a.ctx.derived["LONGITUD_LARGUERO"].value
    lb = b.ctx.derived["LONGITUD_LARGUERO"].value
    assert lb - la == pytest.approx(400)
    assert a.instance("EST.PATA.DI").part.length == b.instance("EST.PATA.DI").part.length   # patas no cambian
    assert b.ctx.derived["N_TRAVESANOS_INT"].value > a.ctx.derived["N_TRAVESANOS_INT"].value


def test_dependency_impact():
    m = build()
    impacted = m.ctx.impact(["ALTURA_BALDA"])
    assert "F30" in impacted and "F13" in impacted and "F20" not in impacted


def test_no_interferences_and_unique_ids():
    m = build(CARGA_TOTAL=400)
    r = check_interferences(m)
    assert r["interferences"] == []
    ids = [i.id for i in m.instances]
    assert len(ids) == len(set(ids))


def test_small_gap_creates_detected_interference():
    m = build(HOLGURA_ENCIMERA=1.0)          # holgura < radio de plegado: aristas de patas en el pliegue
    assert any(n["code"] == "GEO-HOLGURA-RADIO" for n in m.design_notes)
    assert check_interferences(m)["interferences"]


def test_qa_blocks_dossier_on_errors(tmp_path):
    d = regenerate("mesa_industrial", {"LONGITUD": 2000, "ANCHURA": 800, "ALTURA": 900, "HOLGURA_ENCIMERA": 1.0})
    assert d.qa.result()["blocking"] > 0
    with pytest.raises(DossierError):
        generate_dossier(d, {"code": "P-T", "revision": "A"}, tmp_path)
    assert not any(tmp_path.iterdir())       # nada publicado


def test_sizing_without_loads_is_pending():
    d = regenerate("mesa_industrial", {"LONGITUD": 1500, "ANCHURA": 700, "ALTURA": 900, "PERFIL_PATA": "auto",
                                       "CARGA_HORIZONTAL": 100})
    assert d.eng["status"] == "PENDIENTE"
    assert any("CARGA_TOTAL" in p or "encimera" in p for p in d.eng["pending"])
    assert d.model.params.sources["PERFIL_PATA"] == "regla_diseno"


def test_sizing_with_heavy_load_increases_sections():
    light = build(CARGA_TOTAL=200, PERFIL_LARGUERO="auto", PERFIL_PATA="auto")
    heavy = build(CARGA_TOTAL=1500, PERFIL_LARGUERO="auto", PERFIL_PATA="auto", ESPESOR_CHAPA="auto")
    from monxu import catalog
    assert catalog.profile(heavy.params.values["PERFIL_LARGUERO"]).props.Iy >= \
        catalog.profile(light.params.values["PERFIL_LARGUERO"]).props.Iy
    assert heavy.params.sources["PERFIL_LARGUERO"] == "calculo"


def test_bom_masses_from_geometry():
    d = regenerate("mesa_industrial", {"LONGITUD": 1800, "ANCHURA": 800, "ALTURA": 900, "CARGA_TOTAL": 300})
    rows = d.bom["rows"]
    assert sum(r["qty"] for r in rows) == len(d.model.instances)
    for r in rows:
        if r["nominal_mass"]:
            assert r["unit_mass"] == pytest.approx(r["nominal_mass"], rel=0.02)
    assert d.bom["totals"]["total_mass"] == pytest.approx(sum(i.part.mass for i in d.model.instances), abs=0.01)


def test_default_horizontal_hypothesis_can_fail_overturning():
    d = regenerate("mesa_industrial", {"LONGITUD": 1500, "ANCHURA": 700, "ALTURA": 900})
    vuelco = next(c for c in d.eng["checks"] if c["id"] == "E.VUELCO")
    assert vuelco["status"] == "NO_CUMPLE"                  # 300 N por defecto sobre mesa vacía de ~70 kg
    assert any("300 N" in h for h in d.eng["hypotheses"])   # la hipótesis queda declarada
