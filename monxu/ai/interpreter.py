"""Intérprete de solicitudes en lenguaje natural (español) → parámetros técnicos.

Determinista y trazable: cada valor extraído guarda el fragmento de texto que lo justifica.
La IA no inventa geometría: sólo produce parámetros que el motor CAD construye y el motor de
cálculo verifica. Distingue datos del usuario, propuestas preliminares y datos pendientes.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

NUM_WORDS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
             "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12}
NUM = r"(\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
UNIT = r"(?:(mm|milimetros?|cm|centimetros?|m|metros?)\b)"

FAMILY_KEYWORDS = [
    ("mesa_soldadura", r"mesas? de sold|mesas? para soldar|bancos? de soldadura|mesas? de calderer|mesas? de amarre"),
    ("carro_estanteria", r"carros? (estanteria|de (baldas|bandejas|picking|estantes))|carros? de \d+ (niveles|baldas|bandejas|estantes)|estanterias? (con ruedas|movil|movible|rodante|sobre ruedas)"),
    ("estanteria_bateria", r"estanterias? (?:\w+ ){0,3}en bateria|baterias? de (?:\w+ )?(?:estanterias|modulos)|"
                           r"estanterias? (?:\w+ ){0,3}de \w+ (?:modulos|cuerpos|vanos)|\w+ (?:modulos|cuerpos|vanos) de estanteri|"
                           r"estanterias? modular|estanterias? (?:corrida|continua)s?\b"),
    ("puesto_trabajo", r"puesto de trabajo|estacion de trabajo|puesto ergonomico|puesto de (montaje|inspeccion|embalaje)"),
    ("carro_taller", r"\bcarros?\b|\bcarritos?\b|carro de (taller|transporte)"),
    ("estanteria", r"estanteri"),
    ("mesa_industrial", r"\bmesas?\b|banco de (trabajo|montaje)|\bbancos?\b"),
    ("armario", r"\barmario"),
]
#: accesorios que sí implementa una familia (no se marcan como no soportados) y parámetro que activan
SUPPORTED_BY = {("puesto_trabajo", "panel_trasero"): ("PANEL_HERRAMIENTAS", 1), ("carro_taller", "ruedas"): None,
                ("carro_estanteria", "ruedas"): None}
MESA_LIKE = ("mesa_industrial", "puesto_trabajo", "carro_taller", "mesa_soldadura")
SHELF_LIKE = ("estanteria", "carro_estanteria", "estanteria_bateria")
MODULE_WORDS = r"modulos|cuerpos|vanos"
BAY_MAX = 2000.0          # anchura máxima de módulo (ParamSpec de ANCHURA en estanteria_bateria)

UNSUPPORTED_ACCESSORIES = [
    ("cajones", r"cajon|cajonera", "Cajones / cajonera"),
    ("panel_trasero", r"panel (trasero|perforado)|panel de herramientas|panel posterior", "Panel trasero perforado"),
    ("ruedas", r"\bruedas?\b|movil\b", "Ruedas (mesa móvil)"),
    ("puertas", r"\bpuertas?\b|armario inferior", "Puertas / armario inferior"),
    ("iluminacion", r"iluminacion|\bluz\b|luminaria", "Iluminación"),
    ("tomas", r"tomas? electric|enchufes|regleta", "Tomas eléctricas"),
    ("monitor", r"monitor|pantalla", "Soporte para monitor"),
    ("regulable", r"regulable en altura|altura regulable", "Regulación de altura"),
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("×", "x").replace("*", "x")


def to_number(tok: str) -> float:
    tok = tok.strip()
    if tok in NUM_WORDS:
        return float(NUM_WORDS[tok])
    t = tok.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    return float(t)


def to_mm(value: float, unit: str | None, default_unit: str = "mm") -> float:
    u = (unit or default_unit)
    if u.startswith("m") and not u.startswith("mm") and not u.startswith("mil"):
        return value * 1000
    if u.startswith("c"):
        return value * 10
    return value


@dataclass
class Question:
    param: str
    question: str
    why: str
    options: list[dict[str, Any]] = field(default_factory=list)
    blocking: str = "verificacion"        # generacion | verificacion | confirmacion
    proposal: Any = None


@dataclass
class Interpretation:
    family: str | None = None
    family_label: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)
    accessories: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def set(self, k, v, ev):
        self.values[k] = v
        self.evidence[k] = ev.strip()


def parse(text: str, pending: list[str] | None = None) -> Interpretation:
    t = norm(text)
    it = Interpretation()
    # ------------------------------------------------------------- familia
    for fid, rx in FAMILY_KEYWORDS:
        if re.search(rx, t):
            it.family = fid
            break
    # mesa o banco sobre ruedas: carro de taller sin asa de empuje (mesa móvil)
    mobile_table = (it.family == "mesa_industrial" and bool(re.search(r"\bruedas?\b|\bmovil\b|rodante", t))
                    and not re.search(r"sin ruedas", t))
    if mobile_table:
        it.family = "carro_taller"
        it.notes.append("Mesa sobre ruedas: se genera como carro de taller sin asa de empuje (mesa móvil).")
    for word, n in NUM_WORDS.items():
        t = re.sub(rf"\b{word}\b(?=\s+(niveles|baldas|estantes|cajones|travesanos|{MODULE_WORDS}))", str(n), t)
    # ------------------------------------------------------------- dimensiones
    m = re.search(rf"{NUM}\s*{UNIT}?\s*x\s*{NUM}\s*{UNIT}?\s*x\s*{NUM}\s*{UNIT}?", t)
    if m:
        unit = m.group(6) or m.group(4) or m.group(2)
        a, b, c = (to_mm(to_number(m.group(i)), m.group(i + 1) or unit) for i in (1, 3, 5))
        it.set("LONGITUD", a, m.group(0))
        it.set("ANCHURA", b, m.group(0))
        it.set("ALTURA", c, m.group(0))
    dim_words = {"LONGITUD": r"largo|longitud|long\.", "ANCHURA": r"ancho|anchura|profundidad|fondo",
                 "ALTURA": r"altura|alto"}
    for param, words in dim_words.items():
        if param in it.values:
            continue
        for rx in (rf"{NUM}\s*{UNIT}?\s*(?:de\s+)?(?:{words})",
                   rf"(?:{words})\s*(?:de|:|=)?\s*{NUM}\s*{UNIT}?"):
            mm = re.search(rx, t)
            if mm:
                it.set(param, to_mm(to_number(mm.group(1)), mm.group(2)), mm.group(0))
                break
    if it.family in SHELF_LIKE:
        # en estanterías: anchura = frente, profundidad = fondo
        pm = re.search(rf"{NUM}\s*{UNIT}?\s*(?:de\s+)?(?:profundidad|fondo)", t)
        if pm:
            it.set("PROFUNDIDAD", to_mm(to_number(pm.group(1)), pm.group(2)), pm.group(0))
        am = (re.search(rf"{NUM}\s*{UNIT}?\s*(?:de\s+)?(?:ancho|anchura|frente)", t)
              or re.search(rf"\bfrente\s*(?:total\s*)?(?:de|:|=)?\s*{NUM}\s*{UNIT}?", t))
        if am:
            it.set("ANCHURA", to_mm(to_number(am.group(1)), am.group(2)), am.group(0))
        elif pm and it.evidence.get("ANCHURA") == pm.group(0):
            it.values.pop("ANCHURA")          # el único dato era el fondo: la anchura de frente queda por definir
            it.evidence.pop("ANCHURA")
    # ------------------------------------------------------------- niveles
    mm = re.search(r"(\d+)\s+(?:niveles|baldas|estantes)", t)
    if mm:
        it.set("NUMERO_NIVELES", int(mm.group(1)), mm.group(0))
    mm = re.search(rf"(\d+)\s+(?:{MODULE_WORDS})", t)
    if mm and it.family == "estanteria_bateria":
        it.set("NUMERO_MODULOS", int(mm.group(1)), mm.group(0))
    # ------------------------------------------------------------- cargas
    for mm in re.finditer(rf"{NUM}\s*(kg|kilos?|kilogramos?)\b", t):
        val = to_number(mm.group(1))
        ctx = t[max(0, mm.start() - 60): mm.end() + 60]
        after = t[mm.end(): mm.end() + 40]
        before = t[max(0, mm.start() - 40): mm.start()]
        if re.search(r"por nivel|cada nivel|por balda|cada balda|por estante|por bandeja|cada bandeja", ctx):
            it.set("CARGA_POR_NIVEL", val, mm.group(0) + " por nivel")
        elif (re.match(r"\s*(?:de\s+)?(?:carga\s+)?(?:puntual|concentrada)", after)
              or re.search(r"(?:puntual|concentrada)\s*(?:de|:|=)?\s*$", before)):     # pegado al valor
            it.set("CARGA_PUNTUAL", val, ctx)
        elif re.search(r"balda|estante inferior", after) or re.search(r"balda", before):
            it.set("CARGA_BALDA", val, ctx)
        elif pending and pending[0] in ("CARGA_BALDA", "CARGA_PUNTUAL", "CARGA_TOTAL") and \
                not re.search(r"distribuid|encimera", ctx):
            it.set(pending[0], val, mm.group(0))
        else:
            it.set("CARGA_TOTAL", val, ctx)
            if re.search(r"total de la mesa|en total|entre encimera y balda", ctx):
                it.notes.append("La carga indicada es total de la mesa: se asigna a la encimera (hipótesis "
                                "conservadora) hasta que se indique el reparto con la balda.")
    if re.search(r"balda (sin carga|vacia)|sin carga en la balda", t):
        it.set("CARGA_BALDA", 0.0, "balda sin carga")
    mm = re.search(rf"{NUM}\s*(n|newton)\b", t)
    if mm and re.search(r"horizontal|empuje|maniobra|arrastre", t):
        it.set("CARGA_HORIZONTAL", to_number(mm.group(1)), mm.group(0))
    elif re.search(r"(sin|no hay|despreciables?) (empujes|esfuerzos horizontales)|empujes? (ligeros?|despreciables?)|empujes? horizontales? ligeros?", t):
        it.set("CARGA_HORIZONTAL", 100.0, "empujes horizontales ligeros")
        it.notes.append("Empuje horizontal ligero: se adopta 100 N como hipótesis de uso ligero.")
    elif re.search(r"tornillo de banco|golpe|martill", t):
        it.set("CARGA_HORIZONTAL", 600.0, "trabajo con esfuerzos horizontales")
        it.notes.append("Trabajo con esfuerzos horizontales: se adopta 600 N como hipótesis.")
    # ------------------------------------------------------------- materiales
    if re.search(r"inox|inoxidable|aisi\s*3(04|16)|1\.4301|1\.4404", t):
        code = "1.4404" if re.search(r"316|1\.4404", t) else "1.4301"
        it.set("MATERIAL_ESTRUCTURAL", code, "acero inoxidable")
        it.set("MATERIAL_CHAPA", code, "acero inoxidable")
        it.set("ACABADO", "INOX_SATINADO", "acero inoxidable")
    elif re.search(r"alumini", t):
        it.set("MATERIAL_ESTRUCTURAL", "EN AW-6082 T6", "aluminio")
        it.set("MATERIAL_CHAPA", "EN AW-5754 H22", "aluminio")
        it.set("ACABADO", "ANODIZADO_NATURAL", "aluminio")
    elif re.search(r"\bacero\b|chapa de acero|chapa negra|s235|s355", t):
        it.set("MATERIAL_CHAPA", "S235JR", "acero")
        it.set("MATERIAL_ESTRUCTURAL", "S355J2H" if "s355" in t else "S235JRH", "acero")
    if re.search(r"encimera de (madera|contrachapado|tablero|hpl|fenolic)", t):
        it.unsupported.append("Encimera de madera/tablero técnico (sólo chapa metálica en esta versión)")
    mm = re.search(rf"chapa (?:de\s+)?{NUM}\s*mm|{NUM}\s*mm de (?:espesor|chapa)", t)
    if mm:
        it.set("ESPESOR_CHAPA", to_number(mm.group(1) or mm.group(2)), mm.group(0))
    for ral in re.findall(r"ral\s*(\d{4})", t):
        code = f"RAL{ral}_POLVO"
        from .. import catalog
        if code in catalog.finishes():
            it.set("ACABADO", code, f"RAL {ral}")
        else:
            it.notes.append(f"Color RAL {ral} no está en el catálogo de acabados: se mantiene el acabado propuesto.")
    if re.search(r"galvaniz", t):
        it.set("ACABADO", "GALVANIZADO", "galvanizado")
    # ------------------------------------------------------------- configuración
    if re.search(r"sin balda|sin estante", t):
        it.set("NUMERO_BALDAS", 0, "sin balda")
    elif re.search(r"balda inferior|con balda|estante inferior|bandeja inferior|una balda|1 balda", t):
        it.set("NUMERO_BALDAS", 1, "balda inferior")
    mm = re.search(rf"balda (?:a|situada a)\s*{NUM}\s*{UNIT}?", t)
    if mm:
        it.set("ALTURA_BALDA", to_mm(to_number(mm.group(1)), mm.group(2)), mm.group(0))
    mm = re.search(r"tubo (?:cuadrado )?(?:de\s+)?(\d{2,3})\s*x\s*(\d{2,3})(?:\s*x\s*(\d(?:[.,]\d)?))?", t)
    if mm:
        a, b, tt = mm.group(1), mm.group(2), (mm.group(3) or "2").replace(",", ".")
        code = f"SHS {a}x{b}x{float(tt):g}" if a == b else f"RHS {max(a, b, key=int)}x{min(a, b, key=int)}x{float(tt):g}"
        from .. import catalog
        if code in catalog.profiles() and a == b:
            it.set("PERFIL_PATA", code, mm.group(0))
        elif code not in catalog.profiles():
            it.notes.append(f"Perfil {code} no disponible en el catálogo: se propondrá el más próximo.")
    if re.search(r"tubular|tubo", t):
        it.accessories.append("estructura tubular")
    # ------------------------------------------------------------- uso y entorno
    for rx, val in [(r"trabajo pesado|uso intensivo pesado|heavy", "trabajo_pesado"), (r"montaje ligero", "montaje_ligero"),
                    (r"inspeccion|control de calidad", "inspeccion"), (r"laboratorio", "laboratorio"),
                    (r"embalaje|preparacion de pedidos|expedicion", "embalaje"), (r"montaje|ensamblaje", "montaje")]:
        if re.search(rx, t):
            it.set("USO", val, rx.split("|")[0])
            break
    for rx, val in [(r"intensiv|tres turnos|24 ?h", "intensiva"), (r"diari|a diario|cada dia", "diaria"),
                    (r"ocasional|esporadic", "ocasional")]:
        if re.search(rx, t):
            it.set("FRECUENCIA", val, rx)
            break
    for rx, val in [(r"exterior|intemperie", "exterior"), (r"humed", "interior_humedo"),
                    (r"alimentari|alimentos", "alimentario"), (r"sala limpia", "sala_limpia"),
                    (r"interior|nave|taller", "interior_seco")]:
        if re.search(rx, t):
            it.set("ENTORNO", val, rx)
            break
    if re.search(r"anclad|anclaje al suelo|atornillada al suelo|fijada al suelo", t) and not re.search(r"sin anclaj|no anclad", t):
        it.set("ANCLAJE", "al_suelo", "anclaje al suelo")
    elif re.search(r"sin anclaj|no anclad|apoyada|libre", t):
        it.set("ANCLAJE", "ninguno", "sin anclaje")
    if re.search(r"suelo irregular|desnivel", t):
        it.set("TIPO_SUELO", "irregular", "suelo irregular")
    elif re.search(r"suelo (nivelado|plano|liso)", t):
        it.set("TIPO_SUELO", "nivelado", "suelo nivelado")
    if re.search(r"pies? nivelador", t):
        it.set("TIPO_APOYO", "pie_nivelador", "pies niveladores")
    # ------------------------------------------------------------- accesorios no implementados
    if it.family == "puesto_trabajo":
        if re.search(r"sin (estante|altillo)", t):
            it.set("ESTANTE_SUPERIOR", 0, "sin estante superior")
        elif re.search(r"estante superior|altillo|balda superior", t):
            it.set("ESTANTE_SUPERIOR", 1, "estante superior")
        if re.search(r"sin panel", t):
            it.set("PANEL_HERRAMIENTAS", 0, "sin panel")
    if it.family in ("carro_taller", "carro_estanteria"):
        if re.search(r"sin asas?\b", t) or (mobile_table and not re.search(r"\basas?\b", t)):
            it.set("ASA_EMPUJE", "ninguna", "sin asa" if "sin asa" in t else "mesa sobre ruedas")
        elif re.search(r"dos asas|doble asa|asas? en (ambos|los dos) (extremos|lados)|asa en cada (extremo|lado)", t):
            it.set("ASA_EMPUJE", "dos_extremos", "asa en los dos extremos")
        elif re.search(r"\basa\b", t):
            it.set("ASA_EMPUJE", "un_extremo", "asa de empuje")
    if it.family == "mesa_soldadura":
        if re.search(r"sistema\s*28|\bd\s*28\b|ø\s*28|taladros? de 28", t):
            it.set("SISTEMA_TALADROS", "D28_P100", "sistema 28")
        elif re.search(r"sistema\s*16|\bd\s*16\b|ø\s*16|taladros? de 16", t):
            it.set("SISTEMA_TALADROS", "D16_P50", "sistema 16")
        elif re.search(r"sin taladros|placa lisa|sin perforar", t):
            it.set("SISTEMA_TALADROS", "ninguno", "placa sin taladros")
        mm = re.search(rf"(?:placa|chapa) (?:de\s+)?{NUM}\s*mm|{NUM}\s*mm de (?:placa|espesor)", t)
        if mm:
            it.set("ESPESOR_PLACA", to_number(mm.group(1) or mm.group(2)), mm.group(0))
        it.values.pop("ESPESOR_CHAPA", None)           # en esta familia el espesor es el de la placa
        it.evidence.pop("ESPESOR_CHAPA", None)
        mm = re.search(rf"vuelo (?:de\s+)?{NUM}\s*{UNIT}?", t)
        if mm:
            it.set("VUELO", to_mm(to_number(mm.group(1)), mm.group(2)), mm.group(0))
    if it.family in MESA_LIKE:
        PETO = r"peto|tope trasero|reborde trasero"
        if it.family == "mesa_soldadura":
            pass
        elif re.search(rf"sin ({PETO})", t):
            it.set("PETO_TRASERO", 0.0, "sin peto")
        else:
            mm = (re.search(rf"(?:{PETO})(?: trasero)?\s*(?:de|:|=)?\s*{NUM}\s*{UNIT}?", t)
                  or re.search(rf"{NUM}\s*{UNIT}?\s*de (?:{PETO})", t))
            if mm:
                it.set("PETO_TRASERO", to_mm(to_number(mm.group(1)), mm.group(2)), mm.group(0))
            elif re.search(PETO, t):
                it.set("PETO_TRASERO", 50.0, "peto trasero")
                it.notes.append("Peto trasero sin altura indicada: se adoptan 50 mm sobre la encimera.")
        FOOT = r"reposapies|apoyapies|apoya ?pies|barra (?:para|de) (?:los )?pies"
        if re.search(rf"sin ({FOOT})", t):
            it.set("REPOSAPIES", 0, "sin reposapiés")
        elif re.search(FOOT, t):
            it.set("REPOSAPIES", 1, "reposapiés")
            mm = re.search(rf"(?:{FOOT})\s*(?:a|de|:|=)?\s*{NUM}\s*{UNIT}?", t)
            if mm:
                it.set("ALTURA_REPOSAPIES", to_mm(to_number(mm.group(1)), mm.group(2)), mm.group(0))
    for key, rx, label in UNSUPPORTED_ACCESSORIES:
        if (it.family, key) in SUPPORTED_BY:
            sup = SUPPORTED_BY[(it.family, key)]
            if sup and re.search(rx, t) and not re.search(rf"sin ({rx})", t):
                it.set(sup[0], sup[1], label.lower())
            continue
        if re.search(rx, t) and not re.search(rf"sin ({rx})", t):
            mm = re.search(rf"(\d+)\s+(?:{rx})", t)
            it.unsupported.append(label + (f" ({mm.group(1)} uds)" if mm else ""))
            it.accessories.append(key)
    if it.family in SHELF_LIKE:
        if "LONGITUD" in it.values:            # en estanterías el "largo" es la anchura de frente
            L, ev = it.values.pop("LONGITUD"), it.evidence.pop("LONGITUD")
            if "PROFUNDIDAD" not in it.values and "ANCHURA" in it.values and it.evidence.get("ANCHURA") == ev:
                it.set("PROFUNDIDAD", it.values["ANCHURA"], ev)
            it.set("ANCHURA", L, ev)
        if "CARGA_TOTAL" in it.values and "CARGA_POR_NIVEL" not in it.values and it.values.get("NUMERO_NIVELES"):
            n = it.values["NUMERO_NIVELES"]
            it.set("CARGA_POR_NIVEL", round(it.values.pop("CARGA_TOTAL") / n, 1), it.evidence.pop("CARGA_TOTAL"))
            it.notes.append(f"Carga total repartida por igual entre los {n} niveles (hipótesis).")
        it.values.pop("NUMERO_BALDAS", None)
        it.notes = [n for n in it.notes if "total de la mesa" not in n]
    if it.family == "estanteria_bateria":
        _battery_width(it, t)
    return it


def _battery_width(it: Interpretation, t: str) -> None:
    """Estantería en batería: ANCHURA es la de cada módulo (entre ejes de montantes).

    "módulos de 1.000 mm" fija el módulo; un frente mayor que el módulo máximo, o indicado como total/largo, se
    reparte entre los módulos (y si no se dijo cuántos, se deduce del frente y del módulo)."""
    mm = re.search(rf"(?:{MODULE_WORDS})\s+(?:de\s+|:\s*)?{NUM}(?![\d.,])\s*{UNIT}?(?!\s*(?:kg|kilos?|niveles|baldas|bandejas))", t)
    mod_w = to_mm(to_number(mm.group(1)), mm.group(2)) if mm else None
    front, n = it.values.get("ANCHURA"), it.values.get("NUMERO_MODULOS")
    ev_front = it.evidence.get("ANCHURA", "")
    if mod_w:
        if front and front > mod_w * 1.5 and front != mod_w:
            if not n:
                n = max(2, round(front / mod_w))
                it.set("NUMERO_MODULOS", n, ev_front)
                it.notes.append(f"Frente total de {front:,.0f} mm con módulos de {mod_w:,.0f} mm: "
                                f"{n} módulos.".replace(",", "."))
        it.set("ANCHURA", mod_w, mm.group(0))
    elif front and n and (front > BAY_MAX or re.search(r"\btotal|en total|de largo|longitud", t)):
        m = round(front / n)
        it.set("ANCHURA", float(m), ev_front)
        it.notes.append(f"Frente total de {front:,.0f} mm repartido en {n} módulos de {m:,.0f} mm entre ejes de "
                        f"montantes (anchura total = {n} × módulo + un montante).".replace(",", "."))


LABELS = {"mesa_industrial": "Mesa industrial", "estanteria": "Estantería industrial",
          "puesto_trabajo": "Puesto de trabajo industrial", "carro_taller": "Carro de taller",
          "carro_estanteria": "Carro estantería", "mesa_soldadura": "Mesa de soldadura",
          "estanteria_bateria": "Estantería en batería",
          "armario": "Armario / mobiliario auxiliar"}
DIM_PROPOSAL = {"mesa_industrial": (1800.0, 800.0, 900.0), "puesto_trabajo": (1500.0, 750.0, 900.0),
                "carro_taller": (1000.0, 600.0, 900.0), "mesa_soldadura": (1500.0, 1000.0, 850.0)}


def missing_data(family: str, values: dict[str, Any], asked: set[str] | None = None) -> list[Question]:
    """Preguntas concretas para la familia (sólo mesa industrial implementada)."""
    asked = asked or set()
    q: list[Question] = []
    if family in SHELF_LIKE:
        return _missing_shelf(values, asked, family)
    if family not in MESA_LIKE:
        return q
    dL, dW, dH = DIM_PROPOSAL[family]
    for p, lbl, prop in (("LONGITUD", "longitud", dL), ("ANCHURA", "anchura (fondo)", dW),
                         ("ALTURA", "altura de trabajo", dH)):
        if p not in values:
            q.append(Question(p, f"¿Qué {lbl} necesita (mm)?", "Dimensión principal necesaria para generar la geometría.",
                              blocking="generacion", proposal=prop))
    if values.get("CARGA_TOTAL") is None:
        q.append(Question("CARGA_TOTAL", "¿Qué carga debe soportar la encimera (kg) y está distribuida o concentrada?",
                          "Sin carga no puede verificarse la estructura: el resultado quedaría PENDIENTE.",
                          [{"label": "150 kg", "value": 150}, {"label": "300 kg", "value": 300},
                           {"label": "500 kg", "value": 500}], "verificacion"))
    if values.get("NUMERO_BALDAS", 0 if family == "mesa_soldadura" else 1) >= 1 and values.get("CARGA_BALDA") is None \
            and "CARGA_BALDA" not in asked:
        q.append(Question("CARGA_BALDA", "¿Qué carga soportará la balda inferior (kg)? ¿La carga indicada para la encimera "
                                         "incluye la de la balda?",
                          "La balda se dimensiona y verifica de forma independiente.",
                          [{"label": "Sin carga", "value": 0}, {"label": "100 kg", "value": 100},
                           {"label": "200 kg", "value": 200}], "verificacion"))
    if "MATERIAL_ESTRUCTURAL" not in values and "MATERIAL_ESTRUCTURAL" not in asked:
        q.append(Question("MATERIAL_ESTRUCTURAL", "¿Material y acabado? Propuesta: acero S235 con pintura en polvo RAL 7035.",
                          "Determina propiedades mecánicas, espesores comerciales y acabado.",
                          [{"label": "Acero S235 pintado RAL 7035", "value": "S235JRH"},
                           {"label": "Acero inoxidable AISI 304", "value": "1.4301"},
                           {"label": "Aluminio", "value": "EN AW-6082 T6"}], "confirmacion", "S235JRH"))
    if "USO" not in values and "USO" not in asked:
        q.append(Question("USO", "¿Qué uso tendrá (montaje, trabajo pesado, inspección, embalaje...)?",
                          "Fija el espesor mínimo de encimera y la clase de ejecución.",
                          [{"label": "Montaje", "value": "montaje"}, {"label": "Trabajo pesado", "value": "trabajo_pesado"},
                           {"label": "Inspección / ligero", "value": "inspeccion"}], "confirmacion", "montaje"))
    if family == "puesto_trabajo" and values.get("ESTANTE_SUPERIOR", 1) and values.get("CARGA_ESTANTE") is None \
            and "CARGA_ESTANTE" not in asked:
        q.append(Question("CARGA_ESTANTE", "¿Qué carga llevará el estante superior (kg)?",
                          "El estante en voladizo se dimensiona y verifica con su propia carga.",
                          [{"label": "Sin estante", "value": 0}, {"label": "30 kg", "value": 30},
                           {"label": "60 kg", "value": 60}], "verificacion"))
    if "CARGA_HORIZONTAL" not in values and "CARGA_HORIZONTAL" not in asked:
        if family == "carro_taller":
            q.append(Question("CARGA_HORIZONTAL", "¿Qué fuerza de maniobra tendrá el carro (empuje con las ruedas frenadas "
                                                  "o contra un obstáculo)?",
                              "Es la acción que puede volcar el carro; un carro no se ancla.",
                              [{"label": "Ligera (50 N)", "value": 50}, {"label": "Normal (100 N)", "value": 100},
                               {"label": "Alta (150 N)", "value": 150}], "verificacion", 100.0))
        else:
            q.append(Question("CARGA_HORIZONTAL", "¿Habrá esfuerzos horizontales relevantes (empujes, tornillo de banco, "
                                                  "golpes)? ¿Se anclará al suelo?",
                              "Condiciona la verificación de vuelco y del desplome.",
                              [{"label": "Empuje ligero (100 N)", "value": 100},
                               {"label": "Uso general (300 N)", "value": 300},
                               {"label": "Tornillo de banco (600 N)", "value": 600}], "verificacion", 300.0))
    if "ENTORNO" not in values and "ENTORNO" not in asked:
        q.append(Question("ENTORNO", "¿Entorno de uso (interior seco, húmedo, exterior, alimentario)?",
                          "Afecta al material y al acabado (corrosión).",
                          [{"label": "Interior seco", "value": "interior_seco"},
                           {"label": "Interior húmedo", "value": "interior_humedo"},
                           {"label": "Alimentario", "value": "alimentario"}], "confirmacion", "interior_seco"))
    return q


def _missing_shelf(values: dict[str, Any], asked: set[str], family: str = "estanteria") -> list[Question]:
    q: list[Question] = []
    cart = family == "carro_estanteria"
    bat = family == "estanteria_bateria"
    if bat and "NUMERO_MODULOS" not in values:
        q.append(Question("NUMERO_MODULOS", "¿Cuántos módulos contiguos tendrá la batería?",
                          "Los módulos comparten los montantes intermedios; define la longitud total.",
                          [{"label": f"{n} módulos", "value": n} for n in (2, 3, 4)], "generacion", 3))
    for p, lbl, prop in (("ANCHURA", "anchura de cada módulo (entre ejes de montantes)" if bat else "anchura de frente",
                          1000.0 if cart or bat else 1500.0),
                         ("PROFUNDIDAD", "profundidad", 500.0 if bat else 600.0),
                         ("ALTURA", "altura total", 1400.0 if cart else 2000.0)):
        if p not in values:
            q.append(Question(p, f"¿Qué {lbl} necesita (mm)?", "Dimensión principal necesaria para generar la geometría.",
                              blocking="generacion", proposal=prop))
    if "NUMERO_NIVELES" not in values:
        opts = [(3, 4), 3] if cart else [(4, 5), 5]
        q.append(Question("NUMERO_NIVELES", "¿Cuántos niveles de bandejas?", "Define el número de bastidores y bandejas.",
                          [{"label": f"{n} niveles", "value": n} for n in opts[0]], "generacion", opts[1]))
    if values.get("CARGA_POR_NIVEL") is None:
        loads = (25, 40, 60) if cart else (80, 150, 250)
        q.append(Question("CARGA_POR_NIVEL", ("¿Qué carga soportará cada bandeja (cada módulo y nivel, kg)" if bat else
                                              "¿Qué carga soportará cada nivel (kg)") + " y estará repartida (cajas) o "
                                             "concentrada (piezas pesadas)?",
                          "Sin carga no puede verificarse la estructura: el resultado quedaría PENDIENTE.",
                          [{"label": f"{n} kg", "value": n} for n in loads], "verificacion"))
    if cart and "CARGA_HORIZONTAL" not in values and "CARGA_HORIZONTAL" not in asked:
        q.append(Question("CARGA_HORIZONTAL", "¿Qué fuerza de maniobra tendrá el carro (empuje con las ruedas frenadas "
                                              "o contra un obstáculo)?",
                          "Es la acción que puede volcar el carro; un carro no se ancla.",
                          [{"label": "Ligera (50 N)", "value": 50}, {"label": "Normal (100 N)", "value": 100}],
                          "verificacion", 100.0))
    if not cart and "ANCLAJE" not in values and "ANCLAJE" not in asked:
        q.append(Question("ANCLAJE", "¿Se anclará la estantería al suelo o a la pared?",
                          "Una estantería alta y estrecha sin anclaje puede volcar con un empuje moderado.",
                          [{"label": "Anclada al suelo", "value": "al_suelo"}, {"label": "Sin anclaje", "value": "ninguno"}],
                          "verificacion", "al_suelo"))
    if "MATERIAL_ESTRUCTURAL" not in values and "MATERIAL_ESTRUCTURAL" not in asked:
        q.append(Question("MATERIAL_ESTRUCTURAL", "¿Material y acabado? Propuesta: acero S235 con pintura en polvo RAL 7035.",
                          "Determina propiedades mecánicas, espesores comerciales y acabado.",
                          [{"label": "Acero S235 pintado RAL 7035", "value": "S235JRH"},
                           {"label": "Acero inoxidable AISI 304", "value": "1.4301"}], "confirmacion", "S235JRH"))
    if "ENTORNO" not in values and "ENTORNO" not in asked:
        q.append(Question("ENTORNO", "¿Entorno de uso (almacén interior seco, húmedo, cámara, exterior)?",
                          "Afecta al material y al acabado (corrosión).",
                          [{"label": "Interior seco", "value": "interior_seco"},
                           {"label": "Interior húmedo", "value": "interior_humedo"}], "confirmacion", "interior_seco"))
    return q


def proposal_for(family: str, values: dict[str, Any]) -> dict[str, Any]:
    """Configuración constructiva preliminar (propuesta IA) para completar lo no indicado."""
    if family in SHELF_LIKE:
        cart = family == "carro_estanteria"
        dims = ((("ANCHURA", 1000.0), ("PROFUNDIDAD", 600.0), ("ALTURA", 1400.0), ("NUMERO_NIVELES", 3)) if cart else
                (("NUMERO_MODULOS", 3), ("ANCHURA", 1000.0), ("PROFUNDIDAD", 500.0), ("ALTURA", 2000.0),
                 ("NUMERO_NIVELES", 5)) if family == "estanteria_bateria" else
                (("ANCHURA", 1500.0), ("PROFUNDIDAD", 600.0), ("ALTURA", 2000.0), ("NUMERO_NIVELES", 5)))
        p = {k: v for k, v in dims if k not in values}
        for k in ("PERFIL_MONTANTE", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ESPESOR_BALDA") + \
                (("PERFIL_ASA", "RUEDA") if cart else ()):
            if k not in values:
                p[k] = "auto"
        return p
    if family not in MESA_LIKE:
        return {}
    p: dict[str, Any] = {}
    for k, v in zip(("LONGITUD", "ANCHURA", "ALTURA"), DIM_PROPOSAL[family]):
        if k not in values:
            p[k] = v
    p.setdefault("NUMERO_BALDAS", values.get("NUMERO_BALDAS", 0 if family == "mesa_soldadura" else 1))
    have_load = values.get("CARGA_TOTAL") is not None
    top_t = "ESPESOR_PLACA" if family == "mesa_soldadura" else "ESPESOR_CHAPA"
    for k in ("PERFIL_PATA", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "PERFIL_BASTIDOR", top_t):
        if k not in values:
            p[k] = "auto" if have_load else None
    if values.get("CARGA_BALDA"):
        p.setdefault("ESPESOR_BALDA", "auto")
    if family == "puesto_trabajo":
        if "PERFIL_ALTILLO" not in values:
            p["PERFIL_ALTILLO"] = "auto" if have_load else None
        if values.get("CARGA_ESTANTE"):
            p.setdefault("ESPESOR_ESTANTE", "auto")
    if family == "carro_taller":
        for k in ("PERFIL_ASA", "RUEDA"):
            if k not in values:
                p[k] = "auto"
    return {k: v for k, v in p.items() if v is not None}


def describe(it: Interpretation) -> list[str]:
    v = it.values
    out = [f"Familia: {LABELS.get(it.family, 'no identificada')}."]
    bat = it.family == "estanteria_bateria"
    lab = {"LONGITUD": "Longitud", "ANCHURA": "Anchura de módulo (entre ejes)" if bat else "Anchura (frente)"
           if it.family in SHELF_LIKE else "Anchura/fondo", "PROFUNDIDAD": "Profundidad", "ALTURA": "Altura"}
    for k, l in lab.items():
        if k in v:
            out.append(f"{l}: {v[k]:,.0f} mm.".replace(",", "."))
    if bat and "NUMERO_MODULOS" in v:
        out.append(f"Módulos: {v['NUMERO_MODULOS']} (montantes intermedios compartidos).")
    if "NUMERO_NIVELES" in v:
        out.append(f"Niveles: {v['NUMERO_NIVELES']}.")
    if "CARGA_POR_NIVEL" in v:
        out.append(f"Carga por {'bandeja' if bat else 'nivel'}: {v['CARGA_POR_NIVEL']:g} kg.")
        if "NUMERO_NIVELES" in v:
            nb = v["NUMERO_NIVELES"] * (v.get("NUMERO_MODULOS", 1) if bat else 1)
            out.append(f"Carga total nominal solicitada: {v['CARGA_POR_NIVEL'] * nb:g} kg.")
    if "CARGA_TOTAL" in v:
        out.append(f"Carga distribuida sobre encimera: {v['CARGA_TOTAL']:g} kg.")
    if "CARGA_BALDA" in v:
        out.append(f"Carga sobre balda: {v['CARGA_BALDA']:g} kg.")
    if "CARGA_PUNTUAL" in v:
        out.append(f"Carga puntual: {v['CARGA_PUNTUAL']:g} kg.")
    out.append("Material: " + (v["MATERIAL_ESTRUCTURAL"] if "MATERIAL_ESTRUCTURAL" in v else "pendiente de selección") + ".")
    if it.family in ("estanteria", "estanteria_bateria"):
        out.append("Anclaje: " + {"al_suelo": "al suelo", "ninguno": "sin anclaje"}.get(v.get("ANCLAJE"), "pendiente") + ".")
    if it.family in MESA_LIKE:
        out.append("Balda inferior: " + ("sí" if v.get("NUMERO_BALDAS", None) == 1 else
                                         "no" if v.get("NUMERO_BALDAS") == 0 else "no indicada") + ".")
        out.append("Tipo de estructura: tubular soldada" + (" (indicada)." if "estructura tubular" in it.accessories
                                                           else " (propuesta)."))
    if it.family == "puesto_trabajo":
        out.append("Estante superior: " + ("no" if v.get("ESTANTE_SUPERIOR") == 0 else "sí") + " · panel portaherramientas: "
                   + ("no" if v.get("PANEL_HERRAMIENTAS") == 0 else "sí") + ".")
    if it.family in MESA_LIKE and v.get("PETO_TRASERO"):
        out.append(f"Peto trasero: {v['PETO_TRASERO']:g} mm sobre la encimera.")
    if it.family == "carro_estanteria":
        asa = v.get("ASA_EMPUJE", "un_extremo")
        out.append("Asa de empuje: " + {"un_extremo": "en un extremo", "dos_extremos": "en los dos extremos",
                                         "ninguna": "sin asa"}[asa] + ".")
        out.append("Apoyos: ruedas giratorias de espiga roscada, con freno en un extremo (sin anclaje).")
    if it.family == "carro_taller":
        asa = v.get("ASA_EMPUJE", "un_extremo")
        out.append("Asa de empuje: " + {"un_extremo": "en un extremo", "dos_extremos": "en los dos extremos",
                                         "ninguna": "sin asa (mesa móvil)"}[asa] + ".")
        out.append("Apoyos: ruedas giratorias de espiga roscada, con freno en "
                   + ("el lado del asa." if asa == "un_extremo" else "un extremo."))
    return out


def to_dict(it: Interpretation) -> dict[str, Any]:
    return asdict(it)
