"""Invariantes de lógica (tools/invariants.py) sobre una plantilla de cada familia: equilibrio de reacciones,
cargas de superficie exactas, simetría, masas BOM = piezas = modelo, plan de corte, anidado, soldadura y
presupuesto. El barrido completo con casos aleatorios realistas se ejecuta con ``python tools/invariants.py N SEMILLA``."""
import importlib.util
from pathlib import Path

import pytest

from monxu.families import REGISTRY

_spec = importlib.util.spec_from_file_location("invariants", Path(__file__).resolve().parents[1] / "tools" / "invariants.py")
invariants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(invariants)


@pytest.mark.parametrize("fid", list(REGISTRY))
def test_first_template_has_no_logic_incidents(fid):
    t = REGISTRY[fid].templates()[0]
    assert invariants.check_case(fid, t["values"]) == []
