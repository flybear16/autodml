"""Serialization: manifest <-> dict / JSON / YAML (camelCase mdl.json).

Two YAML flavors:
- single-file: one document = one manifest
- multi-file directory: models/*.yml + relationships.yml + metrics.yml + views.yml
  (models/ views/ relationships.yml layout)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

import yaml

from .errors import ParseError
from .model import (
    Calculation,
    Column,
    Manifest,
    Metric,
    Model,
    Relationship,
    RelationshipSide,
    View,
    ViewColumn,
    _canon_keys,
)

PathLike = Union[str, Path]


# ------------------------------------------------------------------ dump


def to_dict(manifest: Manifest) -> dict:
    return manifest.to_dict()


def to_json(manifest: Manifest, indent: int = 2, sort_keys: bool = False) -> str:
    return json.dumps(to_dict(manifest), indent=indent, sort_keys=sort_keys, ensure_ascii=False)


def to_yaml(manifest: Manifest, sort_keys: bool = False) -> str:
    return yaml.safe_dump(to_dict(manifest), sort_keys=sort_keys, allow_unicode=True)


def write_json(manifest: Manifest, path: PathLike) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(to_json(manifest), encoding="utf-8")
    return p


# multi-file layout -------------------------------------------------------


def write_dir(manifest: Manifest, root: PathLike) -> Path:
    """Write standard MDL project layout:

    root/
      relationships.yml
      metrics.yml
      views/<name>.yml
      models/<name>.yml
    """
    root = Path(root)
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "views").mkdir(parents=True, exist_ok=True)

    _yaml_dump(root / "project.yml", {
        "manifest": manifest.manifest,
        "version": manifest.version,
    })
    for m in manifest.models:
        _yaml_dump(root / "models" / f"{m.name}.yml", m.to_dict())
    for v in manifest.views:
        _yaml_dump(root / "views" / f"{v.name}.yml", v.to_dict())
    if manifest.relationships:
        _yaml_dump(root / "relationships.yml",
                   {"relationships": [r.to_dict() for r in manifest.relationships]})
    if manifest.metrics:
        _yaml_dump(root / "metrics.yml",
                   {"metrics": [m.to_dict() for m in manifest.metrics]})
    return root


def _yaml_dump(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ------------------------------------------------------------------ load


def _coerce_manifest(d: dict) -> Manifest:
    """dict -> Manifest with camelCase tolerance (accept snake_case too)."""
    def g(key: str) -> Any:
        return d.get(key, d.get(_snake(key)))

    models = []
    for md in g("models") or []:
        md = _canon_keys(md, Model)
        cols = [Column(**_canon_keys(c, Column)) for c in md.get("columns", [])]
        calcs = [Calculation(**_canon_keys(c, Calculation)) for c in md.get("calculations", [])]
        models.append(Model(
            name=md.get("name", ""),
            refSql=md.get("refSql"),
            tableReference=md.get("tableReference"),
            columns=cols,
            calculations=calcs,
            description=md.get("description"),
            cached=md.get("cached", False),
        ))

    rels = []
    for rd in g("relationships") or []:
        rd = _canon_keys(rd, Relationship)
        left = RelationshipSide.coerce(rd.get("left", {}))
        right = RelationshipSide.coerce(rd.get("right", {}))
        rels.append(Relationship(
            name=rd.get("name", ""),
            relationType=rd.get("relationType", ""),
            left=left, right=right,
        ))

    metrics = []
    for mtd in g("metrics") or []:
        mtd = _canon_keys(mtd, Metric)
        metrics.append(Metric(
            name=mtd.get("name", ""),
            baseModel=mtd.get("baseModel", ""),
            expression=mtd.get("expression", ""),
            type=mtd.get("type", "decimal"),
            description=mtd.get("description"),
        ))

    views = []
    for vd in g("views") or []:
        vd = _canon_keys(vd, View)
        vcols = [ViewColumn(**_canon_keys(c, ViewColumn)) for c in vd.get("columns", [])]
        views.append(View(
            name=vd.get("name", ""),
            statement=vd.get("statement", ""),
            columns=vcols,
            description=vd.get("description"),
        ))

    return Manifest(
        manifest=g("manifest") or "default",
        version=g("version") or "1.0.0",
        models=models, relationships=rels, metrics=metrics, views=views,
    )


def _snake(name: str) -> str:
    return "".join("_" + ch.lower() if ch.isupper() else ch for ch in name).lstrip("_")


def from_dict(d: dict) -> Manifest:
    if not isinstance(d, dict):
        raise ParseError(f"expected dict, got {type(d).__name__}")
    return _coerce_manifest(d)


def from_json(text: str) -> Manifest:
    try:
        return from_dict(json.loads(text))
    except json.JSONDecodeError as e:
        raise ParseError(f"invalid JSON: {e}") from e


def from_yaml(text: str) -> Manifest:
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as e:
        raise ParseError(f"invalid YAML: {e}") from e
    docs = [d for d in docs if d]
    if not docs:
        raise ParseError("empty YAML document")
    if len(docs) > 1:
        raise ParseError("multiple YAML documents not supported in single file")
    return from_dict(docs[0])


def load(path: PathLike) -> Manifest:
    p = Path(path)
    if p.is_dir():
        return load_dir(p)
    text = p.read_text(encoding="utf-8")
    return from_json(text) if p.suffix == ".json" else from_yaml(text)


def load_dir(root: PathLike) -> Manifest:
    """Load standard MDL project directory layout into one manifest."""
    root = Path(root)
    if not root.is_dir():
        raise ParseError(f"not a directory: {root}")

    meta_file = root / "project.yml"
    meta = {}
    if meta_file.exists():
        meta = yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}

    manifest = Manifest(manifest=meta.get("manifest") or root.name,
                        version=meta.get("version") or "1.0.0")

    for file in sorted((root / "models").glob("*.yml")) if (root / "models").is_dir() else []:
        d = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        md = d.get("model", d)  # tolerate {"model": {...}} wrapper
        manifest.models.append(_coerce_manifest({"models": [md]}).models[0])

    for file in sorted((root / "views").glob("*.yml")) if (root / "views").is_dir() else []:
        d = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        vd = d.get("view", d)
        manifest.views.append(_coerce_manifest({"views": [vd]}).views[0])

    for name in ("relationships.yml", "metrics.yml"):
        f = root / name
        if f.exists():
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            sub = _coerce_manifest(d)
            if name == "relationships.yml":
                manifest.relationships.extend(sub.relationships)
            else:
                manifest.metrics.extend(sub.metrics)

    # tolerate flat extra files: root-level *.yml that contain full manifests
    for f in sorted(root.glob("*.yml")):
        if f.name in ("relationships.yml", "metrics.yml", "project.yml"):
            continue
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if isinstance(d, dict) and ("models" in d or "relationships" in d
                                    or "metrics" in d or "views" in d):
            sub = _coerce_manifest(d)
            manifest.models.extend(sub.models)
            manifest.relationships.extend(sub.relationships)
            manifest.metrics.extend(sub.metrics)
            manifest.views.extend(sub.views)

    return manifest
