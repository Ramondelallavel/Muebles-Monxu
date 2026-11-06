"""Libro Excel de fabricación con fórmulas y tablas (openpyxl)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

HEAD = PatternFill("solid", fgColor="1F3A5F")
SUB = PatternFill("solid", fgColor="DCE6F1")
THIN = Side(style="thin", color="9AA7B5")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _header(ws, info: dict[str, Any], title: str) -> int:
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14, color="1F3A5F")
    rows = [("Proyecto", info.get("project_code")), ("Producto", info.get("product_name")),
            ("Revisión", info.get("revision")), ("Fecha", info.get("date")), ("Cliente", info.get("client"))]
    for k, (a, b) in enumerate(rows, start=2):
        ws.cell(k, 1, a).font = Font(bold=True)
        ws.cell(k, 2, b)
    return len(rows) + 3


def _table(ws, r0: int, headers: list[str], rows: list[list[Any]], name: str, widths: list[int] | None = None,
           formats: dict[int, str] | None = None) -> tuple[int, int]:
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(r0, c, h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, row in enumerate(rows, start=1):
        for c, v in enumerate(row, start=1):
            cell = ws.cell(r0 + i, c, v)
            cell.border = BORDER
            if formats and c in formats:
                cell.number_format = formats[c]
    last = r0 + max(1, len(rows))
    if rows:
        ref = f"A{r0}:{get_column_letter(len(headers))}{last}"
        t = Table(displayName=name, ref=ref)
        t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(t)
    for c, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(r0 + 1, 1)
    return r0, last


def export_excel(path: Path, info: dict[str, Any], bom: dict[str, Any], plan: dict[str, Any],
                 eng: dict[str, Any], qa: dict[str, Any] | None = None) -> Path:
    wb = Workbook()
    # ------------------------------------------------------------------ BOM
    ws = wb.active
    ws.title = "BOM"
    r0 = _header(ws, info, "LISTA DE MATERIALES (BOM)")
    headers = ["Posición", "Referencia", "Descripción", "Material", "Espesor (mm)", "Largo (mm)", "Ancho (mm)",
               "Cantidad", "Peso unitario (kg)", "Peso total (kg)", "Tipo", "Proceso", "Acabado"]
    rows = []
    for k, r in enumerate(bom["rows"], start=r0 + 1):
        rows.append([r["pos"], r["ref"], r["description"], r["material"], r["thickness"], r["length"], r["width"],
                     r["qty"], r["unit_mass"], f"=H{k}*I{k}", r["kind_label"], r["process"], r["finish"]])
    _, last = _table(ws, r0, headers, rows, "BOM", [9, 22, 52, 22, 11, 11, 11, 10, 15, 15, 20, 48, 40],
                     {9: "0.0000", 10: "0.0000", 5: "0.0", 6: "0.0", 7: "0.0"})
    tr = last + 2
    ws.cell(tr, 7, "TOTALES").font = Font(bold=True)
    ws.cell(tr, 8, f"=SUBTOTAL(109,H{r0 + 1}:H{last})").font = Font(bold=True)
    ws.cell(tr, 10, f"=SUBTOTAL(109,J{r0 + 1}:J{last})").font = Font(bold=True)
    ws.cell(tr, 10).number_format = "0.000"
    ws.cell(tr + 1, 7, "Componentes fabricados")
    ws.cell(tr + 1, 8, f'=SUMIF(K{r0 + 1}:K{last},"<>Elemento normalizado",H{r0 + 1}:H{last})')
    ws.cell(tr + 2, 7, "Elementos normalizados")
    ws.cell(tr + 2, 8, f'=SUMIF(K{r0 + 1}:K{last},"Elemento normalizado",H{r0 + 1}:H{last})')
    # ------------------------------------------------------------------ perfiles
    wp = wb.create_sheet("Perfiles")
    r0 = _header(wp, info, "METROS DE PERFIL")
    rows = []
    prows = [r for r in bom["rows"] if r["kind"] == "perfil"]
    for k, r in enumerate(prows, start=r0 + 1):
        rows.append([r["ref"], r["section"], r["material"], r["length"], r["qty"], f"=D{k}*E{k}/1000",
                     r["unit_mass"], f"=E{k}*G{k}"])
    _, last = _table(wp, r0, ["Referencia", "Sección", "Material", "Longitud (mm)", "Cantidad", "Metros (m)",
                              "Peso unit. (kg)", "Peso total (kg)"], rows, "Perfiles",
                     [22, 16, 14, 14, 10, 12, 14, 14], {6: "0.000", 7: "0.000", 8: "0.000"})
    rr = last + 2
    wp.cell(rr, 1, "Resumen por sección").font = Font(bold=True)
    for n, sec in enumerate(sorted({r["section"] for r in prows}), start=1):
        wp.cell(rr + n, 2, sec)
        wp.cell(rr + n, 6, f'=SUMIF(B{r0 + 1}:B{last},B{rr + n},F{r0 + 1}:F{last})').number_format = "0.000"
    # ------------------------------------------------------------------ plan de corte
    wc = wb.create_sheet("Plan de corte")
    r0 = _header(wc, info, "PLAN DE CORTE DE BARRAS")
    rows = []
    for c in plan["cutting"]:
        for b in c["bars"]:
            rows.append([c["profile"], c["material"], b["bar"], c["bar_length"], len(b["cuts"]),
                         " + ".join(f"{x['ref'].split('-')[-1]}:{x['length']:g}" for x in b["cuts"]), b["used"],
                         b["kerf_loss"], b["remnant"], "Sí" if b["remnant_reusable"] else "No"])
    _, last = _table(wc, r0, ["Perfil", "Material", "Barra", "Long. barra (mm)", "Nº cortes", "Cortes (pos:long)",
                              "Útil (mm)", "Pérdida sierra+refrentado (mm)", "Retal (mm)", "Retal aprovechable"],
                     rows, "PlanCorte", [14, 12, 8, 14, 10, 70, 12, 16, 12, 14])
    k = last + 2
    wc.cell(k, 6, "Aprovechamiento global").font = Font(bold=True)
    wc.cell(k, 7, f"=SUM(G{r0 + 1}:G{last})/SUM(D{r0 + 1}:D{last})").number_format = "0.0%"
    # ------------------------------------------------------------------ chapa
    wn = wb.create_sheet("Anidado chapa")
    r0 = _header(wn, info, "ANIDADO DE CHAPA")
    rows = []
    for n in plan["nesting"]:
        if not n.get("feasible"):
            rows.append([n["material"], n["thickness"], "—", 0, None, None, None, n.get("reason")])
            continue
        for s in n["sheets"]:
            rows.append([n["material"], n["thickness"], n["format"], s["sheet"], len(s["placements"]),
                         round(s["parts_area_mm2"] / 1e6, 4), round(n["length"] * n["width"] / 1e6, 4),
                         ", ".join(p["ref"].split("-")[-1] + ("(R)" if p["rot"] else "") for p in s["placements"])])
    rws = []
    for k2, r in enumerate(rows, start=r0 + 1):
        rws.append(r[:7] + [f"=IFERROR(F{k2}/G{k2},0)", r[7]])
    _table(wn, r0, ["Material", "Espesor (mm)", "Formato", "Chapa nº", "Piezas", "Superficie piezas (m²)",
                    "Superficie chapa (m²)", "Aprovechamiento", "Piezas (R = girada)"], rws, "Anidado",
           [12, 12, 12, 9, 8, 18, 18, 15, 50], {6: "0.0000", 7: "0.0000", 8: "0.0%"})
    # ------------------------------------------------------------------ compras
    wb_ = wb.create_sheet("Compras")
    r0 = _header(wb_, info, "LISTA DE COMPRAS")
    rows = [[p["type"], p["description"], p["qty"], p["unit"], p["mass_kg"]] for p in bom["purchases"]]
    _, last = _table(wb_, r0, ["Tipo", "Descripción", "Cantidad", "Unidad", "Masa (kg)"], rows, "Compras",
                     [26, 80, 10, 10, 12], {5: "0.00"})
    wb_.cell(last + 2, 4, "Total").font = Font(bold=True)
    wb_.cell(last + 2, 5, f"=SUBTOTAL(109,E{r0 + 1}:E{last})").number_format = "0.00"
    k = last + 4
    wb_.cell(k, 1, "CONSUMIBLES").font = Font(bold=True)
    for n, cdat in enumerate(bom["consumables"], start=1):
        wb_.cell(k + n, 2, cdat["description"])
        wb_.cell(k + n, 3, cdat["qty"])
        wb_.cell(k + n, 4, cdat["unit"])
    # ------------------------------------------------------------------ verificaciones
    wv = wb.create_sheet("Verificaciones")
    r0 = _header(wv, info, "VERIFICACIONES ESTRUCTURALES (CÁLCULO PRELIMINAR AUTOMATIZADO)")
    wv.cell(r0 - 1, 1, eng["status_label"]).font = Font(bold=True, color="B00020" if eng["status"] != "CUMPLE" else "1B5E20")
    rows = [[c["id"], c["category"], c["description"], c["standard"], c["combination"], c["value"], c["limit"],
             c["unit"], c["utilization"], c["status"]] for c in eng["checks"]]
    _table(wv, r0, ["Id", "Categoría", "Comprobación", "Referencia", "Comb.", "Valor", "Límite", "Unidad",
                    "Aprovechamiento", "Estado"], rows, "Verificaciones", [26, 12, 70, 34, 8, 10, 10, 8, 14, 14],
           {9: "0.000"})
    if qa:
        wq = wb.create_sheet("Control de calidad")
        r0 = _header(wq, info, "CONTROL DE CALIDAD PREVIO A EXPORTACIÓN")
        rows = [[q["level"], q["code"], q["message"]] for q in qa["items"]]
        _table(wq, r0, ["Nivel", "Código", "Descripción"], rows, "QA", [16, 26, 120])
    wb.save(path)
    return path


def verify_excel(path: Path, bom: dict[str, Any]) -> dict[str, Any]:
    """Relee el libro y comprueba que los valores coinciden con el BOM (las fórmulas se recalculan aquí)."""
    wb = load_workbook(path)
    ws = wb["BOM"]
    hdr_row = next(r for r in range(1, 20) if ws.cell(r, 1).value == "Posición")
    total_mass = 0.0
    qty = 0
    formulas_ok = True
    r = hdr_row + 1
    while ws.cell(r, 1).value is not None:
        q, um, f = ws.cell(r, 8).value, ws.cell(r, 9).value, ws.cell(r, 10).value
        formulas_ok &= isinstance(f, str) and f.startswith("=H")
        qty += q
        total_mass += q * um
        r += 1
    expected = sum(rw["unit_mass"] * rw["qty"] for rw in bom["rows"])      # lo que calcula Excel con sus fórmulas
    tol_round = 0.00005 * bom["totals"]["components"] + 0.0005             # redondeo de masas unitarias a 0,1 g
    return {"rows": r - hdr_row - 1, "qty": qty, "total_mass": round(total_mass, 4), "formulas": formulas_ok,
            "sheets": wb.sheetnames, "matches_bom": abs(total_mass - expected) < 1e-6 and
            abs(total_mass - bom["totals"]["total_mass"]) <= tol_round and qty == bom["totals"]["components"]}
