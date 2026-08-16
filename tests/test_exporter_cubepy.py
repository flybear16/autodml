"""Tests for the cubepy exporter (mapping + YAML structure)."""

import pytest
import yaml

from autodml import Calculation, Column, Manifest, Metric, Model, Relationship, View
from autodml.exporters.cubepy import manifest_to_cubepy, to_cubepy_yaml


def sample_manifest():
    return (
        Manifest(manifest="shop")
        .add(
            Model(name="customers", refSql="public.customers", columns=[
                Column(name="id", type="integer", isPrimary=True, notNull=True),
                Column(name="name", type="string"),
                Column(name="vip", type="boolean"),
                Column(name="signup_date", type="date"),
            ]),
            Model(name="orders", refSql="public.orders", columns=[
                Column(name="id", type="integer", isPrimary=True, notNull=True),
                Column(name="customer_id", type="integer"),
                Column(name="amount", type="decimal"),
                Column(name="created_at", type="timestamp"),
            ], calculations=[
                Calculation(name="amount_with_tax", expression="amount * 1.1",
                            type="decimal"),
            ]),
            Relationship(
                name="orders_customer_fk", relationType="manyToOne",
                left={"modelName": "orders", "columnName": "customer_id"},
                right={"modelName": "customers", "columnName": "id"},
            ),
            Metric(name="total_revenue", baseModel="orders",
                   expression="SUM(amount)", type="decimal"),
            Metric(name="order_cnt", baseModel="orders", expression="COUNT(*)"),
            Metric(name="buyers", baseModel="orders",
                   expression="COUNT(DISTINCT customer_id)"),
            Metric(name="weird", baseModel="orders",
                   expression="amount / NULLIF(total, 0)"),
            View(name="active_customers", statement="SELECT id FROM customers"),
        )
    )


def cube_by_name(data, name):
    return next(c for c in data["cubes"] if c["name"] == name)


def test_model_to_cube_and_type_map():
    data, warnings = manifest_to_cubepy(sample_manifest())
    cust = cube_by_name(data, "customers")
    assert cust["sql"] == "SELECT * FROM public.customers"
    dims = {d["name"]: d for d in cust["dimensions"]}
    assert dims["id"]["type"] == "number" and dims["id"]["primaryKey"] is True
    assert dims["name"]["type"] == "string"
    assert dims["vip"]["type"] == "boolean"
    assert dims["signup_date"]["type"] == "time"


def test_calculation_becomes_dimension():
    data, _ = manifest_to_cubepy(sample_manifest())
    orders = cube_by_name(data, "orders")
    calc = next(d for d in orders["dimensions"] if d["name"] == "amount_with_tax")
    assert calc["sql"] == "amount * 1.1"
    assert calc["type"] == "number"


def test_many_to_one_join_on_fk_side():
    data, _ = manifest_to_cubepy(sample_manifest())
    orders = cube_by_name(data, "orders")
    assert orders["joins"]["customers"] == {
        "relationship": "belongsTo",
        "sql": "orders.customer_id = customers.id",
    }
    # the PK side cube gets no join
    assert "joins" not in cube_by_name(data, "customers")


@pytest.mark.parametrize("expr,expected", [
    ("SUM(amount)", {"type": "sum", "sql": "amount"}),
    ("count(*)", {"type": "count"}),
    ("COUNT(DISTINCT customer_id)", {"type": "countDistinct", "sql": "customer_id"}),
    ("avg(amount)", {"type": "avg", "sql": "amount"}),
    ("MAX(amount)", {"type": "max", "sql": "amount"}),
    ("SUM(amount * 1.1)", None),
])
def test_measure_parsing(expr, expected):
    from autodml.exporters.cubepy import _measure_from_metric
    assert _measure_from_metric(expr) == expected


def test_metrics_land_on_base_cube_with_warnings():
    data, warnings = manifest_to_cubepy(sample_manifest())
    orders = cube_by_name(data, "orders")
    measures = {m["name"]: m for m in orders["measures"]}
    assert measures["total_revenue"] == {"name": "total_revenue", "type": "sum", "sql": "amount"}
    assert measures["order_cnt"] == {"name": "order_cnt", "type": "count"}
    assert measures["buyers"] == {"name": "buyers", "type": "countDistinct", "sql": "customer_id"}
    assert "weird" not in measures
    assert any("weird" in w for w in warnings)
    assert any("active_customers" in w for w in warnings)  # view skipped


def test_many_to_many_and_one_to_many():
    m = sample_manifest()
    m.add(
        Relationship(name="tagging", relationType="manyToMany",
                     left={"modelName": "orders", "columnName": "id"},
                     right={"modelName": "customers", "columnName": "id"}),
        Relationship(name="cust_orders", relationType="oneToMany",
                     left={"modelName": "customers", "columnName": "id"},
                     right={"modelName": "orders", "columnName": "customer_id"}),
    )
    data, warnings = manifest_to_cubepy(m)
    assert any("tagging" in w and "manyToMany" in w for w in warnings)
    cust = cube_by_name(data, "customers")
    assert cust["joins"]["orders"]["relationship"] == "hasMany"


def test_yaml_is_dumpable_and_loadable():
    text, warnings = to_cubepy_yaml(sample_manifest())
    data = yaml.safe_load(text)
    assert len(data["cubes"]) == 2
    assert {c["name"] for c in data["cubes"]} == {"customers", "orders"}


def test_cubepy_loader_integration():
    """If cubepy is importable (e.g. dev checkout at ~/ws2026/cubepy), load for real."""
    cubepy = pytest.importorskip("cubepy.schema.loader", reason="cubepy not installed")
    import tempfile
    from pathlib import Path

    from autodml.exporters.cubepy import write_cubepy_yaml
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cubes.yml"
        write_cubepy_yaml(sample_manifest(), p)
        metas = cubepy.load_cube_file(str(p))
        by_name = {m.name: m for m in metas}
        assert {"customers", "orders"} <= set(by_name)
        orders = by_name["orders"]
        assert orders.joins["customers"].relationship.value == "belongsTo"
        assert any(m.name == "total_revenue" for m in orders.measures)
