"""Tests for validation rules."""

import pytest

from autodml import Column, Manifest, Metric, Model, Relationship
from autodml.errors import ValidationError
from autodml.validate import validate


def base_manifest():
    return Manifest().add(
        Model(name="t1", refSql="public.t1", columns=[
            Column(name="id", type="integer", isPrimary=True, notNull=True),
        ]),
    )


def issues_by_rule(rep):
    return {i.rule for i in rep.issues}


def test_valid_manifest_ok():
    rep = validate(base_manifest())
    assert rep.ok, str(rep)


def test_missing_ref_flagged():
    m = base_manifest()
    m.models[0].refSql = None
    rep = validate(m)
    assert "model-ref" in issues_by_rule(rep)


def test_bad_type_flagged():
    m = base_manifest()
    m.models[0].columns[0].type = "varchar(255)"
    rep = validate(m)
    assert "type" in issues_by_rule(rep)


def test_duplicate_model_and_column():
    m = base_manifest()
    m.add(Model(name="t1", refSql="x", columns=[Column(name="id", type="integer")]))
    m.models[0].columns.append(Column(name="id", type="integer"))
    rep = validate(m)
    rules = issues_by_rule(rep)
    assert "duplicate" in rules


def test_relationship_missing_model():
    m = base_manifest()
    m.add(Relationship(
        name="r1", relationType="manyToOne",
        left={"modelName": "t1", "columnName": "id"},
        right={"modelName": "ghost", "columnName": "id"},
    ))
    rep = validate(m)
    assert "missing-ref" in issues_by_rule(rep)


def test_relationship_bad_type():
    m = base_manifest()
    m.add(Relationship(
        name="r1", relationType="belongsTo",
        left={"modelName": "t1", "columnName": "id"},
        right={"modelName": "t1", "columnName": "id"},
    ))
    rep = validate(m)
    assert "relation-type" in issues_by_rule(rep)


def test_metric_missing_base_model():
    m = base_manifest()
    m.add(Metric(name="m1", baseModel="ghost", expression="SUM(x)"))
    rep = validate(m)
    assert "missing-ref" in issues_by_rule(rep)


def test_warning_does_not_fail():
    m = base_manifest()
    m.add(Model(name="orders_backup", refSql="public.orders_backup",
                columns=[Column(name="id", type="integer")]))
    rep = validate(m)
    assert rep.ok                      # warning only
    assert rep.warnings and rep.warnings[0].rule == "naming"


def test_assert_valid_raises():
    m = base_manifest()
    m.add(Metric(name="m1", baseModel="ghost", expression="SUM(x)"))
    with pytest.raises(ValidationError):
        from autodml.validate import assert_valid
        assert_valid(m)


def test_view_unknown_identifier_warns():
    from autodml import View
    m = base_manifest()
    m.add(View(name="v1", statement="SELECT unknown_col FROM t1"))
    rep = validate(m)
    assert any(i.rule == "view-ref" and i.severity == "warning" for i in rep.issues)
