"""Core MDL object model.

Python-side naming is snake_case; serialized output is camelCase,
compatible with the mdl.json format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional

# MDL scalar types
MDL_TYPES = (
    "string", "integer", "decimal", "float", "double", "boolean",
    "date", "timestamp", "timestamptz", "time", "json", "unknown",
)
RELATION_TYPES = ("oneToOne", "oneToMany", "manyToOne", "manyToMany")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _clean(d: dict) -> dict:
    """Drop None values recursively (keep False/0/'')."""
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict):
            v = _clean(v)
        elif isinstance(v, list):
            v = [_clean(x) if isinstance(x, dict) else x for x in v]
        out[k] = v
    return out


class _Node:
    """Base: to_dict / from_dict helpers + nested dict coercion."""

    def to_dict(self) -> dict:
        return _clean(asdict(self))

    @classmethod
    def from_dict(cls, d: dict) -> "_Node":
        valid = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in valid})


def _coerce_list(items: list, klass) -> list:
    return [klass(**x) if isinstance(x, dict) else x for x in items]


def _coerce_node(value, klass):
    return klass(**value) if isinstance(value, dict) else value


def _canon_keys(d: dict, klass) -> dict:
    """Camelize keys (ref_sql -> refSql) and keep only known fields."""
    valid = {f.name for f in klass.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    out = {}
    for k, v in d.items():
        ck = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), k)
        if ck in valid:
            out[ck] = v
    return out


# ---------------------------------------------------------------- columns


@dataclass
class Column(_Node):
    name: str
    type: str = "string"
    notNull: bool = False
    isPrimary: bool = False
    description: Optional[str] = None
    # nested struct/enum not in v0.1 core; reserved


@dataclass
class Calculation(_Node):
    name: str
    expression: str
    type: str = "string"
    description: Optional[str] = None


# ---------------------------------------------------------------- models


@dataclass
class Model(_Node):
    name: str
    refSql: Optional[str] = None          # physical table ref, e.g. public.orders
    tableReference: Optional[list[str]] = None  # alternative: ["public", "orders"]
    columns: list[Column] = field(default_factory=list)
    calculations: list[Calculation] = field(default_factory=list)
    description: Optional[str] = None
    cached: bool = False

    def __post_init__(self):
        self.columns = _coerce_list(self.columns, Column)
        self.calculations = _coerce_list(self.calculations, Calculation)

    @property
    def primary_keys(self) -> list[str]:
        return [c.name for c in self.columns if c.isPrimary]

    def column(self, name: str) -> Optional[Column]:
        for c in self.columns:
            if c.name == name:
                return c
        return None


@dataclass
class ViewTableSource(_Node):
    modelName: str
    calculate: Optional[str] = None  # optional pre-aggregation sql


@dataclass
class ViewColumn(_Node):
    name: str
    type: str = "string"
    expression: Optional[str] = None


@dataclass
class View(_Node):
    name: str
    statement: str
    columns: list[ViewColumn] = field(default_factory=list)
    description: Optional[str] = None

    # v0.1: statement is plain SQL over model names
    def __post_init__(self):
        self.columns = _coerce_list(self.columns, ViewColumn)


# ---------------------------------------------------------------- relationships


@dataclass
class RelationshipSide(_Node):
    modelName: str
    columnName: str  # may be comma-separated composite key

    def __post_init__(self):
        # tolerate snake_case dict keys (model_name / column_name)
        pass

    @classmethod
    def coerce(cls, value) -> "RelationshipSide":
        if isinstance(value, dict):
            return cls(**_canon_keys(value, cls))
        return value


@dataclass
class Relationship(_Node):
    name: str
    relationType: str  # oneToOne | oneToMany | manyToOne | manyToMany
    left: RelationshipSide
    right: RelationshipSide

    def __post_init__(self):
        self.left = RelationshipSide.coerce(self.left)
        self.right = RelationshipSide.coerce(self.right)


# ---------------------------------------------------------------- metrics


@dataclass
class Metric(_Node):
    name: str
    baseModel: str
    expression: str
    type: str = "decimal"
    description: Optional[str] = None


# ---------------------------------------------------------------- manifest


@dataclass
class Manifest(_Node):
    manifest: str = "default"
    version: str = "1.0.0"
    models: list[Model] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    views: list[View] = field(default_factory=list)

    def __post_init__(self):
        self.models = _coerce_list(self.models, Model)
        self.relationships = _coerce_list(self.relationships, Relationship)
        self.metrics = _coerce_list(self.metrics, Metric)
        self.views = _coerce_list(self.views, View)

    # -- lookups -----------------------------------------------------

    def model(self, name: str) -> Optional[Model]:
        for m in self.models:
            if m.name == name:
                return m
        return None

    def metric(self, name: str) -> Optional[Metric]:
        for m in self.metrics:
            if m.name == name:
                return m
        return None

    def relationship(self, name: str) -> Optional[Relationship]:
        for r in self.relationships:
            if r.name == name:
                return r
        return None

    def relationships_of(self, model_name: str) -> list[Relationship]:
        return [
            r for r in self.relationships
            if r.left.modelName == model_name or r.right.modelName == model_name
        ]

    def add(self, *nodes: Any) -> "Manifest":
        """Fluent add: accepts Model/Relationship/Metric/View."""
        for n in nodes:
            if isinstance(n, Model):
                self.models.append(n)
            elif isinstance(n, Relationship):
                self.relationships.append(n)
            elif isinstance(n, Metric):
                self.metrics.append(n)
            elif isinstance(n, View):
                self.views.append(n)
            else:
                raise TypeError(f"cannot add {type(n).__name__} to manifest")
        return self
