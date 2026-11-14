"""Tabla central de parámetros y grafo de dependencias.

* :class:`ParamSpec` define un parámetro (tipo, unidad, límites, opciones, grupo del asistente).
* :class:`ParamContext` resuelve parámetros base y derivados registrando automáticamente
  qué parámetros lee cada derivado y cada operación del árbol (dependencias reales, no declaradas
  a mano). Con ese grafo se calcula el impacto de un cambio (qué operaciones se regeneran).
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

AUTO = "auto"


class ParamError(ValueError):
    pass


@dataclass
class ParamSpec:
    name: str
    label: str
    type: str                      # float | int | choice | bool | str
    default: Any
    unit: str | None = None
    group: str = "dimensiones"     # paso del configurador
    min: float | None = None
    max: float | None = None
    choices: list[Any] | None = None
    allow_auto: bool = False
    nullable: bool = False
    help: str = ""
    advanced: bool = False

    def coerce(self, value: Any) -> Any:
        if value is None:
            if self.nullable:
                return None
            raise ParamError(f"{self.name}: valor obligatorio")
        if self.allow_auto and isinstance(value, str) and value.strip().lower() == AUTO:
            return AUTO
        try:
            if self.type == "float":
                v: Any = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
                if math.isnan(v):
                    raise ValueError
            elif self.type == "int":
                v = int(float(value))
            elif self.type == "bool":
                if isinstance(value, str):
                    v = value.strip().lower() in ("1", "true", "si", "sí", "yes")
                else:
                    v = bool(value)
            else:
                v = value
        except (TypeError, ValueError):
            raise ParamError(f"{self.name}: valor no válido '{value}' (se esperaba {self.type})") from None
        if self.type in ("float", "int"):
            if self.min is not None and v < self.min:
                raise ParamError(f"{self.name} = {v} {self.unit or ''} inferior al mínimo {self.min}")
            if self.max is not None and v > self.max:
                raise ParamError(f"{self.name} = {v} {self.unit or ''} superior al máximo {self.max}")
        if self.type == "choice" and self.choices is not None and v not in self.choices:
            raise ParamError(f"{self.name}: '{v}' no está entre las opciones {self.choices}")
        return v

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("name", "label", "type", "default", "unit", "group", "min", "max",
                                              "choices", "allow_auto", "nullable", "help", "advanced")}


# Origen del valor de cada parámetro (trazabilidad usuario / IA / regla)
SOURCES = ("usuario", "defecto", "plantilla", "ia_propuesta", "regla_diseno", "calculo")


@dataclass
class ParameterSet:
    specs: dict[str, ParamSpec]
    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_specs(cls, specs: Iterable[ParamSpec], values: dict[str, Any] | None = None,
                   source: str = "usuario") -> "ParameterSet":
        ps = cls({s.name: s for s in specs})
        for s in ps.specs.values():
            ps.values[s.name] = s.default
            ps.sources[s.name] = "defecto"
        if values:
            ps.update(values, source)
        return ps

    def update(self, values: dict[str, Any], source: str = "usuario") -> list[str]:
        errors = []
        for k, v in values.items():
            if k not in self.specs:
                errors.append(f"Parámetro desconocido: {k}")
                continue
            try:
                self.values[k] = self.specs[k].coerce(v)
                self.sources[k] = source
            except ParamError as e:
                errors.append(str(e))
        if errors:
            raise ParamError("; ".join(errors))
        return list(values)

    def copy(self) -> "ParameterSet":
        return ParameterSet(self.specs, dict(self.values), dict(self.sources))

    def diff(self, other: "ParameterSet") -> dict[str, tuple[Any, Any]]:
        return {k: (other.values.get(k), v) for k, v in self.values.items() if other.values.get(k) != v}


@dataclass
class DerivedParam:
    name: str
    value: Any
    unit: str | None
    label: str
    deps: set[str]


@dataclass
class FeatureRecord:
    """Nodo del árbol de operaciones paramétricas."""
    id: str
    label: str
    reads: set[str] = field(default_factory=set)
    produces: list[str] = field(default_factory=list)      # ids de instancias creadas
    parent: str | None = None


class ParamContext:
    """Acceso a parámetros con registro automático de dependencias."""

    def __init__(self, params: ParameterSet):
        self.params = params
        self.derived: dict[str, DerivedParam] = {}
        self.features: dict[str, FeatureRecord] = {}
        self._stack: list[set[str]] = []
        self._feature_stack: list[FeatureRecord] = []

    # -- lectura
    def __getitem__(self, name: str) -> Any:
        for s in self._stack:
            s.add(name)
        if name in self.derived:
            return self.derived[name].value
        if name in self.params.values:
            return self.params.values[name]
        raise KeyError(f"Parámetro no definido: {name}")

    def get(self, name: str, default: Any = None) -> Any:
        try:
            return self[name]
        except KeyError:
            return default

    def uses(self, *names: str) -> None:
        """Declara dependencias de la operación actual (base o derivadas)."""
        for n in names:
            self[n]

    # -- derivados
    def derive(self, name: str, fn: Callable[["ParamContext"], Any], unit: str | None = None,
               label: str = "") -> Any:
        reads: set[str] = set()
        self._stack.append(reads)
        try:
            value = fn(self)
        finally:
            self._stack.pop()
        for s in self._stack:
            s.add(name)
        self.derived[name] = DerivedParam(name, value, unit, label or name, reads)
        return value

    def set_derived(self, name: str, value: Any, unit: str | None = None, label: str = "",
                    deps: Iterable[str] = ()) -> Any:
        self.derived[name] = DerivedParam(name, value, unit, label or name, set(deps))
        return value

    # -- árbol de operaciones
    @contextmanager
    def feature(self, fid: str, label: str):
        rec = FeatureRecord(fid, label, parent=self._feature_stack[-1].id if self._feature_stack else None)
        self.features[fid] = rec
        self._stack.append(rec.reads)
        self._feature_stack.append(rec)
        try:
            yield rec
        finally:
            self._stack.pop()
            self._feature_stack.pop()

    @property
    def current_feature(self) -> FeatureRecord | None:
        return self._feature_stack[-1] if self._feature_stack else None

    # -- análisis de dependencias
    def base_dependencies(self, name: str, _seen: set[str] | None = None) -> set[str]:
        """Parámetros base de los que depende (transitivamente) un parámetro derivado."""
        if name not in self.derived:
            return {name}
        _seen = _seen if _seen is not None else set()
        out: set[str] = set()
        for d in self.derived[name].deps:
            if d in _seen:
                continue
            _seen.add(d)
            out |= self.base_dependencies(d, _seen)
        return out

    def feature_base_dependencies(self, fid: str) -> set[str]:
        out: set[str] = set()
        for r in self.features[fid].reads:
            out |= self.base_dependencies(r)
        return out

    def impact(self, changed: Iterable[str]) -> list[str]:
        """Operaciones del árbol afectadas por un cambio de parámetros base."""
        changed = set(changed)
        return [fid for fid in self.features if self.feature_base_dependencies(fid) & changed]
