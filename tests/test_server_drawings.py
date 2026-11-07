"""Planos del servidor: ningún texto pisa a otro (símbolos de soldadura, sección de chapa, cajetín, plan de corte)."""
import pdfplumber
import pytest

from monxu.docs import plans
from monxu.docs.drawing_kit import text_width, weld_triangle_offset
from monxu.families import REGISTRY
from monxu.pipeline import regenerate


def test_weld_throat_text_clears_all_around_circle():
    for a in (1.5, 2.0, 3.0, 12.5):
        off = weld_triangle_offset(a, 1)
        assert off - 3.2 - text_width(f"a{a:g}".replace(".", ","), 2.6) >= 1.6 + 0.9     # círculo de contorno r = 1,6


def _overlaps(path):
    bad = []
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(extra_attrs=["upright"])
            for i, a in enumerate(words):
                for b in words[i + 1:]:
                    if (a["x0"] < b["x1"] - 0.3 and b["x0"] < a["x1"] - 0.3 and a["top"] < b["bottom"] - 0.3
                            and b["top"] < a["bottom"] - 0.3
                            and not (abs(a["top"] - b["top"]) < 0.5 and a["upright"] == b["upright"])):
                        bad.append((pno, a["text"], b["text"]))
    return bad


@pytest.mark.slow
@pytest.mark.parametrize("fid,tid", [("carro_estanteria", "CE-1000-3"), ("mesa_industrial", "MI-2200"),
                                     ("puesto_trabajo", "PT-1500-MONTAJE"),
                                     ("estanteria_bateria", "EB-3x1000-5"), ("mesa_soldadura", "MS-2000-28"),
                                     ("tarima", "TA-3000x1200-450")])
def test_server_drawings_without_text_overlaps(tmp_path, fid, tid):
    t = next(t for t in REGISTRY[fid].templates() if t["id"] == tid)
    d = regenerate(fid, t["values"])
    info = {"product_name": f"{d.model.family_name} {d.model.product_code}", "project_code": "P-T", "revision": "A",
            "date": "2026-11-07", "designer": "QA", "company": "MUEBLES MONXU",
            "status_stamp": "PRELIMINAR — cálculo automatizado CUMPLE · pendiente de validación técnica"}
    path = tmp_path / "planos.pdf"
    plans.generate(d.model, d.plan, d.bom, d.eng, info, path)
    assert _overlaps(path) == []
