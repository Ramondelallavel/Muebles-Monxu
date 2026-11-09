"""Interfaz común de las familias de producto y registro de familias."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..core.params import AUTO, ParameterSet, ParamSpec

GROUPS = [
    ("dimensiones", "Configuración dimensional"),
    ("materiales", "Materiales y acabados"),
    ("construccion", "Configuración constructiva"),
    ("accesorios", "Accesorios"),
    ("cargas", "Cargas y condiciones de trabajo"),
]


class ProductFamily(ABC):
    id: str = ""
    name: str = ""
    prefix: str = ""
    category: str = ""
    description: str = ""
    status: str = "implementada"
    configurations: list[str] = []
    #: parámetros sin los cuales no puede realizarse la verificación estructural
    verification_inputs: list[str] = []

    @abstractmethod
    def param_specs(self) -> list[ParamSpec]:
        ...

    @abstractmethod
    def construct(self, params: ParameterSet):
        """Construye el modelo con todos los parámetros concretos (sin 'auto')."""

    def new_params(self, values: dict[str, Any] | None = None, source: str = "usuario") -> ParameterSet:
        return ParameterSet.from_specs(self.param_specs(), values, source)

    def default_loads(self, v: dict[str, Any]) -> dict[str, tuple[float, str]]:
        """Cargas de uso que se adoptan cuando no se indican: {parámetro: (kg, explicación)}."""
        return {}

    def build(self, params: ParameterSet):
        """Resuelve los parámetros 'auto' (dimensionado) y construye el modelo."""
        from ..engineering.analysis import overturning
        from ..engineering.sizing import resolve_auto
        rule_notes: list[dict] = []
        ruled: set[str] = set()         # la regla puede reajustar lo que ella misma fijó (el redimensionado cambia perfiles)
        # cargas de uso no indicadas: se adoptan las del uso previsto (el diseño queda siempre verificado)
        dl = {k: lv for k, lv in self.default_loads(params.values).items() if params.values.get(k) is None}
        if dl:
            params = params.copy()
            for k, (kg, _why) in dl.items():
                params.values[k], params.sources[k] = kg, "por_uso"
            label = {sp.name: sp.label for sp in self.param_specs()}
            rule_notes.append({"level": "propuesta", "code": "CARGA-USO",
                               "message": "Carga de uso no indicada: se adopta " + "; ".join(
                                   f"{label.get(k, k).lower()} {kg:g} kg ({why})" for k, (kg, why) in dl.items()) +
                                          ". Confírmela o indique la real."})
        anchorable = any(s.name == "ANCLAJE" and "al_suelo" in (s.choices or []) for s in self.param_specs())
        for _ in range(5):
            autos = [k for k, v in params.values.items() if v == AUTO]
            resolved, notes = resolve_auto(self, params, autos) if autos else (params.copy(), [])
            model = self.construct(resolved)
            # valores por defecto incompatibles (nunca los del usuario): se corrigen y se vuelve a dimensionar
            fixes = {k: fv for k, fv in model.rule_fixes.items()
                     if (params.sources.get(k) == "defecto" or k in ruled) and params.values.get(k) != fv[0]}
            # sin anclaje (por defecto) el conjunto vacío volcaría con el empuje: se ancla al suelo
            if (not fixes and anchorable and params.sources.get("ANCLAJE") == "defecto"
                    and params.values.get("ANCLAJE") == "ninguno"):
                ov = overturning(model, model.params.values)
                if ov and ov["ratio"] > 1.0 + 1e-9:
                    fixes["ANCLAJE"] = ("al_suelo", f"Anclaje al suelo (regla de diseño): sin anclar, el conjunto vacío "
                                                    f"vuelca con el empuje de {ov['H_N']:g} N (aprovechamiento "
                                                    f"{ov['ratio']:.2f}; admite {ov['admissible_N']} N).")
            if not fixes:
                break
            params = params.copy()
            for k, (val, why) in fixes.items():
                params.values[k], params.sources[k] = val, "regla_diseno"
                rule_notes = [n for n in rule_notes if n["code"] != f"REGLA-{k}"]
                rule_notes.append({"level": "propuesta", "code": f"REGLA-{k}", "message": why})
                ruled.add(k)
        model.requested = params
        for n in notes + rule_notes:
            model.design_notes.insert(0, n)
        return model

    def templates(self) -> list[dict[str, Any]]:
        return []

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "prefix": self.prefix, "category": self.category, "description": self.description,
                "status": self.status, "configurations": self.configurations,
                "groups": [{"id": g, "label": lbl} for g, lbl in GROUPS],
                "params": [s.to_dict() for s in self.param_specs()],
                "verification_inputs": self.verification_inputs}


REGISTRY: dict[str, ProductFamily] = {}

#: Familias previstas en la arquitectura cuyo generador todavía no está implementado.
PLANNED: list[dict[str, str]] = [
    {"id": "puesto_trabajo", "name": "Puestos de trabajo industriales", "category": "A",
     "description": "Puestos de montaje, inspección, preparación de pedidos, laboratorio, ergonómicos y modulares."},
    {"id": "estanteria", "name": "Estanterías industriales", "category": "C",
     "description": "Estanterías ligeras, medias y pesadas, modulares, con bandejas, laterales o puertas."},
    {"id": "armario", "name": "Armarios y mobiliario auxiliar", "category": "D",
     "description": "Armarios industriales y de herramientas, bancos de trabajo, carros y estaciones de almacenamiento."},
]


def register(cls):
    inst = cls()
    REGISTRY[inst.id] = inst
    return cls


def family(fid: str) -> ProductFamily:
    if fid not in REGISTRY:
        planned = [p for p in PLANNED if p["id"] == fid]
        if planned:
            raise NotImplementedError(f"La familia '{planned[0]['name']}' está prevista pero su generador "
                                      "paramétrico todavía no está implementado.")
        raise KeyError(f"Familia desconocida: {fid}")
    return REGISTRY[fid]


def library() -> list[dict[str, Any]]:
    out = [{"id": f.id, "name": f.name, "category": f.category, "description": f.description,
            "status": f.status, "configurations": f.configurations} for f in REGISTRY.values()]
    out += [{**p, "status": "en_desarrollo", "configurations": []} for p in PLANNED if p["id"] not in REGISTRY]
    return out
