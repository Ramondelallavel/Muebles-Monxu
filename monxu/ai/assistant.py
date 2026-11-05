"""Asistente conversacional de ingeniería: interpreta, pregunta lo que falta y propone parámetros.

Flujo: mensaje → interpretación (reglas; opcionalmente Claude con salida estructurada) →
fusión con el estado → preguntas pendientes → propuesta de configuración. Los parámetros se
envían al motor CAD sólo cuando el usuario los aplica; el cálculo los verifica después.
"""
from __future__ import annotations

import os
from typing import Any

from . import interpreter as I

STRUCTURAL_KEYS = ("LONGITUD", "ANCHURA", "ALTURA", "CARGA_TOTAL", "CARGA_BALDA", "CARGA_PUNTUAL", "CARGA_HORIZONTAL",
                   "MATERIAL_ESTRUCTURAL", "MATERIAL_CHAPA", "ACABADO", "ESPESOR_CHAPA", "NUMERO_BALDAS", "ALTURA_BALDA",
                   "USO", "FRECUENCIA", "ENTORNO", "ANCLAJE", "TIPO_SUELO", "TIPO_APOYO", "PERFIL_PATA")


def new_state(family: str | None = None) -> dict[str, Any]:
    return {"family": family, "values": {}, "evidence": {}, "asked": [], "unsupported": [], "notes": [],
            "history": [], "engine": "reglas"}


def _llm_enabled() -> bool:
    return os.environ.get("MONXU_LLM", "").lower() in ("1", "true", "claude") and bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def handle(state: dict[str, Any], message: str = "", answers: dict[str, Any] | None = None,
           llm=None) -> dict[str, Any]:
    """Procesa un mensaje (y/o respuestas estructuradas) y devuelve la respuesta del asistente."""
    st = dict(state)
    st.setdefault("values", {})
    pending = [q["param"] for q in st.get("last_questions", [])]
    it = I.parse(message, pending) if message else I.Interpretation()
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
    values = dict(st["values"])
    values.update(it.values)
    for k, v in (answers or {}).items():
        values[k] = v
        it.evidence[k] = "respuesta del usuario"
    st["values"] = values
    st["evidence"] = {**st.get("evidence", {}), **it.evidence}
    st["unsupported"] = sorted(set(st.get("unsupported", [])) | set(it.unsupported))
    st["notes"] = list(dict.fromkeys(st.get("notes", []) + it.notes))
    asked = set(st.get("asked", []))
    fam = st.get("family")
    questions = I.missing_data(fam, values, asked) if fam else []
    asked |= {q.param for q in questions if q.blocking == "confirmacion"}
    st["asked"] = sorted(asked)
    st["last_questions"] = [q.__dict__ for q in questions]
    st["engine"] = engine
    implemented = fam == "mesa_industrial"
    proposal = I.proposal_for(fam, values) if implemented else {}
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
    gen_block = [q for q in questions if q.blocking == "generacion"]
    if questions:
        reply.append("Necesito confirmar estos datos:")
        reply += [f"{n}. {q.question} ({q.why})" for n, q in enumerate(questions, start=1)]
    if implemented:
        if proposal:
            reply.append("Propuesta constructiva preliminar (pendiente de verificación por cálculo): " +
                         ", ".join(f"{k} = {v}" for k, v in proposal.items()) +
                         ". 'auto' significa que el motor de cálculo dimensionará la sección.")
        reply.append("Puede generar ya un diseño preliminar; los datos pendientes quedarán marcados como tales."
                     if not gen_block else "Faltan dimensiones para generar la geometría.")
    params = {**proposal, **{k: v for k, v in values.items() if k in STRUCTURAL_KEYS}}
    if implemented and "CARGA_HORIZONTAL" not in values:
        params.pop("CARGA_HORIZONTAL", None)
    sources = {k: ("usuario" if k in values else "ia_propuesta") for k in params}
    st.setdefault("history", []).append({"user": message, "answers": answers or {}})
    return {"state": st, "reply": "\n".join(reply), "interpretation": I.to_dict(it),
            "questions": [q.__dict__ for q in questions], "proposal": proposal, "parameters": params,
            "sources": sources, "ready_to_generate": implemented and not gen_block, "family": fam,
            "family_implemented": implemented, "engine": engine}
