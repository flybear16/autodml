"""Tests for SQLAlchemy reflection (in-memory SQLite)."""

import pytest
from sqlalchemy import (
    Column as SAColumn, ForeignKey, MetaData, Table,
    create_engine, insert, text,
)
from sqlalchemy.types import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String

from autodml.introspect import reflect
from autodml.typing import to_mdl_type
from autodml.validate import validate


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    md = MetaData()
    Table(
        "customers", md,
        SAColumn("id", Integer, primary_key=True),
        SAColumn("name", String(100), nullable=False),
        SAColumn("vip", Boolean),
        SAColumn("signup_date", Date),
        SAColumn("big_num", BigInteger),
        SAColumn("balance", Numeric(10, 2)),
    )
    Table(
        "orders", md,
        SAColumn("id", Integer, primary_key=True),
        SAColumn("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
        SAColumn("amount", Numeric(10, 2)),
        SAColumn("created_at", DateTime),
    )
    Table("logs_tmp", md, SAColumn("id", Integer, primary_key=True))
    md.create_all(eng)

    with eng.begin() as conn:
        conn.execute(insert(Table("customers", md)).values(id=1, name="a"))
        conn.execute(insert(Table("customers", md)).values(id=2, name="b"))
        conn.execute(insert(Table("orders", md)).values(id=1, customer_id=1, amount=9.9))

    return eng


def test_type_mapping():
    assert to_mdl_type(String(50)) == "string"
    assert to_mdl_type(Integer()) == "integer"
    assert to_mdl_type(Numeric(10, 2)) == "decimal"
    assert to_mdl_type(Boolean()) == "boolean"
    assert to_mdl_type(Date()) == "date"
    assert to_mdl_type(DateTime()) == "timestamp"
    assert to_mdl_type("varchar(255)") == "string"
    assert to_mdl_type("timestamp with time zone") == "timestamptz"
    assert to_mdl_type(object()) == "unknown"


def test_reflect_tables_and_columns(engine):
    m = reflect("sqlite://", engine=engine)
    names = {x.name for x in m.models}
    assert {"customers", "orders"} <= names

    cust = m.model("customers")
    assert cust.refSql == "customers"
    assert cust.primary_keys == ["id"]
    assert cust.column("name").notNull is True
    assert cust.column("name").type == "string"
    assert cust.column("vip").type == "boolean"
    assert cust.column("signup_date").type == "date"
    assert cust.column("balance").type == "decimal"


def test_reflect_infer_relationship(engine):
    m = reflect("sqlite://", engine=engine)
    assert len(m.relationships) == 1
    rel = m.relationships[0]
    assert rel.name == "orders_customers_fk"
    assert rel.relationType == "manyToOne"
    assert rel.left.modelName == "orders"
    assert rel.left.columnName == "customer_id"
    assert rel.right.modelName == "customers"
    assert rel.right.columnName == "id"


def test_reflect_include_exclude(engine):
    m = reflect("sqlite://", engine=engine, exclude=["logs_*"])
    assert m.model("logs_tmp") is None
    m2 = reflect("sqlite://", engine=engine, include=["orders"])
    assert {x.name for x in m2.models} == {"orders"}


def test_reflect_no_relationships(engine):
    m = reflect("sqlite://", engine=engine, infer_relationships=False)
    assert m.relationships == []


def test_reflected_manifest_validates(engine):
    m = reflect("sqlite://", engine=engine, exclude=["logs_tmp"])
    rep = validate(m)
    assert rep.ok, str(rep)


def test_sample_enrichment(engine):
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("UPDATE customers SET vip = NULL"))
    m = reflect("sqlite://", engine=engine, sample_rows=10, exclude=["logs_tmp"])
    cust = m.model("customers")
    assert cust.description and "vip" in cust.description
