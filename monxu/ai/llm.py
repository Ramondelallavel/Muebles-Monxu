"""Adaptador opcional a Claude para extraer parámetros con salida estructurada validada.

Se activa con ``MONXU_LLM=1`` y credenciales de Anthropic. El modelo sólo devuelve valores
de parámetros que se validan contra el esquema; nunca genera geometría. Si el modelo rechaza
la petición o no está disponible, el asistente continúa con el intérprete determinista.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MODEL = "claude-opus-5-5"

SYSTEM = (
    "Eres un ingeniero de diseño de mobiliario industrial. Extrae de la solicitud del usuario los parámetros "
    "técnicos indicados explícitamente. No inventes valores: deja a null todo lo que el usuario no haya dicho. "
    "Dimensiones en milímetros; cargas en kg (fuerzas horizontales en N). Familias: mesa_industrial, estanteria, "
    "puesto_trabajo, armario."
)


class ExtractedRequest(BaseModel):
    family: Optional[Literal["mesa_industrial", "estanteria", "puesto_trabajo", "armario"]] = None
    LONGITUD: Optional[float] = Field(None, description="Longitud en mm")
    ANCHURA: Optional[float] = Field(None, description="Anchura o fondo en mm")
    ALTURA: Optional[float] = Field(None, description="Altura de trabajo en mm")
    CARGA_TOTAL: Optional[float] = Field(None, description="Carga distribuida sobre la encimera en kg")
    CARGA_BALDA: Optional[float] = Field(None, description="Carga sobre la balda inferior en kg")
    CARGA_PUNTUAL: Optional[float] = Field(None, description="Carga puntual en kg")
    CARGA_HORIZONTAL: Optional[float] = Field(None, description="Empuje horizontal en N")
    NUMERO_BALDAS: Optional[int] = None
    USO: Optional[Literal["montaje_ligero", "montaje", "trabajo_pesado", "inspeccion", "laboratorio", "embalaje"]] = None
    ENTORNO: Optional[Literal["interior_seco", "interior_humedo", "exterior", "alimentario", "sala_limpia"]] = None
    ANCLAJE: Optional[Literal["ninguno", "al_suelo"]] = None


def extract(message: str, state: dict, client=None) -> dict:
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    context = f"Datos ya conocidos: {state.get('values', {})}\n\nSolicitud: {message}"
    response = client.messages.parse(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": context}],
        output_format=ExtractedRequest,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return {}
    data = response.parsed_output.model_dump(exclude_none=True)
    data.pop("family", None)
    return data
