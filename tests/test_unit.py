"""Pruebas unitarias: catálogo, parámetros, geometría, chapa, cálculo, optimización, DXF e intérprete."""
import math

import numpy as np
import pytest

from monxu import catalog
from monxu.ai import assistant
from monxu.ai.interpreter import parse
from monxu.cad import geometry as G
from monxu.cad.sheetmetal import EDGES, FlangeSpec, SheetMetalSpec, bend_deduction, volume_consistency
from monxu.core.params import ParamError, ParameterSet, ParamSpec
from monxu.engineering.fem import Frame3D, line_load_to_nodes
from monxu.engineering.plate import navier
from monxu.manufacturing.optimization import nest_sheets, optimize_bars


# ------------------------------------------------------------------ catálogo y secciones
@pytest.mark.parametrize("code,A,I,Wpl,mass", [
    ("SHS 40x40x2", 2.94, 6.94, 4.13, 2.31),     # EN 10219-2
    ("SHS 50x50x3", 5.41, 19.5, 9.39, 4.25),
])
def test_section_properties_match_en10219(code, A, I, Wpl, mass):
    p = catalog.profile(code)
    sp = p.props
    assert sp.A / 100 == pytest.approx(A, rel=0.01)
    assert sp.Iy / 1e4 == pytest.approx(I, rel=0.01)
    assert sp.Wpl_y / 1e3 == pytest.approx(Wpl, rel=0.01)
    assert p.mass_per_m(7850) == pytest.approx(mass, rel=0.01)


def test_rhs_designation_h_by_b():
    p = catalog.profile("RHS 60x40x2")
    assert (p.H, p.B) == (60, 40) and p.props.Iy > p.props.Iz


def test_k_factor_din6935():
    assert catalog.din6935_k_factor(2, 2) == pytest.approx(0.325)
    assert catalog.din6935_k_factor(10, 2) == 0.5


# ------------------------------------------------------------------ parámetros
def test_param_validation_and_sources():
    ps = ParameterSet.from_specs([ParamSpec("L", "L", "float", 100.0, "mm", min=50, max=200),
                                  ParamSpec("M", "M", "choice", "a", choices=["a", "b"])])
    ps.update({"L": "150,5"}, "usuario")
    assert ps.values["L"] == 150.5 and ps.sources["L"] == "usuario" and ps.sources["M"] == "defecto"
    with pytest.raises(ParamError):
        ps.update({"L": 500})
    with pytest.raises(ParamError):
        ps.update({"M": "z"})


# ------------------------------------------------------------------ chapa
def test_flat_pattern_and_volume_consistency():
    spec = SheetMetalSpec(2000, 800, 2.0, 2.0, 0.325, tuple(FlangeSpec(e, 40) for e in EDGES))
    fp = spec.flat_pattern()
    assert fp.width == pytest.approx(2000 + 2 * 40 - 2 * bend_deduction(2, 2, 0.325), abs=1e-6)
    solid = spec.solid()
    assert solid.isValid()
    lo, hi = G.bbox(solid)
    assert np.allclose(lo, [0, 0, -40], atol=1e-6) and np.allclose(hi, [2000, 800, 0], atol=1e-6)
    _, dev = volume_consistency(spec, G.volume(solid))
    assert dev < 1e-9


def test_notched_shelf_with_flange_holes():
    spec = SheetMetalSpec(1000, 500, 1.5, 1.5, 0.325, tuple(FlangeSpec(e, 25, holes=((300.0, 12.0, 6.6),))
                                                           for e in ("y0", "y1")), notch=(42, 42))
    s = spec.solid()
    assert s.isValid()
    assert volume_consistency(spec, G.volume(s))[1] < 1e-9
    assert len(spec.flat_pattern().holes) == 2


# ------------------------------------------------------------------ FEM y placas
def test_fem_simply_supported_beam():
    sp = catalog.profile("RHS 60x40x2").props
    L, n, q = 2000.0, 20, 1.0
    f = Frame3D()
    ids = [f.node((L * i / n, 0, 0)) for i in range(n + 1)]
    for i in range(n):
        f.element(ids[i], ids[i + 1], 210000, 81000, sp.A, sp.Iy, sp.Iz, sp.It, (0, 0, 1))
    f.support(ids[0], (True, True, True, True, False, False))
    f.support(ids[-1], (False, True, True, False, False, False))
    F = line_load_to_nodes(np.array([L * i / n for i in range(n + 1)]), lambda s: -q, 0, L)
    for k, i in enumerate(ids):
        f.add_nodal_load("Q", i, (0, 0, F[k]))
    r = f.solve()
    w = r.U["Q"][6 * ids[n // 2] + 2]
    M = max(abs(r.element_forces(k, r.U["Q"])[[4, 10]]).max() for k in range(n))
    assert w == pytest.approx(-5 * q * L ** 4 / (384 * 210000 * sp.Iy), rel=0.01)
    assert M == pytest.approx(q * L ** 2 / 8, rel=1e-6)


def test_plate_navier_matches_timoshenko():
    E, nu, t, q, a = 210000, 0.3, 2.0, 0.001, 500.0
    r = navier(a, a, t, E, nu, q=q)
    assert r["w"] * r["D"] / (q * a ** 4) == pytest.approx(0.00406, rel=0.005)
    assert r["Mx"] / (q * a ** 2) == pytest.approx(0.0479, rel=0.005)
    r2 = navier(1000, 500, t, E, nu, q=q)
    assert r2["sigma"] * t ** 2 / (q * 500 ** 2) == pytest.approx(0.6102, rel=0.005)   # Roark a/b = 2


# ------------------------------------------------------------------ optimización
def test_line_load_integration_is_exact_across_kinks():
    """La regla de 45° da densidades con quiebros: partir la cuadratura en ellos conserva la carga total."""
    s = np.linspace(0, 1000, 11)
    a = 250.0                                                   # meseta trapecial (quiebros dentro de los tramos)

    def p(x):
        return min(x, a, 1000 - x)
    total = a * (1000 - a)                                      # área exacta del trapecio
    F = line_load_to_nodes(s, p, 0, 1000, breaks=(a, 1000 - a, 500))
    assert F.sum() == pytest.approx(total, rel=1e-12)
    F0 = line_load_to_nodes(s, p, 0, 1000)                       # sin quiebros: error de cuadratura apreciable
    assert abs(F0.sum() - total) > 1e-6 * total


def test_singular_frame_raises_linalg_error():
    f = Frame3D()
    a, b = f.node((0, 0, 0)), f.node((1000, 0, 0))
    f.element(a, b, 210000, 81000, 100, 1e4, 1e4, 1e4, (0, 0, 1))
    f.support(a, (True, True, True, False, False, False))       # rótula esférica: la barra gira libre (mecanismo)
    f.add_nodal_load("Q", b, (0, 0, -100))
    with pytest.raises(np.linalg.LinAlgError):
        f.solve()


def test_bar_plan_length_balance_when_last_piece_fills_the_bar():
    """Cortes + sierra + retal = longitud de barra, también cuando la última pieza apura la barra sin corte final."""
    r = optimize_bars([{"ref": "A", "length": 2993.0, "qty": 2}], 6000, 3, 10)      # 2·(2993+3) = 5992 > 5990 útiles
    assert r["n_bars"] == 1 == r["lower_bound"] and r["optimal"]
    for b in r["bars"]:
        assert sum(c["length"] for c in b["cuts"]) + b["kerf_loss"] + b["remnant"] == pytest.approx(6000)
        assert b["remnant"] >= 0


def test_bar_optimizer_respects_kerf_and_bound():
    r = optimize_bars([{"ref": "A", "length": 1912, "qty": 4}, {"ref": "B", "length": 712, "qty": 6}], 6000, 3, 10)
    assert r["n_bars"] == r["lower_bound"] == 2
    for b in r["bars"]:
        used = sum(c["length"] + 3 for c in b["cuts"]) + 10
        assert used <= 6000 + 1e-6
    with pytest.raises(ValueError):
        optimize_bars([{"ref": "X", "length": 6500, "qty": 1}])


def test_nesting_no_overlap_and_inside_sheet():
    parts = [{"ref": f"P{i}", "w": 600, "h": 400, "qty": 3, "area": 240000} for i in range(2)]
    r = nest_sheets(parts, 2000, 1000, margin=10, spacing=8, kerf=0.3)
    assert r["feasible"]
    for s in r["sheets"]:
        pl = s["placements"]
        for p in pl:
            assert p["x"] >= 10 - 1e-9 and p["y"] >= 10 - 1e-9 and p["x"] + p["w"] <= 1990 + 1e-6 and p["y"] + p["h"] <= 990 + 1e-6
        for i, a in enumerate(pl):
            for b in pl[i + 1:]:
                sep = a["x"] + a["w"] + 8 <= b["x"] + 1e-6 or b["x"] + b["w"] + 8 <= a["x"] + 1e-6 or \
                    a["y"] + a["h"] + 8 <= b["y"] + 1e-6 or b["y"] + b["h"] + 8 <= a["y"] + 1e-6
                assert sep
    assert not nest_sheets([{"ref": "G", "w": 2500, "h": 900, "qty": 1, "area": 1}], 2000, 1000)["feasible"]


# ------------------------------------------------------------------ intérprete IA
def test_interpreter_acceptance_sentence():
    it = parse("Quiero una mesa industrial de 2.000 × 800 × 900 mm, con estructura tubular, encimera de chapa, "
               "una balda inferior y carga distribuida solicitada de 400 kg.")
    assert it.family == "mesa_industrial"
    assert (it.values["LONGITUD"], it.values["ANCHURA"], it.values["ALTURA"]) == (2000, 800, 900)
    assert it.values["CARGA_TOTAL"] == 400 and it.values["NUMERO_BALDAS"] == 1


def test_interpreter_shelving_example_and_units():
    it = parse("Quiero una estantería industrial de 2 metros de altura, 1.500 mm de ancho, 600 mm de profundidad y "
               "cinco niveles. Cada nivel debe soportar 150 kg")
    assert it.family == "estanteria"
    assert it.values["ALTURA"] == 2000 and it.values["ANCHURA"] == 1500 and it.values["PROFUNDIDAD"] == 600
    assert it.values["NUMERO_NIVELES"] == 5 and it.values["CARGA_POR_NIVEL"] == 150


def test_assistant_asks_and_flags_unsupported():
    r = assistant.handle(assistant.new_state(), "Mesa de 2000 mm de largo, 800 de fondo y 900 de alto con 400 kg, "
                                                "dos cajones y panel trasero perforado")
    params = {q["param"] for q in r["questions"]}
    assert "CARGA_BALDA" in params and "MATERIAL_ESTRUCTURAL" in params
    assert any("Cajones" in u for u in r["state"]["unsupported"])
    r2 = assistant.handle(r["state"], "La balda llevará 100 kg")
    assert r2["parameters"]["CARGA_BALDA"] == 100
    r3 = assistant.handle(assistant.new_state(), "Un armario de herramientas con 4 puertas")
    assert not r3["family_implemented"] and not r3["ready_to_generate"]


def test_llm_adapter_merges_without_overriding_rules():
    class FakeResp:
        stop_reason = "end_turn"

        def __init__(self, obj):
            self.parsed_output = obj

    class FakeMessages:
        def parse(self, **kw):
            from monxu.ai.llm import ExtractedRequest
            return FakeResp(ExtractedRequest(family="mesa_industrial", LONGITUD=9999, CARGA_PUNTUAL=80))

    class FakeClient:
        messages = FakeMessages()

    r = assistant.handle(assistant.new_state(), "Mesa industrial de 2000 mm de largo", llm=FakeClient())
    assert r["parameters"]["LONGITUD"] == 2000          # la evidencia literal prevalece
    assert r["parameters"]["CARGA_PUNTUAL"] == 80       # dato aportado por el modelo
    assert r["engine"] == "claude+reglas"
