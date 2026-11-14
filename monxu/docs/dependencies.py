"""Mapa de dependencias: qué documentos hay que regenerar cuando cambia un parámetro (= engine/dependencies.ts).

Todos los documentos salen del modelo maestro; el mapa dice cuáles cambian con cada parámetro, a partir del árbol de
operaciones (parámetros que lee cada operación y piezas que produce) y de los parámetros que leen los procesos
(cálculo, plan de corte, anidado, presupuesto, instrucciones)."""
from __future__ import annotations

from typing import Any

#: parámetros de proceso que no intervienen en la geometría
PROCESS = {
    "plan_corte": ("LONGITUD_BARRA", "CORTE_SIERRA", "LOTE_FABRICACION"),
    "anidado": ("FORMATO_CHAPA", "LOTE_FABRICACION"),
    "presupuesto": ("ACABADO", "ESPESOR_PINTURA", "LOTE_FABRICACION", "LONGITUD_BARRA", "CORTE_SIERRA", "FORMATO_CHAPA"),
    "planos": ("TOLERANCIAS", "ACABADO", "CLASE_EJECUCION"),
    "calculo": (),
}
DOCUMENTS = {"modelo_3d": "Modelo 3D (STEP, STL, JSON paramétrico)", "planos": "Planos PDF", "dxf": "DXF de corte y desarrollos",
             "bom": "BOM (Excel y CSV)", "plan_corte": "Plan de corte de perfiles", "anidado": "Anidado de chapa",
             "compras": "Lista de compras", "presupuesto": "Presupuesto", "calculo": "Informe de cálculo",
             "montaje": "Instrucciones de montaje", "verificaciones": "Informe de verificaciones (QA)"}


def dependency_map(model) -> dict[str, list[str]]:
    """Documento → parámetros base de los que depende."""
    tree = model.feature_tree()
    inst = {i.id: i for i in model.instances}
    kind_params: dict[str, set[str]] = {"perfil": set(), "chapa": set(), "pletina": set(), "normalizado": set()}
    geo: set[str] = set()
    for f in tree:
        ps = set(f["params"])
        geo |= ps
        for iid in f["produces"]:
            if iid in inst:
                kind_params[inst[iid].part.kind] |= ps
    specs = model.params.specs
    loads = {n for n, s in specs.items() if s.group == "cargas"}
    sheet = kind_params["chapa"] | kind_params["pletina"]
    deps = {
        "modelo_3d": geo, "planos": geo | set(PROCESS["planos"]) | loads, "dxf": sheet,
        "bom": geo | {"ACABADO"}, "plan_corte": kind_params["perfil"] | set(PROCESS["plan_corte"]),
        "anidado": sheet | set(PROCESS["anidado"]),
        "compras": kind_params["perfil"] | sheet | kind_params["normalizado"] | set(PROCESS["plan_corte"]) | set(PROCESS["anidado"]),
        "presupuesto": geo | set(PROCESS["presupuesto"]), "calculo": geo | loads,
        "montaje": kind_params["normalizado"] | {n for n in ("ANCLAJE", "TACO_ANCLAJE", "TIPO_APOYO") if n in specs},
    }
    deps["verificaciones"] = set().union(*deps.values())
    return {k: sorted(n for n in v if n in specs) for k, v in deps.items()}


def affected_documents(dep: dict[str, list[str]], changed) -> list[str]:
    """Documentos que deben regenerarse cuando cambian los parámetros ``changed``."""
    ch = set(changed)
    return [DOCUMENTS[k] for k, v in dep.items() if ch & set(v)]
