"""Tests for the core object model."""

import pytest

from autodml import Calculation, Column, Manifest, Metric, Model, Relationship


def make_manifest():
    customers = Model(
        name="customers",
        refSql="public.customers",
        columns=[
            Column(name="id", type="integer", notNull=True, isPrimary=True),
            Column(name="name", type="string"),
        ],
    )
    orders = Model(
        name="orders",
        refSql="public.orders",
        columns=[
            Column(name="id", type="integer", notNull=True, isPrimary=True),
            Column(name="customer_id", type="integer"),
            Column(name="amount", type="decimal"),
        ],
        calculations=[
            Calculation(name="amount_with_tax", expression="amount * 1.1", type="decimal"),
        ],
    )
    rel = Relationship(
        name="orders_customer_fk",
        relationType="manyToOne",
        left={"modelName": "orders", "columnName": "customer_id"},
        right={"modelName": "customers", "columnName": "id"},
    )
    metric = Metric(name="total_revenue", baseModel="orders",
                    expression="SUM(amount)", type="decimal")
    return Manifest().add(customers, orders, rel, metric)


def test_add_and_lookup():
    m = make_manifest()
    assert m.model("orders") is not None
    assert m.model("nope") is None
    assert m.model("orders").column("amount").type == "decimal"
    assert m.model("customers").primary_keys == ["id"]
    assert len(m.relationships_of("orders")) == 1
    assert len(m.relationships_of("customers")) == 1


def test_add_rejects_unknown():
    with pytest.raises(TypeError):
        Manifest().add(42)


def test_to_dict_drops_none_and_keeps_falsy():
    m = make_manifest()
    d = m.to_dict()
    assert "description" not in d["models"][0]      # None dropped
    assert d["models"][0]["columns"][0]["notNull"] is True
    assert d["models"][0]["cached"] is False          # False kept


def test_from_dict_roundtrip():
    m = make_manifest()
    d = m.to_dict()
    m2 = Manifest.from_dict(d)
    assert m2.model("orders").calculations[0].name == "amount_with_tax"
    assert m2.relationships[0].relationType == "manyToOne"
    assert m2.metrics[0].baseModel == "orders"


def test_relationship_side_accepts_dict():
    rel = Relationship(
        name="r", relationType="oneToOne",
        left={"modelName": "a", "columnName": "id"},
        right={"modelName": "b", "columnName": "a_id"},
    )
    assert rel.left.modelName == "a"
