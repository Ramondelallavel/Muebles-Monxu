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
