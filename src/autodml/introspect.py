"""Live database -> Manifest via SQLAlchemy reflection."""

from __future__ import annotations

from typing import Iterable, Optional

from .model import Column, Manifest, Model, Relationship, RelationshipSide
from .typing import to_mdl_type

try:  # optional dependency
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.engine import Engine
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "database introspection requires SQLAlchemy: pip install 'autodml[db]'"
    ) from e


def reflect(
    url: str,
    schema: Optional[str] = None,
    include: Optional[Iterable[str]] = None,
    exclude: Optional[Iterable[str]] = None,
    infer_relationships: bool = True,
    sample_rows: int = 0,
    engine: Optional[Engine] = None,
) -> Manifest:
    """Reflect a database into a Manifest.

    include/exclude: table-name filters (exact or fnmatch glob, e.g. "public.*").
    infer_relationships: guess relationships from FK metadata.
    sample_rows: >0 probes sampled values to enrich descriptions (e.g. null ratio).
    """
    eng = engine or create_engine(url)
    insp = inspect(eng)
    import fnmatch

    tables = insp.get_table_names(schema=schema)
    views = insp.get_view_names(schema=schema)

    if include:
        pats = list(include)
        tables = [t for t in tables if any(fnmatch.fnmatch(t, p) for p in pats)]
        views = [v for v in views if any(fnmatch.fnmatch(v, p) for p in pats)]
    if exclude:
        pats = list(exclude)
        tables = [t for t in tables if not any(fnmatch.fnmatch(t, p) for p in pats)]
        views = [v for v in views if not any(fnmatch.fnmatch(v, p) for p in pats)]

    manifest = Manifest(manifest=schema or "default")
    pks_by_table: dict[str, list[str]] = {}

    for tname in tables:
        manifest.models.append(_reflect_table(insp, tname, schema))
        pks_by_table[tname] = manifest.models[-1].primary_keys

    # views reflected as models with refSql only (MDL has separate view
    # concept for query-time views; DB views map naturally onto models here)
    for vname in views:
        m = _reflect_table(insp, vname, schema)
        manifest.models.append(m)
        if m.primary_keys:
            pks_by_table[vname] = m.primary_keys

    if infer_relationships:
        used_names: set[str] = set()
        for m in manifest.models:
            for fk in insp.get_foreign_keys(m.name, schema=schema) if m.name in tables else []:
                if not fk.get("referred_table"):
                    continue
                rel = _fk_to_relationship(m.name, fk, pks_by_table, used_names)
                if rel:
                    manifest.relationships.append(rel)

    if sample_rows > 0:
        _enrich_with_samples(eng, manifest, schema, sample_rows)

    return manifest


def _reflect_table(insp, name: str, schema: Optional[str]) -> Model:
    cols = insp.get_columns(name, schema=schema)

    # SQLite sets per-column primary_key=True, but PostgreSQL's get_columns()
    # leaves it None -- the PK must be read from the constraint.
    try:
        pk_cols = set(insp.get_pk_constraint(name, schema=schema)
                      .get("constrained_columns") or [])
    except Exception:
        pk_cols = set()

    mdl_cols = []
    for c in cols:
        mdl_cols.append(Column(
            name=c["name"],
            type=to_mdl_type(c["type"]),
            notNull=bool(c.get("nullable") is False),
            isPrimary=bool(c.get("primary_key")) or c["name"] in pk_cols,
        ))
    ref = f"{schema}.{name}" if schema else name
    comment = None
    try:
        table_comment = insp.get_table_comment(name, schema=schema).get("text")
        comment = table_comment or None
    except Exception:
        pass  # dialect without comment support
    return Model(name=name, refSql=ref, columns=mdl_cols, description=comment)


def _fk_to_relationship(
    table: str, fk: dict, pks_by_table: dict[str, list[str]],
    used_names: Optional[set] = None,
) -> Optional[Relationship]:
    referred = fk["referred_table"]
    constrained = fk.get("constrained_columns") or []
    referred_cols = fk.get("referred_columns") or []
    if not constrained or not referred_cols:
        return None

    # cardinality: if referred side is (part of) the PK -> many-to-one typical
    ref_pk = pks_by_table.get(referred, [])
    is_ref_pk = bool(ref_pk) and set(referred_cols) <= set(ref_pk)
    # if constrained side IS the full PK of this table -> one-to-one
    self_pk = pks_by_table.get(table, [])
    is_full_self_pk = bool(self_pk) and set(constrained) == set(self_pk)

    if is_full_self_pk and is_ref_pk:
        rtype = "oneToOne"
    elif is_ref_pk:
        rtype = "manyToOne"
    else:
        rtype = "manyToOne"  # non-PK target: safest default guess

    name = f"{table}_{referred}_fk"
    if used_names is not None:
        if name in used_names:
            # multiple FKs between the same table pair: disambiguate with columns
            name = f"{table}_{referred}_{ '_'.join(constrained) }_fk"
            n = 2
            base = name
            while name in used_names:
                name = f"{base}{n}"
                n += 1
        used_names.add(name)
    return Relationship(
        name=name,
        relationType=rtype,
        left=RelationshipSide(modelName=table, columnName=",".join(constrained)),
        right=RelationshipSide(modelName=referred, columnName=",".join(referred_cols)),
    )


def _enrich_with_samples(eng, manifest: Manifest, schema: Optional[str], n: int) -> None:
    """Probe sample rows; append null-ratio hints into descriptions."""
    from sqlalchemy import text

    with eng.connect() as conn:
        for m in manifest.models:
            hints = []
            for c in m.columns:
                qtable = f"{schema}.{m.name}" if schema else m.name
                try:
                    r = conn.execute(text(
                        f"SELECT COUNT(*) AS total, "
                        f"SUM(CASE WHEN \"{c.name}\" IS NULL THEN 1 ELSE 0 END) AS nulls "
                        f"FROM {qtable}"
                    )).mappings().first()
                    total, nulls = r["total"], r["nulls"]
                    if total and nulls is not None and nulls / total > 0.5:
                        hints.append(f"{c.name}: >50% null")
                except Exception:
                    continue  # dialect mismatch, permission, etc. -- non-fatal
            if hints:
                note = "sampled hints: " + "; ".join(hints)
                m.description = f"{m.description}; {note}" if m.description else note
