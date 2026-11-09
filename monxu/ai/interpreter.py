"""Intérprete de solicitudes en lenguaje natural (español) → parámetros técnicos.

Determinista y trazable: cada valor extraído guarda el fragmento de texto que lo justifica.
La IA no inventa geometría: sólo produce parámetros que el motor CAD construye y el motor de
cálculo verifica. Distingue datos del usuario, propuestas preliminares y datos pendientes.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

NUM_WORDS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
             "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12}
# miles con punto («1.500») o con espacio sólo tras 1-2 cifras («1 500»): «1800x800x900 400 kg» no es 900.400;
# nunca empieza en mitad de otro número («950 400» no da «50 400»)
NUM = r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{1,2}(?:\s\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
UNIT = r"(?:(mm|milimetros?|cm|centimetros?|m|metros?)\b)"

FAMILY_KEYWORDS = [
    ("mesa_soldadura", r"mesas? de sold|mesas? para soldar|bancos? de soldadura|mesas? de calderer|mesas? de amarre"),
    ("carro_plataforma", r"carros? (?:de )?plataforma|plataformas? (?:\w+ ){0,3}(?:con|sobre) ruedas|"
                         r"plataformas? (?:rodantes?|moviles?|de transporte|de carga)|carros? de (?:base plana|carga pesada)"),
    ("carro_estanteria", r"carros? (estanteria|de (baldas|bandejas|picking|estantes))|carros? de \d+ (niveles|baldas|bandejas|estantes)|estanterias? (con ruedas|movil|movible|rodante|sobre ruedas)"),
    ("estanteria_bateria", r"estanterias? (?:\w+ ){0,3}en bateria|baterias? de (?:\w+ )?(?:estanterias|modulos)|"
                           r"estanterias? (?:\w+ ){0,3}de \w+ (?:modulos|cuerpos|vanos)|\w+ (?:modulos|cuerpos|vanos) de estanteri|"
                           r"estanterias? modular|estanterias? (?:corrida|continua)s?\b"),
    ("cantilever", r"cantilever|estanterias? (?:\w+ ){0,2}(?:de|con) brazos|(?:estanterias?|racks?) (?:\w+ ){0,2}para "
                   r"(?:barras|tubos|perfiles|tableros|chapas)|porta ?(?:barras|tubos|perfiles)|almacen (?:vertical )?de "
                   r"(?:barras|tubos|perfiles)"),
    ("puesto_trabajo", r"puesto de trabajo|estacion de trabajo|puesto ergonomico|puesto de (montaje|inspeccion|embalaje)"),
    ("carro_taller", r"\bcarros?\b|\bcarritos?\b|carro de (taller|transporte)"),
    ("estanteria", r"estanteri"),
    ("tarima", r"\btarimas?\b|plataformas? (?:\w+ ){0,2}(?:de trabajo|baja|para (?:el |los )?operari|de operari)|\bpodios?\b"),
    ("mesa_industrial", r"\bmesas?\b|banco de (trabajo|montaje)|\bbancos?\b"),
    ("armario", r"\barmario"),
]
#: accesorios que sí implementa una familia (no se marcan como no soportados) y parámetro que activan
SUPPORTED_BY = {("puesto_trabajo", "panel_trasero"): ("PANEL_HERRAMIENTAS", 1), ("carro_taller", "ruedas"): None,
                ("carro_estanteria", "ruedas"): None, ("carro_plataforma", "ruedas"): None, ("armario", "puertas"): None}
CARTS = ("carro_taller", "carro_estanteria", "carro_plataforma")
MESA_LIKE = ("mesa_industrial", "puesto_trabajo", "carro_taller", "mesa_soldadura")
SHELF_LIKE = ("estanteria", "carro_estanteria", "estanteria_bateria", "armario")


def carry_params(old_family: str, new_family: str, values: dict, sources: dict, specs) -> tuple[dict, dict]:
    """Parámetros que conservan su significado al cambiar de familia dentro del mismo grupo (mesas o estanterías):
    medidas, cargas, material... Sólo los que existen en la nueva familia y admiten el valor."""
    same_group = any(old_family in g and new_family in g for g in (MESA_LIKE, SHELF_LIKE))
    if not same_group:
        return {}, {}
    sp = {s.name: s for s in specs}
    out = {}
    for k, v in values.items():
        if k in sp:
            try:
                sp[k].coerce(v)
                out[k] = v
            except Exception:
                pass
    return out, {k: sources.get(k, "usuario") for k in out}
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


#: la carga es de la balda sólo si va pegada a ella («balda de 100 kg», «balda inferior: 100 kg», «balda 100 kg»); en
#: «con balda y 400 kg» o «con balda, carga de 400 kg» la carga es la de la encimera
BALDA_BEFORE = r"balda(?:\s+inferior)?\s*(?:(?:de|con|:|=)\s*(?:una\s+)?(?:carga\s+(?:de\s+)?)?)?$"


def parse(text: str, pending: list[str] | None = None, context_family: str | None = None) -> Interpretation:
    """``context_family``: familia de la conversación, para interpretar los mensajes de seguimiento que no la nombran
    («con reposapiés», «sin peto», «carga de 300 kg»)."""
    t = norm(text)
    it = Interpretation()
    # ------------------------------------------------------------- familia
    for fid, rx in FAMILY_KEYWORDS:
        if re.search(rx, t):
            it.family = fid
            break
    if not it.family and context_family:
        it.family = context_family
    # mesa o banco sobre ruedas: carro de taller sin asa de empuje (mesa móvil)
    mobile_table = (it.family == "mesa_industrial" and bool(re.search(r"\bruedas?\b|\bmovil\b|rodante", t))
                    and not re.search(r"sin ruedas", t))
    if mobile_table:
        it.family = "carro_taller"
        it.notes.append("Mesa sobre ruedas: se genera como carro de taller sin asa de empuje (mesa móvil).")
    # plataforma de trabajo para un operario «con ruedas»: es una tarima (las ruedas no se generan)
    if it.family == "carro_plataforma" and re.search(r"de trabajo|operari|podio", t) and not re.search(r"\bcarros?\b", t):
        it.family = "tarima"
    for word, n in NUM_WORDS.items():
        t = re.sub(rf"\b{word}\b(?=\s+(niveles|baldas|estantes|cajones|travesanos|columnas|{MODULE_WORDS}))", str(n), t)
    # ------------------------------------------------------------- dimensiones
    m = re.search(rf"{NUM}\s*{UNIT}?\s*x\s*{NUM}\s*{UNIT}?\s*x\s*{NUM}\s*{UNIT}?", t)
    if m:
        unit = m.group(6) or m.group(4) or m.group(2)
        a, b, c = (to_mm(to_number(m.group(i)), m.group(i + 1) or unit) for i in (1, 3, 5))
        it.set("LONGITUD", a, m.group(0))
        it.set("ANCHURA", b, m.group(0))
        it.set("ALTURA", c, m.group(0))
    else:   # sólo planta: «2000 x 1000», «1500 por 800» (largo × ancho)
        m = re.search(rf"{NUM}\s*{UNIT}?\s*(?:x|por)\s*{NUM}(?!\d|[.,]\d)\s*{UNIT}?(?!\s*(?:x|por)\s*\d)(?!\s*(?:kg|kilos?|n\b|niveles))",
                      t)
        if m:
            unit = m.group(4) or m.group(2)
            it.set("LONGITUD", to_mm(to_number(m.group(1)), m.group(2) or unit), m.group(0))
            it.set("ANCHURA", to_mm(to_number(m.group(3)), m.group(4) or unit), m.group(0))
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
    mm = re.search(r"(\d+)\s+(?:niveles|baldas|estantes|bandejas)", t)
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
        before = re.split(r"\b(?:kg|kilos?|kilogramos?)\b", before)[-1]     # sólo desde la carga anterior
        on_top = re.match(r"\s*(?:en|sobre) (?:la )?(?:encimera|superficie|tablero|plataforma)", after)
        # "por nivel", o en estanterías "5 niveles de 100 kg" / "baldas de 80 kg cada una" (carga de cada nivel)
        if re.search(r"por nivel|cada nivel|por balda|cada balda|por estante|por bandeja|cada bandeja", ctx) or (
                it.family in SHELF_LIKE and (re.search(r"(?:niveles|baldas|estantes|bandejas)\s+(?:de\s+)?$", before)
                                             or re.match(r"\s*(?:cada un[oa]|c/u|por unidad)", after))):
            it.set("CARGA_POR_NIVEL", val, mm.group(0) + " por nivel")
        elif (re.match(r"\s*(?:de\s+)?(?:carga\s+)?(?:puntual|concentrada)", after)
              or re.search(r"(?:puntual|concentrada)\s*(?:de|:|=)?\s*$", before)):     # pegado al valor
            it.set("CARGA_PUNTUAL", val, ctx)
        elif (re.match(r"\s*(?:de carga\s+)?(?:en|sobre|para) (?:la )?(?:balda|estante inferior)", after)
              or re.search(BALDA_BEFORE, before)) and not on_top:     # "100 kg en la balda" o "balda de 100 kg"
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
    if it.family in CARTS:
        # altura del asa («asa a 950 mm»); no es una cota de planta («sin asa de 1200 x 800»)
        ma = re.search(rf"asas? (?:de empuje )?(?:a|de)\s+{NUM}\s*{UNIT}?(?!\s*(?:x|por)\s*\d)(?:\s*de altura)?|"
                       rf"altura (?:del|de la|de) asas?\s*(?:de|:|=|a)?\s*{NUM}\s*{UNIT}?", t)
        if ma and not re.search(r"sin asas?\b", t):
            it.set("ALTURA_ASA", to_mm(to_number(ma.group(1) or ma.group(3)), ma.group(2) or ma.group(4)), ma.group(0))
            if it.evidence.get("ALTURA") and it.evidence["ALTURA"] in ma.group(0):   # «asa a 950 mm de altura»
                it.values.pop("ALTURA")
                it.evidence.pop("ALTURA")
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
    if it.family in MESA_LIKE or it.family == "carro_plataforma":
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
    if it.family == "tarima":
        _tarima_loads(it, t)
    if it.family == "armario":
        _cabinet(it, t)
    if it.family == "cantilever":
        _cantilever(it, t)
    return it


CV_SEP_RANGE = (500.0, 1200.0)       # ParamSpec de SEPARACION_COLUMNAS
CV_ARM_RANGE = (250.0, 1200.0)       # ParamSpec de LONGITUD_BRAZO
CV_COL_W = 100.0                     # ancho aproximado de columna para pasar de longitud total a separación entre ejes


def _cantilever(it: Interpretation, t: str) -> None:
    """Cantilever: columnas, separación, brazos (longitud y caras) y carga por brazo. Una longitud total se reparte entre
    las columnas; el fondo indicado se toma como longitud de brazo; una carga por nivel o total se reparte por brazo."""
    mm = re.search(r"(\d+)\s+columnas", t)
    if mm:
        it.set("NUMERO_COLUMNAS", int(mm.group(1)), mm.group(0))
    mm = (re.search(rf"brazos?\s+(?:de\s+|:\s*|=\s*)?{NUM}(?![\d.,])\s*{UNIT}?(?!\s*(?:kg|kilos?))", t)
          or re.search(rf"voladizo\s+(?:de\s+)?{NUM}(?![\d.,])\s*{UNIT}?(?!\s*(?:kg|kilos?))", t))
    if mm:
        it.set("LONGITUD_BRAZO", to_mm(to_number(mm.group(1)), mm.group(2)), mm.group(0))
    if re.search(r"dos caras|doble cara|dos lados|ambos lados|doble faz", t):
        it.set("CARAS", "dos", "brazos a dos caras")
    elif re.search(r"una cara|un solo lado|cara simple|simple cara", t):
        it.set("CARAS", "una", "brazos a una cara")
    mm = (re.search(rf"(?:separacion|distancia|paso)\s+(?:entre\s+)?(?:las\s+)?columnas\s*(?:de|:|=)?\s*{NUM}\s*{UNIT}?", t)
          or re.search(rf"columnas\s+(?:cada|separadas|a)\s+{NUM}\s*{UNIT}?", t))
    if mm:
        it.set("SEPARACION_COLUMNAS", to_mm(to_number(mm.group(1)), mm.group(2)), mm.group(0))
    if re.search(r"sin tope", t):
        it.set("TOPE_BRAZO", False, "sin tope")
    elif re.search(r"\btopes?\b", t):
        it.set("TOPE_BRAZO", True, "tope en la punta")
    # medidas generales: el fondo es la longitud de brazo; la longitud total fija la separación entre columnas
    W = it.values.pop("ANCHURA", None)
    ev_w = it.evidence.pop("ANCHURA", "")
    if W and "LONGITUD_BRAZO" not in it.values:
        la = min(max(W, CV_ARM_RANGE[0]), CV_ARM_RANGE[1])
        it.set("LONGITUD_BRAZO", la, ev_w)
        it.notes.append(f"Fondo de {W:,.0f} mm tomado como longitud útil de los brazos ({la:,.0f} mm).".replace(",", "."))
    L = it.values.pop("LONGITUD", None)
    ev_l = it.evidence.pop("LONGITUD", "")
    if L and "SEPARACION_COLUMNAS" not in it.values:
        nc = it.values.get("NUMERO_COLUMNAS")
        if not nc:
            nc = min(4, max(2, math.ceil((L - CV_COL_W) / 1000.0) + 1))
            it.set("NUMERO_COLUMNAS", nc, ev_l)
        sep = round((L - CV_COL_W) / (nc - 1) / 10.0) * 10.0
        sep = min(max(sep, CV_SEP_RANGE[0]), CV_SEP_RANGE[1])
        it.set("SEPARACION_COLUMNAS", sep, ev_l)
        it.notes.append(f"Longitud total de {L:,.0f} mm: {nc} columnas a {sep:,.0f} mm entre ejes.".replace(",", "."))
    # carga: por brazo, o repartida desde la carga por nivel o total
    mm = (re.search(rf"{NUM}\s*(?:kg|kilos?)\s*(?:por|cada|en cada|de cada)\s+brazo", t)
          or re.search(rf"brazos?\s+(?:de|para|con|que (?:aguanten|soporten))\s+{NUM}\s*(?:kg|kilos?)", t))
    nc = it.values.get("NUMERO_COLUMNAS", 3)
    n = it.values.get("NUMERO_NIVELES", 4)
    sides = 2 if it.values.get("CARAS") == "dos" else 1
    if mm:
        it.set("CARGA_POR_BRAZO", to_number(mm.group(1)), mm.group(0))
    elif re.search(r"por nivel|cada nivel", t) and ("CARGA_TOTAL" in it.values or "CARGA_POR_NIVEL" in it.values):
        q = it.values.pop("CARGA_POR_NIVEL", None) or it.values.pop("CARGA_TOTAL")
        per = round(q / (nc * sides), 1)
        it.set("CARGA_POR_BRAZO", per, f"{q:g} kg por nivel")
        it.notes.append(f"Carga de {q:g} kg por nivel repartida entre sus {nc * sides} brazos: {per:g} kg por brazo.")
    elif "CARGA_TOTAL" in it.values:
        q = it.values["CARGA_TOTAL"]
        per = round(q / (nc * n * sides), 1)
        it.set("CARGA_POR_BRAZO", per, it.evidence.get("CARGA_TOTAL", f"{q:g} kg"))
        it.notes.append(f"Carga total de {q:g} kg repartida entre los {nc * n * sides} brazos ({nc} columnas × {n} niveles"
                        + (" × 2 caras" if sides == 2 else "") + f"): {per:g} kg por brazo.")
    for k in ("NUMERO_BALDAS", "CARGA_BALDA", "PETO_TRASERO", "MATERIAL_CHAPA", "ESPESOR_CHAPA", "CARGA_TOTAL",
              "CARGA_POR_NIVEL", "PROFUNDIDAD", "ALTURA_BALDA", "CARGA_PUNTUAL", "USO", "FRECUENCIA"):
        it.values.pop(k, None)
        it.evidence.pop(k, None)
    it.notes = [x for x in it.notes if "total de la mesa" not in x]


def _cabinet(it: Interpretation, t: str) -> None:
    """Puertas del armario y «N baldas» (baldas intermedias: las bandejas son además el suelo y el techo)."""
    one = re.search(r"\b(?:una|1) puerta\b|\bpuerta (?:unica|sencilla)\b", t)
    many = re.search(r"\b([3-9]|tres|cuatro|cinco|seis) puertas", t)
    if many:
        it.unsupported.append(f"{many.group(1)} puertas (el armario admite hasta dos; para más, armarios contiguos)")
    elif re.search(r"sin puertas?|armario abierto", t):
        it.set("NUMERO_PUERTAS", 0, "sin puertas")
    elif re.search(r"\b(?:dos|2) puertas|doble puerta|puertas? dobles?", t):
        it.set("NUMERO_PUERTAS", 2, "dos puertas")
    elif one:
        it.set("NUMERO_PUERTAS", 1, one.group(0))
    mm = re.search(r"(\d+)\s+(?:baldas|estantes|bandejas)", t)
    if mm and it.evidence.get("NUMERO_NIVELES") == mm.group(0):
        n = int(mm.group(1))
        it.set("NUMERO_NIVELES", n + 2, mm.group(0))
        it.notes.append(f"{n} baldas intermedias más el suelo y el techo del armario: {n + 2} niveles de bandeja.")


TARIMA_KN_M2 = 2.0       # EN ISO 14122-2: carga repartida mínima de plataformas


def tarima_load_kg(L: float, W: float, q_kn_m2: float = TARIMA_KN_M2) -> float:
    """Carga repartida total (kg) equivalente a q kN/m² sobre la superficie L × W (mm)."""
    return float(math.ceil(q_kn_m2 * L * W * 1e-6 / 9.81e-3))


def _tarima_loads(it: Interpretation, t: str) -> None:
    """Tarima: carga en kN/m² o kg/m² convertida a carga total; sin balda ni peto."""
    mm = re.search(rf"{NUM}\s*(kn|kg)\s*/\s*m(?:2|²|\s*cuadrado)", t)
    if mm:
        q = to_number(mm.group(1)) * (1.0 if mm.group(2) == "kn" else 9.81e-3)
        L, W = it.values.get("LONGITUD"), it.values.get("ANCHURA")
        if L and W:
            it.set("CARGA_TOTAL", tarima_load_kg(L, W, q), mm.group(0))
            it.notes.append(f"Carga de {q:g} kN/m² sobre {L * W * 1e-6:g} m²: {it.values['CARGA_TOTAL']:g} kg repartidos.")
        else:
            it.values.pop("CARGA_TOTAL", None)
            it.notes.append(f"Carga de {q:g} kN/m²: indique largo y ancho para convertirla en carga total.")
    for k in ("NUMERO_BALDAS", "CARGA_BALDA", "PETO_TRASERO", "MATERIAL_CHAPA", "ESPESOR_CHAPA"):
        it.values.pop(k, None)
        it.evidence.pop(k, None)


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
          "estanteria_bateria": "Estantería en batería", "tarima": "Tarima / plataforma de trabajo",
          "carro_plataforma": "Carro plataforma", "armario": "Armario industrial", "cantilever": "Estantería cantilever",
}
DIM_PROPOSAL = {"mesa_industrial": (1800.0, 800.0, 900.0), "puesto_trabajo": (1500.0, 750.0, 900.0),
                "carro_taller": (1000.0, 600.0, 900.0), "mesa_soldadura": (1500.0, 1000.0, 850.0)}


def missing_data(family: str, values: dict[str, Any], asked: set[str] | None = None) -> list[Question]:
    """Preguntas concretas para la familia (sólo mesa industrial implementada)."""
    asked = asked or set()
    q: list[Question] = []
    if family in SHELF_LIKE:
        return _missing_shelf(values, asked, family)
    if family == "tarima":
        return _missing_tarima(values, asked)
    if family == "carro_plataforma":
        return _missing_platform(values, asked)
    if family == "cantilever":
        return _missing_cantilever(values, asked)
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
                          "Si no la indica, se adopta la carga de uso habitual por m² según el uso previsto.",
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


def _missing_platform(values: dict[str, Any], asked: set[str]) -> list[Question]:
    q: list[Question] = []
    for p, lbl, prop in (("LONGITUD", "longitud de la plataforma", 1000.0), ("ANCHURA", "anchura de la plataforma", 600.0)):
        if p not in values:
            q.append(Question(p, f"¿Qué {lbl} necesita (mm)?", "Dimensión principal necesaria para generar la geometría.",
                              blocking="generacion", proposal=prop))
    if values.get("CARGA_TOTAL") is None:
        q.append(Question("CARGA_TOTAL", "¿Qué carga transportará la plataforma (kg)?",
                          "Fija las ruedas, la chapa y el bastidor; si no la indica, se adoptan 250 kg/m².",
                          [{"label": "250 kg", "value": 250}, {"label": "500 kg", "value": 500},
                           {"label": "800 kg", "value": 800}], "verificacion"))
    if "CARGA_HORIZONTAL" not in values and "CARGA_HORIZONTAL" not in asked:
        q.append(Question("CARGA_HORIZONTAL", "¿Qué fuerza de maniobra se aplicará en el asa (empuje o tirón con las ruedas "
                                              "frenadas o contra un obstáculo)?",
                          "Es la acción que puede volcar el carro vacío; se aplica en el asa.",
                          [{"label": "Ligera (30 N)", "value": 30}, {"label": "Normal (50 N)", "value": 50},
                           {"label": "Alta (80 N)", "value": 80}], "verificacion", 50.0))
    if "MATERIAL_ESTRUCTURAL" not in values and "MATERIAL_ESTRUCTURAL" not in asked:
        q.append(Question("MATERIAL_ESTRUCTURAL", "¿Material y acabado? Propuesta: acero S235 con pintura en polvo RAL 7035.",
                          "Determina propiedades mecánicas, espesores comerciales y acabado.",
                          [{"label": "Acero S235 pintado RAL 7035", "value": "S235JRH"},
                           {"label": "Acero inoxidable AISI 304", "value": "1.4301"}], "confirmacion", "S235JRH"))
    if "ENTORNO" not in values and "ENTORNO" not in asked:
        q.append(Question("ENTORNO", "¿Entorno de uso (interior seco, húmedo, alimentario)?",
                          "Afecta al material y al acabado (corrosión).",
                          [{"label": "Interior seco", "value": "interior_seco"},
                           {"label": "Interior húmedo", "value": "interior_humedo"},
                           {"label": "Alimentario", "value": "alimentario"}], "confirmacion", "interior_seco"))
    return q


def _missing_cantilever(values: dict[str, Any], asked: set[str]) -> list[Question]:
    q: list[Question] = []
    for p, lbl, prop in (("ALTURA", "altura total de las columnas", 2000.0),
                         ("LONGITUD_BRAZO", "longitud útil de los brazos (fondo de la carga)", 600.0)):
        if p not in values:
            q.append(Question(p, f"¿Qué {lbl} necesita (mm)?", "Dimensión principal necesaria para generar la geometría.",
                              blocking="generacion", proposal=prop))
    if "NUMERO_COLUMNAS" not in values and "NUMERO_COLUMNAS" not in asked:
        q.append(Question("NUMERO_COLUMNAS", "¿Cuántas columnas? (las piezas largas deben apoyar en al menos dos brazos)",
                          "Fija la longitud de la estantería y el número de brazos por nivel.",
                          [{"label": f"{n} columnas", "value": n} for n in (2, 3, 4)], "confirmacion", 3))
    if "CARAS" not in values and "CARAS" not in asked:
        q.append(Question("CARAS", "¿Brazos a una cara o a dos caras?", "A dos caras la base es simétrica y se carga por ambos "
                          "lados.", [{"label": "Una cara", "value": "una"}, {"label": "Dos caras", "value": "dos"}],
                          "confirmacion", "una"))
    if values.get("CARGA_POR_BRAZO") is None:
        la = values.get("LONGITUD_BRAZO", 600.0)
        q.append(Question("CARGA_POR_BRAZO", "¿Qué carga soportará cada brazo (kg, repartida a lo largo del brazo)?",
                          "Dimensiona brazos, columnas, bases y pies; si no la indica, se adoptan 250 kg por metro de brazo.",
                          [{"label": f"{v:g} kg", "value": v} for v in (100.0, 250.0, 500.0)], "verificacion",
                          float(max(10, math.floor(0.25 * la / 10 + 0.5) * 10))))
    if "ANCLAJE" not in values and "ANCLAJE" not in asked:
        q.append(Question("ANCLAJE", "¿Se anclará al suelo? (recomendado en cantilever)", "Evita el vuelco con el empuje y "
                          "al cargar o descargar.", [{"label": "Anclada al suelo", "value": "al_suelo"},
                                                     {"label": "Sin anclaje", "value": "ninguno"}], "confirmacion",
                          "al_suelo"))
    if "ENTORNO" not in values and "ENTORNO" not in asked:
        q.append(Question("ENTORNO", "¿Entorno de uso (almacén interior, húmedo, exterior)?", "Afecta al acabado (corrosión).",
                          [{"label": "Interior seco", "value": "interior_seco"},
                           {"label": "Exterior", "value": "exterior"}], "confirmacion", "interior_seco"))
    return q


def _missing_tarima(values: dict[str, Any], asked: set[str]) -> list[Question]:
    q: list[Question] = []
    for p, lbl, prop in (("LONGITUD", "longitud", 1200.0), ("ANCHURA", "anchura (fondo)", 800.0),
                         ("ALTURA", "altura de la superficie de tránsito (hasta 500 mm)", 200.0)):
        if p not in values:
            q.append(Question(p, f"¿Qué {lbl} necesita (mm)?", "Dimensión principal necesaria para generar la geometría.",
                              blocking="generacion", proposal=prop))
    if values.get("CARGA_TOTAL") is None:
        L, W = values.get("LONGITUD", 1200.0), values.get("ANCHURA", 800.0)
        prop = tarima_load_kg(L, W)
        q.append(Question("CARGA_TOTAL", "¿Qué carga repartida soportará la tarima (kg en total)? EN ISO 14122-2 pide al "
                                         f"menos 2 kN/m²: {prop:g} kg para {L * W * 1e-6:g} m².",
                          "Si no la indica, se adopta la de EN ISO 14122-2 (2 kN/m²).",
                          [{"label": f"EN ISO 14122-2 ({prop:g} kg)", "value": prop},
                           {"label": f"Taller, 5 kN/m² ({tarima_load_kg(L, W, 5.0):g} kg)",
                            "value": tarima_load_kg(L, W, 5.0)}], "verificacion", prop))
    if "ANCLAJE" not in values and "ANCLAJE" not in asked:
        q.append(Question("ANCLAJE", "¿Se anclará la tarima al suelo?", "Evita desplazamientos y vuelco con empujes.",
                          [{"label": "Anclada al suelo", "value": "al_suelo"}, {"label": "Sin anclaje", "value": "ninguno"}],
                          "confirmacion", "ninguno"))
    if "ENTORNO" not in values and "ENTORNO" not in asked:
        q.append(Question("ENTORNO", "¿Entorno de uso (interior seco, húmedo, exterior)?", "Afecta al acabado (corrosión).",
                          [{"label": "Interior seco", "value": "interior_seco"},
                           {"label": "Interior húmedo", "value": "interior_humedo"}], "confirmacion", "interior_seco"))
    return q


def _missing_shelf(values: dict[str, Any], asked: set[str], family: str = "estanteria") -> list[Question]:
    q: list[Question] = []
    cart = family == "carro_estanteria"
    bat = family == "estanteria_bateria"
    cab = family == "armario"
    if bat and "NUMERO_MODULOS" not in values:
        q.append(Question("NUMERO_MODULOS", "¿Cuántos módulos contiguos tendrá la batería?",
                          "Los módulos comparten los montantes intermedios; define la longitud total.",
                          [{"label": f"{n} módulos", "value": n} for n in (2, 3, 4)], "generacion", 3))
    for p, lbl, prop in (("ANCHURA", "anchura de cada módulo (entre ejes de montantes)" if bat else "anchura de frente",
                          1000.0 if cart or bat or cab else 1500.0),
                         ("PROFUNDIDAD", "profundidad", 500.0 if bat or cab else 600.0),
                         ("ALTURA", "altura total", 1400.0 if cart else 1950.0 if cab else 2000.0)):
        if p not in values:
            q.append(Question(p, f"¿Qué {lbl} necesita (mm)?", "Dimensión principal necesaria para generar la geometría.",
                              blocking="generacion", proposal=prop))
    if "NUMERO_NIVELES" not in values:
        opts = [(3, 4), 3] if cart else [(4, 5, 6), 5] if cab else [(4, 5), 5]
        q.append(Question("NUMERO_NIVELES", "¿Cuántos niveles de bandeja (suelo, baldas y techo)?" if cab else
                          "¿Cuántos niveles de bandejas?", "Define el número de bastidores y bandejas.",
                          [{"label": f"{n} niveles", "value": n} for n in opts[0]], "generacion", opts[1]))
    if cab and "NUMERO_PUERTAS" not in values and "NUMERO_PUERTAS" not in asked:
        q.append(Question("NUMERO_PUERTAS", "¿Una o dos puertas? Propuesta: una hasta 600 mm de anchura y dos por encima.",
                          "Define las hojas, las bisagras y la maneta con cerradura.",
                          [{"label": "Una puerta", "value": 1}, {"label": "Dos puertas", "value": 2},
                           {"label": "Sin puertas (abierto)", "value": 0}], "confirmacion", "auto"))
    if values.get("CARGA_POR_NIVEL") is None:
        loads = (25, 40, 60) if cart else (30, 60, 100) if cab else (80, 150, 250)
        q.append(Question("CARGA_POR_NIVEL", ("¿Qué carga soportará cada bandeja (cada módulo y nivel, kg)" if bat else
                                              "¿Qué carga soportará cada nivel (kg)") + " y estará repartida (cajas) o "
                                             "concentrada (piezas pesadas)?",
                          "Si no la indica, se adopta la carga de uso habitual por m² de bandeja.",
                          [{"label": f"{n} kg", "value": n} for n in loads], "verificacion"))
    if cart and "CARGA_HORIZONTAL" not in values and "CARGA_HORIZONTAL" not in asked:
        q.append(Question("CARGA_HORIZONTAL", "¿Qué fuerza de maniobra tendrá el carro (empuje con las ruedas frenadas "
                                              "o contra un obstáculo)?",
                          "Es la acción que puede volcar el carro; un carro no se ancla.",
                          [{"label": "Ligera (50 N)", "value": 50}, {"label": "Normal (100 N)", "value": 100}],
                          "verificacion", 100.0))
    if not cart and "ANCLAJE" not in values and "ANCLAJE" not in asked:
        what = "el armario" if cab else "la estantería"
        q.append(Question("ANCLAJE", f"¿Se anclará {what} al suelo o a la pared?",
                          f"{'Un armario alto y estrecho' if cab else 'Una estantería alta y estrecha'} sin anclaje puede "
                          "volcar con un empuje moderado.",
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
    if family == "cantilever":
        p = {k: v for k, v in (("ALTURA", 2000.0), ("LONGITUD_BRAZO", 600.0), ("NUMERO_COLUMNAS", 3),
                               ("NUMERO_NIVELES", 4)) if k not in values}
        for k in ("PERFIL_COLUMNA", "PERFIL_BRAZO", "PERFIL_BASE", "PERFIL_ARRIOSTRAMIENTO"):
            if k not in values:
                p[k] = "auto"
        return p
    if family == "tarima":
        p: dict[str, Any] = {k: v for k, v in (("LONGITUD", 1200.0), ("ANCHURA", 800.0), ("ALTURA", 200.0))
                             if k not in values}
        # la carga repartida no se fija aquí: el motor adopta la de EN ISO 14122-2 con las medidas finales
        if values.get("CARGA_PUNTUAL") is None:
            p["CARGA_PUNTUAL"] = 153.0
        for k in ("PERFIL_PATA", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ESPESOR_PLACA"):
            if k not in values:
                p[k] = "auto"
        return p
    if family == "carro_plataforma":
        p = {k: v for k, v in (("LONGITUD", 1000.0), ("ANCHURA", 600.0)) if k not in values}
        have_load = values.get("CARGA_TOTAL") is not None or values.get("CARGA_PUNTUAL") is not None
        for k in ("PERFIL_PATA", "PERFIL_LARGUERO", "PERFIL_TRAVESANO", "ESPESOR_CHAPA"):
            if k not in values and have_load:
                p[k] = "auto"
        for k in ("PERFIL_ASA", "RUEDA"):
            if k not in values:
                p[k] = "auto"
        return p
    if family in SHELF_LIKE:
        cart = family == "carro_estanteria"
        dims = ((("ANCHURA", 1000.0), ("PROFUNDIDAD", 600.0), ("ALTURA", 1400.0), ("NUMERO_NIVELES", 3)) if cart else
                (("ANCHURA", 1000.0), ("PROFUNDIDAD", 500.0), ("ALTURA", 1950.0), ("NUMERO_NIVELES", 5))
                if family == "armario" else
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
        on = {"tarima": "la tarima", "carro_plataforma": "la plataforma"}.get(it.family, "encimera")
        out.append(f"Carga distribuida sobre {on}: {v['CARGA_TOTAL']:g} kg.")
    if "CARGA_BALDA" in v:
        out.append(f"Carga sobre balda: {v['CARGA_BALDA']:g} kg.")
    if "CARGA_PUNTUAL" in v:
        out.append(f"Carga puntual: {v['CARGA_PUNTUAL']:g} kg.")
    if "MATERIAL_ESTRUCTURAL" in v:
        out.append(f"Material: {v['MATERIAL_ESTRUCTURAL']}.")
    if it.family == "tarima":
        out.append("Superficie: chapa de acero soldada al bastidor (antideslizante a prever); cargas de EN ISO 14122-2.")
    if it.family == "armario":
        n = v.get("NUMERO_PUERTAS")
        out.append("Puertas: " + ({0: "sin puertas (armario abierto)", 1: "una", 2: "dos"}.get(n, "una hasta 600 mm de "
                                  "anchura y dos por encima (propuesta)")) + ", con bisagras de pernio y maneta con "
                   "cerradura.")
        out.append("Cerramiento: laterales y fondo de chapa atornillados a los montantes; la bandeja superior es el techo.")
    if it.family == "cantilever":
        nc, la = v.get("NUMERO_COLUMNAS"), v.get("LONGITUD_BRAZO")
        if nc:
            sep = f"{v['SEPARACION_COLUMNAS']:,.0f}".replace(",", ".") if v.get("SEPARACION_COLUMNAS") else None
            out.append(f"Columnas: {nc}" + (f", a {sep} mm entre ejes" if sep else "") + ".")
        if la:
            out.append(f"Brazos: {la:,.0f} mm de longitud útil".replace(",", ".") + {"dos": ", a dos caras",
                                                                                      "una": ", a una cara"}.get(
                v.get("CARAS"), "") + (", sin tope en la punta" if v.get("TOPE_BRAZO") is False else
                                       ", con tope en la punta") + ".")
        if "CARGA_POR_BRAZO" in v:
            out.append(f"Carga por brazo: {v['CARGA_POR_BRAZO']:g} kg (repartida a lo largo del brazo).")
            if nc and v.get("NUMERO_NIVELES"):
                na = nc * v["NUMERO_NIVELES"] * (2 if v.get("CARAS") == "dos" else 1)
                out.append(f"Carga total nominal solicitada: {v['CARGA_POR_BRAZO'] * na:g} kg en {na} brazos.")
    if it.family in ("estanteria", "estanteria_bateria", "tarima", "armario", "cantilever"):
        out.append("Anclaje: " + {"al_suelo": "al suelo", "ninguno": "sin anclaje"}.get(
            v.get("ANCLAJE"), "lo decide el cálculo de vuelco") + ".")
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
    if it.family == "carro_plataforma":
        asa = v.get("ASA_EMPUJE", "un_extremo")
        out.append("Asa de empuje: " + {"un_extremo": "en un extremo", "dos_extremos": "en los dos extremos",
                                         "ninguna": "sin asa (plataforma rodante)"}[asa]
                   + (f", a {v['ALTURA_ASA']:g} mm" if v.get("ALTURA_ASA") and asa != "ninguna" else "") + ".")
        if v.get("PETO_TRASERO"):
            out.append(f"Peto trasero: {v['PETO_TRASERO']:g} mm sobre la plataforma.")
        out.append("Apoyos: ruedas giratorias de espiga roscada elegidas por cálculo, con freno en "
                   + ("el lado del asa." if asa == "un_extremo" else "un extremo."))
    if it.family == "carro_taller":
        asa = v.get("ASA_EMPUJE", "un_extremo")
        out.append("Asa de empuje: " + {"un_extremo": "en un extremo", "dos_extremos": "en los dos extremos",
                                         "ninguna": "sin asa (mesa móvil)"}[asa] + ".")
        out.append("Apoyos: ruedas giratorias de espiga roscada, con freno en "
                   + ("el lado del asa." if asa == "un_extremo" else "un extremo."))
    return out


def to_dict(it: Interpretation) -> dict[str, Any]:
    return asdict(it)
