"""Catálogo ampliado: coherencia de datos y todas las plantillas generan diseños sin errores bloqueantes."""
import math

import pytest

from monxu import catalog
from monxu.families import REGISTRY
from monxu.pipeline import regenerate


def test_profiles_match_en10219_annex_b():
    for code, p in catalog.profiles().items():
        a = 2 * p.t * (p.B + p.H - 2 * p.t) - (4 - math.pi) * (p.r_out ** 2 - p.r_in ** 2)
        assert p.props.A == pytest.approx(a, rel=0.01), code
        assert p.r_out == 2 * p.t and p.H >= p.B


def test_materials_complete_and_flagged():
    for code, m in catalog.materials().items():
        assert m.density > 0 and m.standard
        if m.structural:
            assert m.fu >= m.fy > 0 and m.E > 0
    assert not catalog.material("DX51D+Z").fy_guaranteed and catalog.material("S250GD+Z").fy_guaranteed
    for code in catalog.sheet_data()["thicknesses_mm"]:
        assert "chapa" in catalog._load("materials")["materials"][code]["forms"]


def test_feet_have_matching_weld_nuts():
    for code, c in catalog.components().items():
        if c["category"] == "patas":
            catalog.component(f"TUERCA_SOLDAR_{c['thread']}")
            assert c["rated_load_source"] == "catalogo_generico"


@pytest.mark.slow
@pytest.mark.parametrize("fid,tpl", [(f.id, t) for f in REGISTRY.values() for t in f.templates()],
                         ids=lambda x: x["id"] if isinstance(x, dict) else x)
def test_template_builds_without_blocking(fid, tpl):
    d = regenerate(fid, tpl["values"], {k: "plantilla" for k in tpl["values"]})
    q = d.qa.result()
    assert q["blocking"] == 0, [i for i in q["items"] if i["level"] == "bloqueante"]
    assert d.interferences["interferences"] == []
