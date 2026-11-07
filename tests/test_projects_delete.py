"""Borrado de proyectos: revisiones, historial y expedientes; los códigos de proyecto no se reutilizan."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from monxu.api import main
from monxu.storage.db import ChangeLog, Document, Revision, Store


def _new(st, name="P"):
    return st.create_project(name, "mesa_industrial", values={"LONGITUD": 1200.0}).code


def test_delete_project_removes_everything_and_codes_are_not_reused(tmp_path):
    st = Store(tmp_path)
    a, b, c = _new(st, "A"), _new(st, "B"), _new(st, "C")
    assert [a[-4:], b[-4:], c[-4:]] == ["0001", "0002", "0003"]
    st.freeze_revision(b, "primera", "QA", {"LONGITUD": 1200.0}, {}, "MI1200", 50.0, "CUMPLE", {"blocking": 0})
    st.freeze_revision(b, "segunda", "QA", {"LONGITUD": 1300.0}, {}, "MI1300", 52.0, "CUMPLE", {"blocking": 0})
    with st.Session() as s:
        r = s.scalars(select(Revision)).first()
        s.add(Document(revision_id=r.id, path="02_PLANOS/x.pdf", sha256="0" * 64, bytes=10))
        s.commit()
    folder, other = st.dossiers / b, st.dossiers / c
    (folder / "P_x_RevA").mkdir(parents=True)
    (folder / "P_x_RevA" / "f.txt").write_text("x")
    other.mkdir()
    info = st.delete_project(b)
    assert info["revisions"] == ["A", "B"] and info["files_removed"] and not folder.exists() and other.exists()
    with st.Session() as s:
        assert s.scalar(select(func.count()).select_from(Revision)) == 0
        assert s.scalar(select(func.count()).select_from(Document)) == 0
        codes = {p.code for p in st.list_projects()}
        n_log = s.scalar(select(func.count()).select_from(ChangeLog))
    assert codes == {a, c} and n_log == 2                    # sólo la creación de A y C
    # el código siguiente es mayor que cualquiera emitido, también tras borrar el último
    d = _new(st, "D")
    assert d[-4:] == "0004"
    st.delete_project(d)
    assert _new(st, "E")[-4:] == "0005"
    assert _new(Store(tmp_path), "F")[-4:] == "0006"         # el contador persiste en la base de datos


def test_delete_api_and_not_found_errors(tmp_path):
    main.set_store(Store(tmp_path))
    cl = TestClient(main.app)
    code = cl.post("/api/projects", json={"name": "Borrable", "family": "mesa_industrial"}).json()["code"]
    assert cl.get(f"/api/projects/{code}").status_code == 200
    other = cl.post("/api/projects", json={"name": "Otro", "family": "estanteria"}).json()["code"]
    main.store().freeze_revision(other, "", "QA", {}, {}, "ES", 1.0, "CUMPLE", {"blocking": 0})
    listing = cl.get("/api/projects")           # antes: 500 (revisiones fuera de la sesión) en cuanto había proyectos
    assert listing.status_code == 200 and {code, other} <= {p["code"] for p in listing.json()}
    assert next(p for p in listing.json() if p["code"] == other)["revisions"][0]["rev"] == "A"
    r = cl.delete(f"/api/projects/{code}")
    assert r.status_code == 200 and r.json()["code"] == code
    for resp in (cl.get(f"/api/projects/{code}"), cl.delete(f"/api/projects/{code}"),
                 cl.post(f"/api/projects/{code}/revisions", json={"comment": "", "author": ""}),
                 cl.delete("/api/projects/expedientes"), cl.get("/api/projects/P-2026-9999/revisions/A/files")):
        assert resp.status_code == 404 and "no encontrad" in resp.json()["detail"].lower()
    assert all(p["code"] != code for p in cl.get("/api/projects").json())


def test_store_created_once_under_concurrent_requests(tmp_path, monkeypatch):
    """Con la base de datos vacía, las primeras peticiones simultáneas ya no crean las tablas dos veces."""
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv("MONXU_DATA", str(tmp_path / "datos"))
    main.STORE = None
    with ThreadPoolExecutor(8) as ex:
        stores = list(ex.map(lambda _: main.store(), range(8)))
    assert all(s is stores[0] for s in stores)
    main.set_store(Store(tmp_path / "otro"))
