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


@pytest.mark.skipif(not shutil.which("node") or not ESBUILD.exists(), reason="requiere node y las dependencias del frontend")
def test_planos_sin_solapes_en_una_plantilla_por_familia(tmp_path):
    """Auditoría de legibilidad: ningún texto pisa otro texto, una línea, una cota, un globo ni el cajetín."""
    from monxu.families import REGISTRY
    bundle = tmp_path / "layout.mjs"
    subprocess.run([str(ESBUILD), str(ROOT / "tools/webcheck/layout.ts"), "--bundle", "--platform=node", "--format=esm",
                    f"--outfile={bundle}", "--log-level=warning"], cwd=ROOT / "frontend", check=True)
    cases = [{"id": f.templates()[0]["id"], "family": fid, "values": f.templates()[0]["values"]} for fid, f in REGISTRY.items()]
    out = subprocess.run(["node", str(bundle), "-"], input=json.dumps(cases), capture_output=True, text=True, check=True)
    res = json.loads(out.stdout)
    assert len(res) == len(cases)
    for r in res:
        assert r["planos"]["total"] == 0 and r["montaje"]["total"] == 0, (r["id"], r["planos"]["sheets"], r["montaje"]["sheets"])


@pytest.mark.slow
@pytest.mark.skipif(not shutil.which("node") or not ESBUILD.exists(), reason="requiere node y las dependencias del frontend")
def test_control_de_calidad_igual_en_ambos_motores(tmp_path):
    """Misma lista de comprobaciones de QA (nivel y código) en el navegador y en el servidor, una plantilla por familia."""
    from monxu.families import REGISTRY
    from monxu.pipeline import regenerate
    bundle = tmp_path / "webrun.mjs"
    subprocess.run([str(ESBUILD), str(ROOT / "tools/webcheck/run.ts"), "--bundle", "--platform=node", "--format=esm",
                    f"--outfile={bundle}", "--log-level=warning"], cwd=ROOT / "frontend", check=True)
    cases = [{"id": f.templates()[0]["id"], "family": fid, "values": f.templates()[0]["values"]} for fid, f in REGISTRY.items()]
    js = {c["id"]: c for c in json.loads(subprocess.run(["node", str(bundle)], input=json.dumps(cases), capture_output=True,
                                                         text=True, check=True).stdout)}
    for c in cases:
        r = regenerate(c["family"], c["values"])
        py = sorted((i["level"], i["code"]) for i in r.qa.result()["items"])
        assert py == sorted(tuple(x) for x in js[c["id"]]["qa"]), c["id"]


@pytest.mark.skipif(not shutil.which("node") or not ESBUILD.exists(), reason="requiere node y las dependencias del frontend")
def test_borrado_de_proyectos_en_el_navegador(tmp_path):
    """API local: borrar un proyecto lo elimina y el código no se reutiliza (antes: número de proyectos + 1)."""
    bundle = tmp_path / "projects.mjs"
    subprocess.run([str(ESBUILD), str(ROOT / "tools/webcheck/projects.ts"), "--bundle", "--platform=node", "--format=esm",
                    f"--outfile={bundle}", "--log-level=warning"], cwd=ROOT / "frontend", check=True)
    r = json.loads(subprocess.run(["node", str(bundle)], capture_output=True, text=True, check=True).stdout)
    a, b, c = r["created"]
    assert r["deleted"]["code"] == b and sorted(r["after"]) == [a, c]
    assert r["next"][-4:] == "0004" and r["next2"][-4:] == "0005"
    assert "no encontrado" in r["get_deleted"] and "no encontrado" in r["delete_again"]
