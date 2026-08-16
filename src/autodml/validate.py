"""Manifest validation: structural + semantic rules with warnings.

Design: `validate()` never raises; it returns a report you can act on.
`assert_valid()` raises ValidationError when there is at least one
error-level issue. Warnings never block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .model import (
    MDL_TYPES,
    RELATION_TYPES,
    Manifest,
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
QLIKE_RE = re.compile(r"[^\w\s(),.*+\-/'\"]", re.IGNORECASE)

# rules that lint MDL naming conventions
RESERVED_MODEL_SUFFIXES = ("_tmp", "_backup", "_old", "_copy")


@dataclass
class Issue:
    rule: str
    message: str
    severity: str = "error"      # error | warning
    path: Optional[str] = None   # e.g. "models.orders"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def __str__(self) -> str:
        lines = []
        for i in self.issues:
            loc = f" @ {i.path}" if i.path else ""
            lines.append(f"[{i.severity}] {i.rule}{loc}: {i.message}")
        return "\n".join(lines) or "OK"


# ------------------------------------------------------------------ checks


def _check_ident(rep: Report, kind: str, name: str, path: str) -> None:
    if not name or not _IDENT_RE.match(name):
        rep.issues.append(Issue(
            "naming", f"{kind} name {name!r} is not a valid identifier", path=path))
    if name.lower() in ("select", "from", "where", "order", "group", "limit"):
        rep.issues.append(Issue(
            "naming", f"{kind} name {name!r} is a reserved word", path=path))


def _check_type(rep: Report, type_: str, path: str) -> None:
    if type_ not in MDL_TYPES:
        rep.issues.append(Issue("type",
            f"unknown type {type_!r} (allowed: {', '.join(MDL_TYPES)})", path=path))


def validate(manifest: Manifest) -> Report:
    rep = Report()

    seen_models: set[str] = set()
    for m in manifest.models:
        path = f"models.{m.name}"
        _check_ident(rep, "model", m.name, path)

        if m.name in seen_models:
            rep.issues.append(Issue("duplicate", f"duplicate model {m.name!r}", path=path))
        seen_models.add(m.name)

        if not m.refSql and not m.tableReference:
            rep.issues.append(Issue(
                "model-ref", f"model {m.name!r} needs refSql or tableReference", path=path))

        if m.name.lower().endswith(RESERVED_MODEL_SUFFIXES):
            rep.issues.append(Issue("naming",
                f"model {m.name!r} looks like a temp/backup table", severity="warning", path=path))

        seen_cols: set[str] = set()
        for c in m.columns:
            cpath = f"{path}.{c.name}"
            _check_ident(rep, "column", c.name, cpath)
            _check_type(rep, c.type, cpath)
            if c.name in seen_cols:
                rep.issues.append(Issue("duplicate", f"duplicate column {c.name!r}", path=cpath))
            seen_cols.add(c.name)

        for calc in m.calculations:
            cpath = f"{path}.calculations.{calc.name}"
            _check_ident(rep, "calculation", calc.name, cpath)
            _check_type(rep, calc.type, cpath)
            if calc.name in seen_cols:
                rep.issues.append(Issue(
                    "duplicate", f"calculation {calc.name!r} clashes with a column", path=cpath))
            if not calc.expression.strip():
                rep.issues.append(Issue("expression", "empty expression", path=cpath))

    # relationships
    seen_rels: set[str] = set()
    for r in manifest.relationships:
        path = f"relationships.{r.name}"
        _check_ident(rep, "relationship", r.name, path)
        if r.name in seen_rels:
            rep.issues.append(Issue("duplicate", f"duplicate relationship {r.name!r}", path=path))
        seen_rels.add(r.name)

        if r.relationType not in RELATION_TYPES:
            rep.issues.append(Issue("relation-type",
                f"unknown relationType {r.relationType!r} (allowed: {', '.join(RELATION_TYPES)})",
                path=path))

        for side_name, side in (("left", r.left), ("right", r.right)):
            m = manifest.model(side.modelName)
            if m is None:
                rep.issues.append(Issue(
                    "missing-ref", f"{side_name} model {side.modelName!r} not found", path=path))
                continue
            for col in [x.strip() for x in side.columnName.split(",")]:
                if m.column(col) is None:
                    rep.issues.append(Issue("missing-ref",
                        f"column {side.modelName}.{col} not found", path=path))

        # PK guidance: many-to-one right side should be unique in practice
        if r.relationType == "manyToOne":
            left_model = manifest.model(r.left.modelName)
            if left_model and not left_model.primary_keys:
                rep.issues.append(Issue("relation-pk",
                    f"model {r.left.modelName!r} has no primary key; joins may fan out",
                    severity="warning", path=path))

    # metrics
    for mt in manifest.metrics:
        path = f"metrics.{mt.name}"
        _check_ident(rep, "metric", mt.name, path)
        _check_type(rep, mt.type, path)
        m = manifest.model(mt.baseModel)
        if m is None:
            rep.issues.append(Issue("missing-ref", f"baseModel {mt.baseModel!r} not found", path=path))
        if not mt.expression.strip():
            rep.issues.append(Issue("expression", "empty expression", path=path))

    # views
    for v in manifest.views:
        path = f"views.{v.name}"
        _check_ident(rep, "view", v.name, path)
        if not v.statement.strip():
            rep.issues.append(Issue("expression", "empty statement", path=path))
        # naive: referenced tables should be model names
        for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", v.statement):
            if word.lower() in ("select", "from", "where", "join", "group", "by", "order",
                                "on", "as", "and", "or", "not", "limit", "inner", "left",
                                "right", "outer", "having", "distinct", "case", "when",
                                "then", "else", "end", "sum", "count", "avg", "min", "max",
                                "with", "over", "partition", "true", "false", "null", "is",
                                "in", "between", "like", "cast", "asc", "desc", "union",
                                "all", "cross", "full", "top", "exists"):
                continue
            if manifest.model(word) is None and word not in {c.name for m in manifest.models for c in m.columns}:
                rep.issues.append(Issue("view-ref",
                    f"identifier {word!r} in view statement is not a known model/column",
                    severity="warning", path=path))

    return rep


def assert_valid(manifest: Manifest) -> None:
    rep = validate(manifest)
    if not rep.ok:
        from .errors import ValidationError
        raise ValidationError(rep.errors)
