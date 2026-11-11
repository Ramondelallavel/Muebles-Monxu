"""Instrucciones de montaje generadas desde el modelo maestro.

Los textos de cada familia describen la operación; la tornillería, los taladros, los pares y las herramientas se
añaden aquí a partir de las instancias del modelo y de la base de componentes comerciales, de modo que las
instrucciones usan exactamente las referencias del BOM y del 3D (``N-<código>``). El motor del navegador
(``frontend/src/engine/drawings.ts``) aplica el mismo algoritmo.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .. import catalog

DEFAULT_TEXTS = {
    "EST": "Recepción de la estructura soldada y pintada. Insertar las tuercas remachables en los taladros de "
           "largueros y travesaños.",
    "APO": "Roscar los pies niveladores en las tuercas soldadas de las placas base. Nivelar la mesa en su "
           "emplazamiento (nivel de burbuja sobre encimera al final).",
    "BAL": "Colocar la balda sobre el bastidor inferior, con las escotaduras alrededor de las patas, y fijarla con "
           "la tornillería indicada.",
    "ENC": "Colocar la encimera sobre el bastidor superior y fijarla por las pestañas con la tornillería indicada. "
           "Apretar en cruz desde el centro.",
}
"""Textos por defecto de los pasos de montaje (mesas y carros); las familias los sustituyen con los suyos."""

FASTENER_ROLES = ("tornillo", "tuerca_remachable", "anclaje", "pie_nivelador", "rueda")
# designaciones de tornillería y referencias de componente que pueden aparecer en un texto de montaje
DESIGNATION_RE = re.compile(r"\bM(\d+)\s*[x×]\s*(\d+)\b")
REF_RE = re.compile(r"\bN-[A-Z0-9_]+(?:x\d+)?[A-Z0-9_]*")


def _fmt(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def joint_torque(model, screw: str) -> tuple[float | None, bool]:
    """Par de apriete de un tornillo en sus uniones: el menor entre el del tornillo y el máximo del elemento
    roscado (tuerca remachable). Devuelve (par, validado)."""
    sc = catalog.component(screw)
    tq = sc.get("tightening_torque_Nm")
    ok = (sc.get("validation") or {}).get("status") == "definido_por_norma"
    for j in model.joints:
        if j.kind == "atornillada" and j.data and j.data.get("screw") == screw and j.data.get("rivet"):
            rn = catalog.component(j.data["rivet"])
            mt = rn.get("max_torque_Nm")
            if mt is not None:
                tq = mt if tq is None else min(tq, mt)
            if (rn.get("validation") or {}).get("status") != "definido_por_norma":
                ok = False
    return tq, ok


def fastener_line(model, group: str) -> str:
    """Elementos comerciales del paso de montaje ``group``, con su referencia del BOM y su cantidad."""
    cnt: Counter = Counter()
    for i in model.instances:
        if i.group == group and i.part.kind == "normalizado" and i.part.role in FASTENER_ROLES:
            cnt[i.part.code] += 1
    if not cnt:
        return ""
    parts = []
    for code in sorted(cnt):
        c = catalog.component(code)
        txt = f"{cnt[code]} × N-{code}"
        if c.get("hole_d"):
            txt += f" (taladro Ø{_fmt(c['hole_d'])})"
        if c["category"] == "tornilleria" and c.get("thread") and c.get("length"):
            tq, ok = joint_torque(model, code)
            if tq is not None:
                txt += f" (par {_fmt(round(tq, 1))} N·m{'' if ok else '*'})"
        parts.append(txt)
    return "Elementos según BOM: " + ", ".join(parts) + "."


def step_texts(model, defaults: dict[str, str] | None = None) -> dict[str, str]:
    """Texto final de cada paso de montaje: descripción de la familia + elementos del BOM + anclaje."""
    texts = dict(DEFAULT_TEXTS if defaults is None else defaults)
    texts.update(model.structure.get("assembly_texts", {}))
    anc = next((i for i in model.instances if i.part.role == "anclaje"), None)
    if anc:            # anclaje al suelo: taladro y taco bajo cada pie
        c = anc.part.data
        texts[anc.group] = texts.get(anc.group, "") + (f" Anclar al suelo con los tacos N-{anc.part.code} (taladro "
                                                       f"Ø{c['dims'][0]:g} × {c['embed_mm'] + 10:g} mm; par según la ETA).")
    out = {}
    for sa in model.subassemblies.values():
        line = fastener_line(model, sa.id)
        out[sa.id] = (texts.get(sa.id, "") + (" " + line if line else "")).strip()
    return out


def component_tools(model) -> tuple[list[str], list[str]]:
    """Herramientas y pares de apriete de los componentes comerciales presentes en el modelo."""
    codes = sorted({i.part.code for i in model.instances if i.part.kind == "normalizado"
                    and i.part.role in FASTENER_ROLES})
    tools: list[str] = []
    torques: list[str] = []
    for code in codes:
        c = catalog.component(code)
        if c.get("tool") and c["tool"] not in tools:
            tools.append(c["tool"])
        if c["category"] == "tornilleria" and c.get("length"):
            tq, ok = joint_torque(model, code)
            nut = next((j.data["rivet"] for j in model.joints if j.kind == "atornillada" and j.data
                        and j.data.get("screw") == code and j.data.get("rivet")), None)
            where = f" en N-{nut}" if nut else ""
            torques.append(f"· N-{code}{where}: " + (f"{_fmt(round(tq, 1))} N·m" if tq is not None else "según ficha") +
                           ("" if ok else " (orientativo, PENDIENTE DE VALIDACIÓN)"))
        elif c["category"] == "anclajes":
            torques.append(f"· N-{code}: par de instalación según la ETA (PENDIENTE DE VALIDACIÓN)")
    return tools, torques


def notes(model, base: list[str]) -> list[str]:
    """Cuadro de herramientas y pares: herramientas de los componentes del modelo seguidas de las propias de la
    familia (sección HERRAMIENTAS de ``base``) y, a continuación, los pares de apriete calculados por unión."""
    tools, torques = component_tools(model)
    block = ["PARES DE APRIETE:", *(torques or ["· Sin uniones atornilladas"])]
    if any("PENDIENTE" in t for t in torques):
        block.append("* Par orientativo: confirmar con la ficha del fabricante.")
    if "HERRAMIENTAS:" in base:
        k = base.index("HERRAMIENTAS:")
        end = next((i for i in range(k + 1, len(base)) if base[i] == ""), len(base))
        return base[:k + 1] + [f"· {t}" for t in tools] + base[k + 1:end] + [""] + block + base[end:]
    return ["HERRAMIENTAS:", *[f"· {t}" for t in tools], ""] + block + [""] + base


def default_notes(model) -> list[str]:
    """Cuadro de herramientas, desmontaje y seguridad por defecto (las familias pueden dar el suyo)."""
    sups = model.structure.get("supports") or []
    castor = bool(sups) and catalog.component(sups[0]["component"])["category"].startswith("ruedas")
    return model.structure.get("assembly_notes") or [
        "HERRAMIENTAS:", *([] if castor else ["· Nivel de burbuja"]), "",
        "DESMONTAJE:", "Chapas desmontables (uniones atornilladas). La estructura es un subconjunto soldado no "
        "desmontable.", "",
        "SEGURIDAD:", "Manipular las chapas entre dos personas; usar guantes (cantos de chapa)."]


def foreign_words(model, texts: list[str]) -> list[str]:
    """Palabras de otro tipo de producto en los textos generados: «encimera» en un producto que no la tiene."""
    worktop = any(sf["id"] == "encimera" for sf in model.structure.get("surfaces", []))
    if worktop:
        return []
    return sorted({t[:80] for t in texts if "encimera" in t.lower()})


def designation_issues(model, texts: list[str]) -> list[str]:
    """Referencias o designaciones de tornillería citadas en las instrucciones que no están en el BOM."""
    bom_codes = {i.part.code for i in model.instances if i.part.kind == "normalizado"}
    designations = set()
    for code in bom_codes:
        c = catalog.component(code)
        if c.get("thread") and c.get("length"):
            designations.add((int(float(c["thread"][1:])), int(c["length"])))
    bad = []
    for t in texts:
        for m in REF_RE.finditer(t):
            ref = m.group(0)
            if ref[2:] not in bom_codes:
                bad.append(ref)
        for m in DESIGNATION_RE.finditer(t):
            if (int(m.group(1)), int(m.group(2))) not in designations:
                bad.append(m.group(0))
    return sorted(set(bad))
