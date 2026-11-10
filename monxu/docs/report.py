"""Informes PDF: cálculo y verificaciones, y plan de optimización (anidado y corte)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core.model import PlatePart, SheetPart
from .dxf import sheet_label
from .drawing_kit import LW_THICK, LW_THIN, Drawing, fmt

ST = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ST["Heading1"], fontSize=15, textColor=colors.HexColor("#1F3A5F"))
H2 = ParagraphStyle("h2", parent=ST["Heading2"], fontSize=11.5, textColor=colors.HexColor("#1F3A5F"), spaceBefore=8)
P = ParagraphStyle("p", parent=ST["BodyText"], fontSize=8.6, leading=11)
S = ParagraphStyle("s", parent=P, fontSize=7.4, leading=9)
STATUS_COL = {"CUMPLE": "#1B5E20", "NO_CUMPLE": "#B00020", "PENDIENTE": "#8D6E00", "ADVERTENCIA": "#8D6E00",
              "ok": "#1B5E20", "bloqueante": "#B00020", "advertencia": "#8D6E00", "pendiente": "#8D6E00"}


def _tbl(data, widths, head=True, small=True):
    style = S if small else P
    rows = [[Paragraph(str(c) if c is not None else "—", style) for c in r] for r in data]
    t = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1 if head else 0)
    ts = [("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9AA7B5")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if head:
        ts += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F1"))]
    t.setStyle(TableStyle(ts))
    return t


def _st(s):
    return f'<font color="{STATUS_COL.get(s, "#000000")}"><b>{s}</b></font>'


def engineering_report(path: Path, info: dict[str, Any], model, eng: dict[str, Any], dfm: list, qa: dict | None,
                       history: list[dict] | None = None) -> Path:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=14 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title="Informe de cálculo y verificaciones",
                            author=info.get("designer", ""))
    el = []

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.drawString(16 * mm, 9 * mm, f"{info.get('project_code')} · {info.get('product_name')} · Rev. {info.get('revision')}"
                                      f" · {info.get('date')}")
        c.drawRightString(196 * mm, 9 * mm, f"Página {d.page}")
        c.restoreState()

    el.append(Paragraph("Informe de cálculo y verificaciones", H1))
    el.append(Paragraph(f"<b>{info.get('product_name')}</b> — proyecto {info.get('project_code')}, revisión "
                        f"{info.get('revision')}, {info.get('date')}. Cliente: {info.get('client') or '—'}.", P))
    el.append(Spacer(1, 4))
    el.append(Paragraph(f"Estado: {_st(eng['status'])} — {eng['status_label']}", P))
    el.append(Paragraph(f"<b>{eng['validation_note']}</b>", P))
    g = eng.get("governing")
    if g:
        el.append(Paragraph(f"Comprobación determinante: {g['description']} — aprovechamiento "
                            f"{g['utilization']:.3f} ({g['status']}).", P))
    el.append(Paragraph("1. Normas y referencias", H2))
    el.append(Paragraph(", ".join(eng["standards"]), P))
    el.append(Paragraph("2. Materiales y propiedades mecánicas", H2))
    el.append(_tbl([["Código", "Material", "Norma", "E (MPa)", "fy (MPa)", "fu (MPa)", "ρ (kg/m³)", "fy garantizado"]] +
                   [[m["code"], m["name"], m["standard"], m["E"], m["fy"], m["fu"], m["density"],
                     "sí" if m["fy_guaranteed"] else "NO (hipótesis)"] for m in eng["materials"]],
                   [20, 52, 26, 15, 14, 14, 16, 20]))
    el.append(Paragraph("3. Secciones (propiedades calculadas desde la geometría de la sección)", H2))
    el.append(_tbl([["Perfil", "A (mm²)", "Iy (cm⁴)", "Iz (cm⁴)", "Wpl,y (cm³)", "Wpl,z (cm³)"]] +
                   [list(s) for s in eng["sections"]], [32, 24, 24, 24, 26, 26]))
    el.append(Paragraph("4. Hipótesis de cálculo", H2))
    for h in eng["hypotheses"]:
        el.append(Paragraph("• " + h, P))
    el.append(Paragraph("5. Condiciones de contorno", H2))
    el.append(_tbl([["Apoyo", "Nodo", "Punto (mm)", "Tipo", "Coacción"]] +
                   [[b["support"], b["node"], ", ".join(f"{v:.1f}" for v in b["point"]), b["type"], b.get("restraint")]
                    for b in eng["boundary_conditions"]], [40, 14, 60, 24, 24]))
    el.append(Paragraph("6. Casos de carga y combinaciones", H2))
    el.append(_tbl([["Caso", "Descripción", "Valor", "Total (N)"]] +
                   [[c["id"], c["label"], c["value"], c["total_N"]] for c in eng["load_cases"]], [20, 90, 40, 24]))
    pf = eng["partial_factors"]
    el.append(Paragraph(f"Coeficientes parciales: γG = {pf['gamma_G']}, γQ = {pf['gamma_Q']}, ψ0 = {pf['psi0_Q']}, "
                        f"γG,stb = {pf['gamma_G_stb']} (EQU). Coeficientes de material según la tabla 2.", P))
    combos = [[k, " + ".join(f"{v:g}·{c}" for c, v in f.items())] for k, f in {**eng["combinations"]["ELU"],
                                                                                **eng["combinations"]["ELS"]}.items()]
    el.append(_tbl([["Combinación", "Factores"]] + combos, [30, 140]))
    el.append(Paragraph(f"Modelo de barras: {eng['fem']['nodes']} nodos, {eng['fem']['elements']} elementos, "
                        f"{eng['fem']['dof']} grados de libertad.", P))
    el.append(Paragraph("7. Resultados de las comprobaciones", H2))
    rows = [["Comprobación", "Referencia", "Comb.", "Valor", "Límite", "Aprov.", "Estado"]]
    for c in eng["checks"]:
        rows.append([c["description"], c["standard"], c["combination"],
                     f"{c['value']} {c['unit']}" if c["value"] is not None else "—",
                     f"{c['limit']} {c['unit']}" if c["limit"] is not None else "—",
                     f"{c['utilization']:.3f}" if c["utilization"] is not None else "—", _st(c["status"])])
    el.append(_tbl(rows, [62, 34, 12, 18, 18, 12, 22]))
    el.append(Paragraph("8. Reacciones en apoyos (ELS-1 / ELU-1)", H2))
    rr = [r for r in eng["reactions"] if r["combination"] in ("ELS-1", "ELU-1")]
    el.append(_tbl([["Comb.", "Apoyo", "Rx (N)", "Ry (N)", "Rz (N)"]] +
                   [[r["combination"], r["support"], r["Rx_N"], r["Ry_N"], r["Rz_N"]] for r in rr], [20, 40, 25, 25, 25]))
    el.append(Paragraph("9. Datos pendientes y limitaciones", H2))
    for p_ in eng["pending"]:
        el.append(Paragraph("• PENDIENTE: " + p_, P))
    for l_ in eng["limitations"]:
        el.append(Paragraph("• " + l_, P))
    el.append(PageBreak())
    el.append(Paragraph("10. Diseño para fabricación (DFM)", H2))
    el.append(_tbl([["Nivel", "Código", "Elemento", "Descripción", "Propuesta"]] +
                   [[_st(d["level"]), d["code"], d["element"], d["message"], d.get("proposal", "")] for d in dfm],
                   [18, 28, 30, 70, 34]))
    if qa:
        el.append(Paragraph("11. Control de calidad previo a la exportación", H2))
        el.append(Paragraph(f"Resultado: {_st(qa['result'])} — {qa['summary']}", P))
        el.append(_tbl([["Nivel", "Código", "Descripción"]] +
                       [[_st(q["level"]), q["code"], q["message"]] for q in qa["items"]], [22, 40, 118]))
    if history:
        el.append(Paragraph("12. Historial de revisiones", H2))
        el.append(_tbl([["Rev.", "Fecha", "Autor", "Comentario", "Cambios"]] +
                       [[h["revision"], h["date"], h.get("author", ""), h.get("comment", ""),
                         "; ".join(f"{k}: {v[0]} → {v[1]}" for k, v in (h.get("changes") or {}).items())]
                        for h in history], [12, 24, 26, 50, 68]))
    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    return path


def optimization_pdf(path: Path, info: dict[str, Any], model, plan: dict[str, Any]) -> Path:
    """Láminas A3 con el anidado real de cada chapa (contornos de desarrollo) y resumen de corte."""
    refs = {p.ref: p for p in model.parts.values()}
    d = Drawing(str(path), dict(info, total_sheets=sum(len(n.get("sheets", [])) for n in plan["nesting"])))
    for n in plan["nesting"]:
        if not n.get("feasible"):
            continue
        for sh in n["sheets"]:
            L, W = sh.get("length", n["length"]), sh.get("width", n["width"])
            k = min(360 / L, 170 / W)
            d.new_sheet(f"OPT-{sh['sheet']}", f"Anidado chapa {n['material']} e={fmt(n['thickness'])} mm — "
                                              f"{sheet_label(n, sh)}", f"1:{round(1 / k)}" if k < 1 else "1:1",
                        f"{n['material']} e={fmt(n['thickness'])}")
            ox, oy = 35, 95
            d.polyline([(ox, oy), (ox + L * k, oy), (ox + L * k, oy + W * k), (ox, oy + W * k), (ox, oy)], LW_THICK)
            for pl in sh["placements"]:
                part = refs[pl["ref"]]
                if isinstance(part, SheetPart):
                    fp = part.flat.normalized()
                    pts, hgt = list(fp.outline.exterior.coords), fp.height
                else:
                    pts, hgt = list(part.outline_2d().exterior.coords), part.h
                tr = [((hgt - y, x) if pl["rot"] else (x, y)) for x, y in pts]
                d.polyline([(ox + (pl["x"] + x) * k, oy + (pl["y"] + y) * k) for x, y in tr], LW_THIN)
                d.text(ox + (pl["x"] + pl["w"] / 2) * k, oy + (pl["y"] + pl["h"] / 2) * k, pl["ref"].split("-")[-1],
                       2.6, "c")
            rem = sh.get("remnant")
            if rem:
                x0, y0 = (rem["at"], 0.0) if rem["axis"] == "x" else (0.0, rem["at"])
                d.c.setDash(2, 1)
                d.polyline([(ox + x0 * k, oy + y0 * k), (ox + (x0 + rem["length"]) * k, oy + y0 * k),
                            (ox + (x0 + rem["length"]) * k, oy + (y0 + rem["width"]) * k),
                            (ox + x0 * k, oy + (y0 + rem["width"]) * k), (ox + x0 * k, oy + y0 * k)], LW_THIN)
                d.c.setDash()
            pu = n.get("purchase") or {}
            d.notes(35, 85, [f"Chapa {sh['sheet']} de {len(n['sheets'])} · aprovechamiento {sh['utilization'] * 100:.1f} % · "
                             f"margen {fmt(n['margin'])} mm · separación {fmt(n['spacing'])} mm · ancho de corte "
                             f"{fmt(n['kerf'])} mm.",
                             (f"Retal reutilizable {fmt(rem['length'])}×{fmt(rem['width'])} mm (línea de trazos). " if rem
                              else "Sin retal reutilizable en esta chapa. ") +
                             f"Compra del grupo: {pu.get('n_full', 0)} chapas enteras, {pu.get('n_custom', 0)} a medida; "
                             f"aprovechamiento real {pu.get('utilization', 0) * 100:.1f} %.",
                             "Anidado por envolvente rectangular (MaxRects). Alternativas de formato: " +
                             "; ".join(f"{a['format']}: " + (f"{a['n_sheets']} ch., {a['utilization'] * 100:.1f} %, "
                                                             f"{a['purchased_area_m2']:.3f} m² comprados"
                                                             if a["feasible"] else "no cabe")
                                       for a in n.get("alternatives", []))], width=185)
    d.finish()
    return path
