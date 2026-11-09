"""Asistente conversacional de ingeniería: interpreta, completa lo que falta y propone parámetros.

Flujo: mensaje → interpretación (reglas; opcionalmente Claude con salida estructurada) → fusión con el estado y con
los parámetros del proyecto → supuestos para lo no indicado (medidas propuestas, cargas de uso calculadas por el motor,
material y uso habituales) → parámetros a aplicar. El motor dimensiona y verifica después todo lo que queda 'auto'.
"""
from __future__ import annotations

import os
from typing import Any

from . import interpreter as I

STRUCTURAL_KEYS = ("PROFUNDIDAD", "NUMERO_NIVELES", "CARGA_POR_NIVEL", "ALTURA_PRIMER_NIVEL", "DISTANCIA_BALDAS",
                   "PERFIL_MONTANTE", "LONGITUD", "ANCHURA", "ALTURA", "CARGA_TOTAL", "CARGA_BALDA", "CARGA_PUNTUAL", "CARGA_HORIZONTAL",
                   "MATERIAL_ESTRUCTURAL", "MATERIAL_CHAPA", "ACABADO", "ESPESOR_CHAPA", "NUMERO_BALDAS", "ALTURA_BALDA",
                   "USO", "FRECUENCIA", "ENTORNO", "ANCLAJE", "TIPO_SUELO", "TIPO_APOYO", "PERFIL_PATA",
                   "NUMERO_COLUMNAS", "SEPARACION_COLUMNAS", "LONGITUD_BRAZO", "CARAS", "CARGA_POR_BRAZO",
                   "NUMERO_PELDANOS", "FONDO_MESETA", "HUELLA", "CARGA_REPARTIDA")
#: cargas de uso que el motor adopta por el uso previsto cuando no se indican (ProductFamily.default_loads)
LOAD_PARAMS = ("CARGA_TOTAL", "CARGA_BALDA", "CARGA_POR_NIVEL", "CARGA_ESTANTE", "CARGA_POR_BRAZO")


def new_state(family: str | None = None) -> dict[str, Any]:
    return {"family": family, "values": {}, "evidence": {}, "asked": [], "unsupported": [], "notes": [],
            "history": [], "engine": "reglas"}


def _llm_enabled() -> bool:
    return os.environ.get("MONXU_LLM", "").lower() in ("1", "true", "claude") and bool(
        os.environ.get("MONXU_LLM_MODEL")) and bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _fmt(spec, v) -> str:
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, (int, float)):
        return f"{v:g} {spec.unit}" if spec is not None and spec.unit else f"{v:g}"
    return str(v).replace("_", " ")


def assumptions(fam: str, questions: list, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Supuestos que se adoptan para lo no indicado (antes eran preguntas que dejaban el cálculo PENDIENTE): el valor
    propuesto de cada pregunta y, para las cargas, la carga de uso que el motor calcula para el uso previsto."""
    from ..families import REGISTRY
    f = REGISTRY[fam]
    specs = {sp.name: sp for sp in f.param_specs()}
    merged = {k: sp.default for k, sp in specs.items()}
    merged.update({k: v for k, v in params.items() if k in specs})
    loads = f.default_loads(merged)
    out = []
    for q in questions:
        sp = specs.get(q.param)
        if sp is None:
            continue
        if q.param in LOAD_PARAMS and merged.get(q.param) is None:
            if q.param not in loads:
                continue
            kg, why = loads[q.param]
            out.append({"param": q.param, "label": sp.label, "value": kg,
                        "text": f"{sp.label}: {kg:g} kg, calculada para el uso previsto ({why})."})
        elif q.param == "ANCLAJE":
            out.append({"param": q.param, "label": sp.label, "value": None,
                        "text": f"{sp.label}: lo decide el cálculo (se ancla al suelo, con el taco dimensionado, sólo "
                                "si el conjunto vacío volcaría con el empuje)."})
        else:
            v = params.get(q.param, q.proposal if q.proposal is not None else merged.get(q.param))
            if v is None:
                continue
            txt = ("según la anchura" if q.param == "NUMERO_PUERTAS" else "lo dimensiona el cálculo") \
                if v == "auto" else _fmt(sp, v)
            out.append({"param": q.param, "label": sp.label, "value": v, "text": f"{sp.label}: {txt}."})
    return out


def handle(state: dict[str, Any], message: str = "", answers: dict[str, Any] | None = None,
           llm=None, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Procesa un mensaje (y/o respuestas estructuradas) y devuelve la respuesta del asistente.

    ``current``: parámetros de trabajo del proyecto ({"values", "sources"}). Lo ya definido en el proyecto (formulario,
    plantilla o turnos anteriores) cuenta como conocido y no se vuelve a proponer; ``to_apply`` contiene sólo lo que
    este turno cambia o añade, para no deshacer lo que el usuario haya editado en el formulario."""
    st = dict(state)
    st.setdefault("values", {})
    cur_vals = dict((current or {}).get("values") or {})
    cur_src = dict((current or {}).get("sources") or {})
    known = {k: v for k, v in cur_vals.items() if v != "auto" and cur_src.get(k, "usuario") != "defecto"}
    pending = [q["param"] for q in st.get("last_questions", [])]
    it = I.parse(message, pending, st.get("family")) if message else I.Interpretation()
    engine = "reglas"
    if message and (llm is not None or _llm_enabled()):
        try:
            from .llm import extract
            ext = extract(message, st, client=llm)
            if ext:
                engine = "claude+reglas"
                for k, v in ext.items():
                    if k not in it.values and k in STRUCTURAL_KEYS:     # las reglas prevalecen (evidencia literal)
                        it.set(k, v, "interpretación del modelo de lenguaje")
        except Exception as e:      # la IA es opcional: nunca bloquea al intérprete determinista
            st.setdefault("notes", []).append(f"Asistente LLM no disponible ({type(e).__name__}); se usa el intérprete local.")
    if it.family and not st.get("family"):
        st["family"] = it.family
    values = {**dict(st["values"]), **known}        # el proyecto (formulario) prevalece sobre turnos anteriores
    values.update(it.values)
    for k, v in (answers or {}).items():
        values[k] = v
        it.evidence[k] = "respuesta del usuario"
    turn = set(it.values) | set(answers or {})
    st["values"] = values
    st["evidence"] = {**st.get("evidence", {}), **it.evidence}
    st["unsupported"] = sorted(set(st.get("unsupported", [])) | set(it.unsupported))
    st["notes"] = list(dict.fromkeys(st.get("notes", []) + it.notes))
    asked = set(st.get("asked", []))
    fam = st.get("family")
    questions = I.missing_data(fam, values, asked) if fam else []
    # cada supuesto se expone una vez; las cargas se recuerdan mientras no se indiquen (dependen de las medidas)
    asked |= {q.param for q in questions if q.param not in LOAD_PARAMS}
    st["asked"] = sorted(asked)
    st["last_questions"] = [q.__dict__ for q in questions]
    st["engine"] = engine
    from ..families import REGISTRY
    implemented = fam in REGISTRY
    proposal = I.proposal_for(fam, values) if implemented else {}
    # todo lo interpretado o respondido pasa al motor (antes sólo STRUCTURAL_KEYS: se perdían el asa, el peto o el
    # reposapiés); abajo se filtra a los parámetros que existen en la familia y admiten el valor
    params = {**proposal, **values}
    labels: dict[str, str] = {}
    if implemented:     # sólo parámetros que existen en la familia y con valores admisibles
        specs = {sp.name: sp for sp in REGISTRY[fam].param_specs()}
        labels = {k: sp.label for k, sp in specs.items()}
        clean = {}
        for k, val in params.items():
            if k in specs:
                try:
                    specs[k].coerce(val)
                    clean[k] = val
                except Exception:
                    st["notes"] = list(dict.fromkeys(st["notes"] + [f"Valor «{val}» no admisible para {k}: se ignora."]))
        params = clean
    sources = {k: ("usuario" if k in values else "ia_propuesta") for k in params}
    assumed = assumptions(fam, questions, params) if implemented else []
    reply: list[str] = []
    if not fam:
        reply.append("No identifico la familia de producto. ¿Se trata de una mesa, una estantería, un puesto de trabajo "
                     "o un armario?")
    else:
        reply.append("Interpretación de la solicitud:")
        reply += ["• " + s for s in I.describe(I.Interpretation(fam, values=values, accessories=it.accessories))]
        if not implemented:
            reply.append(f"La familia «{I.LABELS.get(fam, fam)}» está prevista en la arquitectura, pero su generador "
                         "paramétrico todavía no está implementado: no puedo generar un diseño técnico fiable para ella.")
    if st["unsupported"]:
        reply.append("Elementos solicitados que esta versión todavía no genera (no se incluirán en el diseño): "
                     + "; ".join(st["unsupported"]) + ".")
    for n in st["notes"]:
        reply.append("Nota: " + n)
    if assumed:
        reply.append("Lo que no ha indicado lo adopto yo (puede cambiarlo con los botones o escribiendo el dato):")
        reply += ["• " + a["text"] for a in assumed]
    if implemented:
        reply.append("Perfiles, espesores de chapa, pies o ruedas y tacos de anclaje los dimensiona el cálculo, que "
                     "verifica resistencia, pandeo, flechas, soldaduras, apoyos y vuelco con estos datos.")
    st.setdefault("history", []).append({"user": message, "answers": answers or {}})
    # sólo lo que este turno cambia o añade, y lo que el proyecto todavía no tiene
    to_apply = {k: v for k, v in params.items() if k in turn or k not in cur_vals}
    qs = [{**q.__dict__, "label": labels.get(q.param, q.param)} for q in questions]
    return {"state": st, "reply": "\n".join(reply), "interpretation": I.to_dict(it),
            "questions": qs, "assumptions": assumed, "proposal": proposal, "parameters": params,
            "to_apply": to_apply, "sources": sources, "ready_to_generate": implemented, "family": fam,
            "family_implemented": implemented, "engine": engine}
