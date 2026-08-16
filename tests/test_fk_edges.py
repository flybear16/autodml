"""Regression tests for FK inference edge cases.

Covers bugs found in real testing (2026-08-16):
- same-table double FK used to produce duplicate relationship names
- set == list comparison made oneToOne undetectable
- self-referencing FK
- composite (multi-column) FK
"""

import pytest
from sqlalchemy import (
    Column as SAColumn, ForeignKey, ForeignKeyConstraint, Integer, MetaData,
    String, Table, create_engine,
)

from autodml.introspect import reflect
from autodml.validate import validate


@pytest.fixture()
def edge_engine():
    eng = create_engine("sqlite://")
    md = MetaData()
    Table("users", md, SAColumn("id", Integer, primary_key=True),
          SAColumn("username", String))
    # self-referencing
    Table("employees", md, SAColumn("id", Integer, primary_key=True),
          SAColumn("manager_id", Integer, ForeignKey("employees.id")))
    # two FKs to the same table
    Table("transfers", md, SAColumn("id", Integer, primary_key=True),
          SAColumn("from_user", Integer, ForeignKey("users.id")),
          SAColumn("to_user", Integer, ForeignKey("users.id")))
    # composite FK
    Table("orders_c", md, SAColumn("tenant_id", Integer, primary_key=True),
          SAColumn("order_no", String, primary_key=True))
    Table("order_items", md, SAColumn("id", Integer, primary_key=True),
          SAColumn("o_tenant", Integer), SAColumn("o_no", String),
          ForeignKeyConstraint(["o_tenant", "o_no"],
                               ["orders_c.tenant_id", "orders_c.order_no"]))
    # FK column is the full PK of this table -> oneToOne
    Table("profiles", md,
          SAColumn("user_id", Integer, ForeignKey("users.id"), primary_key=True),
          SAColumn("bio", String))
    md.create_all(eng)
    return eng


def rel_map(m):
    return {r.name: r for r in m.relationships}


def test_double_fk_no_duplicate_names(edge_engine):
    m = reflect("sqlite://", engine=edge_engine)
    names = [r.name for r in m.relationships]
    assert len(names) == len(set(names)), f"duplicates: {names}"

    rm = rel_map(m)
    assert "transfers_users_fk" in rm
    assert "transfers_users_to_user_fk" in rm
    assert rm["transfers_users_fk"].left.columnName == "from_user"
    assert rm["transfers_users_to_user_fk"].left.columnName == "to_user"


def test_one_to_one_inferred_when_fk_is_full_pk(edge_engine):
    m = reflect("sqlite://", engine=edge_engine)
    rm = rel_map(m)
    assert rm["profiles_users_fk"].relationType == "oneToOne"


def test_self_referencing_fk(edge_engine):
    m = reflect("sqlite://", engine=edge_engine)
    rm = rel_map(m)
    r = rm["employees_employees_fk"]
    assert r.relationType == "manyToOne"
    assert r.left.modelName == r.right.modelName == "employees"


def test_composite_fk(edge_engine):
    m = reflect("sqlite://", engine=edge_engine)
    rm = rel_map(m)
    r = rm["order_items_orders_c_fk"]
    assert r.left.columnName == "o_tenant,o_no"
    assert r.right.columnName == "tenant_id,order_no"


def test_edge_manifest_validates(edge_engine):
    m = reflect("sqlite://", engine=edge_engine)
    rep = validate(m)
    assert rep.ok, str(rep)
