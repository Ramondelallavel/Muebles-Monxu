"""Adaptador opcional a Claude para extraer parámetros con salida estructurada validada.

Se activa con ``MONXU_LLM=1``, el modelo en ``MONXU_LLM_MODEL`` y credenciales de Anthropic. El modelo sólo devuelve valores
de parámetros que se validan contra el esquema; nunca genera geometría. Si el modelo rechaza
la petición o no está disponible, el asistente continúa con el intérprete determinista.
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from pydantic import BaseModel, Field

#: modelo de Claude que se usa (identificador de la API de Anthropic), configurable sin tocar el código
MODEL = os.environ.get("MONXU_LLM_MODEL", "")

SYSTEM = (
    "Eres un ingeniero de diseño de mobiliario industrial. Extrae de la solicitud del usuario los parámetros "
    "técnicos indicados explícitamente. No inventes valores: deja a null todo lo que el usuario no haya dicho. "
    "Dimensiones en milímetros; cargas en kg (fuerzas horizontales en N). Familias: mesa_industrial, estanteria, "
    "estanteria_bateria, puesto_trabajo, carro_taller, carro_estanteria, carro_plataforma, mesa_soldadura, tarima, armario, "
    "cantilever (estantería de brazos en voladizo para barras, tubos o tableros)."
)


class ExtractedRequest(BaseModel):
    family: Optional[Literal["mesa_industrial", "estanteria", "estanteria_bateria", "puesto_trabajo", "carro_taller",
                             "carro_estanteria", "carro_plataforma", "mesa_soldadura", "tarima", "armario",
                             "cantilever"]] = None
    LONGITUD: Optional[float] = Field(None, description="Longitud en mm")
    ANCHURA: Optional[float] = Field(None, description="Anchura o fondo en mm")
    ALTURA: Optional[float] = Field(None, description="Altura de trabajo en mm")
    PROFUNDIDAD: Optional[float] = Field(None, description="Profundidad (fondo) de estantería en mm")
    NUMERO_NIVELES: Optional[int] = Field(None, description="Niveles de bandejas de estantería")
    NUMERO_MODULOS: Optional[int] = Field(None, description="Módulos contiguos de una estantería en batería")
    CARGA_POR_NIVEL: Optional[float] = Field(None, description="Carga por nivel (o por bandeja en batería) en kg")
    CARGA_TOTAL: Optional[float] = Field(None, description="Carga distribuida sobre la encimera en kg")
    CARGA_BALDA: Optional[float] = Field(None, description="Carga sobre la balda inferior en kg")
    CARGA_PUNTUAL: Optional[float] = Field(None, description="Carga puntual en kg")
    CARGA_HORIZONTAL: Optional[float] = Field(None, description="Empuje horizontal en N")
    NUMERO_BALDAS: Optional[int] = None
    USO: Optional[Literal["montaje_ligero", "montaje", "trabajo_pesado", "inspeccion", "laboratorio", "embalaje"]] = None
    ENTORNO: Optional[Literal["interior_seco", "interior_humedo", "exterior", "alimentario", "sala_limpia"]] = None
    ANCLAJE: Optional[Literal["ninguno", "al_suelo"]] = None
    NUMERO_COLUMNAS: Optional[int] = Field(None, description="Columnas de una estantería cantilever")
    SEPARACION_COLUMNAS: Optional[float] = Field(None, description="Separación entre ejes de columnas cantilever en mm")
    LONGITUD_BRAZO: Optional[float] = Field(None, description="Longitud útil de los brazos cantilever en mm")
    CARAS: Optional[Literal["una", "dos"]] = Field(None, description="Brazos a una o a dos caras (cantilever)")
    CARGA_POR_BRAZO: Optional[float] = Field(None, description="Carga uniforme por brazo cantilever en kg")


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
