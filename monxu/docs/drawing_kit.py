"""Primitivas de dibujo técnico sobre reportlab (unidades de papel en mm).

Formato A3 horizontal, recuadro con margen de archivo, cuadro de rotulación según ISO 7200,
tipos de línea ISO 128-2, acotación ISO 129-1, marcas de posición y símbolos de soldadura ISO 2553.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

PAGE_W, PAGE_H = 420.0, 297.0
FRAME = (20.0, 10.0, 410.0, 287.0)       # recuadro (margen de archivo a la izquierda)
TB_W, TB_H = 180.0, 58.0                 # cuadro de rotulación
LW_THICK, LW_THIN, LW_DIM = 0.5, 0.25, 0.18
TEXT_H = 3.5
SCALES = [(1, 1), (1, 2), (1, 5), (1, 10), (1, 20), (1, 50), (1, 100)]
RED = Color(0.78, 0.1, 0.1)
GREY = Color(0.45, 0.45, 0.45)


def text_width(s: str, h: float, bold: bool = False) -> float:
    return stringWidth(s, "Helvetica-Bold" if bold else "Helvetica", h / 0.72)


def fit_text(s: str, width: float, h: float) -> str:
    if text_width(s, h) <= width:
        return s
    while s and text_width(s + "…", h) > width:
        s = s[:-1]
    return s + "…"


def fmt(v: float, dec: int = 1) -> str:
    if abs(v - round(v)) < 0.05:
        return f"{round(v):d}"
    return f"{v:.{dec}f}".replace(".", ",")


def scale_label(s: tuple[int, int]) -> str:
    return f"{s[0]}:{s[1]}"


class Drawing:
    """Documento PDF multipágina; cada página es una hoja de plano."""

    def __init__(self, path: str, info: dict[str, Any]):
        self.c = Canvas(path, pagesize=landscape(A3))
        self.c.setTitle(info.get("title", "Planos"))
        self.c.setAuthor(info.get("designer", ""))
        self.c.setSubject(f"{info.get('project_code', '')} Rev.{info.get('revision', '')}")
        self.info = info
        self.pages: list[dict[str, Any]] = []
        self._open = False

    # ---------------------------------------------------------------- hojas
    def new_sheet(self, number: str, title: str, scale: str, material: str = "Ver lista", sheet_meta=None):
        if self._open:
            self.c.showPage()
        self.c.saveState()
        self.c.scale(mm, mm)
        self._open = True
        self.pages.append({"number": number, "title": title, "scale": scale, "dims": [], **(sheet_meta or {})})
        self._frame()
        self._title_block(number, title, scale, material)

    def finish(self, total: int | None = None):
        if self._open:
            self.c.restoreState()
            self.c.showPage()
        self.c.save()

    @property
    def page(self) -> dict[str, Any]:
        return self.pages[-1]

    def record_dim(self, name: str, value: float, source: str):
        """Registro de cotas dibujadas (para verificar coherencia plano–geometría)."""
        self.page["dims"].append({"name": name, "value": round(float(value), 3), "source": source})

    def _frame(self):
        c = self.c
        x0, y0, x1, y1 = FRAME
        c.setLineWidth(0.7)
        c.rect(x0, y0, x1 - x0, y1 - y0)
        c.setLineWidth(LW_THIN)
        # marcas de centrado y zonas
        for i in range(8):
            x = x0 + (x1 - x0) * (i + 0.5) / 8
            self.text(x, y1 + 2.5, str(i + 1), 2.5, "c")
        for j, ch in enumerate("ABCDEF"):
            y = y1 - (y1 - y0) * (j + 0.5) / 6
            self.text(x0 - 3, y, ch, 2.5, "c")
        c.line(PAGE_W / 2, y1, PAGE_W / 2, y1 + 4)
        c.line(PAGE_W / 2, y0, PAGE_W / 2, y0 - 4)

    def _title_block(self, number, title, scale, material):
        c, I = self.c, self.info
        x1, y0 = FRAME[2], FRAME[1]
        x0, y1 = x1 - TB_W, y0 + TB_H
        c.setLineWidth(0.5)
        c.rect(x0, y0, TB_W, TB_H)
        c.setLineWidth(LW_THIN)
        rows = [y0 + 10, y0 + 20, y0 + 30, y0 + 46]
        for y in rows:
            c.line(x0, y, x1, y)
        cols_top = [x0 + 45, x0 + 90, x0 + 135]
        for x in cols_top:
            c.line(x, y0 + 46, x, y1)
        # fila superior: responsabilidades
        self.field(x0, y0 + 46, 45, 12, "Diseñado", I.get("designer", ""))
        self.field(x0 + 45, y0 + 46, 45, 12, "Comprobado", I.get("checked", "—"))
        self.field(x0 + 90, y0 + 46, 45, 12, "Aprobado", I.get("approved", "—"))
        self.field(x0 + 135, y0 + 46, 45, 12, "Fecha", I.get("date", ""))
        # título
        self.label(x0 + 1.5, y0 + 43.5, "Título")
        self.text(x0 + 3, y0 + 37.5, I.get("product_name", "")[:60], 4.2, "l", bold=True)
        self.text(x0 + 3, y0 + 32, title[:70], 3.2, "l")
        # fila de datos
        for x in (x0 + 40, x0 + 75, x0 + 100, x0 + 125, x0 + 150):
            c.line(x, y0 + 20, x, y0 + 30)
        self.field(x0, y0 + 20, 40, 10, "Nº de plano", number, bold=True)
        self.field(x0 + 40, y0 + 20, 35, 10, "Código proyecto", I.get("project_code", ""))
        self.field(x0 + 75, y0 + 20, 25, 10, "Revisión", str(I.get("revision", "")), bold=True)
        self.field(x0 + 100, y0 + 20, 25, 10, "Escala", scale)
        self.field(x0 + 125, y0 + 20, 25, 10, "Unidades", "mm")
        self.field(x0 + 150, y0 + 20, 30, 10, "Hoja", f"{len(self.pages)}/{I.get('total_sheets', '?')}")
        for x in (x0 + 70, x0 + 125, x0 + 155):
            c.line(x, y0 + 10, x, y0 + 20)
        self.field(x0, y0 + 10, 70, 10, "Material", material[:40])
        self.field(x0 + 70, y0 + 10, 55, 10, "Ref. conjunto", I.get("assembly_ref", ""))
        self.field(x0 + 125, y0 + 10, 30, 10, "Cliente", I.get("client", "")[:18])
        self.label(x0 + 156.5, y0 + 17.5, "Proyección")
        self.first_angle_symbol(x0 + 167.5, y0 + 13.5)
        c.line(x0 + 120, y0, x0 + 120, y0 + 10)
        self.label(x0 + 1.5, y0 + 7.5, "Tolerancias generales")
        self.text(x0 + 3, y0 + 2.5, f"{I.get('tolerances', 'ISO 2768-mK')} · soldadura EN ISO 13920-BF", 2.6, "l")
        self.text(x0 + 121.5, y0 + 6, I.get("company", ""), 3.2, "l", bold=True)
        self.text(x0 + 121.5, y0 + 2, "Documento generado del modelo CAD", 1.9, "l")
        # estado del diseño
        st = I.get("status_stamp")
        if st:
            col = RED if I.get("status_level") == "error" else GREY
            c.setFillColor(col)
            c.setStrokeColor(col)
            c.setLineWidth(0.4)
            c.rect(x0, y1 + 2, TB_W, 7)
            self.text(x0 + TB_W / 2, y1 + 4, st[:95], 2.6, "c", bold=True)
            c.setFillColor(black)
            c.setStrokeColor(black)

    def first_angle_symbol(self, cx, cy):
        c = self.c
        c.setLineWidth(LW_THIN)
        # tronco de cono: vista de alzado (trapecio) a la izquierda y vista lateral (círculos) a la derecha (ISO E)
        c.line(cx - 9, cy - 1.5, cx - 9, cy + 1.5)
        c.line(cx - 3, cy - 3, cx - 3, cy + 3)
        c.line(cx - 9, cy + 1.5, cx - 3, cy + 3)
        c.line(cx - 9, cy - 1.5, cx - 3, cy - 3)
        c.circle(cx + 4, cy, 3)
        c.circle(cx + 4, cy, 1.5)

    def field(self, x, y, w, h, label, value, bold=False):
        self.label(x + 1.5, y + h - 2.5, label)
        self.text(x + 2, y + 2, str(value), 3.0 if h >= 10 else 2.8, "l", bold=bold)

    def label(self, x, y, s):
        self.text(x, y, s, 1.8, "l", color=GREY)

    # ---------------------------------------------------------------- texto y líneas
    def text(self, x, y, s, h=TEXT_H, align="l", angle=0.0, bold=False, color=black):
        c = self.c
        c.saveState()
        c.setFillColor(color)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", h / 0.72)
        c.translate(x, y)
        if angle:
            c.rotate(angle)
        if align == "c":
            c.drawCentredString(0, 0, s)
        elif align == "r":
            c.drawRightString(0, 0, s)
        else:
            c.drawString(0, 0, s)
        c.restoreState()

    def polyline(self, pts, lw=LW_THICK, dash=None, color=black):
        if len(pts) < 2:
            return
        c = self.c
        c.setLineWidth(lw)
        c.setStrokeColor(color)
        c.setDash(dash or [])
        p = c.beginPath()
        p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        c.drawPath(p, stroke=1, fill=0)
        c.setDash([])
        c.setStrokeColor(black)

    def line(self, p, q, lw=LW_THIN, dash=None, color=black):
        self.polyline([p, q], lw, dash, color)

    def arrow(self, tip, direction, size=3.0):
        dx, dy = direction
        n = math.hypot(dx, dy)
        dx, dy = dx / n, dy / n
        w = size * math.tan(math.radians(10))
        bx, by = tip[0] - dx * size, tip[1] - dy * size
        p = self.c.beginPath()
        p.moveTo(*tip)
        p.lineTo(bx - dy * w, by + dx * w)
        p.lineTo(bx + dy * w, by - dx * w)
        p.close()
        self.c.setFillColor(black)
        self.c.drawPath(p, stroke=0, fill=1)

    # ---------------------------------------------------------------- acotación
    def dim_h(self, x1, x2, y_feat1, y_feat2, y_dim, value, name=None, source="geometria", prefix=""):
        """Cota horizontal entre x1 y x2 (papel); extensiones desde y_feat* hasta y_dim."""
        if abs(x2 - x1) < 0.5:
            return
        x1, x2 = min(x1, x2), max(x1, x2)
        sgn = 1 if y_dim >= max(y_feat1, y_feat2) else -1
        for x, yf in ((x1, y_feat1), (x2, y_feat2)):
            self.line((x, yf + sgn * 1.0), (x, y_dim + sgn * 2.0), LW_DIM)
        self.line((x1, y_dim), (x2, y_dim), LW_DIM)
        inside = (x2 - x1) > 9
        if inside:
            self.arrow((x1, y_dim), (-1, 0))
            self.arrow((x2, y_dim), (1, 0))
        else:
            self.line((x1 - 5, y_dim), (x2 + 5, y_dim), LW_DIM)
            self.arrow((x1, y_dim), (1, 0))
            self.arrow((x2, y_dim), (-1, 0))
        txt = prefix + fmt(value)
        tx = (x1 + x2) / 2 if (x2 - x1) > len(txt) * 2.2 + 2 else x2 + 3 + len(txt) * 1.2
        self.text(tx, y_dim + 1.0, txt, 3.0, "c")
        if name:
            self.record_dim(name, value, source)

    def dim_v(self, y1, y2, x_feat1, x_feat2, x_dim, value, name=None, source="geometria", prefix=""):
        if abs(y2 - y1) < 0.5:
            return
        y1, y2 = min(y1, y2), max(y1, y2)
        sgn = 1 if x_dim >= max(x_feat1, x_feat2) else -1
        for y, xf in ((y1, x_feat1), (y2, x_feat2)):
            self.line((xf + sgn * 1.0, y), (x_dim + sgn * 2.0, y), LW_DIM)
        self.line((x_dim, y1), (x_dim, y2), LW_DIM)
        if (y2 - y1) > 9:
            self.arrow((x_dim, y1), (0, -1))
            self.arrow((x_dim, y2), (0, 1))
        else:
            self.line((x_dim, y1 - 5), (x_dim, y2 + 5), LW_DIM)
            self.arrow((x_dim, y1), (0, 1))
            self.arrow((x_dim, y2), (0, -1))
        txt = prefix + fmt(value)
        ty = (y1 + y2) / 2 if (y2 - y1) > len(txt) * 2.2 + 2 else y2 + 3 + len(txt) * 1.2
        self.text(x_dim - 1.0, ty, txt, 3.0, "c", angle=90)
        if name:
            self.record_dim(name, value, source)

    # ---------------------------------------------------------------- marcas y símbolos
    def balloon(self, center, target, label, r=4.0):
        cx, cy = center
        dx, dy = target[0] - cx, target[1] - cy
        d = math.hypot(dx, dy) or 1
        self.line((cx + dx / d * r, cy + dy / d * r), target, LW_THIN)
        self.c.setFillColor(black)
        self.c.circle(target[0], target[1], 0.5, stroke=0, fill=1)
        self.c.setFillColor(white)
        self.c.setLineWidth(LW_THIN)
        self.c.circle(cx, cy, r, stroke=1, fill=1)
        self.c.setFillColor(black)
        self.text(cx, cy - 1.2, str(label), 3.2, "c", bold=True)

    def weld_symbol(self, target, base, a: float, all_around=True, process="135", length=None, side=1):
        """Símbolo ISO 2553: flecha, línea de referencia, triángulo de cordón en ángulo, garganta a, contorno."""
        bx, by = base
        self.line(base, target, LW_THIN)
        dx, dy = target[0] - bx, target[1] - by
        self.arrow(target, (dx, dy), 2.5)
        Lr = 22 * side
        self.line((bx, by), (bx + Lr, by), LW_THIN)
        self.line((bx, by - 1.2), (bx + Lr, by - 1.2), LW_THIN, dash=[1.2, 0.8])   # línea de identificación
        tx = bx + 9 * side
        p = self.c.beginPath()
        p.moveTo(tx - 2.2, by)
        p.lineTo(tx + 2.2, by)
        p.lineTo(tx - 2.2, by + 4.0)
        p.close()
        self.c.setLineWidth(LW_THIN)
        self.c.drawPath(p, stroke=1, fill=0)
        self.text(tx - 3.2, by + 0.8, f"a{fmt(a)}", 2.6, "r")
        if length:
            self.text(tx + 3.0, by + 0.8, fmt(length), 2.6, "l")
        if all_around:
            self.c.circle(bx, by, 1.6, stroke=1, fill=0)
        ex = bx + Lr
        self.line((ex, by), (ex + 2.5 * side, by + 2.5), LW_THIN)
        self.line((ex, by), (ex + 2.5 * side, by - 2.5), LW_THIN)
        self.text(ex + 3.5 * side, by - 1.0, process, 2.4, "l" if side > 0 else "r")

    def table(self, x, y_top, cols: list[tuple[str, float, str]], rows: list[list[Any]], row_h=5.0, head_h=6.0,
              text_h=2.4, max_rows: int | None = None) -> float:
        """Tabla con cabecera; cols = [(título, ancho, alineación)]. Devuelve la cota inferior."""
        c = self.c
        W = sum(w for _, w, _ in cols)
        rows = rows if max_rows is None else rows[:max_rows]
        H = head_h + row_h * len(rows)
        c.setLineWidth(0.35)
        c.rect(x, y_top - H, W, H)
        c.setLineWidth(LW_THIN)
        c.line(x, y_top - head_h, x + W, y_top - head_h)
        xx = x
        for k, (t, w, al) in enumerate(cols):
            if k:
                c.line(xx, y_top, xx, y_top - H)
            self.text(xx + w / 2, y_top - head_h + 1.8, t, 2.4, "c", bold=True)
            xx += w
        for r_i, row in enumerate(rows):
            yy = y_top - head_h - row_h * (r_i + 1)
            if r_i:
                c.setLineWidth(0.1)
                c.line(x, yy + row_h, x + W, yy + row_h)
            xx = x
            for (t, w, al), v in zip(cols, row):
                s = "" if v is None else (fmt(v, 2) if isinstance(v, float) else str(v))
                s = fit_text(s, w - 2.4, text_h)
                if al == "c":
                    self.text(xx + w / 2, yy + 1.4, s, text_h, "c")
                elif al == "r":
                    self.text(xx + w - 1.2, yy + 1.4, s, text_h, "r")
                else:
                    self.text(xx + 1.2, yy + 1.4, s, text_h, "l")
                xx += w
        return y_top - H

    def notes(self, x, y_top, lines: list[str], h=2.6, width_chars=95, width: float | None = None, bold_first=False):
        """Texto en párrafos ajustado a un ancho en mm (``width``) o en caracteres."""
        y = y_top
        for n, ln in enumerate(lines):
            if not ln:
                y -= h * 0.8
                continue
            while ln:
                if width:
                    words, part = ln.split(" "), ""
                    for w_ in words:
                        cand = (part + " " + w_).strip()
                        if text_width(cand, h) > width and part:
                            break
                        part = cand
                else:
                    part = ln[:width_chars]
                    if len(ln) > width_chars and " " in part:
                        part = part[:part.rfind(" ")]
                self.text(x, y, part, h, "l", bold=bold_first and n == 0)
                ln = ln[len(part):].lstrip()
                y -= h * 1.55
        return y


@dataclass
class ViewPlacement:
    proj: dict
    scale: float              # papel/modelo
    ox: float                 # posición en papel de la esquina inferior izquierda de la vista
    oy: float
    u0: float                 # mínimos de la vista en coordenadas de modelo proyectado
    v0: float
    label: str = ""
    label_offset: float = 20.0

    def P(self, u: float, v: float) -> tuple[float, float]:
        return self.ox + (u - self.u0) * self.scale, self.oy + (v - self.v0) * self.scale

    @property
    def w(self) -> float:
        b = self.proj["bbox"]
        return (b[2] - b[0]) * self.scale

    @property
    def h(self) -> float:
        b = self.proj["bbox"]
        return (b[3] - b[1]) * self.scale

    def draw(self, d: Drawing, hidden=True, lw=LW_THICK):
        for pl in self.proj["visible"]:
            d.polyline([self.P(*p) for p in pl], lw)
        if hidden:
            for pl in self.proj["hidden"]:
                d.polyline([self.P(*p) for p in pl], LW_THIN * 0.8, dash=[2.0, 1.0], color=GREY)
        if self.label:
            d.text(self.ox + self.w / 2, self.oy - self.label_offset, self.label, 3.0, "c", bold=True)


def place_view(proj, scale, ox, oy, label="") -> ViewPlacement:
    b = proj["bbox"]
    return ViewPlacement(proj, scale, ox, oy, b[0], b[1], label)


def choose_scale(fits: Callable[[float], bool]) -> tuple[int, int]:
    for s in SCALES:
        if fits(s[0] / s[1]):
            return s
    return SCALES[-1]
