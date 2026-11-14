"""Las plantillas integradas de la base de datos siguen al código; las del usuario no se tocan."""
from sqlalchemy import select

from monxu.families import REGISTRY
from monxu.storage.db import Store, Template


def test_builtin_templates_follow_code(tmp_path):
    st = Store(tmp_path)
    code = {t["id"]: t for f in REGISTRY.values() for t in f.templates()}
    # simula una base creada con una versión anterior: plantilla integrada con valores viejos
    with st.Session() as s:
        row = s.get(Template, "MI-1200")
        row.values, row.name = {"LONGITUD": 1.0}, "antigua"
        s.commit()
    st.save_template("MIA-1", "mesa_industrial", "Mía", {"LONGITUD": 1234.0})
    st2 = Store(tmp_path)
    rows = {t.id: t for t in st2.templates()}
    assert rows["MI-1200"].values == code["MI-1200"]["values"] and rows["MI-1200"].name == code["MI-1200"]["name"]
    assert set(code) <= set(rows)
    assert rows["MIA-1"].values == {"LONGITUD": 1234.0} and not rows["MIA-1"].builtin
    with st2.Session() as s:
        assert len(s.scalars(select(Template)).all()) == len(code) + 1
