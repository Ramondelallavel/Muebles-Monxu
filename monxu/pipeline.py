"""Sincronización total: una única fuente de datos (parámetros → modelo CAD) de la que se derivan
cálculo, fabricación, BOM, planos y archivos. El expediente se genera de forma atómica: si
cualquier verificación bloqueante falla no se publica ningún archivo."""
from __future__ import annotations

import numbers
import hashlib
import json
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cadquery as cq

from . import catalog
from .cad import export as X
from .cad.interference import check_interferences
from .core.model import PlatePart, SheetPart
from .docs import dxf, excel, plans, report
from .docs.bom import build_bom
from .docs.dependencies import dependency_map
from .engineering.analysis import analyze
from .engineering.autofix import propose_fix
from .families import family
from .manufacturing.costing import quotation
from .manufacturing.plan import dfm_check, manufacturing_plan
from .validation import qa as QA

FOLDERS = ["01_MODELO_3D", "02_PLANOS", "03_DXF_CORTE", "04_LISTA_MATERIALES", "05_OPTIMIZACION", "06_DOCUMENTACION"]


class DossierError(RuntimeError):
    def __init__(self, message: str, qa: dict[str, Any] | None = None):
        super().__init__(message)
        self.qa = qa


@dataclass
class Design:
    family_id: str
    model: Any
    eng: dict[str, Any]
    plan: dict[str, Any]
    bom: dict[str, Any]
    dfm: list[dict[str, Any]]
    interferences: dict[str, Any]
    qa: QA.QA
    timings: dict[str, float] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    fix: dict[str, Any] | None = None          # corrección automática comprobada si el diseño NO CUMPLE

    @property
    def geometry_complete(self) -> bool:
        return self.qa.result()["blocking"] == 0

    @property
    def technically_verified(self) -> bool:
        """Solo con el cálculo completo y sin comprobaciones pendientes de validación."""
        return self.eng.get("verdict") == "CUMPLE"

    def summary(self) -> dict[str, Any]:
        m = self.model
        return {
            "family": self.family_id, "product_code": m.product_code,
            "parameters": m.parameter_table(),
            "requested": {k: v for k, v in m.requested.values.items()},
            "design_notes": m.design_notes, "feature_tree": m.feature_tree(), "component_tree": m.component_tree(),
            "engineering": self.eng, "manufacturing": self.plan, "bom": self.bom, "dfm": self.dfm,
            "interferences": self.interferences, "qa": self.qa.result(),
            "status": {"geometry_complete": self.geometry_complete, "technically_verified": self.technically_verified,
                       "structural": self.eng["status"], "structural_label": self.eng["status_label"]},
            "mass_kg": self.bom["totals"]["total_mass"], "timings": self.timings, "cost": self.cost, "fix": self.fix,
            "verdict": self.eng.get("verdict"), "dependencies": dependency_map(self.model),
            "catalog_versions": catalog.catalog_versions(),
        }


def regenerate(family_id: str, values: dict[str, Any], sources: dict[str, str] | None = None,
               stock: list[dict[str, Any]] | None = None) -> Design:
    """Regenera todo desde el modelo maestro. ``stock``: retales del inventario que pueden usar el plan de corte y el
    anidado (la revisión guarda la instantánea usada para que el expediente sea reproducible)."""
    t: dict[str, float] = {}
    t0 = time.perf_counter()
    fam = family(family_id)
    ps = fam.new_params()
    by_source: dict[str, dict[str, Any]] = {}
    for k, v in values.items():
        by_source.setdefault((sources or {}).get(k, "usuario"), {})[k] = v
    for src, vals in by_source.items():
        ps.update(vals, src)
    model = fam.build(ps)
    t["modelo"] = time.perf_counter() - t0
    t1 = time.perf_counter()
    for p in model.parts.values():       # geometría B-rep de todas las piezas
        p.shape
    t["geometria"] = time.perf_counter() - t1
    t1 = time.perf_counter()
    eng = analyze(model)
    t["calculo"] = time.perf_counter() - t1
    t1 = time.perf_counter()
    plan = manufacturing_plan(model, stock)
    dfm = dfm_check(model, plan)
    bom = build_bom(model, plan)
    t["fabricacion"] = time.perf_counter() - t1
    t1 = time.perf_counter()
    interf = check_interferences(model)
    t["interferencias"] = time.perf_counter() - t1
    cost = quotation(model, plan)
    q = QA.model_checks(model, interf, eng, dfm, bom, plan, cost)
    fix = None
    # corrección mínima de los valores fijados (cálculo o geometría), comprobada antes de ofrecerla
    if eng["status"] == "NO_CUMPLE" or model.rule_fixes:
        t1 = time.perf_counter()
        fix = propose_fix(family_id, values, sources, eng, model)
        t["correccion"] = time.perf_counter() - t1
    t["total"] = time.perf_counter() - t0
    return Design(family_id, model, eng, plan, bom, dfm, interf, q, {k: round(v, 3) for k, v in t.items()}, cost, fix)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def design_info(design: Design, project: dict[str, Any]) -> dict[str, Any]:
    """Cajetín y sello de los documentos. El sello sale del estado de aprobación de la revisión: ningún documento dice
    «verificado» o «aprobado» mientras las firmas correspondientes están vacías."""
    from .validation import approval as A
    m, eng = design.model, design.eng
    qa = design.qa.result()
    ap = project.get("approval") or {}
    sig = (ap.get("records") or {}).get("signoffs") or {}
    state = ap.get("state") or "diseno_generado"
    st = A.stamp(state, eng["status"], sig)
    return {
        "product_name": f"{m.family_name} {m.product_code}", "project_code": project["code"],
        "revision": project["revision"], "date": project.get("date") or time.strftime("%Y-%m-%d"),
        "designer": project.get("designer", ""), "checked": (sig.get("calculo") or {}).get("by") or "—",
        "approved": (sig.get("aprobacion") or {}).get("by") or "—", "client": project.get("client", ""),
        "company": project.get("company", "MUEBLES MONXU"), "assembly_ref": m.product_code,
        "tolerances": m.params.values.get("TOLERANCIAS", "ISO 2768-mK"), "status_stamp": st["text"],
        "status_level": st["level"], "qa_result": qa["result"], "approval_state": state,
        "approval_label": A.LABELS[state], "structural_verdict": eng.get("verdict"),
    }


def generate_dossier(design: Design, project: dict[str, Any], dest_root: Path,
                     history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    pre = design.qa.result()
    if pre["blocking"]:
        raise DossierError("El diseño tiene errores bloqueantes: no se genera documentación incoherente.", pre)
    m = design.model
    info = design_info(design, project)
    name = f"{project['code']}_{m.product_code}_Rev{project['revision']}"
    dest_root.mkdir(parents=True, exist_ok=True)
    final = dest_root / name
    if final.exists() and project.get("edition"):      # nueva edición tras la aprobación: se conserva la anterior
        k = 1
        while (dest_root / f"{name}_ed{k}").exists():
            k += 1
        final.rename(dest_root / f"{name}_ed{k}")
        if (dest_root / f"{name}.zip").exists():
            (dest_root / f"{name}.zip").rename(dest_root / f"{name}_ed{k}.zip")
    if final.exists():
        raise DossierError(f"Ya existe el expediente {name}: las revisiones anteriores no se sobrescriben.")
    tmp = dest_root / f".{name}.tmp-{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()
    try:
        dirs = {f: tmp / f for f in FOLDERS}
        for d in dirs.values():
            d.mkdir(parents=True)
        (dirs["01_MODELO_3D"] / "componentes").mkdir()
        (dirs["03_DXF_CORTE"] / "anidado").mkdir()
        files: dict[str, Any] = {}
        code = m.product_code
        # ---- 01 modelo 3D
        step = X.export_step_assembly(m, dirs["01_MODELO_3D"] / f"{code}_conjunto.step")
        for p in m.parts.values():
            X.export_step_part(p, dirs["01_MODELO_3D"] / "componentes" / f"{p.ref}.step")
        stl = X.export_stl(m, dirs["01_MODELO_3D"] / f"{code}_conjunto.stl")
        files["stl"] = {**X.verify_stl(stl), "model_volume": sum(i.part.volume for i in m.instances),
                        "model_bbox": [list(map(float, v)) for v in m.bounding_box()]}
        X.export_brep(m, dirs["01_MODELO_3D"] / f"{code}_conjunto.brep")
        X.export_glb(m, dirs["01_MODELO_3D"] / f"{code}_visualizacion.glb")
        native = {"format": "monxu-parametrico", "version": 1, "family": design.family_id,
                  "parameters": m.params.values, "sources": m.params.sources,
                  "requested": m.requested.values, "catalog_versions": catalog.catalog_versions(),
                  "product_code": code, "feature_tree": m.feature_tree(),
                  "note": "Formato editable nativo: abrir con la plataforma para regenerar la geometría paramétrica."}
        (dirs["01_MODELO_3D"] / f"{code}_parametrico.json").write_text(
            json.dumps(native, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        re = cq.importers.importStep(str(step)).solids().vals()
        files["step"] = {"solids": len(re), "volume": sum(s.Volume() for s in re),
                         "model_volume": sum(i.part.volume for i in m.instances),
                         # una pieza puede tener varios cuerpos (rueda: espiga y horquilla + rueda)
                         "model_solids": sum(len(i.part.shape.Solids()) for i in m.instances)}
        # ---- 02 planos
        dr = plans.generate(m, design.plan, design.bom, design.eng, info, dirs["02_PLANOS"] / f"{code}_planos.pdf")
        cons = QA.drawing_consistency(m, dr)
        import pdfplumber
        with pdfplumber.open(dr["path"]) as pdf:
            npages = len(pdf.pages)
        files["drawings"] = {"pages": npages, "expected_pages": dr["total"], **cons}
        # ---- 03 DXF
        files["dxf"] = []
        for p in m.parts.values():
            if isinstance(p, (SheetPart, PlatePart)):
                r = dxf.export_part_dxf(p, dirs["03_DXF_CORTE"] / f"{p.ref}.dxf", project)
                exp = (p.flat.width, p.flat.height) if isinstance(p, SheetPart) else (p.w, p.h)
                files["dxf"].append({**r, "file": f"{p.ref}.dxf", "expected": exp})
        refs = {p.ref: p for p in m.parts.values()}
        files["nesting_dxf"] = []
        for n in design.plan["nesting"]:
            if n.get("feasible"):
                paths = dxf.export_nesting_dxf(n, refs, str(dirs["03_DXF_CORTE"] / "anidado" /
                                                            f"anidado_{n['material']}_{n['thickness']:g}mm_{{n}}.dxf"))
                for pth, sh in zip(paths, n["sheets"]):
                    files["nesting_dxf"].append({**dxf.verify_nesting_dxf(pth), "file": pth.name,
                                                 "expected_parts": len(sh["placements"]),
                                                 "expected_format": (sh["length"], sh["width"])})
        # ---- 04 lista de materiales
        q = QA.QA()
        q.items = list(design.qa.items)
        xl = excel.export_excel(dirs["04_LISTA_MATERIALES"] / f"{code}_BOM.xlsx", info, design.bom, design.plan,
                                design.eng, design.qa.result(), design.cost)
        files["excel"] = excel.verify_excel(xl, design.bom)
        lot = design.plan.get("lot", 1)
        _csv(dirs["04_LISTA_MATERIALES"] / "lista_compras.csv", PURCHASE_HEADER, purchase_rows(design.bom, lot))
        c = design.cost
        if c:
            _csv(dirs["04_LISTA_MATERIALES"] / "presupuesto_estimado.csv", QUOTE_HEADER, quote_rows(c))
            (dirs["04_LISTA_MATERIALES"] / "presupuesto_estimado.json").write_text(
                json.dumps(c, indent=2, ensure_ascii=False), encoding="utf-8")
        _csv(dirs["04_LISTA_MATERIALES"] / "pesos_materiales.csv", WEIGHT_HEADER, weight_rows(design.bom))
        # ---- 05 optimización
        report.optimization_pdf(dirs["05_OPTIMIZACION"] / "anidado_chapa.pdf", info, m, design.plan)
        _csv(dirs["05_OPTIMIZACION"] / "plan_corte_perfiles.csv", CUT_PLAN_HEADER, cut_plan_rows(design.plan))
        _csv(dirs["05_OPTIMIZACION"] / "balance_material.csv", BALANCE_HEADER, balance_rows(design.plan))
        (dirs["05_OPTIMIZACION"] / "aprovechamientos.json").write_text(json.dumps(
            optimization_summary(design.plan), indent=2, ensure_ascii=False), encoding="utf-8")
        # ---- 06 documentación
        q = QA.export_checks(q, m, files, design.bom)
        qa_final = q.result()
        report.engineering_report(dirs["06_DOCUMENTACION"] / "informe_calculo_y_verificaciones.pdf", info, m,
                                  design.eng, design.dfm, qa_final, history)
        from .docs.drawing_kit import Drawing
        d = Drawing(str(dirs["06_DOCUMENTACION"] / "instrucciones_montaje.pdf"), dict(info, total_sheets=1))
        plans.plan_assembly(d, plans._Ctx(m, design.plan, design.bom, design.eng, info))
        d.finish()
        shutil.copy(dirs["02_PLANOS"] / f"{code}_planos.pdf", dirs["06_DOCUMENTACION"] / "documentacion_tecnica.pdf")
        (dirs["06_DOCUMENTACION"] / "historial_revisiones.json").write_text(
            json.dumps(history or [], indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        (dirs["06_DOCUMENTACION"] / "informe_verificaciones.json").write_text(
            json.dumps({"qa": qa_final, "engineering": design.eng, "dfm": design.dfm,
                        "interferences": design.interferences}, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        if qa_final["blocking"]:
            raise DossierError("La verificación de los archivos exportados ha fallado: no se publica el expediente.",
                               qa_final)
        manifest = {"dossier": name, "project": project["code"], "revision": project["revision"],
                    "product": code, "family": design.family_id, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "status": info["status_stamp"], "approval_state": info["approval_state"],
                    "structural": design.eng["status"], "structural_verdict": design.eng.get("verdict"),
                    "qa": qa_final["summary"], "release_blockers": qa_final.get("release_blockers", []),
                    "parameters": m.params.values, "files": []}
        for f in sorted(tmp.rglob("*")):
            if f.is_file():
                manifest["files"].append({"path": str(f.relative_to(tmp)), "bytes": f.stat().st_size,
                                          "sha256": _sha(f)})
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
                                           encoding="utf-8")
        tmp.rename(final)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    zpath = dest_root / f"{name}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(final.rglob("*")):
            if f.is_file():
                z.write(f, Path(name) / f.relative_to(final))
    return {"name": name, "path": str(final), "zip": str(zpath), "qa": qa_final, "files": manifest["files"],
            "approval_state": info["approval_state"], "edition": bool(project.get("edition")),
            "verification": files, "seconds": round(time.perf_counter() - t0, 1), "info": info}


CUT_PLAN_HEADER = ["Perfil", "Material", "Barra", "Origen", "Long. barra mm", "Despunte inicial mm", "Piezas (ref:long)",
                   "Nº piezas", "Nº cortes", "Ancho sierra mm", "Sierra total mm", "Σ piezas mm", "Despunte final mm",
                   "Retal final mm", "Estado del retal", "Balance mm"]
BALANCE_HEADER = ["Tipo", "Grupo", "Unidad", "Comprado", "De inventario", "Neto en piezas", "Desperdicio no recuperable",
                  "Retal reutilizable", "Comprado kg", "De inventario kg", "Neto kg", "Desperdicio kg", "Retal kg",
                  "Balance"]


PURCHASE_HEADER = ["Tipo", "Descripción", "Referencia", "Cantidad", "Unidad", "Masa kg", "Origen", "Validación", "Lote"]
QUOTE_HEADER = ["Partida", "Concepto", "Cantidad", "Unidad", "Precio unitario EUR", "Importe EUR", "Base"]
WEIGHT_HEADER = ["Pos", "Referencia", "Descripción", "Material", "Cantidad", "Peso unit kg", "Peso total kg"]


def purchase_rows(bom: dict[str, Any], lot: int) -> list[list[Any]]:
    """Lista de compras del lote: material, componentes comerciales y consumibles (= docs.purchaseRows)."""
    return ([[p["type"], p["description"], p.get("ref", ""), p["qty"], p["unit"], p["mass_kg"], p.get("basis", ""),
              p.get("validation", ""), lot] for p in bom["purchases"]]
            + [["Consumible", c["description"], "", c["qty"], c["unit"], "", c.get("basis", ""), "", lot]
               for c in bom["consumables"]])


def quote_rows(c: dict[str, Any]) -> list[list[Any]]:
    """Presupuesto estimado: partidas, totales y coste por lote (mismas celdas que el motor del navegador)."""
    return ([[ln["group"], ln["concept"], ln["qty"], ln["unit"], ln["unit_eur"], ln["eur"], ln.get("basis", "")]
             for ln in c["lines"]]
            + [["", "Coste directo", "", "", "", c["direct"], ""],
               ["", f"Gastos generales {c['overhead_rate'] * 100:g} %", "", "", "", c["overheads"], ""],
               ["", "Coste total", "", "", "", c["cost"], ""],
               ["", f"Margen {c['margin_rate'] * 100:g} %", "", "", "", c["margin"], ""],
               ["", "Precio de venta estimado", "", "", "", c["price"], f"material: {c['material_basis']}"]]
            + [["Lote", f"{x['lot']} ud", "", "", "coste/precio por unidad",
                f"{csv_cell(x['cost'])} / {csv_cell(x['price'])}", ""] for x in c["by_lot"]])


def weight_rows(bom: dict[str, Any]) -> list[list[Any]]:
    return [[r["pos"], r["ref"], r["description"], r["material"], r["qty"], r["unit_mass"], r["total_mass"]]
            for r in bom["rows"]] + weight_summary_rows(bom)


def cut_plan_rows(plan: dict[str, Any]) -> list[list[Any]]:
    """Plan de corte barra a barra: L = despunte inicial + Σ piezas + sierra + despunte final + retal."""
    return [[c["profile"], c["material"], b["bar"], f"retal {b['stock_id']}" if b["source"] == "retal" else "comercial",
             b["length"], b["trim_start"], " + ".join(f"{x['ref']}:{x['length']:g}" for x in b["cuts"]), b["n_pieces"],
             b["n_cuts"], c["kerf"], b["kerf_total"], b["used"], b["trim_end"], b["remnant"], b["remnant_status"],
             b["balance_mm"]] for c in plan["cutting"] for b in c["bars"]]


def balance_rows(plan: dict[str, Any]) -> list[list[Any]]:
    rows = [[r["kind"], r["group"], r["unit"], r["purchased"], r["from_stock"], r["net"], r["waste"], r["reusable"],
             r["purchased_kg"], r["from_stock_kg"], r["net_kg"], r["waste_kg"], r["reusable_kg"], r["balance"]]
            for r in plan["balance"]["rows"]]
    t = plan["balance"]["totals"]
    return rows + [["total", f"lote de {plan.get('lot', 1)}", "kg", "", "", "", "", "", t["purchased_kg"],
                    t["from_stock_kg"], t["net_kg"], t["waste_kg"], t["reusable_kg"], ""]]


def weight_summary_rows(bom: dict[str, Any]) -> list[list[Any]]:
    """Masas separadas: producto (por unidad) y material en bruto del lote; nunca se suman entre sí."""
    t = bom["totals"]
    lot = t.get("material_lot", 1)
    return [["", "", "Masa neta de piezas fabricadas (por unidad)", "", "", "", t["mass_manufactured_kg"]],
            ["", "", "Masa de componentes comerciales (por unidad)", "", "", "", t["mass_commercial_kg"]],
            ["", "", "Masa total del producto (por unidad)", "", "", "", t["mass_product_kg"]],
            ["", "", f"Material en bruto comprado (lote de {lot})", "", "", "", t["mass_purchased_kg"]],
            ["", "", f"Material de retales del inventario (lote de {lot})", "", "", "", t["mass_from_stock_kg"]],
            ["", "", f"Desperdicio no recuperable (lote de {lot})", "", "", "", t["mass_waste_kg"]],
            ["", "", f"Retales reutilizables al inventario (lote de {lot})", "", "", "", t["mass_reusable_kg"]]]


def optimization_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "lote": plan.get("lot", 1), "parametros_corte": plan.get("cutting_params"),
        "perfiles": [{k: c[k] for k in ("profile", "material", "n_bars", "n_stock_used", "stock_used", "lower_bound",
                                        "pieces", "n_cuts", "pieces_length", "purchased_length", "stock_length",
                                        "kerf_total", "trim_total", "scrap_remnant_length", "reusable_length",
                                        "waste_length", "balance_mm", "utilization", "reusable_remnants")}
                     for c in plan["cutting"]],
        "chapa": [{**{k: n.get(k) for k in ("material", "thickness", "format", "n_sheets", "utilization", "waste_m2")},
                   "compra": n.get("purchase")} for n in plan["nesting"]],
        "balance": plan["balance"]}


def csv_cell(c: Any) -> str:
    """Celda de los CSV del expediente, igual en los dos motores: separador «;», de modo que los números van con coma
    decimal y los enteros sin «.0» (con punto, una hoja de cálculo en español leería 110.702 kg como 110 702)."""
    if c is None:
        return ""
    if isinstance(c, bool) or not isinstance(c, numbers.Real):
        return str(c)
    f = float(c)
    return (str(int(f)) if f.is_integer() else repr(f)).replace(".", ",")


def csv_text(header: list[str], rows: list[list[Any]]) -> str:
    """Texto de un CSV del expediente (BOM de UTF-8, separador «;», fin de línea CRLF), igual en los dos motores."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows([[csv_cell(c) for c in r] for r in rows])
    return "\ufeff" + buf.getvalue()


def _csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(csv_text(header, rows))
