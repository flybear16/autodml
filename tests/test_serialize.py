"""Tests for YAML/JSON serialization round-trips."""

import json
from pathlib import Path

import pytest
import yaml

from autodml import Calculation, Column, Manifest, Metric, Model, Relationship, View
from autodml.serialize import (
    from_dict,
    from_json,
    from_yaml,
    load,
    load_dir,
    to_dict,
    to_json,
    to_yaml,
    write_dir,
    write_json,
)


def sample_manifest():
    return (
        Manifest(manifest="shop", version="1.0.0")
        .add(
            Model(name="customers", refSql="public.customers", columns=[
                Column(name="id", type="integer", isPrimary=True, notNull=True),
                Column(name="name", type="string"),
            ]),
            Model(name="orders", refSql="public.orders", columns=[
                Column(name="id", type="integer", isPrimary=True, notNull=True),
                Column(name="customer_id", type="integer"),
            ], calculations=[
                Calculation(name="double_amount", expression="amount * 2", type="decimal"),
            ]),
            Relationship(
                name="orders_customer_fk", relationType="manyToOne",
                left={"modelName": "orders", "columnName": "customer_id"},
                right={"modelName": "customers", "columnName": "id"},
            ),
            Metric(name="order_count", baseModel="orders",
                   expression="COUNT(*)", type="integer"),
            View(name="active_customers",
                 statement="SELECT id, name FROM customers WHERE id > 0"),
        )
    )


def test_to_json_is_camelcase():
    d = json.loads(to_json(sample_manifest()))
    assert "refSql" in d["models"][0]
    assert "isPrimary" in d["models"][0]["columns"][0]
    assert d["relationships"][0]["relationType"] == "manyToOne"
    assert d["metrics"][0]["baseModel"] == "orders"


def test_json_roundtrip():
    m1 = sample_manifest()
    m2 = from_json(to_json(m1))
    assert to_dict(m1) == to_dict(m2)


def test_yaml_roundtrip():
    m1 = sample_manifest()
    m2 = from_yaml(to_yaml(m1))
    assert to_dict(m1) == to_dict(m2)


def test_from_dict_accepts_snake_case():
    d = {
        "models": [{
            "name": "t", "ref_sql": "public.t",
            "columns": [{"name": "id", "type": "integer"}],
        }],
        "relationships": [{
            "name": "r", "relation_type": "oneToOne",
            "left": {"model_name": "t", "column_name": "id"},
            "right": {"model_name": "t", "column_name": "id"},
        }],
    }
    m = from_dict(d)
    assert m.models[0].refSql == "public.t"
    assert m.relationships[0].relationType == "oneToOne"


def test_invalid_json_raises_parse_error():
    from autodml.errors import ParseError
    with pytest.raises(ParseError):
        from_json("{not json")


def test_invalid_yaml_raises_parse_error():
    from autodml.errors import ParseError
    with pytest.raises(ParseError):
        from_yaml("foo: [unclosed")


def test_write_and_load_json_file(tmp_path: Path):
    m1 = sample_manifest()
    p = write_json(m1, tmp_path / "out" / "mdl.json")
    assert p.exists()
    m2 = load(p)
    assert to_dict(m1) == to_dict(m2)


def test_write_and_load_yaml_dir(tmp_path: Path):
    m1 = sample_manifest()
    root = write_dir(m1, tmp_path / "proj")
    assert (root / "models" / "orders.yml").exists()
    assert (root / "relationships.yml").exists()
    assert (root / "views" / "active_customers.yml").exists()

    m2 = load_dir(root)
    assert {m.name for m in m2.models} == {"customers", "orders"}
    assert m2.relationships[0].name == "orders_customer_fk"
    assert m2.metrics[0].name == "order_count"
    assert m2.views[0].name == "active_customers"
    assert to_dict(m1) == to_dict(m2)


def test_load_dir_tolerates_wrapper(tmp_path: Path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "wrapped.yml").write_text(
        "model:\n  name: wrapped\n  refSql: public.wrapped\n"
        "  columns:\n    - name: id\n      type: integer\n",
        encoding="utf-8",
    )
    m = load_dir(tmp_path)
    assert m.model("wrapped") is not None
