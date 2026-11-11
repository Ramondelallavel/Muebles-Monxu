"""Auditoría integral: regresión del proyecto de referencia P-2026-0039 (EB3x1000-600-2000), propagación de
parámetros, pruebas negativas (incoherencias que deben detectarse) y flujo de aprobación técnica."""
import copy
import json
import math
from pathlib import Path

import pytest

from monxu import catalog
from monxu.docs import assembly
from monxu.engineering.analysis import applicable_standards
from monxu.manufacturing.optimization import nest_sheets, optimize_bars, sheet_purchase
from monxu.pipeline import regenerate
from monxu.validation import approval as AP
from monxu.validation import qa as QA

REF = json.loads((Path(__file__).parent / "data" / "ref_P-2026-0039.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ref():
    return regenerate("estanteria_bateria", REF["params"], REF["sources"])


def qa_item(d, code):
    return next(i for i in d.qa.result()["items"] if i["code"] == code)


# ----------------------------------------------------------------------------- 1-15: proyecto de referencia
def test_ref_01_tornilleria_de_instrucciones_es_la_del_bom(ref):
    codes = {i.part.code for i in ref.model.instances if i.part.role == "tornillo"}
    assert codes == {"TORNILLO_ISO7380_M6x10"}
    texts = assembly.step_texts(ref.model)
    assert any("N-TORNILLO_ISO7380_M6x10" in t for t in texts.values())
    assert not any("M6x12" in t for t in texts.values())
    assert assembly.designation_issues(ref.model, list(texts.values())) == []
    assert qa_item(ref, "XDOC-TORNILLERIA-INSTR")["level"] == "ok"


def test_ref_02_tuerca_remachable_sin_norma_inventada(ref):
    c = catalog.component("TUERCA_REMACHABLE_M6")
    assert c["standard"] is None and c["validation"]["status"] == "pendiente_validacion"
    row = next(r for r in ref.bom["rows"] if r["code"] == "TUERCA_REMACHABLE_M6")
    assert "7340" not in (row["standard"] or "") and "sin norma de producto" in row["standard"]
    assert qa_item(ref, "COMP-TUERCA_REMACHABLE_M6")["level"] == "pendiente"


def test_ref_03_placa_5mm_misma_superficie_y_masa_en_bom_anidado_compras_y_presupuesto(ref):
    n = next(n for n in ref.plan["nesting"] if n["thickness"] == 5)
    bom_area = ref.bom["totals"]["sheet_area_m2"]["S235JR e=5 mm"]
    assert bom_area == pytest.approx(n["parts_area_m2"], abs=1e-4) == pytest.approx(n["purchase"]["parts_area_m2"], abs=1e-4)
    pur = next(p for p in ref.plan["purchases"]["items"] if p["group"] == "S235JR e=5 mm")
    assert pur["type"] == "Chapa (corte a medida)" and n["purchase"]["n_custom"] == 1 and n["purchase"]["n_full"] == 0
    line = next(ln for ln in ref.cost["lines"] if "e=5 mm" in ln["concept"] and ln["group"] == "Material")
    assert line["qty"] == pytest.approx(pur["mass_kg"], abs=0.01)


def test_ref_04_chapas_de_2mm_compradas_son_las_presupuestadas(ref):
    n = next(n for n in ref.plan["nesting"] if n["thickness"] == 2)
    pur = next(p for p in ref.plan["purchases"]["items"] if p["group"] == "S235JR e=2 mm")
    assert pur["qty"] == n["purchase"]["n_full"] == 5
    line = next(ln for ln in ref.cost["lines"] if "e=2 mm" in ln["concept"] and ln["group"] == "Material")
    assert line["qty"] == pytest.approx(pur["mass_kg"], abs=0.01)
    assert ref.cost["material_basis"] == "compra"


def test_ref_05_barras_compradas_son_las_presupuestadas(ref):
    for c in ref.plan["cutting"]:
        pur = next(p for p in ref.plan["purchases"]["items"] if p["type"] == "Perfil" and p["group"] == f"{c['profile']} {c['material']}")
        assert pur["qty"] == c["n_bars"]
        line = next(ln for ln in ref.cost["lines"] if ln["concept"].startswith(f"Perfil {c['profile']} {c['material']}"))
        assert line["qty"] == pytest.approx(c["purchased_length"] * c["kg_per_m"] / 1000, abs=1e-3)
        assert pur["mass_kg"] == pytest.approx(line["qty"], abs=0.006)        # compra = presupuesto = balance
        row = next(r for r in ref.plan["balance"]["rows"] if r["group"] == f"{c['profile']} {c['material']}")
        assert row["purchased_kg"] == pytest.approx(pur["mass_kg"], abs=0.006)
    assert qa_item(ref, "XDOC-PRESUPUESTO-COMPRAS")["level"] == "ok"


def test_ref_06_peso_del_bom_igual_al_peso_propio_del_calculo(ref):
    sw = ref.eng["self_weight"]
    assert sw["total_kg"] == pytest.approx(ref.bom["totals"]["mass_product_kg"], rel=2e-3)
    assert qa_item(ref, "XDOC-PESO-CALC")["level"] == "ok"
    t = ref.bom["totals"]
    assert t["mass_product_kg"] == pytest.approx(t["mass_manufactured_kg"] + t["mass_commercial_kg"], abs=2e-3)
    assert t["mass_purchased_kg"] > t["mass_product_kg"]          # material comprado y producto no se mezclan


def test_ref_07_plan_de_corte_con_despuntes_y_balance(ref):
    for c in ref.plan["cutting"]:
        assert c["trim_start"] == 10 and c["trim_end"] == 0 and c["balance_mm"] == 0
        for b in c["bars"]:
            assert b["trim_start"] + b["used"] + b["kerf_total"] + b["trim_end"] + b["remnant"] == pytest.approx(b["length"])
            assert b["n_cuts"] == b["n_pieces"] + 1
            assert b["remnant_status"] in ("reutilizable", "chatarra", "sin retal")
        assert c["purchased_length"] == pytest.approx(c["pieces_length"] + c["waste_length"] + c["reusable_length"])
    assert qa_item(ref, "XDOC-BALANCE")["level"] == "ok"


def test_ref_08_aprovechamientos_reales_sobre_lo_comprado(ref):
    for n in ref.plan["nesting"]:
        pu = n["purchase"]
        assert pu["utilization"] == pytest.approx(pu["parts_area_m2"] / (pu["purchased_area_m2"] + pu["stock_area_m2"]), abs=1e-4)
    five = next(n for n in ref.plan["nesting"] if n["thickness"] == 5)
    assert five["purchase"]["utilization"] > 0.5        # antes 0,96 % frente a una chapa entera


def test_ref_09_capacidad_generica_de_pies_pendiente_de_validacion(ref):
    pies = next(c for c in ref.eng["checks"] if c["id"] == "A.PIES")
    assert pies["status"] == "PENDIENTE_VALIDACION" and "catálogo genérico" in pies["details"]["validacion"]
    assert ref.eng["verdict"] == "PENDIENTE DE VALIDACIÓN" and not ref.technically_verified


def test_ref_10_saliente_de_cabezas_documentado(ref):
    it = qa_item(ref, "GEO-SALIENTE")
    assert it["difference"] == pytest.approx(3.3, abs=0.05) and "envolvente máxima" in it["obtained"]


def test_ref_11_avisos_de_soldadura_calculados_y_wps_bloquea_liberacion(ref):
    codes = {f["code"]: f for f in ref.dfm}
    assert "encimera" not in codes["SOL-DEFORMACION"]["message"]
    # enrase y radio de esquina calculados desde la geometría (antes, un texto fijo que no correspondía al producto)
    from monxu.manufacturing.plan import weld_face_conditions
    wf = weld_face_conditions(ref.model)
    assert ("SOL-ENRASE" in codes) == (wf["flush"] > 0) and ("SOL-RADIO-ESQUINA" in codes) == (wf["corner"] > 0)
    assert wf == {"flush": 60, "corner": 60, "corner_min": 0.5, "corner_r": 4.0}
    assert "60 uniones" in codes["SOL-ENRASE"]["message"] and "0.5 mm" in codes["SOL-RADIO-ESQUINA"]["message"]
    assert "patas" not in codes["SOL-ENRASE"]["message"]
    wps = qa_item(ref, "SOL-WPS")
    assert wps["level"] == "pendiente" and wps["release_block"]


def test_ref_12_imperfecciones_y_segundo_orden(ref):
    ids = {c["id"]: c for c in ref.eng["checks"]}
    assert ids["S.IMPERF"]["status"] == "CUMPLE" and ids["S.IMPERF"]["value"] == pytest.approx(1 / 200)
    assert ids["S.ALFA-CR-X"]["value"] >= 10 and ids["S.ALFA-CR-Y"]["value"] >= 10
    assert any("Horne" in t for t in ref.eng["limitations"])
    assert "ELU-1X" in ref.eng["combinations"]["ELU"] and "IXG" in ref.eng["combinations"]["ELU"]["ELU-1X"]


def test_ref_13_solo_normas_aplicables(ref):
    codes = {s["code"] for s in applicable_standards(ref.model)}
    assert "EN 1993-1-4" not in codes and "EN 1999-1-1" not in codes
    assert {"EN 1993-1-1", "EN 15635", "EN ISO 5817"} <= codes
    assert next(c for c in ref.eng["checks"] if c["id"] == "N.ANEJO-NACIONAL")["status"] == "PENDIENTE_VALIDACION"


def test_ref_14_sellos_sin_aprobacion_no_dicen_verificado(ref):
    ev = AP.evaluate(ref.qa.result(), ref.eng["status"], None, {})
    assert ev["state"] in ("diseno_generado", "geometria_validada")
    for word in ("VERIFICADO", "VALIDADO POR", "APROBADO TÉCNICAMENTE —", "LIBERADO"):
        assert word not in ev["stamp"]["text"]
    assert "NO APTO PARA FABRICACIÓN" in ev["stamp"]["text"]


def test_ref_15_exportaciones_corresponden_al_modelo(ref, tmp_path):
    # STL y DXF de anidado se releen y se comparan con el modelo maestro
    from monxu.cad import export as X
    from monxu.docs import dxf
    stl = X.verify_stl(X.export_stl(ref.model, tmp_path / "m.stl"))
    vol = sum(i.part.volume for i in ref.model.instances)
    assert stl["bytes_ok"] and abs(stl["volume"] - vol) / vol < 0.01
    refs = {p.ref: p for p in ref.model.parts.values()}
    for n in ref.plan["nesting"]:
        for pth, sh in zip(dxf.export_nesting_dxf(n, refs, str(tmp_path / f"n{n['thickness']:g}_{{n}}.dxf")), n["sheets"]):
            v = dxf.verify_nesting_dxf(pth)
            assert v["cut_contours"] == len(sh["placements"]) and v["format"] == pytest.approx((sh["length"], sh["width"]))


def test_ref_controles_cruzados_todos_correctos(ref):
    xd = [i for i in ref.qa.result()["items"] if i["code"].startswith("XDOC-")]
    assert len(xd) >= 10 and all(i["level"] == "ok" for i in xd), [i for i in xd if i["level"] != "ok"]
    for i in ref.qa.result()["items"]:
        assert {"severity", "result", "document", "expected", "obtained", "criterion", "action", "release_block"} <= set(i)


# ----------------------------------------------------------------------------- propagación de parámetros
PROPAGATION = [
    ("ANCHURA", 1200, lambda a, b: b.bom["totals"]["profile_meters"] != a.bom["totals"]["profile_meters"]),
    ("PROFUNDIDAD", 800, lambda a, b: b.bom["totals"]["sheet_area_m2"] != a.bom["totals"]["sheet_area_m2"]),
    ("ALTURA", 2400, lambda a, b: b.bom["totals"]["profile_meters"] != a.bom["totals"]["profile_meters"]),
    ("NUMERO_MODULOS", 4, lambda a, b: len(b.model.instances) > len(a.model.instances)),
    ("NUMERO_NIVELES", 4, lambda a, b: len(b.model.instances) < len(a.model.instances)),
    ("ESPESOR_BALDA", 3, lambda a, b: any(n["thickness"] == 3 for n in b.plan["nesting"])),
    ("PERFIL_MONTANTE", "SHS 60x60x3", lambda a, b: any(c["profile"] == "SHS 60x60x3" for c in b.plan["cutting"])),
    ("MATERIAL_CHAPA", "DC01", lambda a, b: any(n["material"] == "DC01" for n in b.plan["nesting"])),
    ("CARGA_POR_NIVEL", 150, lambda a, b: b.eng["governing"]["utilization"] != a.eng["governing"]["utilization"]),
    ("ACABADO", "GALVANIZADO", lambda a, b: b.cost["price"] != a.cost["price"]),
    ("LOTE_FABRICACION", 3, lambda a, b: b.plan["lot"] == 3 and next(p for p in b.plan["purchases"]["items"]
                                                                   if p["type"] == "Comercial")["qty"] % 3 == 0),
]


@pytest.mark.parametrize("name,value,changed", PROPAGATION, ids=[p[0] for p in PROPAGATION])
def test_propagacion_de_parametros(ref, name, value, changed):
    vals = {**REF["params"], name: value}
    src = {**REF["sources"], name: "usuario"}
    # los parámetros dimensionados por cálculo se dejan en «auto» para que el modelo se recalcule con el cambio
    for k, s in REF["sources"].items():
        if s == "calculo" and k != name:
            vals[k] = "auto"
            src.pop(k, None)
    d = regenerate("estanteria_bateria", vals, src)
    assert changed(ref, d)
    q = d.qa.result()
    xd = [i for i in q["items"] if i["code"].startswith("XDOC-") and i["level"] != "ok"]
    assert xd == [], xd                                     # los documentos siguen coherentes entre sí
    dep = d.summary()["dependencies"]
    assert any(name in v for v in dep.values())


def test_mapa_de_dependencias(ref):
    from monxu.docs.dependencies import affected_documents
    dep = ref.summary()["dependencies"]
    assert "Plan de corte de perfiles" in affected_documents(dep, ["LONGITUD_BARRA"])
    assert "Anidado de chapa" in affected_documents(dep, ["FORMATO_CHAPA"])
    assert "Informe de cálculo" in affected_documents(dep, ["CARGA_POR_NIVEL"])
    assert "Modelo 3D (STEP, STL, JSON paramétrico)" not in affected_documents(dep, ["CARGA_POR_NIVEL"])


# ----------------------------------------------------------------------------- pruebas negativas
def _recheck(d, bom=None, plan=None, cost=None, eng=None, dfm=None):
    return QA.model_checks(d.model, d.interferences, eng or d.eng, dfm or d.dfm, bom or d.bom, plan or d.plan,
                           cost or d.cost).result()


def test_negativa_cantidad_del_bom_distinta_del_3d(ref):
    bom = copy.deepcopy(ref.bom)
    bom["rows"][0]["qty"] += 1
    assert next(i for i in _recheck(ref, bom=bom)["items"] if i["code"] == "XDOC-BOM-3D")["level"] == "bloqueante"


def test_negativa_compras_distintas_del_bom(ref):
    plan = copy.deepcopy(ref.plan)
    next(p for p in plan["purchases"]["items"] if p["type"] == "Comercial")["qty"] += 2
    assert next(i for i in _recheck(ref, plan=plan)["items"] if i["code"] == "XDOC-BOM-COMPRAS")["level"] == "bloqueante"


def test_negativa_barras_compradas_distintas_del_plan(ref):
    plan = copy.deepcopy(ref.plan)
    next(p for p in plan["purchases"]["items"] if p["type"] == "Perfil")["qty"] -= 1
    assert next(i for i in _recheck(ref, plan=plan)["items"] if i["code"] == "XDOC-COMPRAS-OPT")["level"] == "bloqueante"


def test_negativa_balance_de_barra_roto(ref):
    plan = copy.deepcopy(ref.plan)
    plan["cutting"][0]["bars"][0]["balance_mm"] = 12.0
    assert next(i for i in _recheck(ref, plan=plan)["items"] if i["code"] == "XDOC-BALANCE")["level"] == "bloqueante"


def test_negativa_pieza_que_falta_en_el_plan_de_corte(ref):
    plan = copy.deepcopy(ref.plan)
    plan["cutting"][0]["bars"][0]["cuts"].pop()
    assert next(i for i in _recheck(ref, plan=plan)["items"] if i["code"] == "XDOC-BOM-CORTE")["level"] == "bloqueante"


def test_negativa_peso_del_calculo_distinto(ref):
    eng = copy.deepcopy(ref.eng)
    eng["self_weight"]["total_kg"] *= 1.2
    assert next(i for i in _recheck(ref, eng=eng)["items"] if i["code"] == "XDOC-PESO-CALC")["level"] == "bloqueante"


def test_negativa_presupuesto_distinto_de_compras(ref):
    cost = copy.deepcopy(ref.cost)
    cost["material_kg_per_unit"] *= 0.8                 # p. ej. un aprovechamiento genérico del 80 %
    assert next(i for i in _recheck(ref, cost=cost)["items"] if i["code"] == "XDOC-PRESUPUESTO-COMPRAS")["level"] == "bloqueante"


def test_negativa_instruccion_con_tornillo_que_no_esta_en_el_bom(ref):
    texts = list(assembly.step_texts(ref.model).values()) + ["Fijar con tornillos ISO 7380 M6x12 (8 N·m)."]
    assert assembly.designation_issues(ref.model, texts) == ["M6x12"]


def test_negativa_garganta_del_calculo_distinta(ref):
    eng = copy.deepcopy(ref.eng)
    w = next(c for c in eng["checks"] if c["id"].startswith("W."))
    w["details"]["a_mm"] += 1
    assert next(i for i in _recheck(ref, eng=eng)["items"] if i["code"] == "XDOC-SOLDADURA-CALC")["level"] == "bloqueante"


def test_negativa_componente_comercial_sin_masa(ref):
    bom = copy.deepcopy(ref.bom)
    next(r for r in bom["rows"] if r["kind"] == "normalizado")["unit_mass"] = 0.0
    assert next(i for i in _recheck(ref, bom=bom)["items"] if i["code"] == "BOM-COMERCIALES")["level"] == "bloqueante"


def test_negativa_texto_de_otro_tipo_de_producto(ref):
    dfm = copy.deepcopy(ref.dfm) + [{"level": "advertencia", "code": "SOL-DEFORMACION", "element": "Estructura",
                                     "message": "verificar planitud de la superficie de apoyo de la encimera", "proposal": ""}]
    it = next(i for i in _recheck(ref, dfm=dfm)["items"] if i["code"] == "XDOC-TEXTOS-PRODUCTO")
    assert it["level"] == "bloqueante" and "encimera" in it["message"]
    assert qa_item(ref, "XDOC-TEXTOS-PRODUCTO")["level"] == "ok"


def test_negativa_geometria_invalida_bloquea():
    with pytest.raises(ValueError):
        optimize_bars([{"ref": "X", "length": 6100, "qty": 1}], bar_length=6000)
    n = nest_sheets([{"ref": "G", "w": 5000, "h": 3000, "qty": 1, "area": 1.5e7}], 2500, 1250)
    assert n["feasible"] is False


# ----------------------------------------------------------------------------- despiece de los planos y CSV
def test_despiece_de_los_planos_con_las_cifras_del_bom(ref, tmp_path, monkeypatch):
    """La hoja de despiece imprime dimensiones y pesos con las cifras del BOM (un tornillo de 3,8 g no puede salir
    «0» ni 157,95 kg salir «158»); el control de planos compara el peso impreso con el de cada pieza."""
    import pdfplumber
    from monxu.docs import plans
    from monxu.docs.drawing_kit import bom_num, fmt
    assert [bom_num(v) for v in (0.0038, 157.9545, 0.96, 1051.3, 2.0, 950, None)] == [
        "0,0038", "157,9545", "0,96", "1051,3", "2", "950", ""]
    info = {"product_name": "Estantería", "project_code": "P-2026-0039", "revision": "A", "date": "2026-11-11",
            "designer": "QA", "company": "MUEBLES MONXU",
            "status_stamp": AP.stamp("geometria_validada", ref.eng["status"], {})["text"]}
    dr = plans.generate(ref.model, ref.plan, ref.bom, ref.eng, info, tmp_path / "planos.pdf")
    cons = QA.drawing_consistency(ref.model, dr)
    assert cons["mismatches"] == []
    drawn = {dm["name"]: dm["value"] for sh in dr["sheets"] for dm in sh["dims"] if dm["name"].startswith("PESO_G_")}
    assert drawn == {f"PESO_G_{r['ref']}": pytest.approx(r["unit_mass"] * 1000, abs=1e-6) for r in ref.bom["rows"]}
    with pdfplumber.open(dr["path"]) as pdf:
        words = set((pdf.pages[-1].extract_text() or "").split())
    for r in ref.bom["rows"]:
        assert bom_num(r["unit_mass"]) in words and bom_num(r["total_mass"]) in words, r["ref"]
    # negativa: con el formato de cotas (el defecto corregido) el control de planos lo detecta y bloquea
    monkeypatch.setattr(plans, "bom_num", lambda v: "" if v is None else fmt(v, 2) if isinstance(v, float) else str(v))
    dr2 = plans.generate(ref.model, ref.plan, ref.bom, ref.eng, info, tmp_path / "planos_mal.pdf")
    bad = {m_["dim"] for m_ in QA.drawing_consistency(ref.model, dr2)["mismatches"]}
    assert {"PESO_G_N-TORNILLO_ISO7380_M6x10", "PESO_G_N-TUERCA_REMACHABLE_M6", "PESO_G_N-ANCLAJE_M8"} <= bad


def test_hoja_de_perfiles_sin_omitir_ni_truncar():
    """Hoja 02B: todos los perfiles (con hojas de continuación), todos sus taladros en líneas completas y todas las
    barras del plan de corte. Antes se cortaba el texto a 110 caracteres («890» salía «89») y se omitían sin aviso
    los perfiles a partir del undécimo y las barras que no cabían."""
    from monxu.core.model import ProfilePart
    from monxu.docs import plans
    d = regenerate("puesto_trabajo", _plantilla("puesto_trabajo", "PT-2000-TALLER"))
    profs = [p for p in d.model.parts.values() if isinstance(p, ProfilePart)]
    assert len(profs) > 10
    pages = plans.profile_flow(d.model, d.plan)
    assert len(pages) == 2
    drawn = [op[2] for ops in pages for op in ops if op[0] == "perfil"]
    assert sorted(p.ref for p in drawn) == sorted(p.ref for p in profs)
    for ops in pages:
        for op in ops:
            if op[0] == "perfil":
                _, y, p, w, lines = op
                assert y - plans.profile_extra_depth(len(lines)) >= plans.PROFILE_Y_MIN
                assert plans.hole_positions_in(lines) == len(p.holes)
                assert all(plans.text_width(ln, 2.4) <= 400 - (40 + w + 6) + 1e-6 for ln in lines)
    bars = sum(len(op[3]) for ops in pages for op in ops if op[0] == "barra")
    assert bars == sum(len(c["bars"]) for c in d.plan["cutting"])
    # posiciones con decimales: se separan con «;» (la coma es el separador decimal)
    assert plans.hole_positions_in(["Taladros Ø9,1 en cara exterior a: 60; 432,4; 804,8;", "1177,2; 1922"]) == 5
    # barras iguales consecutivas: una fila con su multiplicidad; un retal del inventario nunca se agrupa
    b = lambda n, src="comercial", rem=272.0: {"bar": n, "source": src, "stock_id": f"R-{n}" if src == "retal" else None,     # noqa: E731
                                              "length": 6000.0, "trim_start": 10.0, "n_cuts": 7, "remnant": rem,
                                              "remnant_status": "chatarra", "cuts": [{"ref": "X-01", "length": 950.0}] * 6}
    groups = plans.bar_groups({"bars": [b(1), b(2), b(3), b(4, rem=100.0), b(5, "retal"), b(6, "retal")]})
    assert [len(g) for g in groups] == [3, 1, 1, 1]
    assert plans.bar_label(groups[0]).startswith("Barras 1 a 3 (3 iguales): 7 cortes")
    assert plans.bar_label(groups[2]).startswith("Barra 5 (retal R-5): 7 cortes")


def test_negativa_plano_con_perfil_taladro_o_barra_ausente_o_texto_cortado(ref):
    """El control de planos detecta lo que debe figurar y no figura, y los textos de tabla cortados."""
    from monxu.docs import plans
    exp = plans.drawing_expected(ref.model, ref.plan)
    prof = next(p for p in ref.model.parts.values() if p.kind == "perfil" and p.holes)
    dims = ([{"name": f"L_{p.ref}", "value": p.length} for p in ref.model.parts.values() if p.kind == "perfil"]
            + [{"name": k, "value": v} for k, v in exp.items()]
            + [x for r in ref.bom["rows"] for x in ({"name": f"CANT_{r['ref']}", "value": r["qty"]},
                                                    {"name": f"PESO_G_{r['ref']}", "value": r["unit_mass"] * 1000})])
    ok = {"sheets": [{"number": "02B", "dims": dims}], "expected": exp, "announced": 1}
    assert QA.drawing_consistency(ref.model, ok)["mismatches"] == []

    def bad(change):
        dr = copy.deepcopy(ok)
        change(dr)
        return {(m_["dim"], m_["drawn"]) for m_ in QA.drawing_consistency(ref.model, dr)["mismatches"]}
    drop = lambda name: lambda dr: dr["sheets"][0].update(dims=[x for x in dims if x["name"] != name])     # noqa: E731
    assert bad(drop(f"L_{prof.ref}")) == {(f"L_{prof.ref}", None)}                 # perfil omitido de la hoja 02B
    assert bad(drop(f"TAL_{prof.ref}")) == {(f"TAL_{prof.ref}", None)}             # sus taladros sin listar
    assert bad(drop("BARRAS_1")) == {("BARRAS_1", None)}                           # plan de corte sin sus barras
    assert bad(drop(f"CANT_{ref.bom['rows'][-1]['ref']}")) == {(f"CANT_{ref.bom['rows'][-1]['ref']}", None)}

    def fewer_bars(dr):
        next(x for x in dr["sheets"][0]["dims"] if x["name"] == "BARRAS_1")["value"] -= 1
    assert bad(fewer_bars) == {("BARRAS_1", exp["BARRAS_1"] - 1)}                  # una barra sin dibujar
    assert bad(lambda dr: dr["sheets"][0].update(truncated=["N-TORNILLO_ISO7380_M6x10"])) == {("TEXTO_TRUNCADO", None)}
    assert bad(lambda dr: dr.update(announced=2)) == {("HOJAS", 1)}                # el cajetín anuncia otras hojas


def test_tabla_de_planos_parte_el_texto_en_lineas_y_no_lo_corta(tmp_path):
    from monxu.docs.drawing_kit import Drawing, text_width, wrap_text
    long = "Tornillo cabeza abombada hexágono interior M6x10 8.8 zincado"
    lines = wrap_text(long, 60.0, 2.2)
    assert len(lines) == 2 and " ".join(lines) == long and all(text_width(ln, 2.2) <= 60.0 for ln in lines)
    d = Drawing(str(tmp_path / "t.pdf"), {"product_name": "P", "project_code": "P-T", "revision": "A", "date": "2026-11-11",
                                          "designer": "QA", "company": "MUEBLES MONXU", "total_sheets": 1})
    d.new_sheet("T", "Tabla", "—")
    y = d.table(40, 260, [("Pos", 10, "c"), ("Descripción", 62.4, "l"), ("Ref", 20, "l")],
                [[1, long, "corta"], [2, "Pata", "N-TORNILLO_ISO7380_M6x10_MUY_LARGA_SIN_ESPACIOS"]], row_h=4.6, text_h=2.2)
    assert y == pytest.approx(260 - 6 - (4.6 + 1.5 * 2.2) - 4.6)   # la fila con dos líneas crece; nada se corta en ella
    assert d.page.get("truncated") == ["N-TORNILLO_ISO7380_M6x10_MUY_LARGA_SIN_ESPACIOS"]    # lo que ni reducido cabe, se registra
    d.finish()


def test_csv_del_expediente_con_coma_decimal_y_las_mismas_celdas_que_el_navegador(ref):
    """CSV de «;»: números con coma decimal y enteros sin «.0» (con punto, una hoja de cálculo en español leería
    110.702 kg como 110 702); filas de totales y de lotes con todas sus celdas."""
    from monxu import pipeline as PL
    assert [PL.csv_cell(v) for v in (6000.0, 110.702, 0, None, "RHS 40x20x2", -2.5)] == [
        "6000", "110,702", "0", "", "RHS 40x20x2", "-2,5"]
    txt = PL.csv_text(PL.QUOTE_HEADER, PL.quote_rows(ref.cost))
    assert txt.startswith("\ufeffPartida;Concepto;") and txt.endswith("\r\n")
    rows = [ln.split(";") for ln in txt.splitlines()]
    assert all(len(r) == len(PL.QUOTE_HEADER) for r in rows)
    direct = next(r for r in rows if r[1] == "Coste directo")
    assert direct[5] == PL.csv_cell(ref.cost["direct"]) and "." not in direct[5]
    lots = [r for r in rows if r[0] == "Lote"]
    assert len(lots) == len(ref.cost["by_lot"]) and all("." not in r[5] and " / " in r[5] for r in lots)
    bal = PL.csv_text(PL.BALANCE_HEADER, PL.balance_rows(ref.plan))
    import re
    assert not re.search(r"(^|;)-?\d+\.\d+(;|\r)", bal)          # ninguna celda numérica con punto decimal


# ----------------------------------------------------------------------------- estabilidad global y anclajes
def _plantilla(fid, tid):
    from monxu.families import family
    return next(t for t in family(fid).templates() if t["id"] == tid)["values"]


def test_estabilidad_global_anclada_queda_pendiente_de_validacion():
    """α_cr < 3 con el apoyo isostático y ≥ 3 con los apoyos anclados: se informan los dos valores y la comprobación
    queda PENDIENTE DE VALIDACIÓN (bloquea la liberación), nunca CUMPLE; el dimensionado no agota perfiles."""
    d = regenerate("cantilever", _plantilla("cantilever", "CV-3-2500-800-DOBLE"))
    c = next(k for k in d.eng["checks"] if k["id"] == "S.ALFA-CR-X")
    det = c["details"]
    assert c["status"] == "PENDIENTE_VALIDACION" and det["modelo_apoyos"] == "anclado"
    assert det["alpha_cr_isostatico"] < 3.0 <= c["value"] and det["delta_isostatico_mm"] > det["delta_mm"]
    assert det["cortante_taco_imperfeccion_N"] > 0 and "cortante" in det["validacion"]
    k = 1 / (1 - 1 / c["value"]) if c["value"] < 10 else 1.0     # amplificación con el α_cr adoptado
    assert det["k_amplificacion"] == pytest.approx(k, rel=2e-3)
    assert d.eng["status"] == "CUMPLE" and d.eng["verdict"] == "PENDIENTE DE VALIDACIÓN"
    assert not [n for n in d.model.design_notes if n["level"] == "error"]
    it = qa_item(d, "CALC-VAL-S.ALFA-CR-X")
    assert it["level"] == "pendiente" and it["release_block"]
    assert "CALC-VAL-S.ALFA-CR-X" in d.qa.result()["release_blockers"]
    assert any("apoyos anclados" in h and "PENDIENTE DE VALIDACIÓN" in h for h in d.eng["hypotheses"])
    # sin la validación registrada no se puede firmar el cálculo ni aprobar
    ev = AP.evaluate(d.qa.result(), d.eng["status"], None, {})
    assert "CALC-VAL-S.ALFA-CR-X" in ev["open_validations"] and "CALC-VAL-S.ALFA-CR-X" in ev["release_blockers"]
    assert not AP.can_sign(ev, "calculo")[0] and not AP.can_sign(ev, "aprobacion")[0]


def test_estabilidad_global_sin_anclar_no_cumple_y_la_correccion_dice_lo_que_queda_pendiente():
    vals = {"NUMERO_COLUMNAS": 4, "SEPARACION_COLUMNAS": 700, "ALTURA": 1200, "LONGITUD_BRAZO": 900, "CARAS": "dos",
            "NUMERO_NIVELES": 1, "ALTURA_PRIMER_NIVEL": 400, "ANCLAJE": "ninguno", "VUELO_BASE": 0,
            "CARGA_HORIZONTAL": 150}
    d = regenerate("cantilever", vals)
    bad = [c["id"] for c in d.eng["checks"] if c["status"] == "NO_CUMPLE"]
    assert d.eng["verdict"] == "NO CUMPLE" and bad == ["S.ALFA-CR-X"]
    c = next(k for k in d.eng["checks"] if k["id"] == "S.ALFA-CR-X")
    assert c["value"] < 3 and "modelo_apoyos" not in c["details"]          # sin tacos no hay modelo anclado
    assert d.qa.result()["blocking"] > 0
    # la corrección propuesta ancla al suelo y declara el veredicto real del diseño corregido: no dice «cumple»
    assert d.fix and d.fix["params"] == {"ANCLAJE": "al_suelo", "TACO_ANCLAJE": "auto"}
    assert d.fix["verdict"] == "PENDIENTE DE VALIDACIÓN" and d.fix["validation_pending"] >= 1
    assert "pendiente de validación" in d.fix["reasons"][0]
    d2 = regenerate("cantilever", {**vals, **d.fix["params"]})
    c2 = next(k for k in d2.eng["checks"] if k["id"] == "S.ALFA-CR-X")
    assert c2["status"] == "PENDIENTE_VALIDACION" and d2.eng["verdict"] == d.fix["verdict"]
    assert len(d2.eng["validation_pending"]) == d.fix["validation_pending"]


def test_optimizador_usa_retales_del_inventario_y_balancea():
    r = optimize_bars([{"ref": "A", "length": 950, "qty": 7}], stock=[{"id": "R1", "length": 1966}])
    assert r["stock_used"] == ["R1"] and r["n_bars"] == 1 and r["balance_mm"] == 0
    n = nest_sheets([{"ref": "P", "w": 50, "h": 50, "qty": 8, "area": 2397, "rotate": True}], 2000, 1000, 10, 8, 0.3)
    pu = sheet_purchase(n, [{"ref": "P", "w": 50, "h": 50, "qty": 8, "area": 2397, "rotate": True}])
    assert pu["n_custom"] == 1 and n["sheets"][0]["length"] * n["sheets"][0]["width"] < 2000 * 1000 * 0.05
    assert pu["purchased_area_m2"] == pytest.approx(pu["parts_area_m2"] + pu["waste_area_m2"] + pu["reusable_area_m2"])


# ----------------------------------------------------------------------------- aprobación técnica
def test_flujo_de_aprobacion_con_almacen(tmp_path, ref):
    from monxu.storage.db import Store
    st = Store(tmp_path)
    p = st.create_project("Ref", "estanteria_bateria", designer="Diseño")
    q = ref.qa.result()
    st.freeze_revision(p.code, "A", "Diseño", REF["params"], REF["sources"], ref.model.product_code,
                       ref.bom["totals"]["total_mass"], ref.eng["status"], q)
    ap = st.approval(p.code)
    assert ap["state"] == "geometria_validada" and "COMP-PIE_NIV_M10_D50" in ap["open_validations"]
    with pytest.raises(ValueError):                     # sin validar componentes no puede firmarse nada
        st.signoff(p.code, "A", "fabricabilidad", "Revisor")
    with pytest.raises(ValueError):                     # «validado» exige aprobación técnica
        st.set_status(p.code, "validado", "x", "Ing.")
    with pytest.raises(ValueError):                     # una validación exige referencia documental
        st.record_validation(p.code, "A", "COMP-PIE_NIV_M10_D50", "Ing. Calidad", "")
    for code in ap["open_validations"]:
        st.record_validation(p.code, "A", code, "Ing. Calidad", f"DOC-{code}")
    ap = st.approval(p.code)
    assert ap["state"] == "bom_validado"
    st.signoff(p.code, "A", "fabricabilidad", "Revisor")
    st.signoff(p.code, "A", "calculo", "Ing. Cálculo")
    assert st.approval(p.code)["state"] == "calculo_validado"
    with pytest.raises(ValueError):                     # sin expediente no puede aprobarse
        st.signoff(p.code, "A", "aprobacion", "Ing. Jefe")
    sig = st.approval(p.code)["records"]["signoffs"]
    assert set(sig) == {"fabricabilidad", "calculo"}


def test_revision_anterior_a_la_auditoria_no_puede_aprobarse():
    old_qa = {"items": [{"code": "GEO-VALIDA", "level": "ok"}], "blocking": 0}          # QA sin controles cruzados
    ev = AP.evaluate(old_qa, "CUMPLE", {"qa": old_qa, "state": None},
                     {"signoffs": {k: {"by": "x", "date": "2026-01-01"} for k in AP.SIGNOFFS}})
    assert ev["state"] == "diseno_generado" and "emita una revisión nueva" in ev["gates"][1]["reasons"][0]


def test_sello_segun_estado_de_aprobacion():
    assert "NO APTO" in AP.stamp("calculo_validado", "CUMPLE", {})["text"]
    assert AP.stamp("aprobado_tecnicamente", "CUMPLE", {"aprobacion": {"by": "Ing. Jefe", "date": "2026-11-10"}})["text"] \
        .startswith("APROBADO TÉCNICAMENTE — Ing. Jefe (2026-11-10)")
    assert AP.stamp("liberado_fabricacion", "NO_CUMPLE", {})["level"] == "error"            # un no cumple manda siempre


def test_migracion_de_estado_validado_antiguo(tmp_path):
    from sqlalchemy import text
    from monxu.storage.db import Store
    st = Store(tmp_path)
    p = st.create_project("Antiguo", "mesa_industrial")
    st.freeze_revision(p.code, "A", "x", {}, {}, "MI", 1.0, "CUMPLE", {"items": [], "blocking": 0})
    with st.engine.begin() as cx:                       # estado de un proyecto anterior a la auditoría
        cx.execute(text("UPDATE projects SET status='validado', validated_by='Ing. Antiguo'"))
        cx.execute(text("UPDATE counters SET value=1 WHERE name='schema_version'"))
    st2 = Store(tmp_path)
    q = st2.get(p.code)
    assert q.status == "pendiente_validacion"
    assert q.revisions[-1].approval["legacy"]["validated_by"] == "Ing. Antiguo"
