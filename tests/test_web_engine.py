"""Validación cruzada del motor del navegador (TypeScript) frente al motor de referencia, en las plantillas."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ESBUILD = ROOT / "frontend" / "node_modules" / ".bin" / "esbuild"


@pytest.mark.skipif(not shutil.which("node") or not ESBUILD.exists(), reason="requiere node y las dependencias del frontend")
def test_motor_navegador_coincide_con_servidor(tmp_path):
    bundle = tmp_path / "webrun.mjs"
    subprocess.run([str(ESBUILD), str(ROOT / "tools/webcheck/run.ts"), "--bundle", "--platform=node", "--format=esm",
                    f"--outfile={bundle}", "--log-level=warning"], cwd=ROOT / "frontend", check=True)
    r = subprocess.run([sys.executable, "tools/webcheck/compare.py", str(bundle), "4", "3"], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert "DIFERENCIAS 0" in r.stdout


@pytest.mark.skipif(not shutil.which("node") or not ESBUILD.exists(), reason="requiere node y las dependencias del frontend")
def test_expediente_del_navegador_verificado_con_herramientas_del_servidor(tmp_path):
    """El ZIP del artefacto (STEP, planos, montaje, Excel, DXF) se relee con OpenCascade, pdfplumber, openpyxl y ezdxf."""
    bundle = tmp_path / "dossier.mjs"
    subprocess.run([str(ESBUILD), str(ROOT / "tools/webcheck/dossier.ts"), "--bundle", "--platform=node", "--format=esm",
                    f"--outfile={bundle}", "--log-level=warning"], cwd=ROOT / "frontend", check=True)
    values = json.dumps({"LONGITUD": 2000, "ANCHURA": 800, "ALTURA": 900, "CARGA_TOTAL": 400})
    z = tmp_path / "exp.zip"
    out = subprocess.run(["node", str(bundle), "mesa_industrial", values, str(z)], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)["blocking"] == []
    r = subprocess.run([sys.executable, "tools/webcheck/verify_dossier.py", str(z), "mesa_industrial", values], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert "ERRORES 0" in r.stdout
