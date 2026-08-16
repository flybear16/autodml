"""Export a Manifest to cubepy (Cube.js-style) schema YAML.

Mapping (autodml -> cubepy):

  Model        -> Cube   (refSql -> ``SELECT * FROM <refSql>``)
  Column       -> Dimension (type-mapped; isPrimary -> primaryKey flag)
  Calculation  -> Dimension with sql = expression
  Relationship -> Join on the FK side (manyToOne -> belongsTo, oneToMany -> hasMany,
                  oneToOne -> hasOne; manyToMany skipped — needs a bridge cube)
  Metric       -> Measure on the base model's cube (SUM(x)/COUNT(*)/COUNT(DISTINCT x)/
                  AVG/MIN/MAX parsed; anything else is skipped with a warning)
  View         -> no cubepy equivalent, skipped with a warning

Emitted YAML loads with ``cubepy.schema.loader.load_cube_file``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Union

import yaml

from ..model import Manifest, Model

PathLike = Union[str, Path]

# MDL type -> cubepy DimensionType
TYPE_MAP = {
    "string": "string",
    "integer": "number",
    "decimal": "number",
    "float": "number",
    "double": "number",
    "boolean": "boolean",
    "date": "time",
    "timestamp": "time",
    "timestamptz": "time",
    "time": "time",
    "json": "string",
    "unknown": "string",
}

_MEASURE_RE = re.compile(
    r"^\s*(SUM|AVG|MIN|MAX|COUNT)\s*\(\s*(\*|(?:DISTINCT\s+)?[\w.]+)\s*\)\s*$",
    re.IGNORECASE,
)


def _measure_from_metric(expr: str) -> dict | None:
    """Parse ``SUM(amount)`` / ``COUNT(*)`` / ``COUNT(DISTINCT id)`` -> measure dict."""
    m = _MEASURE_RE.match(expr or "")
    if not m:
        return None
    agg, arg = m.group(1).lower(), m.group(2)
    if agg == "count":
        if arg == "*":
            return {"type": "count"}
        if arg.upper().startswith("DISTINCT"):
            return {"type": "countDistinct", "sql": arg.split(None, 1)[1]}
        return {"type": "count", "sql": arg}
    return {"type": agg, "sql": arg}


def _join_sql(left_model: str, left_cols: str, right_model: str, right_cols: str) -> str:
    ls = [f"{left_model}.{c.strip()}" for c in left_cols.split(",")]
    rs = [f"{right_model}.{c.strip()}" for c in right_cols.split(",")]
    return " AND ".join(f"{a} = {b}" for a, b in zip(ls, rs))


def manifest_to_cubepy(manifest: Manifest) -> tuple[dict, list[str]]:
    """Convert a Manifest to a cubepy schema dict ``{"cubes": [...]}``.

    Returns ``(data, warnings)``; warnings list human-readable skips.
    """
    warnings: list[str] = []
    cubes: list[dict] = []
    by_name = {m.name: m for m in manifest.models}

    joins_by_cube: dict[str, dict] = {}
    for rel in manifest.relationships:
        if rel.relationType == "manyToOne":
            # left holds the FK -> left cube belongsTo right
            joins_by_cube.setdefault(rel.left.modelName, {})[rel.right.modelName] = {
                "relationship": "belongsTo",
                "sql": _join_sql(rel.left.modelName, rel.left.columnName,
                                 rel.right.modelName, rel.right.columnName),
            }
        elif rel.relationType == "oneToMany":
            # right holds the FK -> left cube hasMany right
            joins_by_cube.setdefault(rel.left.modelName, {})[rel.right.modelName] = {
                "relationship": "hasMany",
                "sql": _join_sql(rel.left.modelName, rel.left.columnName,
                                 rel.right.modelName, rel.right.columnName),
            }
        elif rel.relationType == "oneToOne":
            joins_by_cube.setdefault(rel.left.modelName, {})[rel.right.modelName] = {
                "relationship": "hasOne",
                "sql": _join_sql(rel.left.modelName, rel.left.columnName,
                                 rel.right.modelName, rel.right.columnName),
            }
        else:  # manyToMany
            warnings.append(
                f"relationship {rel.name!r}: manyToMany has no single-join cubepy "
                "equivalent (needs a bridge cube); skipped"
            )

    measures_by_cube: dict[str, list[dict]] = {}
    for mt in manifest.metrics:
        base = mt.baseModel
        if base not in by_name:
            warnings.append(f"metric {mt.name!r}: baseModel {base!r} not found; skipped")
            continue
        parsed = _measure_from_metric(mt.expression)
        if parsed is None:
            warnings.append(
                f"metric {mt.name!r}: expression {mt.expression!r} is not a simple "
                "SUM/COUNT/AVG/MIN/MAX aggregate; skipped (add it by hand as a "
                "calculated measure)"
            )
            continue
        entry = {"name": mt.name, **parsed}
        if mt.description:
            entry["description"] = mt.description
        measures_by_cube.setdefault(base, []).append(entry)

    for model in manifest.models:
        cube: dict = {
            "name": model.name,
            "sql": f"SELECT * FROM {model.refSql or model.name}",
        }
        if model.description:
            cube["description"] = model.description

        dimensions = []
        for col in model.columns:
            d: dict = {"name": col.name, "sql": col.name,
                       "type": TYPE_MAP.get(col.type, "string")}
            if col.isPrimary:
                d["primaryKey"] = True
            if col.description:
                d["description"] = col.description
            dimensions.append(d)
        for calc in model.calculations:
            dimensions.append({
                "name": calc.name, "sql": calc.expression,
                "type": TYPE_MAP.get(calc.type, "string"),
                **({"description": calc.description} if calc.description else {}),
            })
        if dimensions:
            cube["dimensions"] = dimensions

        measures = measures_by_cube.get(model.name, [])
        if measures:
            cube["measures"] = measures

        joins = joins_by_cube.get(model.name)
        if joins:
            cube["joins"] = joins

        cubes.append(cube)

    for v in manifest.views:
        warnings.append(f"view {v.name!r}: no cubepy equivalent; skipped")

    return {"cubes": cubes}, warnings


def to_cubepy_yaml(manifest: Manifest) -> tuple[str, list[str]]:
    data, warnings = manifest_to_cubepy(manifest)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True), warnings


def write_cubepy_yaml(manifest: Manifest, path: PathLike) -> tuple[Path, list[str]]:
    text, warnings = to_cubepy_yaml(manifest)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p, warnings
