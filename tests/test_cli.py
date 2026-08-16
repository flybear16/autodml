"""CLI integration tests."""

import json
from pathlib import Path

from autodml.cli import main

SAMPLE_YML = """\
manifest: shop
models:
  - name: customers
    refSql: public.customers
    columns:
      - name: id
        type: integer
        isPrimary: true
        notNull: true
      - name: name
        type: string
relationships:
  - name: broken_fk
    relationType: manyToOne
    left:
      modelName: customers
      columnName: id
    right:
      modelName: ghost_table
      columnName: id
"""


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, out


def test_version(capsys):
    with __import__("pytest").raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0


def test_init_scaffolds_project(tmp_path: Path, capsys):
    proj = tmp_path / "proj"
    code, out = run(capsys, "init", str(proj))
    assert code == 0
    assert (proj / "models" / "example.yml").exists()
    assert (proj / "views").is_dir()
    assert (proj / "relationships.yml").exists()

    # scaffolded project must validate
    code, out = run(capsys, "validate", str(proj))
    assert code == 0, out
    assert "VALID" in out


def test_validate_detects_errors(tmp_path: Path, capsys):
    f = tmp_path / "bad.yml"
    f.write_text(SAMPLE_YML, encoding="utf-8")
    code, out = run(capsys, "validate", str(f))
    assert code == 1
    assert "missing-ref" in out
    assert "INVALID" in out


def test_export_json_and_roundtrip(tmp_path: Path, capsys):
    src = tmp_path / "m.yml"
    src.write_text(SAMPLE_YML.split("relationships:")[0], encoding="utf-8")
    out_json = tmp_path / "mdl.json"
    code, _ = run(capsys, "export", str(src), "-o", str(out_json))
    assert code == 0

    d = json.loads(out_json.read_text(encoding="utf-8"))
    assert d["manifest"] == "shop"
    assert d["models"][0]["refSql"] == "public.customers"

    # validate the exported json too
    code, out = run(capsys, "validate", str(out_json))
    assert code == 0, out


def test_export_yaml_dir(tmp_path: Path, capsys):
    src = tmp_path / "m.yml"
    src.write_text(SAMPLE_YML.split("relationships:")[0], encoding="utf-8")
    proj = tmp_path / "proj"
    code, _ = run(capsys, "export", str(src), "-o", str(proj), "--format", "yaml-dir")
    assert code == 0
    assert (proj / "models" / "customers.yml").exists()

    code, out = run(capsys, "validate", str(proj))
    assert code == 0, out


def test_reflect_sqlite(tmp_path: Path, capsys):
    out_json = tmp_path / "reflected.json"
    code, out = run(capsys, "reflect", "sqlite://", "-o", str(out_json))
    assert code == 0
    d = json.loads(out_json.read_text(encoding="utf-8"))
    assert isinstance(d["models"], list)
